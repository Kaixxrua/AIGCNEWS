from __future__ import annotations

import asyncio
import json
import sys
import types
from datetime import date, datetime
from typing import Any

import pytest

from backend.app.core.config import settings
from backend.app.services.ingestion import source_producthunt as ph


class _FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):  # type: ignore[no-untyped-def]
        value = cls(2026, 7, 27, 1, 2, 3)
        return value.replace(tzinfo=tz) if tz else value


def _post(**overrides: Any) -> dict[str, Any]:
    post: dict[str, Any] = {
        "__typename": "Post",
        "id": "101",
        "name": "Contract Kit",
        "tagline": "Freeze the boundary",
        "slug": "contract-kit",
        "featuredAt": "2026-07-26T08:00:00-07:00",
        "launchDayScore": 42,
        "latestScore": 40,
        "dailyRank": 3,
        "weeklyRank": None,
        "monthlyRank": 12,
        "topics": {
            "edges": [
                {"node": {"name": "Developer Tools"}},
                {"node": {"name": "Testing"}},
            ]
        },
    }
    post.update(overrides)
    return post


def test_date_policy_parsing_and_period_boundaries() -> None:
    anchor = date(2026, 7, 27)

    assert ph._parse_featured_at("2026-07-26T23:30:00-07:00") == date(2026, 7, 26)
    assert ph._parse_featured_at("2026-07-26") == date(2026, 7, 26)
    assert ph._parse_featured_at("") is None
    assert ph._parse_featured_at("not-a-date") is None

    assert ph._within_period(None, "daily", anchor) is True
    assert ph._within_period(date(2026, 7, 25), "daily", anchor) is True
    assert ph._within_period(date(2026, 7, 24), "daily", anchor) is False
    assert ph._within_period(date(2026, 7, 28), "daily", anchor) is True
    assert ph._within_period(date(2026, 7, 29), "daily", anchor) is False
    assert ph._within_period(date(2026, 7, 20), "weekly", anchor) is True
    assert ph._within_period(date(2026, 6, 27), "monthly", anchor) is True


def test_parser_deduplicates_posts_across_item_arrays() -> None:
    first = _post()
    duplicate = _post(name="Must Not Replace First")
    second = _post(id="202", name="Second Product", slug="second-product")
    first_items = json.dumps([first], separators=(",", ":"))
    later_items = json.dumps([duplicate, second], separators=(",", ":"))
    payload = (
        '<script>window[Symbol.for("ApolloSSRDataTransport")];'
        f'"featuredAt";"launchDayScore";"items":{first_items};'
        f'"items":{later_items}</script>'
    )

    posts = ph._extract_posts_from_html(payload)

    assert [post["id"] for post in posts] == ["101", "202"]
    assert posts[0]["name"] == "Contract Kit"
    assert ph._extract_posts_from_html("<html><script>no feed</script></html>") == []


def test_html_channel_returns_exact_daily_item_and_projects_pst_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_api(*args: Any, **kwargs: Any) -> None:
        return None

    async def html(_: str) -> str:
        return "synthetic-html"

    monkeypatch.setattr(ph, "datetime", _FrozenDateTime)
    monkeypatch.setattr(ph, "_fetch_via_api", no_api)
    monkeypatch.setattr(ph, "_fetch_html", html)
    monkeypatch.setattr(ph, "_extract_posts_from_html", lambda _: [_post()])

    result = asyncio.run(
        ph.fetch_producthunt_products_async(
            limit=20, period=" DAILY ", target_date="2026-07-27"
        )
    )

    assert result == [
        {
            "title": "Contract Kit",
            "abstract": "Freeze the boundary [Developer Tools, Testing]",
            "summary": "Freeze the boundary [Developer Tools, Testing]",
            "url": "https://www.producthunt.com/posts/contract-kit",
            "votes": 42,
            "raw_score": 42.0,
            "score": 42.0,
            "source": "producthunt",
            "source_channel": "producthunt_daily_html",
            "channel": "producthunt_daily_html",
            "published_date": "2026-07-27",
            "tags": ["ProductHunt", "daily", "Developer Tools", "Testing"],
            "pdf_url": "",
            "featured_at": "2026-07-26T08:00:00-07:00",
            "daily_rank": "3",
            "weekly_rank": "",
            "monthly_rank": "12",
        }
    ]


