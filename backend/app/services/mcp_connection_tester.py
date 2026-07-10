from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

MAX_MESSAGE_LENGTH = 500
MAX_TOOLS = 20
MAX_DESCRIPTION_LENGTH = 240
MAX_RESPONSE_BYTES = 1_000_000
MCP_PROTOCOL_VERSION = "2025-06-18"


class McpConnectionTestError(ValueError):
    """Raised when an MCP server config cannot be tested safely."""


def _sanitize_message(value: Any, token: str = "") -> str:
    message = str(value or "").strip()
    if token:
        message = message.replace(token, "****")
    if len(message) > MAX_MESSAGE_LENGTH:
        return message[: MAX_MESSAGE_LENGTH - 1] + "…"
    return message


def validate_mcp_http_url(url: str) -> str:
    clean_url = (url or "").strip()
    parsed = urlparse(clean_url)
    if parsed.scheme not in {"http", "https"}:
        raise McpConnectionTestError("MCP Server URL 只支持 http 或 https。")
    if not parsed.netloc:
        raise McpConnectionTestError("MCP Server URL 缺少主机名。")
    if parsed.username or parsed.password:
        raise McpConnectionTestError("MCP Server URL 不允许包含用户名或密码。")
    return clean_url


def _mcp_payload(method: str, params: Dict[str, Any] | None = None, request_id: Optional[int] = 1) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "jsonrpc": "2.0",
        "method": method,
    }
    if request_id is not None:
        payload["id"] = request_id
    if params is not None:
        payload["params"] = params
    return payload


def _extract_tools(data: Any) -> List[Dict[str, str]]:
    if not isinstance(data, dict):
        return []
    result = data.get("result")
    if not isinstance(result, dict):
        return []
    raw_tools = result.get("tools")
    if not isinstance(raw_tools, list):
        return []

    tools: List[Dict[str, str]] = []
    for tool in raw_tools[:MAX_TOOLS]:
        if not isinstance(tool, dict):
            continue
        name = str(tool.get("name") or "").strip()
        if not name:
            continue
        description = str(tool.get("description") or "").strip()
        if len(description) > MAX_DESCRIPTION_LENGTH:
            description = description[: MAX_DESCRIPTION_LENGTH - 1] + "…"
        tools.append({"name": name, "description": description})
    return tools


