from __future__ import annotations

"""X 关注账号探测：拉取单账号近期推文，同时验证 handle 有效性与 cookie 凭据。

供 /ops/x-watch-accounts/{id}/test 使用。传输层异常分级与采集器一致：
凭据未配置/失效/限流为响亮失败；账号不存在（传输层跳过）映射为
"请检查 handle" 的失败结果。
"""

import asyncio
import logging
from typing import Any, Mapping

from backend.app.services.ingestion.sources.x_transport import (
    XAuthAbort,
    XAuthNotConfigured,
    XRateLimitAbort,
    XTransport,
)

logger = logging.getLogger(__name__)

PROBE_TWEET_COUNT = 2


def test_x_watch_account(handle: str) -> Mapping[str, Any]:
    """同步探测入口（调用方经 asyncio.to_thread 转入线程池）。"""
    transport = XTransport(inter_account_delay=0.0)
    return probe_x_watch_account(handle, transport)


def probe_x_watch_account(handle: str, transport: Any) -> Mapping[str, Any]:
    """用给定传输层探测单账号，返回 {"status", "message"} 结果。"""
    try:
        result = asyncio.run(transport.fetch_watchlist_tweets([handle], PROBE_TWEET_COUNT))
    except XAuthNotConfigured as exc:
        return {"status": "failed", "message": str(exc)}
    except XAuthAbort as exc:
        return {"status": "failed", "message": str(exc)}
    except XRateLimitAbort as exc:
        return {"status": "failed", "message": str(exc)}
    except Exception as exc:  # 传输层以外的意外故障（网络、解析等）
        logger.exception("[XWatchProbe] 账号 %s 探测出现意外异常", handle)
        return {"status": "failed", "message": f"x_probe_error: {exc}"}

    if handle not in result:
        return {
            "status": "failed",
            "message": "未拉取到该账号：handle 不存在、已改名或抓取被跳过，请检查拼写",
        }
    tweets = result[handle]
    return {"status": "succeeded", "message": f"成功拉取 {len(tweets)} 条近期推文"}
