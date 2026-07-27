from __future__ import annotations

import asyncio
import inspect
import json
from datetime import date
from typing import Any

import pytest

from backend.app.services.ingestion import producthunt_coordinator as coordinator
from backend.app.services.ingestion import producthunt_parser as parser
from backend.app.services.ingestion import producthunt_policy as policy
from backend.app.services.ingestion import source_producthunt as ph


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


def _exact_item(*, summary: str, published_date: str) -> dict[str, Any]:
    return {
        "title": "Contract Kit",
        "abstract": "Freeze the boundary [Developer Tools, Testing]",
        "summary": summary,
        "url": "https://www.producthunt.com/posts/contract-kit",
        "votes": 42,
        "raw_score": 42.0,
        "score": 42.0,
        "source": "producthunt",
        "source_channel": "producthunt_daily_html",
        "channel": "producthunt_daily_html",
        "published_date": published_date,
        "tags": ["ProductHunt", "daily", "Developer Tools", "Testing"],
        "pdf_url": "",
        "featured_at": "2026-07-26T08:00:00-07:00",
        "daily_rank": "3",
        "weekly_rank": "",
        "monthly_rank": "12",
    }


def test_apollo_parser_preserves_deduplication_and_facade_forwarding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _post()
    duplicate = _post(name="Must Not Replace First")
    second = _post(id="202", name="Second Product", slug="second-product")
    payload = (
        '<script>window[Symbol.for("ApolloSSRDataTransport")];'
        '"featuredAt";"launchDayScore";'
        f'"items":{json.dumps([first], separators=(",", ":"))};'
        f'"items":{json.dumps([duplicate, second], separators=(",", ":"))}'
        "</script>"
    )

    posts = parser.extract_posts_from_html(payload)
    assert [post["id"] for post in posts] == ["101", "202"]
    assert posts[0]["name"] == "Contract Kit"

    sentinel = [{"id": "forwarded"}]
    monkeypatch.setattr(parser, "extract_posts_from_html", lambda html: sentinel)
    assert ph._extract_posts_from_html("synthetic-html") is sentinel


def test_coordinator_returns_exact_api_projection_without_html() -> None:
    calls: list[str] = []

    async def api_transport(limit: int) -> list[dict[str, Any]]:
        calls.append(f"api:{limit}")
        return [
            {
                "node": {
                    **_post(),
                    "url": None,
                    "votesCount": 9,
                    "commentsCount": 2,
                }
            }
        ]

    async def forbidden_html(url: str) -> str:
        raise AssertionError(f"HTML must not run after API success: {url}")

    result = asyncio.run(
        coordinator.fetch_producthunt_products(
            limit=99,
            period=" DAILY ",
            target_date="synthetic-target",
            resolve_anchor=lambda value: (
                calls.append(f"anchor:{value}") or date(2026, 7, 27)
            ),
            crawl_date=lambda: calls.append("crawl-date") or "2026-07-27",
            api_transport=api_transport,
            html_transport=forbidden_html,
        )
    )

    assert result == [
        {
            **_exact_item(summary="Freeze the boundary [Developer Tools, Testing]", published_date="2026-07-27"),
            "votes": 9,
            "raw_score": 9.0,
            "score": 9.0,
            "daily_rank": "",
            "monthly_rank": "",
        }
    ]
    assert calls == ["anchor:synthetic-target", "crawl-date", "api:99"]


