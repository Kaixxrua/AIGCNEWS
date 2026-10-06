from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Container
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Protocol

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

# 工具名基数封顶：未知名一律归入固定桶，防止攻击者用随机 tools/call name
# 无限膨胀计数器（每个新 name 都会永久落盘）。
UNKNOWN_TOOL_NAME = "__unknown__"
MAX_TOOL_NAME_LENGTH = 64

# MCP 工具名冻结表：生产 /api/mcp 已由 Go 网关服务（mcp-go/），Python 入站
# 工具栈退役（W6）后，本表是指标播种与分桶的唯一工具名来源。工具集变更 =
# 先改 Go catalog，再逐序同步本表（顺序即 tools/list 契约顺序）。
MCP_TOOL_NAMES: tuple[str, ...] = (
    "search_papers",
    "search_documents",
    "get_paper_detail",
    "get_top_items",
    "search_github_projects",
    "search_github_ai_projects",
    "get_project_categories",
    "submit_project_adoption",
    "search_my_project_favorites",
    "get_my_tracking",
)


def bucket_tool_name(tool_name: str, known_names: Container[str]) -> str:
    """把 tools/call 名归并到有限基数桶。

    仅 ``known_names``（MCP_TOOL_NAMES）内的名字保留原名单独统计；
    其余（含超长、空串）截断判定后统一归入 ``__unknown__`` 桶。已知工具
    名本身远短于上限，截断只影响未知名的判定路径。
    """
    name = tool_name.strip()[:MAX_TOOL_NAME_LENGTH]
    if name and name in known_names:
        return name
    return UNKNOWN_TOOL_NAME


# 客户端来源桶：仅 User-Agent 前缀命中已知客户端时单独成桶，其余一律空桶
# 不计数。与工具名同策略，防止随机 UA 字符串无限膨胀计数器基数（每个新桶
# 都会永久落盘）。
DSH_PLUGIN_CLIENT = "dsh-aigc-radar"
_CLIENT_UA_PREFIXES = ((DSH_PLUGIN_CLIENT, "dsh-aigc-radar/"),)

# 压测打标：scripts/benchmark_mcp_latency.py 等压测客户端以该 UA 前缀自我
# 标识；命中前缀的 tools/call 完全不进入本计数器（dashboard 的
# mcp_total_calls 不含压测流量）。打标不影响限流——压测仍受既有突发/配额
# 约束，以保证测量结果代表真实客户端体验。
BENCHMARK_UA_PREFIX = "mcp-latency-bench/"


def is_benchmark_user_agent(user_agent: Any) -> bool:
    """判断 User-Agent 是否为压测客户端；非字符串或空前缀不命中。"""
    if not isinstance(user_agent, str):
        return False
    return user_agent.strip().startswith(BENCHMARK_UA_PREFIX)


def bucket_client_name(user_agent: Any) -> str:
    """把 User-Agent 归并到已知客户端桶；未命中或非字符串一律返回空串。"""
    if not isinstance(user_agent, str):
        return ""
    ua = user_agent.strip()
    for bucket, prefix in _CLIENT_UA_PREFIXES:
        if ua.startswith(prefix):
            return bucket
    return ""


class McpToolCallStore(Protocol):
    """Persistence boundary for MCP tool-call counter state."""

    def load(self) -> Optional[Dict[str, Any]]:
        """Return the persisted payload, or ``None`` when missing/unreadable."""
        ...

    def save(self, payload: Dict[str, Any]) -> None:
        """Persist the payload, replacing any previous state."""
        ...


