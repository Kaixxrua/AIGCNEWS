"""X 采集源插件契约。

本模块只包含公开契约：异常类型、常量与传输层 Protocol。敏感实现
（twitter-cli 响应解析补丁、凭据池轮询、私有 GraphQL/REST 端点）位于
仓库外私有包 ``aigcnews_private``（经部署 overlay 注入 PYTHONPATH，
开源检出中不可得）。两侧实现共用本契约，公共代码不得反向依赖实现细节。

实现类构造约定（公共代码负责注入，签名以 ``XTransport.__init__`` 为准）：
``client_factory`` / ``credential_provider`` / ``credential_factory`` /
``inter_account_delay`` / ``id_cache`` / ``sleep`` 全部可注入、皆有默认值。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

# 凭据池模式下相邻账号请求间隔秒数（与实现侧默认值保持一致）。
DEFAULT_INTER_ACCOUNT_DELAY = 5.0


class XAuthNotConfigured(Exception):
    """缺少可用 X 凭据。"""


class XAuthAbort(Exception):
    """认证失效，中止整轮采集（避免死凭据连续锤击触发风控）。"""


class XRateLimitAbort(Exception):
    """凭据池耗尽后触发限流；单 client 路径立即中止整轮采集。

    provider 模式会在 429 后丢弃当前凭据的 partial 结果，并按配置顺序
    用下一凭据从完整 watchlist 开始串行重试；所有可用凭据均限流后才上抛。
    """


class XTransportUnavailable(Exception):
    """传输面系统性故障（代理断连/解析漂移等），整轮零成功时上抛。

    与单账号跳过区分：零星失败是账号个体问题，静默跳过；整轮零成功
    意味着基础设施级故障（2026-08-09 代理断连导致 16.5h 静默停摆），
    必须让采集轮以 error 收场进入调度失败面。
    """


# ── rolling-window 完整性契约 ────────────────────────────────────────────
#
# 滚动 24 小时采集的完整性证据：每个 handle 只有在「最早的**时间线外层条目**
# 时间戳 ≤ window_start」或「响应明确且结构完整地证明 timeline 已耗尽」时
# 才能标记 complete；否则该 handle 的 partial 结果一律视为不可入库。
#
# reason 只使用下列有限的无密安全码（crawler/日志据此给出稳定错误标记，
# 不得拼入 cookie、token、Authorization、代理凭据或原始 GraphQL 响应）：
X_WINDOW_REASONS = frozenset(
    {
        "boundary_reached",        # 已抓取到窗口下界（含恰好等于 window_start）
        "timeline_exhausted",      # 响应明确证明 timeline 到头
        "account_unavailable",     # 账号不存在/改名/保护/暂停（外部原因）
        "cursor_stalled",          # Bottom cursor 不再推进
        "pagination_metadata_missing",  # 未到边界却缺可验证 terminal 元数据
        "parser_drift",            # timeline 结构/instruction 解析漂移
        "page_limit_reached",      # 页安全预算耗尽仍未证明边界
        "transport_error",         # 单账号传输级故障（非凭据轮换理由）
    }
)


@dataclass(frozen=True)
class XWindowHandleResult:
    """单个 handle 的 rolling-window 抓取结果与完整性证据。

    ``tweets`` 仅在 ``complete=True`` 时可被上层消费；``complete=False``
    时允许携带 partial 供安全诊断，但绝不允许进入 enrich/persist/翻译链。
    """

    tweets: tuple[Any, ...] = ()
    complete: bool = False
    reason: str = "transport_error"
    page_count: int = 0
    fetched_count: int = 0
    oldest_seen: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "tweets", tuple(self.tweets))
        if self.reason not in X_WINDOW_REASONS:
            object.__setattr__(self, "reason", "transport_error")
        if self.oldest_seen is not None and self.oldest_seen.tzinfo is None:
            object.__setattr__(
                self, "oldest_seen", self.oldest_seen.replace(tzinfo=timezone.utc)
            )


@dataclass(frozen=True)
class XWindowFetchResult:
    """整轮 rolling-window 抓取结果：覆盖且仅覆盖请求的 handles。

    构造时归一化 handles 与窗口边界（UTC）；缺失或多余 handle 由 crawler
    判定为非法（不完整）。``complete`` 仅在每个 handle 都 complete 时为真。
    """

    requested_handles: tuple[str, ...] = ()
    window_start: datetime | None = None
    window_end: datetime | None = None
    by_handle: Mapping[str, XWindowHandleResult] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "requested_handles", tuple(self.requested_handles))
        object.__setattr__(self, "by_handle", dict(self.by_handle))
        for key in ("window_start", "window_end"):
            value = getattr(self, key)
            if value is not None and value.tzinfo is None:
                object.__setattr__(self, key, value.replace(tzinfo=timezone.utc))

    @property
    def complete(self) -> bool:
        """整轮完整 = 覆盖所有请求 handle 且每个 handle 均 complete。"""
        if set(self.by_handle) != set(self.requested_handles):
            return False
        return all(result.complete for result in self.by_handle.values())

    def incomplete_handles(self) -> tuple[str, ...]:
        """返回未证明完整的 handle（含缺失 handle），供诊断日志使用。"""
        return tuple(
            handle
            for handle in self.requested_handles
            if handle not in self.by_handle or not self.by_handle[handle].complete
        )


@runtime_checkable
class XTransportProtocol(Protocol):
    """X 传输层公开方法面（采集爬虫与凭据/关注探针/janitor 仅依赖这些方法）。"""

    async def fetch_watchlist_tweets(
        self,
        handles: Iterable[str],
        count_per_user: int = 20,
    ) -> dict[str, list[Any]]:
        """按 watchlist 顺序逐账号抓取近期推文，返回 {handle: [Tweet, ...]}。

        provider 模式下，账号级 429 会放弃当前凭据的 partial 结果，
        用下一凭据从完整 watchlist 串行重试；凭据池耗尽才抛出限流异常。

        Raises:
            XAuthNotConfigured: 凭据未配置。
            XAuthAbort / XRateLimitAbort: 中止级故障，调用方应整轮失败。
        """
        ...

    async def fetch_watchlist_tweets_window(
        self,
        handles: Iterable[str],
        *,
        window_start: datetime,
        window_end: datetime,
        count_per_user: int = 20,
    ) -> XWindowFetchResult:
        """抓取固定 UTC 半开窗口 ``[window_start, window_end)`` 内的推文。

        必须沿 Bottom cursor 分页直到每个账号都证明窗口覆盖完整
        （``XWindowFetchResult.complete`` 为真），并以
        ``XWindowFetchResult`` 返回逐 handle 的 ``XWindowHandleResult``。
        ``count_per_user`` 仅作为单页大小提示，不再是窗口总条数上限。

        账号请求保持串行；provider 模式遇到 429/认证失效（含第二页以后）
        时丢弃当前凭据全部 partial，按配置顺序切换凭据并从完整 watchlist
        第一个账号重试；失败凭据的 partial 结果不会返回。

        不再回退到 count 驱动的 ``fetch_watchlist_tweets``：缺少本方法、
        返回 plain dict 或任何 ``complete=False`` 都由 crawler fail-closed
        判定为 ``x_window_incomplete``，绝不伪装成完整覆盖。

        Raises:
            XAuthNotConfigured: 凭据未配置。
            XAuthAbort / XRateLimitAbort: 中止级故障，调用方应整轮失败。
        """
        ...

    def fetch_tweet_translations(self, tweet_ids: Iterable[str]) -> dict[str, str]:
        """尽力而为抓 X 自带中文翻译，返回 {tweet_id: 译文}。

        同步方法（内部走阻塞 HTTP），调用方应经 asyncio.to_thread 转入
        线程池。任何异常都不上抛：翻译是增强不是阻断项。
        """
        ...

    def probe_tweet_existence(
        self,
        tweet_ids: Iterable[str],
        authors: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        """逐条探测推文存活状态，返回 {tweet_id: alive/deleted/unavailable/unknown}。

        deleted 仅指原作者删除（墓碑文案/Unavailable Deleted/code 144，或
        推文本体不可见且作者账号存活公开——2026-08-13 实测作者删帖形态
        为 HTTP 200 空 tweetResult，须经 authors 交叉验证区分账号连坐）；
        Suspended/404/网络/解析漂移一律落在 unavailable/unknown（调用方
        据此 fail-closed 不删）。authors 为 {tweet_id: screen_name}；同步
        方法（内部走阻塞 HTTP），调用方应经 asyncio.to_thread 转入线程池。

        Raises:
            XAuthNotConfigured: 无启用凭据（整轮中止）。
            XAuthAbort / XRateLimitAbort: 中止级故障，已探测部分结果丢弃。
        """
        ...
