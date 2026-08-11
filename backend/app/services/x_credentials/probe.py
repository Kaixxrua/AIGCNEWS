from __future__ import annotations

"""X cookie credential probing.

Provides both single-credential and pool-credential health checks. All probe
results are sanitized: no raw auth_token or ct0 is ever written to messages,
logs, or returned data.
"""

import asyncio
import logging
from typing import Any, Callable, Mapping

from backend.app.services.source_plugins import load_x_transport_class
from backend.app.services.source_plugins.x_source import (
    XAuthAbort,
    XAuthNotConfigured,
    XRateLimitAbort,
    XTransportProtocol,
    XTransportUnavailable,
)

logger = logging.getLogger(__name__)

PROBE_TWEET_COUNT = 2


def _build_transport(credential: Mapping[str, Any]) -> XTransportProtocol | None:
    """经插件加载器构造单凭证探测传输层；插件缺失时返回 None（fail closed）。"""
    transport_class = load_x_transport_class()
    if transport_class is None:
        return None
    return transport_class(
        credential_provider=lambda: [dict(credential)],
        inter_account_delay=0.0,
    )


def probe_x_credential(
    credential: Mapping[str, Any],
    handle: str,
    *,
    transport: XTransportProtocol | None = None,
) -> Mapping[str, Any]:
    """Probe a single credential against one watch handle.

    Args:
        credential: Row containing at least ``auth_token`` and ``ct0``.
        handle: The watch handle to fetch (callers should pass the first
            enabled handle, or return ``x_probe_no_watch_handle`` when empty).
        transport: Optional injected transport for testing.

    Returns:
        ``{"status": "succeeded" | "failed", "message": "..."}``.
    """
    if not handle:
        return {"status": "failed", "message": "x_probe_no_watch_handle"}

    probe_transport = transport or _build_transport(credential)
    if probe_transport is None:
        return {"status": "failed", "message": "x_transport_unavailable"}
    try:
        result = asyncio.run(
            probe_transport.fetch_watchlist_tweets([handle], PROBE_TWEET_COUNT)
        )
    except XAuthNotConfigured:
        return {"status": "failed", "message": "x_auth_not_configured"}
    except XAuthAbort:
        return {"status": "failed", "message": "x_auth_expired"}
    except XRateLimitAbort:
        return {"status": "failed", "message": "x_rate_limited"}
    except XTransportUnavailable:
        return {"status": "failed", "message": "x_transport_unavailable"}
    except Exception:  # noqa: BLE001
        logger.exception("[XCredentialProbe] 凭证探测出现意外异常")
        return {"status": "failed", "message": "x_probe_error"}

    if handle not in result:
        return {
            "status": "failed",
            "message": "x_probe_handle_missing",
        }
    tweets = result[handle]
    return {
        "status": "succeeded",
        "message": f"成功拉取 {len(tweets)} 条近期推文",
    }


def probe_all_x_credentials(
    credentials: list[Mapping[str, Any]],
    handle: str,
    *,
    update_result: Callable[[int, Mapping[str, Any]], Any] | None = None,
    transport: XTransportProtocol | None = None,
) -> list[dict[str, Any]]:
    """Serially probe every enabled credential and optionally persist results.

    Args:
        credentials: Already-ordered credential rows (normally from the
            repository's ``list_enabled_x_credentials`` method).
        handle: The first enabled watch handle to use as the probe target.
        update_result: Optional callback ``(credential_id, result)`` to write
            the result back to storage.
        transport: Optional injected transport for testing.

    Returns:
        A list of ``{"credential_id": int, "status": str, "message": str}``.
    """
    results: list[dict[str, Any]] = []
    if not handle:
        for credential in credentials:
            credential_id = int(credential.get("id") or 0)
            result = {
                "status": "failed",
                "message": "x_probe_no_watch_handle",
            }
            if update_result is not None:
                try:
                    update_result(credential_id, result)
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "[XCredentialProbe] 写入凭证 %d 测活结果失败", credential_id
                    )
            results.append({"credential_id": credential_id, **result})
        return results

    for credential in credentials:
        credential_id = int(credential.get("id") or 0)
        result = probe_x_credential(credential, handle, transport=transport)
        if update_result is not None:
            try:
                update_result(credential_id, result)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "[XCredentialProbe] 写入凭证 %d 测活结果失败", credential_id
                )
        results.append({"credential_id": credential_id, **result})
    return results
