from __future__ import annotations

"""ProductHunt 爬虫包装器：封装 source_producthunt.fetch_producthunt_products。

采集 Product Hunt 主页热门产品，仅支持 daily 周期。
"""

import logging
from datetime import date, timedelta
from typing import List, Optional

from backend.app.services.ingestion import producthunt_policy
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

        # 归属切换（PR2）：PH 日榜跟随 featuredAt 的太平洋日期，不再按
        # CST 爬取日。北京时间上午抓到的仍是 PT 昨日榜，快照写入昨日
        # 切片并随每次采集滚动补完；PT 翻页后写入新一天切片，昨日切片
        # 随之冻结——静默期内的写入是自然发生的，与分源定稿契约对齐。
        # 显式 target_date（回填）保持优先，不做归属推导。
        if target_date is None:
            board_date = producthunt_policy.resolve_board_date(
                producthunt_policy.parse_featured_at(str(item.get("featured_at") or ""))
                for item in items
            )
            # 守卫：众数落在 [爬取日-1, 爬取日] 之外只可能来自陈旧的
            # 宽松兜底数据——不回写历史已定稿切片，保持爬取日归属。
            crawl_day = date.fromisoformat(snapshot_date)
            if (
                board_date is not None
                and crawl_day - timedelta(days=1) <= board_date <= crawl_day
            ):
                snapshot_date = board_date.isoformat()
        for item in items:
            item["snapshot_date"] = snapshot_date

        return CrawlResult(
            source="producthunt",
            source_channel=channel,
            snapshot_date=snapshot_date,
            period="daily",
            items=items,
        )
