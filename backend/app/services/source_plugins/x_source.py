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

from collections.abc import Iterable
from typing import Any, Protocol, runtime_checkable

# 凭据池模式下相邻账号请求间隔秒数（与实现侧默认值保持一致）。
DEFAULT_INTER_ACCOUNT_DELAY = 5.0


class XAuthNotConfigured(Exception):
    """缺少可用 X 凭据。"""


class XAuthAbort(Exception):
    """认证失效，中止整轮采集（避免死凭据连续锤击触发风控）。"""


class XRateLimitAbort(Exception):
    """触发限流（twitter-cli 内部退避后仍 429），中止整轮采集。"""


class XTransportUnavailable(Exception):
    """传输面系统性故障（代理断连/解析漂移等），整轮零成功时上抛。

    与单账号跳过区分：零星失败是账号个体问题，静默跳过；整轮零成功
    意味着基础设施级故障（2026-08-09 代理断连导致 16.5h 静默停摆），
    必须让采集轮以 error 收场进入调度失败面。
    """


@runtime_checkable
class XTransportProtocol(Protocol):
    """X 传输层公开方法面（采集爬虫与凭据/关注探针/janitor 仅依赖这些方法）。"""

    async def fetch_watchlist_tweets(
        self,
        handles: Iterable[str],
        count_per_user: int = 20,
    ) -> dict[str, list[Any]]:
        """按 watchlist 顺序抓取各账号近期推文，返回 {handle: [Tweet, ...]}。

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

    def probe_tweet_existence(self, tweet_ids: Iterable[str]) -> dict[str, str]:
        """逐条探测推文存活状态，返回 {tweet_id: alive/deleted/unavailable/unknown}。

        deleted 仅指原作者删除（墓碑文案/Unavailable Deleted/code 144）；
        Suspended/404/网络/解析漂移一律落在 unavailable/unknown（调用方
        据此 fail-closed 不删）。同步方法（内部走阻塞 HTTP），调用方应经
        asyncio.to_thread 转入线程池。

        Raises:
            XAuthNotConfigured: 无启用凭据（整轮中止）。
            XAuthAbort / XRateLimitAbort: 中止级故障，已探测部分结果丢弃。
        """
        ...