class JsonMcpToolCallStore:
    """Single-writer JSON file store with atomic replace and tolerant reads."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> Optional[Dict[str, Any]]:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            logger.warning(
                "mcp tool call metrics unreadable, starting empty path=%s err=%s",
                self._path,
                exc,
            )
            return None
        try:
            data = json.loads(raw)
        except ValueError:
            logger.warning(
                "mcp tool call metrics corrupt, starting empty path=%s", self._path
            )
            return None
        return data if isinstance(data, dict) else None

    def save(self, payload: Dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(self._path.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._path)


def _parse_iso(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class McpToolCallMetrics:
    """Thread-safe counter for inbound MCP ``tools/call`` dispatches.

    Counts every validated tool-call attempt by name, including unknown tools
    and calls that later fail authorization or validation, so deprecated-tool
    usage stays observable from the monitor metrics endpoint. Callers should
    pass names through :func:`bucket_tool_name` first so only registry-known
    tools are counted individually and everything else lands in the fixed
    ``__unknown__`` bucket (bounded cardinality on disk).

    With a ``store`` attached, state hydrates lazily on first use and persists
    on every ``record``, so counts and the first-use ``since`` timestamp
    survive process restarts. Persistence failures are logged and never break
    dispatch. Without a store the counter stays process-local and resets on
    restart; pair with ``uptime_seconds`` when reading such snapshots.

    ``record`` additionally accepts a known-client bucket (see
    :func:`bucket_client_name`) so calls from first-party clients such as the
    dsh plugin are counted alongside the per-tool totals. Client counts are
    persisted under the ``clients`` key of the same payload.
    """

    def __init__(self, store: McpToolCallStore | None = None) -> None:
        self._lock = threading.Lock()
        self._store = store
        self._loaded = store is None
        self._since = datetime.now(timezone.utc)
        self._calls: Dict[str, int] = {}
        self._last_called_at: Dict[str, datetime] = {}
        self._clients: Dict[str, int] = {}
        self._client_last_called_at: Dict[str, datetime] = {}

    def record(self, tool_name: str, client: str = "") -> None:
        now = datetime.now(timezone.utc)
        with self._lock:
            self._ensure_loaded()
            self._calls[tool_name] = self._calls.get(tool_name, 0) + 1
            self._last_called_at[tool_name] = now
            if client:
                self._clients[client] = self._clients.get(client, 0) + 1
                self._client_last_called_at[client] = now
            if self._store is not None:
                try:
                    self._store.save(self._snapshot())
                except Exception:
                    logger.exception("mcp tool call metrics persist failed")

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            self._ensure_loaded()
            return self._snapshot()

    @staticmethod
    def _hydrate_entries(payload: Any) -> tuple[Dict[str, int], Dict[str, datetime]]:
        """宽容读取 ``{name: {calls, last_called_at}}`` 映射；坏条目一律跳过。"""
        counts: Dict[str, int] = {}
        last_called_at: Dict[str, datetime] = {}
        if not isinstance(payload, dict):
            return counts, last_called_at
        for name, entry in payload.items():
            if not isinstance(name, str) or not isinstance(entry, dict):
                continue
            calls = entry.get("calls")
            last_seen = _parse_iso(entry.get("last_called_at"))
            if not isinstance(calls, int) or calls <= 0 or last_seen is None:
                continue
            counts[name] = calls
            last_called_at[name] = last_seen
        return counts, last_called_at

    def _ensure_loaded(self) -> None:
        """Hydrate from the store exactly once; caller must hold ``_lock``."""
        if self._loaded:
            return
        self._loaded = True
        payload = self._store.load() if self._store is not None else None
        if not payload:
            return
        self._calls, self._last_called_at = self._hydrate_entries(
            payload.get("tools")
        )
        self._clients, self._client_last_called_at = self._hydrate_entries(
            payload.get("clients")
        )
        since = _parse_iso(payload.get("since"))
        if since is not None:
            self._since = since

    @staticmethod
    def _entries_payload(
        counts: Dict[str, int], last_called_at: Dict[str, datetime]
    ) -> Dict[str, Any]:
        return {
            name: {
                "calls": counts[name],
                "last_called_at": last_called_at[name].isoformat(),
            }
            for name in sorted(counts)
        }

    def _snapshot(self) -> Dict[str, Any]:
        """Build the wire payload; caller must hold ``_lock``."""
        return {
            "since": self._since.isoformat(),
            "total_calls": sum(self._calls.values()),
            "tools": self._entries_payload(self._calls, self._last_called_at),
            "clients": self._entries_payload(
                self._clients, self._client_last_called_at
            ),
        }


MCP_TOOL_CALL_METRICS = McpToolCallMetrics(
    store=JsonMcpToolCallStore(
        getattr(
            settings,
            "mcp_tool_call_metrics_path",
            "storage/metrics/mcp_tool_calls.json",
        )
    )
)
