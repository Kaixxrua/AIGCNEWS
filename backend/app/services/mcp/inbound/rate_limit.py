"""Redis fixed-window rate limiting for the public inbound MCP endpoint.

Anonymous callers are limited per client IP, authenticated callers per user;
expensive ``tools/call`` traffic is bucketed separately from cheap protocol
methods. Redis outages fail open (availability over strictness), mirroring the
auth rate-limit policy.
"""

from __future__ import annotations

import logging
from typing import Any

from starlette.requests import Request

from backend.app.services.auth.rate_limit import (
    RateLimitExceededError,
    hit_rate_limit,
)
from backend.app.services.mcp.inbound.application import McpProtocolResponse
from backend.app.services.mcp.inbound.context import McpSessionTransport

logger = logging.getLogger(__name__)

MCP_RATE_LIMIT_WINDOW_SECONDS = 60
MCP_PROTOCOL_BUCKET = "mcp.protocol"
MCP_TOOL_CALL_BUCKET = "mcp.tool_call"
MCP_ANONYMOUS_PROTOCOL_LIMIT = 60
MCP_ANONYMOUS_TOOL_CALL_LIMIT = 30
MCP_AUTHENTICATED_PROTOCOL_LIMIT = 240
MCP_AUTHENTICATED_TOOL_CALL_LIMIT = 120
MCP_JSONRPC_RATE_LIMITED = -32000


def mcp_client_ip(request: Request) -> str:
    """Resolve the caller IP behind a reverse proxy (first X-Forwarded-For hop)."""

    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def enforce_mcp_rate_limit(
    request: Request,
    *,
    method: str,
    user_id: int,
) -> None:
    """Consume one hit for this request; raise RateLimitExceededError when over.

    ``tools/call`` is bucketed separately because tool handlers may hit the
    database or the bounded GitHub API fallback. Anonymous callers are keyed
    by client IP with tighter limits; authenticated callers are keyed by user
    id. Redis unavailability fails open so the endpoint stays usable.
    """

    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        return
    if method == "tools/call":
        bucket = MCP_TOOL_CALL_BUCKET
        anonymous_limit = MCP_ANONYMOUS_TOOL_CALL_LIMIT
        authenticated_limit = MCP_AUTHENTICATED_TOOL_CALL_LIMIT
    else:
        bucket = MCP_PROTOCOL_BUCKET
        anonymous_limit = MCP_ANONYMOUS_PROTOCOL_LIMIT
        authenticated_limit = MCP_AUTHENTICATED_PROTOCOL_LIMIT
    if user_id > 0:
        identity = f"user:{user_id}"
        limit = authenticated_limit
    else:
        identity = f"ip:{mcp_client_ip(request)}"
        limit = anonymous_limit
    try:
        await hit_rate_limit(
            redis_client,
            action=bucket,
            identity=identity,
            limit=limit,
            window_seconds=MCP_RATE_LIMIT_WINDOW_SECONDS,
        )
    except RateLimitExceededError:
        raise
    except Exception:
        logger.warning("MCP rate limit skipped: redis unavailable", exc_info=True)


def mcp_rate_limited_projection(request_id: Any) -> McpProtocolResponse:
    """HTTP 429 projection with a JSON-RPC error body for throttled requests."""

    return McpProtocolResponse(
        status_code=429,
        body={
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": MCP_JSONRPC_RATE_LIMITED,
                "message": (
                    "Rate limit exceeded; slow down and retry after "
                    f"{MCP_RATE_LIMIT_WINDOW_SECONDS} seconds."
                ),
            },
        },
        headers={
            **McpSessionTransport().headers(),
            "Retry-After": str(MCP_RATE_LIMIT_WINDOW_SECONDS),
        },
    )
