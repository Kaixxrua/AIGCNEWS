from __future__ import annotations

"""X/Twitter 爬虫包装器：watchlist 账号推文采集。

采集逻辑：
  - watchlist_provider 提供账号列表（默认读 TWITTER_WATCH_HANDLES env，
    DB 实现经 composition 注入，crawler 不感知来源）
  - XTransport 顺序抓取各账号近期推文（同步库经 asyncio.to_thread）
  - x_policy 过滤/打分/投影为标准条目
  - snapshot_date 默认当天物理日期（CST）；显式 target_date（回填/关榜轮）
    按指定日期归属并过滤

仅支持 daily 周期。
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, List, Optional

from backend.app.services.ingestion.base_crawler import (
    BaseCrawler,
    CrawlResult,
    today_cst,
)
from backend.app.services.ingestion.sources import x_policy
from backend.app.services.source_plugins import load_x_transport_class
from backend.app.services.source_plugins.x_source import (
    DEFAULT_INTER_ACCOUNT_DELAY,
    XAuthAbort,
    XAuthNotConfigured,
    XRateLimitAbort,
    XTransportProtocol,
    XTransportUnavailable,
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
    transport: 可注入 fake；缺省经 source_plugins loader 解析 XTransport
        实现类构造（特性开关关闭或插件缺失时抛 XTransportUnavailable），
        并读 TWITTER_INTER_ACCOUNT_DELAY_SECONDS 作为账号间隔基线。
    tweets_per_account: 缺省读 TWITTER_TWEETS_PER_ACCOUNT env（回落 20）。
    """

    def __init__(
        self,
        transport: Optional[XTransportProtocol] = None,
        watchlist_provider: Optional[Callable[[], list[str]]] = None,
        credential_provider: Optional[Callable[[], list[dict[str, Any]]]] = None,
        tweets_per_account: Optional[int] = None,
    ) -> None:
        if transport is not None:
            self._transport = transport
        else:
            transport_class = load_x_transport_class()
            if transport_class is None:
                raise XTransportUnavailable(
                    "X 源插件不可用（x_source_enabled 关闭或实现缺失）"
                )
            self._transport = transport_class(
                credential_provider=credential_provider,
                inter_account_delay=_env_inter_account_delay(),
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
        # 显式 target_date 保留历史 CST 日历日回填语义；默认采集固定 UTC
        # 滚动窗口，window_end 在本轮入口只取一次，避免账号间窗口漂移。
        snapshot_date = target_date or today_cst()
        window_end = datetime.now(timezone.utc)
        window_start = window_end - timedelta(hours=24)
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
            if target_date:
                tweets_by_handle = await self._transport.fetch_watchlist_tweets(
                    handles,
                    self._tweets_per_account,
                )
                tweets = [tweet for batch in tweets_by_handle.values() for tweet in batch]
                tweets = x_policy.filter_tweets_to_snapshot_date(tweets, snapshot_date)
                timeline = False
            else:
                window_fetch = getattr(self._transport, "fetch_watchlist_tweets_window", None)
                if callable(window_fetch):
                    tweets_by_handle = await window_fetch(
                        handles,
                        window_start=window_start,
                        window_end=window_end,
                        count_per_user=self._tweets_per_account,
                    )
                else:
                    # 旧私有插件/测试替身兼容：旧接口结果仍经窗口过滤，
                    # 但其固定 count 可能无法覆盖完整窗口，日志会明确标识。
                    tweets_by_handle = await self._transport.fetch_watchlist_tweets(
                        handles,
                        self._tweets_per_account,
                    )
                tweets = [tweet for batch in tweets_by_handle.values() for tweet in batch]
                tweets = x_policy.filter_tweets_to_window(
                    tweets,
                    window_start=window_start,
                    window_end=window_end,
                )
                timeline = True
        except (XAuthNotConfigured, XAuthAbort, XRateLimitAbort, XTransportUnavailable) as exc:
            # 中止级故障：整轮失败，走 ingestion_tasks 失败面（响亮、不连锤）
            return CrawlResult(
                source="x",
                source_channel=channel,
                snapshot_date=snapshot_date,
                period="daily",
                items=[],
                error=str(exc),
            )

        fetched_count = sum(len(batch) for batch in tweets_by_handle.values())
        items = x_policy.project_tweets(
            tweets,
            limit=None if timeline else limit,
            source_channel=channel,
            timeline=timeline,
        )
        for item in items:
            item.setdefault("source", "x")
            item.setdefault("source_channel", channel)
            item.setdefault("channel", channel)

        logger.info(
            "[X] 爬虫完成: %d/%d 账号抓取 %d 条，窗口/快照过滤后 %d 条入库候选，"
            "mode=%s window=%s..%s snapshot=%s",
            len(tweets_by_handle),
            len(handles),
            fetched_count,
            len(items),
            "timeline" if timeline else "snapshot",
            window_start.isoformat(),
            window_end.isoformat(),
            snapshot_date,
        )

        return CrawlResult(
            source="x",
            source_channel=channel,
            snapshot_date=snapshot_date,
            period="daily",
            items=items,
        )

