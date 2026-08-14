from __future__ import annotations

"""GitHub Trending 爬虫包装器：封装 source_github_trending.fetch_github_trending。

直接爬取 github.com/trending 页面，仅采 daily 日榜。
weekly/monthly 榜单采集已退役（遗留看板，2026-08-14 起停止写入
github_trending_weekly / github_trending_monthly channel）；解析层的
多周期支持保留给 github_hot_service 项目库候选池使用。
"""

import logging
from typing import List, Optional

from backend.app.services.ingestion.base_crawler import (
    BaseCrawler,
    CrawlResult,
    today_cst,
)
from backend.app.services.ingestion.source_github_trending import (
    fetch_github_trending_async,
)

logger = logging.getLogger(__name__)

_CHANNEL_MAP = {
    "daily": "github_trending_daily",
}


class GitHubCrawler(BaseCrawler):
    """GitHub Trending 爬虫（数据源：github.com/trending 页面，仅日榜）。"""

    @property
    def source_name(self) -> str:
        return "github"

    @property
    def supported_periods(self) -> List[str]:
        return ["daily"]

    async def _do_fetch(
        self,
        period: str,
        limit: int,
        target_date: Optional[str] = None,
    ) -> CrawlResult:
        # GitHub Trending 是实时快照，snapshot_date 取 CST 当天
        snapshot_date = target_date or today_cst()
        channel = _CHANNEL_MAP.get(period, _CHANNEL_MAP["daily"])

        items = await fetch_github_trending_async(period=period, limit=limit)

        # 标准化字段（fetch_github_trending 已设置大部分字段）
        for item in items:
            item.setdefault("source", "github")
            item.setdefault("source_channel", channel)
            item.setdefault("channel", channel)

        return CrawlResult(
            source="github",
            source_channel=channel,
            snapshot_date=snapshot_date,
            period=period,
            items=items,
        )
