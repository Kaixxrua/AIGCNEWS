from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Dict


class McpToolCallMetrics:
    """Thread-safe process-local counter for inbound MCP ``tools/call`` dispatches.

    Counts every validated tool-call attempt by name, including unknown tools
    and calls that later fail authorization or validation, so deprecated-tool
    usage stays observable from the monitor metrics endpoint. Counts reset on
    process restart; pair with ``uptime_seconds`` when reading snapshots.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._since = datetime.now(timezone.utc)
        self._calls: Dict[str, int] = {}
        self._last_called_at: Dict[str, datetime] = {}

    def record(self, tool_name: str) -> None:
        now = datetime.now(timezone.utc)
        with self._lock:
            self._calls[tool_name] = self._calls.get(tool_name, 0) + 1
            self._last_called_at[tool_name] = now

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            tools = {
                name: {
                    "calls": self._calls[name],
                    "last_called_at": self._last_called_at[name].isoformat(),
                }
                for name in sorted(self._calls)
            }
            total_calls = sum(self._calls.values())
            since = self._since.isoformat()
        return {"since": since, "total_calls": total_calls, "tools": tools}


MCP_TOOL_CALL_METRICS = McpToolCallMetrics()
