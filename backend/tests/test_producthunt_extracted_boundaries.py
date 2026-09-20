from __future__ import annotations

import asyncio
import sys
import types
from datetime import date, datetime
from typing import Any

import pytest

from backend.app.core.config import settings
from backend.app.services.ingestion import (
    producthunt_policy as policy,
    producthunt_projection as projection,
    producthunt_transport as transport,
)


class _FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):  # type: ignore[no-untyped-def]
        value = cls(2026, 7, 27, 1, 2, 3)
        return value.replace(tzinfo=tz) if tz else value


def _post(**overrides: Any) -> dict[str, Any]:
    post: dict[str, Any] = {
        "name": " Contract Kit ",
        "tagline": " Freeze the boundary ",
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


def test_date_policy_preserves_cst_parsing_window_and_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(policy, "datetime", _FrozenDateTime)
    anchor = date(2026, 7, 27)

    assert policy.today_cst() == anchor
    assert policy.crawl_date_cst() == "2026-07-27"
    assert policy.normalize_period(" DAILY ") == "daily"
    assert policy.normalize_period("") == "daily"
    assert policy.resolve_anchor("2026-07-20") == date(2026, 7, 20)
    # PR5：缺省/不可解析锚点回落 PT 当日（冻结时钟下 PT 日期同为 07-27）
    assert policy.resolve_anchor("not-a-date") == anchor
    assert policy.resolve_anchor(None) == anchor
    assert policy.today_pt() == anchor
    assert policy.parse_featured_at("2026-07-26T23:30:00-07:00") == date(2026, 7, 26)
    assert policy.parse_featured_at("2026-07-26") == date(2026, 7, 26)
    # PR2：带偏移时间串先换算 PT 再取日期——UTC 深夜是 PT 当天傍晚
    assert policy.parse_featured_at("2026-07-27T05:00:00+00:00") == date(2026, 7, 26)
    assert policy.parse_featured_at("2026-07-27T06:59:59Z") == date(2026, 7, 26)
    assert policy.parse_featured_at("2026-07-27T07:00:00Z") == date(2026, 7, 27)
    assert policy.parse_featured_at("") is None
    assert policy.parse_featured_at("not-a-date") is None
    # PR5 严格榜日过滤：featuredAt 缺失一律拒绝；daily 锚定单个 PT 榜日
    assert policy.within_period(None, "daily", anchor) is False
    assert policy.within_period(None, "weekly", anchor) is False
    assert policy.within_period(date(2026, 7, 25), "unknown", anchor) is True
    assert policy.within_period(date(2026, 7, 27), "daily", anchor) is True
    assert policy.within_period(date(2026, 7, 26), "daily", anchor) is False
    assert policy.within_period(date(2026, 7, 28), "daily", anchor) is False
    assert policy.within_period(date(2026, 7, 24), "daily", anchor) is False
    assert policy.within_period(date(2026, 7, 20), "weekly", anchor) is True
    assert policy.within_period(date(2026, 6, 27), "monthly", anchor) is True
    # PR2 行为变化：clamp 已删除——featured 日期恒取自身（PT 口径），
    # 不再把早于爬取锚点的日期改写为锚点日
    assert policy.published_date(date(2026, 7, 26), "daily", anchor, "2026-07-27") == "2026-07-26"
    assert policy.published_date(date(2026, 7, 20), "weekly", anchor, "2026-07-27") == "2026-07-20"
    assert policy.published_date(None, "daily", anchor, "2026-07-27") == "2026-07-27"


def test_resolve_board_date_picks_mode_with_newer_tiebreak() -> None:
    """整页归属日 = featured 日期众数；平票取较新；全空返回 None。"""
    assert (
        policy.resolve_board_date(
            [date(2026, 7, 26), date(2026, 7, 26), date(2026, 7, 25), None]
        )
        == date(2026, 7, 26)
    )
    assert (
        policy.resolve_board_date([date(2026, 7, 25), date(2026, 7, 26)])
        == date(2026, 7, 26)
    )
    assert policy.resolve_board_date([None, None]) is None
    assert policy.resolve_board_date([]) is None


def test_exact_api_and_html_item_projections() -> None:
    # PR5：daily 锚定单个 PT 榜日——featured 日期 07-26 须以 anchor=07-26 投影
    anchor = date(2026, 7, 26)
    channel = "producthunt_daily_html"
    api_node = {
        **_post(),
        "url": None,
        "votesCount": 9,
        "commentsCount": 2,
    }

    api_items = projection.project_api_items(
        [{"node": api_node}], "daily", anchor, channel, "2026-07-27"
    )
    assert api_items == [
        {
            "title": "Contract Kit",
            "abstract": "Freeze the boundary [Developer Tools, Testing]",
            "summary": "Freeze the boundary [Developer Tools, Testing]",
            "url": "https://www.producthunt.com/posts/contract-kit",
            "votes": 9,
            "raw_score": 9.0,
            "score": 9.0,
            "source": "producthunt",
            "source_channel": channel,
            "channel": channel,
            "published_date": "2026-07-26",
            "tags": ["ProductHunt", "daily", "Developer Tools", "Testing"],
            "pdf_url": "",
            "featured_at": "2026-07-26T08:00:00-07:00",
            "daily_rank": "",
            "weekly_rank": "",
            "monthly_rank": "",
        }
    ]

    html_items = projection.project_html_items(
        [_post()], 20, "daily", anchor, channel, "2026-07-27"
    )
    assert html_items == [
        {
            **api_items[0],
            "votes": 42,
            "raw_score": 42.0,
            "score": 42.0,
            "daily_rank": "3",
            "weekly_rank": "",
            "monthly_rank": "12",
        }
    ]

    # PR5 严格过滤：featuredAt 缺失的条目不再进入投影
    assert (
        projection.project_html_items(
            [_post(featuredAt=None)], 1, "daily", anchor, channel, "2026-07-27"
        )
        == []
    )
    assert (
        projection.project_api_items(
            [{"node": {**api_node, "featuredAt": None}}],
            "daily",
            anchor,
            channel,
            "2026-07-27",
        )
        is None
    )


def test_projection_preserves_none_and_conversion_behaviors() -> None:
    anchor = date(2026, 7, 27)
    channel = "producthunt_daily_html"

    assert projection.project_api_items([], "daily", anchor, channel, "2026-07-27") is None
    assert projection.project_api_items([{"node": {}}], "daily", anchor, channel, "2026-07-27") is None
    assert projection.project_html_items([_post(name="")], 1, "daily", anchor, channel, "2026-07-27") == []
    with pytest.raises(ValueError):
        projection.project_api_items(
            [{"node": {**_post(), "votesCount": 1, "commentsCount": "invalid"}}],
            "daily",
            anchor,
            channel,
            "2026-07-27",
        )


def test_api_transport_preserves_token_request_and_none_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class Response:
        status_code = 200
        text = ""

        @staticmethod
        def json() -> dict[str, Any]:
            return {"data": {"posts": {"edges": [{"node": {"id": "101"}}]}}}

    class Client:
        def __init__(self, **kwargs: Any) -> None:
            calls.append({"client": kwargs})

        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, **kwargs: Any) -> Response:
            calls.append({"url": url, **kwargs})
            return Response()

    monkeypatch.setattr(settings, "producthunt_api_token", "synthetic-token")
    monkeypatch.setattr(transport.httpx, "AsyncClient", Client)
    result = asyncio.run(transport.fetch_api_edges(99))

    assert result == [{"node": {"id": "101"}}]
    assert calls[0] == {
        "client": {"timeout": 20, "follow_redirects": True, "trust_env": True}
    }
    assert calls[1]["url"] == "https://api.producthunt.com/v2/api/graphql"
    # PR5 分页取样：首页 after=None，页大小固定 20
    assert calls[1]["json"] == {
        "query": transport._PH_POSTS_QUERY,
        "variables": {"first": 20, "after": None, "order": "FEATURED_AT"},
    }
    assert calls[1]["headers"] == {
        "Authorization": "Bearer synthetic-token",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "RAG-AIGC-Agent/1.0",
    }

    monkeypatch.setattr(settings, "producthunt_api_token", "")
    calls.clear()
    assert asyncio.run(transport.fetch_api_edges(1)) is None
    assert calls == []


