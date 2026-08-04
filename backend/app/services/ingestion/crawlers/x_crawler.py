from __future__ import annotations

"""X/Twitter 爬虫包装器：watchlist 账号推文采集。

采集逻辑：
  - watchlist_provider 提供账号列表（默认读 TWITTER_WATCH_HANDLES env，
    DB 实现经 composition 注入，crawler 不感知来源）
  - XTransport 顺序抓取各账号近期推文（同步库经 asyncio.to_thread）
  - x_policy 过滤/打分/投影为标准条目
  - snapshot_date 固定为当天物理日期（CST），确保日历查询正确

仅支持 daily 周期。
"""

import logging
import os
from typing import Callable, List, Optional

from backend.app.services.ingestion.base_crawler import (
    BaseCrawler,
    CrawlResult,
    today_cst,
)
from backend.app.services.ingestion.sources import x_policy
from backend.app.services.ingestion.sources.x_transport import (
    DEFAULT_INTER_ACCOUNT_DELAY,
    XAuthAbort,
    XAuthNotConfigured,
    XRateLimitAbort,
    XTransport,
)

logger = logging.getLogger(__name__)

DEFAULT_TWEETS_PER_ACCOUNT = 20


def _env_watchlist_provider() -> list[str]:
    """默认 watchlist 来源：TWITTER_WATCH_HANDLES 逗号分隔 env。"""
    return x_policy.parse_watch_handles(os.environ.get("TWITTER_WATCH_HANDLES", ""))


def _env_tweets_per_account() -> int:
    """TWITTER_TWEETS_PER_ACCOUNT env，非法/缺省回落 DEFAULT_TWEETS_PER_ACCOUNT。"""
    raw = os.environ.get("TWITTER_TWEETS_PER_ACCOUNT", "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return DEFAULT_TWEETS_PER_ACCOUNT


def _env_inter_account_delay() -> float:
    """TWITTER_INTER_ACCOUNT_DELAY_SECONDS env，非法/缺省回落默认基线。"""
    raw = os.environ.get("TWITTER_INTER_ACCOUNT_DELAY_SECONDS", "").strip()
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_INTER_ACCOUNT_DELAY
    return value if value > 0 else DEFAULT_INTER_ACCOUNT_DELAY


class XCrawler(BaseCrawler):
    """X/Twitter 爬虫（数据源：twitter-cli 内部 GraphQL，cookie 凭据）。

    watchlist_provider: () -> list[str]，可注入（P3 切换为 DB 实现）。
    transport: 可注入 fake；缺省构造 XTransport 并读
        TWITTER_INTER_ACCOUNT_DELAY_SECONDS 作为账号间隔基线。
    tweets_per_account: 缺省读 TWITTER_TWEETS_PER_ACCOUNT env（回落 20）。
    """

    def __init__(
        self,
        transport: Optional[XTransport] = None,
        watchlist_provider: Optional[Callable[[], list[str]]] = None,
        tweets_per_account: Optional[int] = None,
    ) -> None:
        self._transport = (
            transport
            if transport is not None
            else XTransport(inter_account_delay=_env_inter_account_delay())
        )
        self._watchlist_provider = watchlist_provider or _env_watchlist_provider
        self._tweets_per_account = (
            tweets_per_account
            if tweets_per_account is not None
            else _env_tweets_per_account()
        )

    @property
    def source_name(self) -> str:
        return "x"

    @property
    def supported_periods(self) -> List[str]:
        return ["daily"]

    async def _do_fetch(
        self,
        period: str,
        limit: int,
        target_date: Optional[str] = None,
    ) -> CrawlResult:
        # snapshot_date 固定为当天 CST 物理日期，不使用 target_date
        snapshot_date = today_cst()
        channel = x_policy.X_CHANNEL

        handles = self._watchlist_provider()
        if not handles:
            logger.warning(
                "[X] watchlist 为空（TWITTER_WATCH_HANDLES 未配置或均被禁用），本轮 0 条"
            )
            return CrawlResult(
                source="x",
                source_channel=channel,
                snapshot_date=snapshot_date,
                period="daily",
                items=[],
            )

        try:
            tweets_by_handle = await self._transport.fetch_watchlist_tweets(
                handles,
                self._tweets_per_account,
            )
        except (XAuthNotConfigured, XAuthAbort, XRateLimitAbort) as exc:
            # 中止级故障：整轮失败，走 ingestion_tasks 失败面（响亮、不连锤）
            return CrawlResult(
                source="x",
                source_channel=channel,
                snapshot_date=snapshot_date,
                period="daily",
                items=[],
                error=str(exc),
            )

        tweets = [tweet for batch in tweets_by_handle.values() for tweet in batch]
        items = x_policy.project_tweets(tweets, limit=limit, source_channel=channel)
        for item in items:
            item.setdefault("source", "x")
            item.setdefault("source_channel", channel)
            item.setdefault("channel", channel)

        logger.info(
            "[X] 爬虫完成: %d/%d 账号产出 %d 条（互动分降序 + rank_in_period），snapshot=%s",
            len(tweets_by_handle),
            len(handles),
            len(items),
            snapshot_date,
        )

        return CrawlResult(
            source="x",
            source_channel=channel,
            snapshot_date=snapshot_date,
            period="daily",
            items=items,
        )
