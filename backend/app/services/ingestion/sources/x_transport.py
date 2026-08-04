from __future__ import annotations

"""X/Twitter 传输层：包装 twitter-cli 同步客户端的异步门面。

设计要点：
  - twitter-cli（curl_cffi + time.sleep）是同步库，所有调用经
    asyncio.to_thread 转入线程池，不阻塞事件循环
  - 账号顺序处理 + 账号间抖动延迟：凭据为主账号 cookie，
    温和节奏优先于吞吐（不并发 gather）
  - screen_name → user_id 模块级 24h 缓存：请求量减半
  - 异常分级：认证失效/限流 → 中止整轮（不拿死凭据锤其余账号）；
    单账号 NotFound/其他异常 → 记录并跳过

凭据来自环境变量 TWITTER_AUTH_TOKEN / TWITTER_CT0（twitter-cli 原生
约定；Settings 字段在调度配置提交中接入，二者读同一组 env）。
"""

import asyncio
import logging
import os
import random
import time
from typing import Any, Awaitable, Callable, Iterable, MutableMapping

from twitter_cli.exceptions import (
    AuthenticationError,
    NotFoundError,
    RateLimitError,
)

logger = logging.getLogger(__name__)

USER_ID_CACHE_TTL_SECONDS = 24 * 3600
DEFAULT_INTER_ACCOUNT_DELAY = 5.0

# screen_name(lower) -> (user_id, 过期时间戳)
_USER_ID_CACHE: dict[str, tuple[str, float]] = {}


def clear_user_id_cache() -> None:
    """清空 user_id 缓存（测试缝 + 运维排障用）。"""
    _USER_ID_CACHE.clear()


class XAuthNotConfigured(Exception):
    """缺少 TWITTER_AUTH_TOKEN / TWITTER_CT0 环境变量。"""


class XAuthAbort(Exception):
    """认证失效，中止整轮采集（避免死凭据连续锤击触发风控）。"""


class XRateLimitAbort(Exception):
    """触发限流（twitter-cli 内部退避后仍 429），中止整轮采集。"""


def _default_client_factory() -> Any:
    """从环境变量构造真实 TwitterClient（延迟导入，测试注入 fake 时不触碰）。"""
    from twitter_cli.client import TwitterClient

    auth_token = os.environ.get("TWITTER_AUTH_TOKEN", "").strip()
    ct0 = os.environ.get("TWITTER_CT0", "").strip()
    if not auth_token or not ct0:
        raise XAuthNotConfigured(
            "x_auth_not_configured: set TWITTER_AUTH_TOKEN and TWITTER_CT0"
        )
    return TwitterClient(auth_token, ct0)


class XTransport:
    """X 关注账号推文抓取传输层。

    client_factory: 可注入的客户端工厂（默认 _default_client_factory），
        签名 () -> 具有 fetch_user/fetch_user_tweets 同步方法的对象。
    id_cache: 可注入的 user_id 缓存映射（默认模块级缓存）。
    sleep: 可注入的延迟函数（默认 asyncio.sleep）。
    """

    def __init__(
        self,
        client_factory: Callable[[], Any] | None = None,
        *,
        inter_account_delay: float = DEFAULT_INTER_ACCOUNT_DELAY,
        id_cache: MutableMapping[str, tuple[str, float]] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._client_factory = client_factory or _default_client_factory
        self._inter_account_delay = inter_account_delay
        self._id_cache = id_cache if id_cache is not None else _USER_ID_CACHE
        self._sleep = sleep or asyncio.sleep

    async def fetch_watchlist_tweets(
        self,
        handles: Iterable[str],
        count_per_user: int = 20,
    ) -> dict[str, list[Any]]:
        """按 watchlist 顺序抓取各账号近期推文。

        Returns:
            {handle: [Tweet, ...]}；被跳过的账号不出现在结果中。

        Raises:
            XAuthNotConfigured: 凭据未配置（默认工厂）。
            XAuthAbort / XRateLimitAbort: 中止级故障，调用方应整轮失败。
        """
        client = self._client_factory()
        result: dict[str, list[Any]] = {}
        for index, handle in enumerate(handles):
            if index > 0:
                await self._sleep(self._jittered_delay())
            try:
                user_id = await self._resolve_user_id(client, handle)
                result[handle] = await asyncio.to_thread(
                    client.fetch_user_tweets, user_id, count_per_user
                )
            except AuthenticationError as exc:
                raise XAuthAbort(f"x_auth_expired: {exc}") from exc
            except RateLimitError as exc:
                raise XRateLimitAbort(f"x_rate_limited: {exc}") from exc
            except NotFoundError:
                logger.warning("[XTransport] 账号不存在/已注销/已改名，跳过: %s", handle)
            except Exception:
                logger.exception("[XTransport] 账号 %s 抓取失败，跳过", handle)
        return result

    async def _resolve_user_id(self, client: Any, handle: str) -> str:
        """screen_name → user_id，优先读 24h 缓存（省一次 UserByScreenName 请求）。"""
        key = handle.strip().lower()
        now = time.monotonic()
        cached = self._id_cache.get(key)
        if cached and cached[1] > now:
            return cached[0]
        profile = await asyncio.to_thread(client.fetch_user, handle)
        user_id = str(profile.id)
        self._id_cache[key] = (user_id, now + USER_ID_CACHE_TTL_SECONDS)
        return user_id

    def _jittered_delay(self) -> float:
        """账号间隔：基线 × [0.8, 1.6) 抖动，避免机械式固定节拍。"""
        return self._inter_account_delay * random.uniform(0.8, 1.6)
