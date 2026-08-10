from __future__ import annotations

"""HackerNews 爬虫包装器：封装 source_hackernews.fetch_hackernews_items。

采集逻辑（v2 重构）：
  - 通过 HN 官方 Firebase API 获取首页 Top-30
  - 24小时时间过滤 → 按 score 降序 → 赋予 rank_in_period
  - snapshot_date 默认当天物理日期（CST）；显式 target_date（回填/关榜轮）
    按指定日期归属

仅支持 daily 周期。
"""

import logging
from typing import List, Optional

from backend.app.services.ingestion.base_crawler import (
    BaseCrawler,
    CrawlResult,
    today_cst,
)
from backend.app.services.ingestion.source_hackernews import (
    fetch_hackernews_items_async,
)

logger = logging.getLogger(__name__)


class HackerNewsCrawler(BaseCrawler):
    """Hacker News 爬虫（数据源：HN Firebase API Top-30）。

    采集规则：
      1. 取首页 topstories 前 30 条
      2. 排除发布时间超过 24 小时的帖子
      3. 按 score (Points) 降序排列
      4. rank_in_period 从 1 开始递增
      5. snapshot_date 默认当天 CST 日期；显式 target_date 按指定日期归属
    """

    @property
    def source_name(self) -> str:
        return "hackernews"

    @property
    def supported_periods(self) -> List[str]:
        return ["daily"]

    async def _do_fetch(
        self,
        period: str,
        limit: int,
        target_date: Optional[str] = None,
    ) -> CrawlResult:
        # snapshot_date 默认当天 CST；显式 target_date（回填/关榜轮）按指定
        # 日期归属——关榜轮在次日 00:3x 把滚动 24h 窗口的终态写入昨日切片，
        # 收齐 hourly 末轮（23:0x）之后的排名/分数变化。
        snapshot_date = target_date or today_cst()
        channel = "hn_daily_html"

        items = await fetch_hackernews_items_async(
            limit=limit,
            period="daily",
        )

        # 标准化字段（source_hackernews.py 已设置 rank_in_period）
        for item in items:
            item.setdefault("source", "hackernews")
            item.setdefault("source_channel", channel)
            item.setdefault("channel", channel)

        logger.info(
            "[HackerNews] 爬虫完成: %d 条（24h内 + score降序 + rank_in_period），snapshot=%s",
            len(items),
            snapshot_date,
        )

        return CrawlResult(
            source="hackernews",
            source_channel=channel,
            snapshot_date=snapshot_date,
            period="daily",
            items=items,
        )
