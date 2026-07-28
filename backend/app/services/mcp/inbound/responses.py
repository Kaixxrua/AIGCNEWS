from __future__ import annotations

import json
from typing import Any

from backend.app.services.mcp.inbound.catalog import (
    MAX_RESOURCE_TEXT_CHARS,
    MAX_TOOL_RESULT_CHARS,
)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _tool_response(data: dict[str, Any], *, is_error: bool = False) -> dict[str, Any]:
    safe_data = _json_safe(data)
    text = json.dumps(safe_data, ensure_ascii=False)
    if len(text) > MAX_TOOL_RESULT_CHARS:
        safe_data = {
            "truncated": True,
            "reason": f"Tool result exceeded {MAX_TOOL_RESULT_CHARS} characters.",
            "preview": text[:MAX_TOOL_RESULT_CHARS],
        }
        text = json.dumps(safe_data, ensure_ascii=False)
    result: dict[str, Any] = {"content": [{"type": "text", "text": text}], "isError": is_error}
    if not is_error:
        result["structuredContent"] = safe_data
    return result


def _tool_error(message: str) -> dict[str, Any]:
    return _tool_response({"error": message}, is_error=True)


def _resource_content(uri: str, data: Any, *, mime_type: str = "application/json") -> dict[str, Any]:
    if mime_type == "application/json":
        text = json.dumps(_json_safe(data), ensure_ascii=False)
        if len(text) > MAX_RESOURCE_TEXT_CHARS:
            text = json.dumps(
                {
                    "truncated": True,
                    "reason": f"Resource exceeded {MAX_RESOURCE_TEXT_CHARS} characters.",
                    "preview": text[:MAX_RESOURCE_TEXT_CHARS],
                },
                ensure_ascii=False,
            )
    else:
        text = str(data or "")
        if len(text) > MAX_RESOURCE_TEXT_CHARS:
            text = text[:MAX_RESOURCE_TEXT_CHARS] + "\n\n[truncated]"

    return {"contents": [{"uri": uri, "mimeType": mime_type, "text": text}]}
