from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any

from starlette.requests import Request

from backend.app.services.mcp.inbound.catalog import (
    _JSONRPC_INVALID_PARAMS,
    _JSONRPC_INVALID_REQUEST,
    _JSONRPC_PARSE_ERROR,
    MAX_REQUEST_BYTES,
    MCP_PROTOCOL_VERSION,
)


@dataclass(frozen=True)
class McpRequestError(Exception):
    """JSON-RPC request validation failure with its preserved wire projection."""

    request_id: Any
    code: int
    message: str


@dataclass(frozen=True)
class McpInboundRequest:
    """Validated inbound JSON-RPC request fields consumed by the route adapter."""

    request_id: Any
    method: str
    params: dict[str, Any]
    has_id: bool

    @property
    def is_initialized_notification(self) -> bool:
        return self.method == "notifications/initialized" and not self.has_id


@dataclass(frozen=True)
class McpAuthorizationContext:
    """Bounded identity and scope view for one inbound MCP request."""

    user: dict[str, Any] | None

    @property
    def is_authenticated(self) -> bool:
        return self.user is not None

    @property
    def user_id(self) -> int:
        try:
            return int((self.user or {}).get("user_id") or 0)
        except (TypeError, ValueError):
            return 0

    def has_scope(self, scope: str) -> bool:
        return scope in (self.user or {}).get("scopes", frozenset())


@dataclass(frozen=True)
class McpSessionTransport:
    """Stateless MCP response header and initialize-session policy."""

    protocol_version: str = MCP_PROTOCOL_VERSION

    def headers(self, session_id: str | None = None) -> dict[str, str]:
        headers = {"MCP-Protocol-Version": self.protocol_version}
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        return headers

    def new_session_id(self) -> str:
        return f"aigc-news-{uuid.uuid4().hex}"


async def parse_mcp_request(request: Request) -> McpInboundRequest:
    """Read and validate the bounded JSON-RPC envelope without dispatching it."""

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_REQUEST_BYTES:
                raise McpRequestError(
                    None, _JSONRPC_INVALID_REQUEST, "Request body too large"
                )
        except ValueError:
            raise McpRequestError(
                None, _JSONRPC_INVALID_REQUEST, "Invalid Content-Length"
            ) from None

    raw = await request.body()
    if len(raw) > MAX_REQUEST_BYTES:
        raise McpRequestError(None, _JSONRPC_INVALID_REQUEST, "Request body too large")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, JSONDecodeError):
        raise McpRequestError(None, _JSONRPC_PARSE_ERROR, "Parse error") from None

    if isinstance(payload, list):
        raise McpRequestError(
            None,
            _JSONRPC_INVALID_REQUEST,
            "Batch JSON-RPC requests are not supported",
        )
    if not isinstance(payload, dict):
        raise McpRequestError(None, _JSONRPC_INVALID_REQUEST, "Invalid Request")

    request_id = payload.get("id")
    if request_id is not None and not isinstance(request_id, (str, int, float)):
        raise McpRequestError(None, _JSONRPC_INVALID_REQUEST, "Invalid request id")
    if payload.get("jsonrpc") != "2.0":
        raise McpRequestError(
            request_id, _JSONRPC_INVALID_REQUEST, "Invalid JSON-RPC version"
        )

    method = payload.get("method")
    if not isinstance(method, str) or not method:
        raise McpRequestError(request_id, _JSONRPC_INVALID_REQUEST, "Missing method")

    if "params" not in payload:
        params: dict[str, Any] = {}
    else:
        raw_params = payload["params"]
        if not isinstance(raw_params, dict):
            raise McpRequestError(
                request_id, _JSONRPC_INVALID_PARAMS, "params must be an object"
            )
        params = raw_params

    inbound = McpInboundRequest(
        request_id=request_id,
        method=method,
        params=params,
        has_id="id" in payload,
    )
    if not inbound.has_id and not inbound.is_initialized_notification:
        raise McpRequestError(
            None, _JSONRPC_INVALID_REQUEST, "Request id is required"
        )
    return inbound
