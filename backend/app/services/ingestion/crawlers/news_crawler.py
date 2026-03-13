from __future__ import annotations

"""News 爬虫包装器：封装 source_news.fetch_news_articles。

采集 Techmeme 科技新闻（RSS + 主页 HTML 双通道）。

⚠️ 只支持 daily 周期：
  Techmeme RSS 和主页都是同一份滚动更新的内容，
  不存在独立的 weekly/monthly 榜单。
  之前支持三周期会导致同一份 RSS 被重复采集三次（约 10×3=30 条），
  实际独特内容只有约 15 条。
  现在改为仅 daily 周期，通过 RSS + HTML 双通道获取更多独特条目。
"""

import logging
from typing import List, Optional

from backend.app.services.ingestion.base_crawler import (
    BaseCrawler,
    CrawlResult,
    today_cst,
)
from backend.app.services.ingestion.source_news import fetch_news_articles

logger = logging.getLogger(__name__)


class NewsCrawler(BaseCrawler):
    """Techmeme 新闻爬虫（数据源：RSS + 主页 HTML 双通道）。

    ⚠️ 仅支持 daily 周期。
    Techmeme 没有独立的 weekly/monthly 榜单，
    RSS 和主页始终是同一份滚动更新内容。
    之前三周期重复采集导致"总是 30 条"的问题已修复。
    """

    @property
    def source_name(self) -> str:
        return "news"

    @property
    def supported_periods(self) -> List[str]:
        # 只支持 daily：Techmeme 没有独立的 weekly/monthly 榜单
        # RSS + 主页都是同一份内容，多周期采集只会重复
        return ["daily"]

    async def _do_fetch(
        self,
        period: str,
        limit: int,
        target_date: Optional[str] = None,
    ) -> CrawlResult:
        snapshot_date = target_date or today_cst()
        channel = "techmeme_daily_rss"

        items = fetch_news_articles(
            limit=limit,
            period="daily",  # 固定 daily
            target_date=target_date,
        )

        # 标准化字段
        for item in items:
            item.setdefault("source", "news")
            item.setdefault("source_channel", channel)
            item.setdefault("channel", channel)

        logger.info(
            "[News] 爬虫完成: %d 条（RSS + HTML 双通道），snapshot=%s",
            len(items),
            snapshot_date,
        )

        return CrawlResult(
            source="news",
            source_channel=channel,
            snapshot_date=snapshot_date,
            period="daily",
            items=items,
        )
