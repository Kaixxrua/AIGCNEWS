from __future__ import annotations

"""Arxiv 爬虫包装器：封装 source_arxiv_mcp.fetch_latest_papers。

采集 HuggingFace Papers 页面上的 Arxiv 论文，支持 daily/weekly/monthly 三周期。
"""

import logging
from typing import List, Optional

from backend.app.services.ingestion.base_crawler import (
    BaseCrawler,
    CrawlResult,
    today_cst,
)
from backend.app.services.ingestion.source_arxiv_mcp import fetch_latest_papers_async

logger = logging.getLogger(__name__)

_CHANNEL_MAP = {
    "daily": "huggingface_daily_html",
    "weekly": "huggingface_weekly_html",
    "monthly": "huggingface_monthly_html",
}


class ArxivCrawler(BaseCrawler):
    """Arxiv 论文爬虫（数据源：HuggingFace Papers 页面）。"""

    @property
    def source_name(self) -> str:
        return "arxiv"

    @property
    def supported_periods(self) -> List[str]:
        return ["daily", "weekly", "monthly"]

    async def _do_fetch(
        self,
        period: str,
        limit: int,
        target_date: Optional[str] = None,
    ) -> CrawlResult:
        snapshot_date = target_date or today_cst()
        channel = _CHANNEL_MAP.get(period, _CHANNEL_MAP["daily"])

        papers = await fetch_latest_papers_async(
            limit=limit,
            period=period,
            target_date=target_date,
        )

        # daily 榜可能回退到昨天/前天，快照必须归属实际命中的 HF 日期。
        if period == "daily" and papers:
            snapshot_date = str(papers[0].get("snapshot_date") or snapshot_date)

        # 标准化字段
        for p in papers:
            p.setdefault("source", "arxiv")
            p.setdefault("source_channel", channel)
            p.setdefault("channel", channel)
            p["snapshot_date"] = snapshot_date

        return CrawlResult(
            source="arxiv",
            source_channel=channel,
            snapshot_date=snapshot_date,
            period=period,
            items=papers,
        )
