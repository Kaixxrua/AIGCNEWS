from __future__ import annotations

"""DailyHot 聚合热榜爬虫包装器：封装 source_dailyhot.fetch_dailyhot_items。

上游为编排内网自托管 DailyHotApi（默认 http://dailyhot:6688，服务不可达时
返回 error CrawlResult，不影响其他源）。仅支持 daily 周期；
source_channel 固定 dailyhot_daily，端点名存于条目的 endpoint/feed_name 字段。
"""

import logging
from typing import List, Optional

from backend.app.core.config import settings
from backend.app.services.ingestion.base_crawler import (
    BaseCrawler,
    CrawlResult,
    today_cst,
)
from backend.app.services.ingestion.source_dailyhot import (
    SOURCE_CHANNEL,
    SOURCE_NAME,
    fetch_dailyhot_items,
    parse_endpoint_list,
)

logger = logging.getLogger(__name__)


class DailyHotCrawler(BaseCrawler):
    """DailyHot 聚合热榜爬虫（数据源：编排内网自托管 DailyHotApi）。

    端点清单由 settings.dailyhot_endpoints 提供（逗号分隔），
    每端点按 hot 降序保留 settings.dailyhot_per_endpoint_limit 条。
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        endpoints: list[str] | None = None,
        per_endpoint_limit: int | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._base_url = base_url or settings.dailyhot_api_base_url
        self._endpoints = (
            endpoints
            if endpoints is not None
            else parse_endpoint_list(settings.dailyhot_endpoints)
        )
        self._per_endpoint_limit = (
            per_endpoint_limit
            if per_endpoint_limit is not None
            else settings.dailyhot_per_endpoint_limit
        )
        self._timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.dailyhot_request_timeout_seconds
        )

    @property
    def source_name(self) -> str:
        return SOURCE_NAME

    @property
    def supported_periods(self) -> List[str]:
        return ["daily"]

    async def _do_fetch(
        self,
        period: str,
        limit: int,
        target_date: Optional[str] = None,
    ) -> CrawlResult:
        # snapshot_date 固定当天 CST 物理日期（与 hackernews 同一约定）。
        snapshot_date = today_cst()

        items = await fetch_dailyhot_items(
            base_url=self._base_url,
            endpoints=self._endpoints,
            per_endpoint_limit=self._per_endpoint_limit,
            timeout_seconds=self._timeout_seconds,
        )

        return CrawlResult(
            source=SOURCE_NAME,
            source_channel=SOURCE_CHANNEL,
            snapshot_date=snapshot_date,
            period="daily",
            items=items,
        )
