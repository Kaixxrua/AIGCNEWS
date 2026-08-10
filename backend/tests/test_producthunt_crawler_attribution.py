from __future__ import annotations

import asyncio
from typing import Any

import pytest

from backend.app.services.ingestion.crawlers import producthunt_crawler as crawler_module

# 归属切换契约（PR2）：PH 日榜快照跟随 featuredAt 的太平洋日期众数，
# 不再按 CST 爬取日。北京时间上午抓到的仍是 PT 昨日榜，写入昨日切片
# 并随采集滚动补完；PT 翻页后写入新切片，昨日切片随之冻结。显式
# target_date（回填）保持优先；陈旧宽松兜底数据不得回写历史切片。

CRAWL_DATE = "2026-08-10"


def _item(featured_at: Any, **overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "title": "Synthetic Product",
        "url": "https://www.producthunt.com/posts/synthetic",
        "featured_at": featured_at,
    }
    item.update(overrides)
    return item


def _fetch(
    monkeypatch: pytest.MonkeyPatch,
    items: list[dict[str, Any]],
    target_date: str | None = None,
) -> crawler_module.CrawlResult:
    async def fake_fetch(**kwargs: Any) -> list[dict[str, Any]]:
        return items

    monkeypatch.setattr(crawler_module, "fetch_producthunt_products_async", fake_fetch)
    monkeypatch.setattr(crawler_module, "today_cst", lambda: CRAWL_DATE)
    crawler = crawler_module.ProductHuntCrawler()
    return asyncio.run(crawler.fetch(period="daily", limit=25, target_date=target_date))


def test_pt_yesterday_board_attributes_to_pt_featured_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CST 08-10 上午抓到 PT 08-09 的榜：快照归属 08-09 而非爬取日。"""
    result = _fetch(
        monkeypatch,
        [_item("2026-08-09T08:00:00-07:00"), _item("2026-08-09T15:30:00-07:00")],
    )

    assert result.ok
    assert result.snapshot_date == "2026-08-09"
    assert [item["snapshot_date"] for item in result.items] == [
        "2026-08-09",
        "2026-08-09",
    ]


def test_utc_featured_at_converts_to_pt_date_before_attribution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UTC 深夜时间戳是 PT 当天傍晚：换算后再参与归属。"""
    result = _fetch(monkeypatch, [_item("2026-08-10T05:00:00Z")])
    assert result.snapshot_date == "2026-08-09"


def test_board_date_mode_resists_stray_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """众数归属：个别陈旧/缺失 featured_at 的条目不拖走整页归属。"""
    result = _fetch(
        monkeypatch,
        [
            _item("2026-08-09T08:00:00-07:00"),
            _item("2026-08-09T09:00:00-07:00"),
            _item("2026-08-08T08:00:00-07:00"),
            _item(None),
            _item(""),
        ],
    )
    assert result.snapshot_date == "2026-08-09"


def test_stale_mode_does_not_rewrite_historical_slice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """守卫：众数落在 [爬取日-1, 爬取日] 之外（陈旧宽松兜底数据）时
    保持爬取日归属，绝不回写已定稿的历史切片。"""
    result = _fetch(
        monkeypatch,
        [
            _item("2026-08-05T08:00:00-07:00"),
            _item("2026-08-05T09:00:00-07:00"),
        ],
    )
    assert result.snapshot_date == CRAWL_DATE


def test_explicit_target_date_still_wins_for_backfill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """回填语义不变：显式 target_date 时不做 featured 归属推导。"""
    result = _fetch(
        monkeypatch,
        [_item("2026-08-09T08:00:00-07:00")],
        target_date="2026-08-01",
    )
    assert result.snapshot_date == "2026-08-01"


def test_missing_featured_at_falls_back_to_crawl_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _fetch(monkeypatch, [_item(None), _item("")])
    assert result.snapshot_date == CRAWL_DATE
    assert [item["snapshot_date"] for item in result.items] == [
        CRAWL_DATE,
        CRAWL_DATE,
    ]