def test_html_empty_semantics_and_out_of_window_relaxation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_api(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(ph, "datetime", _FrozenDateTime)
    monkeypatch.setattr(ph, "_fetch_via_api", no_api)

    async def no_html(_: str) -> str:
        return ""

    monkeypatch.setattr(ph, "_fetch_html", no_html)
    assert asyncio.run(ph.fetch_producthunt_products_async()) == []

    async def html(_: str) -> str:
        return "synthetic-html"

    monkeypatch.setattr(ph, "_fetch_html", html)
    monkeypatch.setattr(
        ph,
        "_extract_posts_from_html",
        lambda _: [_post(featuredAt="2020-01-01T00:00:00-08:00")],
    )

    result = asyncio.run(
        ph.fetch_producthunt_products_async(
            limit=1, period="daily", target_date="2026-07-27"
        )
    )
    assert result[0]["published_date"] == "2026-07-27"
    assert result[0]["abstract"] == "Freeze the boundary [Developer Tools, Testing]"
    assert result[0]["summary"] == "Freeze the boundary"


def test_api_returns_exact_item_and_none_for_unusable_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "producthunt_api_token", "synthetic-token")

    class Response:
        status_code = 200
        text = ""

        @staticmethod
        def json() -> dict[str, Any]:
            return {
                "data": {
                    "posts": {
                        "edges": [
                            {
                                "node": {
                                    "id": "101",
                                    "name": " API Product ",
                                    "tagline": " Stable API ",
                                    "slug": "api-product",
                                    "url": None,
                                    "votesCount": 9,
                                    "commentsCount": 2,
                                    "featuredAt": "2026-07-26T08:00:00-07:00",
                                    "topics": {
                                        "edges": [{"node": {"name": "APIs"}}]
                                    },
                                }
                            }
                        ]
                    }
                }
            }

    class Client:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, *args: Any, **kwargs: Any) -> Response:
            assert kwargs["json"]["variables"] == {"first": 20, "order": "FEATURED_AT"}
            assert kwargs["headers"]["Authorization"] == "Bearer synthetic-token"
            return Response()

    monkeypatch.setattr(ph.httpx, "AsyncClient", Client)
    result = asyncio.run(
        ph._fetch_via_api(
            99,
            "daily",
            date(2026, 7, 27),
            "producthunt_daily_html",
            "2026-07-27",
        )
    )

    assert result == [
        {
            "title": "API Product",
            "abstract": "Stable API [APIs]",
            "summary": "Stable API [APIs]",
            "url": "https://www.producthunt.com/posts/api-product",
            "votes": 9,
            "raw_score": 9.0,
            "score": 9.0,
            "source": "producthunt",
            "source_channel": "producthunt_daily_html",
            "channel": "producthunt_daily_html",
            "published_date": "2026-07-27",
            "tags": ["ProductHunt", "daily", "APIs"],
            "pdf_url": "",
            "featured_at": "2026-07-26T08:00:00-07:00",
            "daily_rank": "",
            "weekly_rank": "",
            "monthly_rank": "",
        }
    ]

    class EmptyResponse(Response):
        @staticmethod
        def json() -> dict[str, Any]:
            return {"data": {"posts": {"edges": []}}}

    async def empty_post(self: Client, *args: Any, **kwargs: Any) -> EmptyResponse:
        return EmptyResponse()

    monkeypatch.setattr(Client, "post", empty_post)
    assert (
        asyncio.run(
            ph._fetch_via_api(
                1,
                "daily",
                date(2026, 7, 27),
                "producthunt_daily_html",
                "2026-07-27",
            )
        )
        is None
    )


def test_fetch_order_is_api_then_curl_then_httpx(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def curl(_: str) -> None:
        calls.append("curl")
        return None

    async def httpx(_: str) -> str:
        calls.append("httpx")
        return "x" * 1001

    monkeypatch.setattr(ph, "_fetch_html_curl_cffi", curl)
    monkeypatch.setattr(ph, "_fetch_html_httpx", httpx)
    assert asyncio.run(ph._fetch_html("https://synthetic.invalid")) == "x" * 1001
    assert calls == ["curl", "httpx"]

    calls.clear()

    async def api_success(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        calls.append("api")
        return [{"title": "from-api"}]

    async def forbidden_html(_: str) -> str:
        calls.append("html")
        raise AssertionError("HTML must not run after a truthy API result")

    monkeypatch.setattr(ph, "_fetch_via_api", api_success)
    monkeypatch.setattr(ph, "_fetch_html", forbidden_html)
    assert asyncio.run(ph.fetch_producthunt_products_async()) == [{"title": "from-api"}]
    assert calls == ["api"]


def test_curl_and_httpx_retry_three_times_without_live_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(ph.asyncio, "sleep", fake_sleep)

    curl_calls: list[str] = []

    class CurlResponse:
        status_code = 503
        text = "blocked"

    def curl_get(url: str, **kwargs: Any) -> CurlResponse:
        curl_calls.append(kwargs["impersonate"])
        return CurlResponse()

    curl_module = types.ModuleType("curl_cffi")
    curl_module.requests = types.SimpleNamespace(get=curl_get)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "curl_cffi", curl_module)

    assert asyncio.run(ph._fetch_html_curl_cffi("https://synthetic.invalid")) is None
    assert curl_calls == ["chrome124", "chrome120", "chrome116"]
    assert sleeps == [2.0, 4.0]

    sleeps.clear()
    httpx_calls = 0

    class HttpxResponse:
        status_code = 200
        text = "short"

    class Client:
        def __init__(self, **kwargs: Any) -> None:
            assert kwargs["headers"] == ph._BROWSER_HEADERS

        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def get(self, _: str) -> HttpxResponse:
            nonlocal httpx_calls
            httpx_calls += 1
            return HttpxResponse()

    monkeypatch.setattr(ph.httpx, "AsyncClient", Client)
    assert asyncio.run(ph._fetch_html_httpx("https://synthetic.invalid")) is None
    assert httpx_calls == 3
    assert sleeps == [2.0, 4.0]


def test_sync_wrapper_works_without_and_inside_running_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(
        limit: int = 20, period: str = "daily", target_date: str | None = None
    ) -> list[dict[str, Any]]:
        return [{"limit": limit, "period": period, "target_date": target_date}]

    monkeypatch.setattr(ph, "fetch_producthunt_products_async", fake_fetch)
    expected = [{"limit": 3, "period": "weekly", "target_date": "2026-07-20"}]

    assert ph.fetch_producthunt_products(3, "weekly", "2026-07-20") == expected

    async def call_from_loop() -> list[dict[str, Any]]:
        return ph.fetch_producthunt_products(3, "weekly", "2026-07-20")

    assert asyncio.run(call_from_loop()) == expected