def _extract_protocol_version(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    result = data.get("result")
    if not isinstance(result, dict):
        return ""
    return str(result.get("protocolVersion") or "").strip()


def _response_id_matches(data: Dict[str, Any], expected_id: Optional[int]) -> bool:
    if expected_id is None:
        return True
    return data.get("id") in {expected_id, str(expected_id)}


def _validate_json_rpc_data(data: Any, *, expected_id: Optional[int]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise McpConnectionTestError("MCP Server 响应格式不是 JSON 对象。")
    if data.get("error"):
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("code") or error
        else:
            message = error
        raise McpConnectionTestError(f"MCP Server JSON-RPC 错误：{message}")
    if not _response_id_matches(data, expected_id):
        raise McpConnectionTestError("MCP Server JSON-RPC 响应 id 与请求不匹配。")
    return data


def _parse_sse_event(event_data: List[str]) -> List[Dict[str, Any]]:
    if not event_data:
        return []
    raw_event = "\n".join(event_data).strip()
    event_data.clear()
    if not raw_event or raw_event == "[DONE]":
        return []
    try:
        parsed = json.loads(raw_event)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, dict):
        return [parsed]
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    return []


def _json_from_sse(raw_text: str, *, expected_id: Optional[int]) -> Dict[str, Any]:
    """Extract a JSON-RPC object from a complete SSE response body."""

    event_data: List[str] = []
    candidates: List[Dict[str, Any]] = []

    def flush_event() -> None:
        candidates.extend(_parse_sse_event(event_data))

    for line in raw_text.splitlines():
        if not line.strip():
            flush_event()
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            event_data.append(line[5:].lstrip())
    flush_event()

    if not candidates:
        raise McpConnectionTestError("MCP Server 返回了 SSE，但未包含有效 JSON-RPC 数据。")
    if expected_id is not None:
        for item in candidates:
            if _response_id_matches(item, expected_id):
                return _validate_json_rpc_data(item, expected_id=expected_id)
    return _validate_json_rpc_data(candidates[-1], expected_id=expected_id)


def _json_from_sse_stream(response: httpx.Response, *, expected_id: Optional[int]) -> Dict[str, Any]:
    """Read an SSE stream only until the expected JSON-RPC response arrives."""

    event_data: List[str] = []
    last_candidate: Dict[str, Any] | None = None
    bytes_seen = 0

    def handle_candidates(candidates: List[Dict[str, Any]]) -> Dict[str, Any] | None:
        nonlocal last_candidate
        for item in candidates:
            last_candidate = item
            if item.get("error") and (item.get("id") in {None, expected_id, str(expected_id)}):
                return _validate_json_rpc_data(item, expected_id=None)
            if _response_id_matches(item, expected_id):
                return _validate_json_rpc_data(item, expected_id=expected_id)
        return None

    for line in response.iter_lines():
        bytes_seen += len(line.encode("utf-8", errors="ignore"))
        if bytes_seen > MAX_RESPONSE_BYTES:
            raise McpConnectionTestError("MCP Server 响应过大，已停止解析。")
        if not line.strip():
            matched = handle_candidates(_parse_sse_event(event_data))
            if matched is not None:
                return matched
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            event_data.append(line[5:].lstrip())

    matched = handle_candidates(_parse_sse_event(event_data))
    if matched is not None:
        return matched
    if last_candidate is not None:
        return _validate_json_rpc_data(last_candidate, expected_id=expected_id)
    raise McpConnectionTestError("MCP Server 返回了 SSE，但未包含有效 JSON-RPC 数据。")


def _decode_json_rpc_response(response: httpx.Response, *, expected_id: Optional[int]) -> Dict[str, Any]:
    content_type = response.headers.get("content-type", "").lower()
    if "text/event-stream" in content_type:
        return _json_from_sse_stream(response, expected_id=expected_id)

    raw = response.read()
    if len(raw) > MAX_RESPONSE_BYTES:
        raise McpConnectionTestError("MCP Server 响应过大，已停止解析。")
    text = raw.decode(response.encoding or "utf-8", errors="replace").strip()
    if not text:
        raise McpConnectionTestError("MCP Server 返回空响应。")

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise McpConnectionTestError("MCP Server 未返回有效的 JSON-RPC 响应。") from exc
    return _validate_json_rpc_data(data, expected_id=expected_id)


def _post_json_rpc(
    client: httpx.Client,
    url: str,
    payload: Dict[str, Any],
    *,
    expect_response: bool = True,
) -> tuple[Dict[str, Any], httpx.Headers]:
    # Streamable HTTP MCP servers may return text/event-stream responses that stay
    # open. Stream the response and stop reading as soon as the matching JSON-RPC
    # result arrives, rather than waiting for the HTTP body to close.
    with client.stream("POST", url, json=payload) as response:
        headers = httpx.Headers(response.headers)
        if response.status_code in {401, 403}:
            raise McpConnectionTestError("MCP Server 鉴权失败，请检查 Token。")
        if response.status_code >= 400:
            raise McpConnectionTestError(f"MCP Server 返回 HTTP {response.status_code}。")
        if not expect_response:
            return {}, headers
        return _decode_json_rpc_response(response, expected_id=payload.get("id")), headers


def test_mcp_server_connection(config: Dict[str, Any]) -> Dict[str, Any]:
    """Test HTTP MCP connectivity without executing arbitrary tools."""

    token = str(config.get("auth_token") or "").strip()
    try:
        url = validate_mcp_http_url(str(config.get("url") or ""))
        transport = (config.get("transport") or "streamable_http").strip().lower()
        if transport != "streamable_http":
            raise McpConnectionTestError("当前仅支持 HTTP/Streamable HTTP MCP Server 测试。")

        auth_type = (config.get("auth_type") or "none").strip().lower()
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        }
        if auth_type == "bearer" and token:
            headers["Authorization"] = f"Bearer {token}"

        initialize_params = {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "aigc-news-admin", "version": "1.0.0"},
        }
        with httpx.Client(
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
            follow_redirects=False,
            trust_env=True,
            headers=headers,
        ) as client:
            initialize_data, initialize_headers = _post_json_rpc(
                client,
                url,
                _mcp_payload("initialize", initialize_params, 1),
            )
            session_id = initialize_headers.get("mcp-session-id")
            if session_id:
                client.headers["Mcp-Session-Id"] = session_id
            negotiated_version = _extract_protocol_version(initialize_data)
            if negotiated_version:
                client.headers["MCP-Protocol-Version"] = negotiated_version

            # MCP clients should acknowledge initialization before making other requests.
            # This notification has no id and may legitimately return an empty/202/204 response.
            try:
                _post_json_rpc(
                    client,
                    url,
                    _mcp_payload("notifications/initialized", request_id=None),
                    expect_response=False,
                )
            except McpConnectionTestError:
                raise
            except httpx.RequestError:
                raise
            tools_data, _ = _post_json_rpc(client, url, _mcp_payload("tools/list", {}, 2))
            tools = _extract_tools(tools_data)
            message = "连接成功。"
            if tools:
                message = f"连接成功，发现 {len(tools)} 个工具。"
            return {"status": "success", "message": message, "tools": tools}
    except McpConnectionTestError as exc:
        return {"status": "failed", "message": _sanitize_message(exc, token), "tools": []}
    except httpx.TimeoutException as exc:
        return {"status": "failed", "message": _sanitize_message(f"连接 MCP Server 超时：{exc}", token), "tools": []}
    except httpx.RequestError as exc:
        return {"status": "failed", "message": _sanitize_message(f"无法连接 MCP Server：{exc}", token), "tools": []}
    except Exception as exc:
        return {"status": "failed", "message": _sanitize_message(f"MCP 测试失败：{exc}", token), "tools": []}