def test_coordinator_preserves_html_and_relaxed_fallback_outputs() -> None:
    calls: list[str] = []

    async def no_api(limit: int) -> None:
        calls.append(f"api:{limit}")
        return None

    async def html_transport(url: str) -> str:
        calls.append(f"html:{url}")
        return "synthetic-html"

    def apollo_parser(html: str) -> list[dict[str, Any]]:
        calls.append(f"parser:{html}")
        return [_post()]

    common = {
        "limit": 1,
        "period": "daily",
        "target_date": "2026-07-27",
        "resolve_anchor": lambda value: date.fromisoformat(value or ""),
        "crawl_date": lambda: "2026-07-27",
        "api_transport": no_api,
        "html_transport": html_transport,
        "apollo_parser": apollo_parser,
    }
    result = asyncio.run(coordinator.fetch_producthunt_products(**common))
    assert result == [
        _exact_item(
            summary="Freeze the boundary [Developer Tools, Testing]",
            published_date="2026-07-27",
        )
    ]
    assert calls == [
        "api:1",
        f"html:{coordinator.PH_HOME_URL}",
        "parser:synthetic-html",
    ]

    calls.clear()

    def old_post_parser(html: str) -> list[dict[str, Any]]:
        calls.append(f"parser:{html}")
        return [_post(featuredAt="2020-01-01T00:00:00-08:00")]

    relaxed = asyncio.run(
        coordinator.fetch_producthunt_products(**{**common, "apollo_parser": old_post_parser})
    )
    assert relaxed == [
        {
            **_exact_item(summary="Freeze the boundary", published_date="2026-07-27"),
            "featured_at": "2020-01-01T00:00:00-08:00",
        }
    ]


@pytest.mark.parametrize("html, posts", [("", [_post()]), ("synthetic-html", [])])
def test_coordinator_preserves_empty_fallback_semantics(
    html: str, posts: list[dict[str, Any]]
) -> None:
    async def no_api(_: int) -> None:
        return None

    async def html_transport(_: str) -> str:
        return html

    assert (
        asyncio.run(
            coordinator.fetch_producthunt_products(
                resolve_anchor=lambda _: date(2026, 7, 27),
                crawl_date=lambda: "2026-07-27",
                api_transport=no_api,
                html_transport=html_transport,
                apollo_parser=lambda _: posts,
            )
        )
        == []
    )


def test_facade_transport_and_api_wrappers_forward_at_call_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def curl(url: str) -> str:
        return f"curl:{url}"

    async def httpx(url: str) -> str:
        return f"httpx:{url}"

    async def edges(limit: int) -> list[dict[str, Any]]:
        assert limit == 3
        return [{"node": {**_post(), "votesCount": 7, "commentsCount": 0}}]

    monkeypatch.setattr(ph.producthunt_transport, "fetch_html_curl_cffi", curl)
    monkeypatch.setattr(ph.producthunt_transport, "fetch_html_httpx", httpx)
    monkeypatch.setattr(ph.producthunt_transport, "fetch_api_edges", edges)

    assert asyncio.run(ph._fetch_html_curl_cffi("url")) == "curl:url"
    assert asyncio.run(ph._fetch_html_httpx("url")) == "httpx:url"
    result = asyncio.run(
        ph._fetch_via_api(
            3,
            "daily",
            date(2026, 7, 27),
            "producthunt_daily_html",
            "2026-07-27",
        )
    )
    assert result is not None
    assert result[0]["votes"] == 7


def test_public_async_entry_delegates_to_coordinator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    expected = [{"title": "from-coordinator"}]

    async def coordinated_fetch(**kwargs: Any) -> list[dict[str, Any]]:
        calls.append(kwargs)
        return expected

    monkeypatch.setattr(coordinator, "fetch_producthunt_products", coordinated_fetch)

    result = asyncio.run(
        ph.fetch_producthunt_products_async(3, " WEEKLY ", "2026-07-20")
    )

    assert result is expected
    assert len(calls) == 1
    call = calls[0]
    assert {
        "limit": call["limit"],
        "period": call["period"],
        "target_date": call["target_date"],
    } == {"limit": 3, "period": " WEEKLY ", "target_date": "2026-07-20"}
    assert call["normalize_period"] is policy.normalize_period
    assert call["resolve_anchor"] is ph._resolve_anchor
    assert call["api_channel"] is ph._fetch_via_api
    assert call["html_transport"] is ph._fetch_html
    assert call["apollo_parser"] is ph._extract_posts_from_html
    assert "producthunt_coordinator" in inspect.getsource(
        ph.fetch_producthunt_products_async
    )
