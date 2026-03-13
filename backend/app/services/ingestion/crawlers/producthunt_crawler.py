from __future__ import annotations

"""ProductHunt 爬虫包装器：封装 source_producthunt.fetch_producthunt_products。

采集 Product Hunt 主页热门产品，仅支持 daily 周期。
"""

import logging
from typing import List, Optional

from backend.app.services.ingestion.base_crawler import (
    BaseCrawler,
    CrawlResult,
    today_cst,
)
from backend.app.services.ingestion.source_producthunt import (
    fetch_producthunt_products_async,
)

logger = logging.getLogger(__name__)


class ProductHuntCrawler(BaseCrawler):
    """Product Hunt 爬虫（数据源：PH 主页 Apollo SSR Transport）。"""

    @property
    def source_name(self) -> str:
        return "producthunt"

    @property
    def supported_periods(self) -> List[str]:
        return ["daily"]

    async def _do_fetch(
        self,
        period: str,
        limit: int,
        target_date: Optional[str] = None,
    ) -> CrawlResult:
        snapshot_date = target_date or today_cst()
        channel = "producthunt_daily_html"

        items = await fetch_producthunt_products_async(
            limit=limit,
            period="daily",  # PH 本质上只有 daily
            target_date=target_date,
        )

        # 标准化字段
        for item in items:
            item.setdefault("source", "producthunt")
            item.setdefault("source_channel", channel)
            item.setdefault("channel", channel)

        return CrawlResult(
            source="producthunt",
            source_channel=channel,
            snapshot_date=snapshot_date,
            period="daily",
            items=items,
        )
