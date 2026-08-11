"""严格榜日契约（PR5+PR7）：PH 取样与过滤的诚实语义。

覆盖：
  - 锚点：缺省锚定 PT 当日（PH 首页正在展示的榜日），显式
    target_date（回填）优先；
  - 严格过滤：daily 只收锚定榜日条目，featuredAt 缺失/窗口外一律
    拒绝，严格为空即诚实回空（PR7 已删除 relaxed 宽松兜底）；
  - API 分页取样：FEATURED_AT 降序游标翻页收齐整个榜日，越出榜日
    即停、封顶 _MAX_PAGES 页；首页失败判通道不可用，后续页失败
    返回已收集的部分结果。
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, Optional

import pytest

from backend.app.core.config import settings
from backend.app.services.ingestion import (
    producthunt_coordinator as coordinator,
    producthunt_policy as policy,
    producthunt_transport as transport,
)


def _post(post_id: str, featured_at: Optional[str]) -> dict[str, Any]:
    return {
        "__typename": "Post",
        "id": post_id,
        "name": f"Product {post_id}",
        "tagline": "strict board",
        "slug": f"product-{post_id}",
        "featuredAt": featured_at,
        "launchDayScore": 10,
        "latestScore": 9,
        "topics": {"edges": []},
    }


def test_default_anchor_is_pt_today(monkeypatch: pytest.MonkeyPatch) -> None:
    """缺省锚点 = PT 当日：CST 上午抓到的仍是 PT 昨日榜，锚点必须同口径。"""
    sentinel = date(2026, 8, 10)
    monkeypatch.setattr(policy, "today_pt", lambda: sentinel)

    assert policy.resolve_anchor(None) is sentinel
    assert policy.resolve_anchor("not-a-date") is sentinel
    # 显式 target_date（回填）保持优先
    assert policy.resolve_anchor("2026-08-01") == date(2026, 8, 1)


def test_coordinator_keeps_only_anchor_board_day_and_rejects_missing_featured() -> None:
    """混合页：只有锚定榜日的条目存活；None/窗口外一律拒绝，不再宽松兜底。"""

    async def no_api(_: int, __: Any = None) -> None:
        return None

    posts = [
        _post("1", "2026-08-09T08:00:00-07:00"),
        _post("2", "2026-08-09T15:30:00-07:00"),
        _post("3", "2026-08-08T08:00:00-07:00"),  # 昨日榜残余
        _post("4", None),  # 无 featuredAt
        _post("5", ""),  # 空 featuredAt
    ]

    result = asyncio.run(
        coordinator.fetch_producthunt_products(
            limit=20,
            period="daily",
            target_date="2026-08-09",
            crawl_date=lambda: "2026-08-10",
            api_transport=no_api,
            html_transport=lambda url: asyncio.sleep(0, result="synthetic-html"),
            apollo_parser=lambda html: posts,
        )
    )

    assert [item["title"] for item in result] == ["Product 1", "Product 2"]
    assert {item["published_date"] for item in result} == {"2026-08-09"}


def test_coordinator_strict_empty_returns_empty_without_relaxed_fill() -> None:
    """整页无一条落在锚定榜日：诚实回空，不再用窗口外数据静默填版。"""

    async def no_api(_: int, __: Any = None) -> None:
        return None

    result = asyncio.run(
        coordinator.fetch_producthunt_products(
            limit=20,
            period="daily",
            target_date="2026-08-09",
            crawl_date=lambda: "2026-08-10",
            api_transport=no_api,
            html_transport=lambda url: asyncio.sleep(0, result="synthetic-html"),
            apollo_parser=lambda html: [
                _post("1", "2026-08-08T08:00:00-07:00"),
                _post("2", None),
            ],
        )
    )

    assert result == []


# ── API 分页取样 ────────────────────────────────────────────────────────────


def _edge(post_id: str, featured_at: str) -> dict[str, Any]:
    return {
        "node": {
            "id": post_id,
            "featuredAt": featured_at,
        }
    }


def _page(edges: list[dict[str, Any]], cursor: Optional[str]) -> dict[str, Any]:
    return {
        "data": {
            "posts": {
                "edges": edges,
                "pageInfo": {
                    "hasNextPage": cursor is not None,
                    "endCursor": cursor,
                },
            }
        }
    }


class _FakeResponse:
    def __init__(self, payload: Optional[dict[str, Any]] = None, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = ""

    def json(self) -> dict[str, Any]:
        assert self._payload is not None
        return self._payload


def _run_paginated_fetch(
    monkeypatch: pytest.MonkeyPatch,
    pages: list[_FakeResponse],
    *,
    limit: int = 20,
    board_date: Optional[date] = date(2026, 8, 9),
) -> tuple[Optional[list[dict[str, Any]]], list[dict[str, Any]]]:
    requests: list[dict[str, Any]] = []

    class Client:
        queue = list(pages)

        def __init__(self, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, **kwargs: Any) -> _FakeResponse:
            requests.append(kwargs["json"]["variables"])
            return self.queue.pop(0)

    monkeypatch.setattr(settings, "producthunt_api_token", "synthetic-token")
    monkeypatch.setattr(transport.httpx, "AsyncClient", Client)
    result = asyncio.run(transport.fetch_api_edges(limit, board_date))
    return result, requests


def test_paginates_with_cursor_until_leaving_board_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """两页收齐榜日：第二页最老条目越出榜日（08-08 < 08-09）即停。"""
    pages = [
        _FakeResponse(
            _page(
                [
                    _edge("1", "2026-08-09T20:00:00Z"),
                    _edge("2", "2026-08-09T15:00:00Z"),
                ],
                "cursor-1",
            )
        ),
        _FakeResponse(
            _page(
                [
                    _edge("3", "2026-08-09T10:00:00Z"),
                    _edge("4", "2026-08-08T23:00:00Z"),
                ],
                "cursor-2",
            )
        ),
        _FakeResponse(_page([_edge("5", "2026-08-08T10:00:00Z")], None)),
    ]

    result, requests = _run_paginated_fetch(monkeypatch, pages)

    assert [request["after"] for request in requests] == [None, "cursor-1"]
    assert [edge["node"]["id"] for edge in result or []] == ["1", "2", "3", "4"]


def test_pagination_capped_at_max_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    """页页都在榜日内且有下一页：翻满 _MAX_PAGES 页即截断，不无限翻。"""
    pages = [
        _FakeResponse(
            _page([_edge(f"{page}-1", "2026-08-09T10:00:00Z")], f"cursor-{page}")
        )
        for page in range(transport._MAX_PAGES + 2)
    ]

    result, requests = _run_paginated_fetch(monkeypatch, pages)

    assert len(requests) == transport._MAX_PAGES
    assert len(result or []) == transport._MAX_PAGES


def test_first_page_failure_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """首页失败 = 通道不可用，回退 HTML；401 同样判死。"""
    result, _ = _run_paginated_fetch(monkeypatch, [_FakeResponse(status_code=500)])
    assert result is None

    result, _ = _run_paginated_fetch(monkeypatch, [_FakeResponse(status_code=401)])
    assert result is None


def test_later_page_failure_returns_partial_edges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """后续页失败：返回已收集的部分榜日（下游严格过滤，无伪造数据）。"""
    pages = [
        _FakeResponse(_page([_edge("1", "2026-08-09T20:00:00Z")], "cursor-1")),
        _FakeResponse(status_code=500),
    ]

    result, requests = _run_paginated_fetch(monkeypatch, pages)

    assert len(requests) == 2
    assert [edge["node"]["id"] for edge in result or []] == ["1"]


def test_without_board_date_paginates_until_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """兼容路径（无榜日锚点）：按 limit 收够即停。"""
    pages = [
        _FakeResponse(
            _page([_edge(f"1-{idx}", "2026-08-09T10:00:00Z") for idx in range(20)], "c1")
        ),
        _FakeResponse(
            _page([_edge(f"2-{idx}", "2026-08-09T09:00:00Z") for idx in range(20)], "c2")
        ),
    ]

    result, requests = _run_paginated_fetch(
        monkeypatch, pages, limit=25, board_date=None
    )

    assert len(requests) == 2
    assert len(result or []) == 40
