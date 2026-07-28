from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

MCP_PROTOCOL_VERSION = "2025-06-18"
MAX_TOOLS = 20
MAX_DESCRIPTION_LENGTH = 240


class McpProtocolError(ValueError):
    pass


def json_rpc_payload(
    method: str,
    params: Mapping[str, Any] | None = None,
    request_id: int | None = 1,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if request_id is not None:
        payload["id"] = request_id
    if params is not None:
        payload["params"] = dict(params)
    return payload


def response_id_matches(data: Mapping[str, Any], expected_id: int | None) -> bool:
    if expected_id is None:
        return True
    return data.get("id") in {expected_id, str(expected_id)}


def validate_json_rpc_data(
    data: Any,
    *,
    expected_id: int | None,
) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise McpProtocolError("MCP Server 响应格式不是 JSON 对象。")
    if data.get("error"):
        error = data["error"]
        if isinstance(error, dict):
            message = error.get("message") or error.get("code") or error
        else:
            message = error
        raise McpProtocolError(f"MCP Server JSON-RPC 错误：{message}")
    if not response_id_matches(data, expected_id):
        raise McpProtocolError("MCP Server JSON-RPC 响应 id 与请求不匹配。")
    return data


def parse_sse_event(event_data: list[str]) -> list[dict[str, Any]]:
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


def decode_sse_text(raw_text: str, *, expected_id: int | None) -> dict[str, Any]:
    event_data: list[str] = []
    candidates: list[dict[str, Any]] = []
    for line in raw_text.splitlines():
        if not line.strip():
            candidates.extend(parse_sse_event(event_data))
        elif not line.startswith(":") and line.startswith("data:"):
            event_data.append(line[5:].lstrip())
    candidates.extend(parse_sse_event(event_data))
    if not candidates:
        raise McpProtocolError("MCP Server 返回了 SSE，但未包含有效 JSON-RPC 数据。")
    if expected_id is not None:
        for item in candidates:
            if response_id_matches(item, expected_id):
                return validate_json_rpc_data(item, expected_id=expected_id)
    return validate_json_rpc_data(candidates[-1], expected_id=expected_id)


def extract_protocol_version(data: Any) -> str:
    if not isinstance(data, dict) or not isinstance(data.get("result"), dict):
        return ""
    return str(data["result"].get("protocolVersion") or "").strip()


def extract_tools(data: Any) -> list[dict[str, str]]:
    if not isinstance(data, dict) or not isinstance(data.get("result"), dict):
        return []
    raw_tools = data["result"].get("tools")
    if not isinstance(raw_tools, list):
        return []
    tools: list[dict[str, str]] = []
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


def initialize_payload() -> dict[str, Any]:
    return json_rpc_payload(
        "initialize",
        {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "aigc-news-admin", "version": "1.0.0"},
        },
        1,
    )


def initialized_payload() -> dict[str, Any]:
    return json_rpc_payload("notifications/initialized", request_id=None)


def tools_list_payload() -> dict[str, Any]:
    return json_rpc_payload("tools/list", {}, 2)