def test_html_transports_preserve_retries_parameters_and_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(transport.asyncio, "sleep", fake_sleep)
    curl_calls: list[dict[str, Any]] = []

    class CurlResponse:
        status_code = 503
        text = "blocked"

    def curl_get(url: str, **kwargs: Any) -> CurlResponse:
        curl_calls.append({"url": url, **kwargs})
        return CurlResponse()

    curl_module = types.ModuleType("curl_cffi")
    curl_module.requests = types.SimpleNamespace(get=curl_get)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "curl_cffi", curl_module)
    assert asyncio.run(transport.fetch_html_curl_cffi("https://synthetic.invalid")) is None
    assert [call["impersonate"] for call in curl_calls] == [
        "chrome124",
        "chrome120",
        "chrome116",
    ]
    assert all(call["timeout"] == 30 for call in curl_calls)
    assert all(call["allow_redirects"] is True for call in curl_calls)
    assert sleeps == [2.0, 4.0]

    sleeps.clear()
    client_kwargs: list[dict[str, Any]] = []

    class HttpxResponse:
        status_code = 200
        text = "short"

    class Client:
        def __init__(self, **kwargs: Any) -> None:
            client_kwargs.append(kwargs)

        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def get(self, _: str) -> HttpxResponse:
            return HttpxResponse()

    monkeypatch.setattr(transport.httpx, "AsyncClient", Client)
    assert asyncio.run(transport.fetch_html_httpx("https://synthetic.invalid")) is None
    assert client_kwargs == [
        {
            "timeout": 30,
            "follow_redirects": True,
            "headers": transport._BROWSER_HEADERS,
            "trust_env": True,
        }
    ] * 3
    assert sleeps == [2.0, 4.0]

    order: list[str] = []

    async def no_curl(_: str) -> None:
        order.append("curl")
        return None

    async def yes_httpx(_: str) -> str:
        order.append("httpx")
        return "x" * 1001

    monkeypatch.setattr(transport, "fetch_html_curl_cffi", no_curl)
    monkeypatch.setattr(transport, "fetch_html_httpx", yes_httpx)
    assert asyncio.run(transport.fetch_html("https://synthetic.invalid")) == "x" * 1001
    assert order == ["curl", "httpx"]


@pytest.mark.parametrize("kind", ["api", "html"])
@pytest.mark.parametrize("thumbnail", [None, {}, {"url": "javascript:alert(1)"}, {"url": "https://ph-files.imgix.net/logo.png"}])
def test_product_logo_survives_projection_and_persistence(kind, thumbnail):
    import json

    from langchain_core.documents import Document

    from backend.app.services.ingestion.persistence_adapter import project_document_write

    post = _post(thumbnail=thumbnail)
    args = ("daily", date(2026, 7, 26), "producthunt_daily_html", "2026-07-27")
    rows = (projection.project_api_items([{"node": post}], *args) if kind == "api"
            else projection.project_html_items([post], 10, *args))
    row = rows[0]
    if thumbnail and thumbnail.get("url", "").startswith("https:"):
        assert row["link_card"]["image_url"] == thumbnail["url"]
        payload = project_document_write(row, Document(page_content="", metadata={"id": "product"}), "producthunt")
        assert json.loads(payload["link_card"])["image_url"] == thumbnail["url"]
    else:
        assert "link_card" not in row
