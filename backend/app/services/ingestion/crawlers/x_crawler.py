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

import asyncio
import logging
import os
from typing import Any, Callable, List, Optional

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


def _needs_zh_translation(lang: str) -> bool:
    """zh*（含 zh-cn/zh-tw）与 zxx（无语言内容，如纯媒体）不需要翻译。

    lang 缺失时仍尝试翻译（X 服务端自行判定），宁可多请求不漏翻。
    """
    code = (lang or "").strip().lower()
    return not code.startswith("zh") and code != "zxx"


class XCrawler(BaseCrawler):
    """X/Twitter 爬虫（数据源：twitter-cli 内部 GraphQL，cookie 凭据）。

    watchlist_provider: () -> list[str]，可注入（P3 切换为 DB 实现）。
    transport: 可注入 fake；缺省构造 XTransport 并读
        TWITTER_INTER_ACCOUNT_DELAY_SECONDS 作为账号间隔基线。
    tweets_per_account: 缺省读 TWITTER_TWEETS_PER_ACCOUNT env（回落 20）。
    translation_fetcher: 可注入的翻译抓取器 (tweet_ids) -> {id: 译文}；
        缺省回落 transport.fetch_tweet_translations（duck-typed，旧 fake
        transport 无此方法时自动跳过翻译附着）。
    """

    def __init__(
        self,
        transport: Optional[XTransport] = None,
        watchlist_provider: Optional[Callable[[], list[str]]] = None,
        credential_provider: Optional[Callable[[], list[dict[str, Any]]]] = None,
        tweets_per_account: Optional[int] = None,
        translation_fetcher: Optional[Callable[[list[str]], dict[str, str]]] = None,
    ) -> None:
        self._transport = (
            transport
            if transport is not None
            else XTransport(
                credential_provider=credential_provider,
                inter_account_delay=_env_inter_account_delay(),
            )
        )
        self._watchlist_provider = watchlist_provider or _env_watchlist_provider
        self._tweets_per_account = (
            tweets_per_account
            if tweets_per_account is not None
            else _env_tweets_per_account()
        )
        self._translation_fetcher = translation_fetcher

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
        # snapshot_date 默认当天 CST；显式 target_date（回填/关榜轮）按指定
        # 日期归属并过滤——关榜轮在次日 00:3x 采集昨日（D）推文，accumulate
        # 语义幂等补入 D 切片，收齐 hourly 末轮之后发布的尾巴推文。
        snapshot_date = target_date or today_cst()
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

        tweets = [tweet for batch in tweets_by_handle.values() for tweet in batch]
        # 日榜只收当天（CST）发布的推文：watchlist 抓的是账号近期 N 条，
        # 不过滤会把数周前的旧推文混进当天快照
        fetched_count = len(tweets)
        tweets = x_policy.filter_tweets_to_snapshot_date(tweets, snapshot_date)
        items = x_policy.project_tweets(tweets, limit=limit, source_channel=channel)
        await self._attach_zh_translations(tweets, items)
        for item in items:
            item.setdefault("source", "x")
            item.setdefault("source_channel", channel)
            item.setdefault("channel", channel)

        logger.info(
            "[X] 爬虫完成: %d/%d 账号抓取 %d 条，当日(CST)过滤后 %d 条入库候选，snapshot=%s",
            len(tweets_by_handle),
            len(handles),
            fetched_count,
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

    async def _attach_zh_translations(self, tweets: list[Any], items: list[dict]) -> None:
        """尽力而为：为最终入选的非中文推文附着 X 中文翻译（translation_zh）。

        仅对 project_tweets 截断后的条目抓取（请求量有界）；被引推文
        同口径补译，附着于 quote.translation_zh。翻译链路任何失败只记
        日志，绝不影响主采集结果入库。
        """
        fetcher = self._translation_fetcher or getattr(
            self._transport, "fetch_tweet_translations", None
        )
        if fetcher is None or not items:
            return
        lang_by_id = {
            str(getattr(tweet, "id", "")): str(getattr(tweet, "lang", "") or "")
            for tweet in tweets
        }
        tweets_by_id = {str(getattr(tweet, "id", "")): tweet for tweet in tweets}
        # 被引推文映射：quote 投影不含被引 id，只能经原始 Tweet 对象找回翻译主键
        quoted_by_outer: dict[str, Any] = {}
        for tweet in tweets:
            outer_id = str(getattr(tweet, "id", "") or "")
            quoted = getattr(tweet, "quoted_tweet", None)
            quote_id = str(getattr(quoted, "id", "") or "") if quoted is not None else ""
            if outer_id and quote_id:
                quoted_by_outer[outer_id] = quoted
        targets: list[str] = []
        for item in items:
            outer_id = str(item.get("tweet_id") or "")
            if outer_id and _needs_zh_translation(lang_by_id.get(outer_id, "")):
                targets.append(outer_id)
            quoted = quoted_by_outer.get(outer_id)
            if (
                quoted is not None
                and isinstance(item.get("quote"), dict)
                and _needs_zh_translation(str(getattr(quoted, "lang", "") or ""))
            ):
                targets.append(str(getattr(quoted, "id", "")))
        # 去重保序：被引推文可能同时是另一条入选外推（或自引），只请求一次
        targets = list(dict.fromkeys(targets))
        if not targets:
            return
        try:
            translations = await asyncio.to_thread(fetcher, targets)
        except Exception:
            logger.warning("[X] 中文翻译抓取失败，跳过（不影响入库）", exc_info=True)
            return
        attached = 0
        attached_quotes = 0
        for item in items:
            text = translations.get(str(item.get("tweet_id") or ""), "")
            if text:
                # X 译文会剥掉全部链接：按实体补回缺失链接（媒体尾巴除外）
                tweet = tweets_by_id.get(str(item.get("tweet_id") or ""))
                if tweet is not None:
                    text = x_policy.restore_translation_urls(
                        text,
                        str(getattr(tweet, "text", "") or ""),
                        item.get("media") or [],
                        getattr(tweet, "urls", None),
                    )
                item["translation_zh"] = text
                attached += 1
            # 被引推文同口径补译：附着于 quote.translation_zh（随 quote JSON 落库）
            quote = item.get("quote")
            quoted = quoted_by_outer.get(str(item.get("tweet_id") or ""))
            if not isinstance(quote, dict) or quoted is None:
                continue
            quote_text = translations.get(str(getattr(quoted, "id", "") or ""), "")
            if not quote_text:
                continue
            quote["translation_zh"] = x_policy.restore_translation_urls(
                quote_text,
                str(getattr(quoted, "text", "") or ""),
                quote.get("media") or [],
                getattr(quoted, "urls", None),
            )
            attached_quotes += 1
        logger.info(
            "[X] 中文翻译附着: 外推 %d 条、引文 %d 条（请求 %d 条）",
            attached,
            attached_quotes,
            len(targets),
        )
