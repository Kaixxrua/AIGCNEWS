"""MCP 工具调用计数的 Redis 聚合实现（PR 0.2）。

背景：/api/mcp 由主进程（backend-api）与独立 MCP 进程（mcp-api）共同服务，
两个进程各自持有一份 JSON 计数文件（storage/metrics 与 storage/metrics_mcp），
dashboard 只能读到本进程那一份，计数分裂。本模块把计数源迁移到共享 Redis
命名空间 ``mcpmetrics:*``，两个进程写同一份聚合；Go 重写切换期 Python/Go
双写者并存时也靠它收敛（Go 侧只写 Redis）。

键布局（hash 而非 per-bucket key，快照读取无需 SCAN，键数有界）：

- ``mcpmetrics:total``        字符串计数器，INCR/INCRBY
- ``mcpmetrics:since``        首次计数时间（ISO 字符串；seed 取最早值）
- ``mcpmetrics:tool_calls``   HASH field=工具桶 value=累计次数
- ``mcpmetrics:tool_last``    HASH field=工具桶 value=最近调用时间
- ``mcpmetrics:client_calls`` HASH field=客户端桶 value=累计次数
- ``mcpmetrics:client_last``  HASH field=客户端桶 value=最近调用时间
- ``mcpmetrics:seeded:{src}`` 种子迁移幂等标记（每源一次）

过渡策略（一个发布周期）：写路径双写——本地 JSON shadow（既有
``McpToolCallMetrics``，行为不变）+ Redis 原子 Lua；读路径 Redis 优先，
Redis 故障或尚未有任何计数（total 键不存在）时回退本地 JSON shadow，
保持今日"Redis 不可用时只看本进程计数"的行为下限。所有 Redis 调用
fail-open：任何异常只记日志，绝不影响 MCP 分派与 dashboard 响应。

迁移：lifespan 绑定后调用 :meth:`RedisMcpToolCallMetrics.seed_from_json`
把本进程历史 JSON 一次性并入 Redis；``mcpmetrics:seeded:{seed_id}``
SETNX 认领保证每源只种子一次（backend-api 与 mcp-api 各自一份历史文件）。
种子失败删除标记允许下次启动重试。未知名（bucket 特性上线前的旧文件）
在种子时重新归桶到 ``__unknown__``，计数合并、last 取最大。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Container, Dict, Optional, Protocol

from redis.asyncio import Redis

from backend.app.monitoring.mcp_tools import (
    MCP_TOOL_CALL_METRICS,
    McpToolCallMetrics,
    McpToolCallStore,
    bucket_tool_name,
)

logger = logging.getLogger(__name__)

REDIS_METRICS_NAMESPACE = "mcpmetrics"

# 单次 EVAL 全原子：total 自增、since 先到先得、工具/客户端桶 HINCRBY+HSET。
# KEYS: total, since, tool_calls, tool_last, client_calls, client_last
# ARGV: tool, client（空串跳过客户端桶）, now_iso
_RECORD_SCRIPT = """
redis.call('INCR', KEYS[1])
redis.call('SETNX', KEYS[2], ARGV[3])
redis.call('HINCRBY', KEYS[3], ARGV[1], 1)
redis.call('HSET', KEYS[4], ARGV[1], ARGV[3])
if ARGV[2] ~= '' then
  redis.call('HINCRBY', KEYS[5], ARGV[2], 1)
  redis.call('HSET', KEYS[6], ARGV[2], ARGV[3])
end
return 1
"""

# 种子迁移：平铺 ARGV（避免 cjson 依赖），since 取最早、last 取最新、计数累加。
# KEYS: 同 _RECORD_SCRIPT
# ARGV: since, total, n_tools, [name, calls, last_iso]*n, n_clients, [同上]*n
_SEED_SCRIPT = """
local since = ARGV[1]
if since ~= '' then
  local cur = redis.call('GET', KEYS[2])
  if (not cur) or since < cur then redis.call('SET', KEYS[2], since) end
end
local total = tonumber(ARGV[2]) or 0
if total > 0 then redis.call('INCRBY', KEYS[1], total) end
local i = 3
local function merge(calls_key, last_key)
  local n = tonumber(ARGV[i]) or 0
  i = i + 1
  for _ = 1, n do
    local name = ARGV[i]
    local calls = tonumber(ARGV[i + 1]) or 0
    local last = ARGV[i + 2]
    i = i + 3
    if calls > 0 then redis.call('HINCRBY', calls_key, name, calls) end
    if last ~= '' then
      local cur = redis.call('HGET', last_key, name)
      if (not cur) or last > cur then redis.call('HSET', last_key, name, last) end
    end
  end
end
merge(KEYS[3], KEYS[4])
merge(KEYS[5], KEYS[6])
return 1
"""

# PostgreSQL checkpoint 回灌：仅当 checkpoint 比 Redis 更新时整组替换。
# 比较与替换在同一段 Lua 内完成，启动期间即使仍有 MCP 写入也不会倒退。
# KEYS: 同 _RECORD_SCRIPT
# ARGV: total, since, n_tools, [name, calls, last_iso]*n, n_clients, [同上]*n
_RESTORE_SCRIPT = """
local incoming = tonumber(ARGV[1]) or 0
local current = tonumber(redis.call('GET', KEYS[1])) or -1
if current >= incoming then return 0 end
redis.call('SET', KEYS[1], incoming)
if ARGV[2] ~= '' then redis.call('SET', KEYS[2], ARGV[2]) else redis.call('DEL', KEYS[2]) end
redis.call('DEL', KEYS[3], KEYS[4], KEYS[5], KEYS[6])
local i = 3
local function restore(calls_key, last_key)
  local n = tonumber(ARGV[i]) or 0
  i = i + 1
  for _ = 1, n do
    redis.call('HSET', calls_key, ARGV[i], ARGV[i + 1])
    redis.call('HSET', last_key, ARGV[i], ARGV[i + 2])
    i = i + 3
  end
end
restore(KEYS[3], KEYS[4])
restore(KEYS[5], KEYS[6])
return 1
"""


class McpToolCallMetricsRecorder(Protocol):
    """MCP 分派层依赖的异步计数接口（record/snapshot 均在事件循环内 await）。"""

    async def record(self, tool_name: str, client: str = "") -> None:
        ...

    async def snapshot(self) -> Dict[str, Any]:
        ...


def _decode(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


class LocalMcpToolCallMetrics:
    """同步 JSON 计数器的异步门面：Redis 不可用时的默认实现。

    record/snapshot 直接委托既有 ``McpToolCallMetrics``（线程安全、落盘
    失败不影响计数的语义原样保留）；保持与 Redis 实现相同的异步签名，
    分派层无需感知底层是哪种存储。
    """

    def __init__(self, shadow: McpToolCallMetrics) -> None:
        self._shadow = shadow

    @property
    def shadow(self) -> McpToolCallMetrics:
        return self._shadow

    async def record(self, tool_name: str, client: str = "") -> None:
        self._shadow.record(tool_name, client=client)

    async def snapshot(self) -> Dict[str, Any]:
        return self._shadow.snapshot()


class RedisMcpToolCallMetrics:
    """Redis 聚合计数器：原子 Lua 写入 + Redis 优先读取 + JSON shadow 双写兜底。"""

    def __init__(
        self,
        redis: Redis,
        shadow: McpToolCallMetrics,
        *,
        seed_store: McpToolCallStore | None = None,
        seed_id: str = "",
        namespace: str = REDIS_METRICS_NAMESPACE,
    ) -> None:
        self._redis = redis
        self._shadow = shadow
        self._seed_store = seed_store
        self._seed_id = seed_id
        self._ns = namespace

    @property
    def shadow(self) -> McpToolCallMetrics:
        return self._shadow

    def _keys(self) -> tuple[str, str, str, str, str, str]:
        ns = self._ns
        return (
            f"{ns}:total",
            f"{ns}:since",
            f"{ns}:tool_calls",
            f"{ns}:tool_last",
            f"{ns}:client_calls",
            f"{ns}:client_last",
        )

    async def record(self, tool_name: str, client: str = "") -> None:
        # 双写：shadow（本地 JSON，同步语义与既有行为一致）先行，Redis 随后；
        # Redis 故障只损失聚合副本，本地计数与既有单进程行为对齐。
        self._shadow.record(tool_name, client=client)
        now = datetime.now(timezone.utc).isoformat()
        try:
            await self._redis.eval(_RECORD_SCRIPT, 6, *self._keys(), tool_name, client, now)
        except Exception:
            logger.warning(
                "mcp tool call metrics redis write failed (shadow kept)",
                exc_info=True,
            )

    async def snapshot(self) -> Dict[str, Any]:
        try:
            payload = await self._redis_snapshot()
        except Exception:
            logger.warning(
                "mcp tool call metrics redis read failed, falling back to shadow",
                exc_info=True,
            )
            return self._shadow.snapshot()
        if payload is None:
            # Redis 可达但从未有任何计数/种子（total 键不存在）：回退本地
            # shadow，与 Redis 化之前的单进程读取行为一致。
            return self._shadow.snapshot()
        return payload

    async def _redis_snapshot(self) -> Optional[Dict[str, Any]]:
        total_key, since_key, tool_calls_key, tool_last_key, client_calls_key, client_last_key = (
            self._keys()
        )
        total_raw = await self._redis.get(total_key)
        if total_raw is None:
            return None
        since_raw, tool_calls, tool_lasts, client_calls, client_lasts = (
            await self._redis.get(since_key),
            await self._redis.hgetall(tool_calls_key),
            await self._redis.hgetall(tool_last_key),
            await self._redis.hgetall(client_calls_key),
            await self._redis.hgetall(client_last_key),
        )
        since = _decode(since_raw) if since_raw is not None else ""
        return {
            "since": since or self._shadow.snapshot()["since"],
            "total_calls": int(_decode(total_raw)),
            "tools": self._entries_payload(tool_calls, tool_lasts),
            "clients": self._entries_payload(client_calls, client_lasts),
        }

    @staticmethod
    def _entries_payload(calls_raw: Dict[Any, Any], last_raw: Dict[Any, Any]) -> Dict[str, Any]:
        """把两个 HASH 装配成与 JSON shadow 同形的 ``{name: {calls, last_called_at}}``。

        与 ``McpToolCallMetrics._hydrate_entries`` 同口径的宽容读取：计数非正
        或 last 缺失/不可解析的条目跳过；按键名排序输出，保持与 shadow 快照一致。
        """
        calls = {_decode(k): int(_decode(v)) for k, v in calls_raw.items()}
        lasts = {_decode(k): _decode(v) for k, v in last_raw.items()}
        entries: Dict[str, Any] = {}
        for name in sorted(calls):
            if calls[name] <= 0:
                continue
            last = lasts.get(name, "")
            try:
                datetime.fromisoformat(last)
            except ValueError:
                continue
            entries[name] = {"calls": calls[name], "last_called_at": last}
        return entries

    async def seed_from_json(self, known_names: Container[str]) -> None:
        """把本进程历史 JSON 计数一次性并入 Redis；幂等、失败可重试、永不抛出。"""
        if self._seed_store is None or not self._seed_id:
            return
        marker = f"{self._ns}:seeded:{self._seed_id}"
        try:
            claimed = await self._redis.set(marker, "1", nx=True)
        except Exception:
            logger.warning(
                "mcp tool call metrics seed marker claim failed (seed skipped)",
                exc_info=True,
            )
            return
        if not claimed:
            return
        try:
            payload = self._seed_store.load()
            if payload:
                args = self._seed_args(payload, known_names)
                if args is not None:
                    await self._redis.eval(_SEED_SCRIPT, 6, *self._keys(), *args)
                    logger.info(
                        "[Startup] MCP tool call metrics seeded from JSON (source=%s).",
                        self._seed_id,
                    )
        except Exception:
            # 种子写失败：删除标记让下次启动重试，避免历史计数永久丢失。
            logger.warning(
                "mcp tool call metrics seed failed, marker released for retry",
                exc_info=True,
            )
            try:
                await self._redis.delete(marker)
            except Exception:
                logger.warning("mcp tool call metrics seed marker release failed", exc_info=True)

    async def restore_if_newer(self, payload: Dict[str, Any]) -> bool:
        """从持久化快照回灌 Redis；Redis 已持平或更新时保持原样。"""
        args = self._restore_args(payload)
        try:
            restored = await self._redis.eval(
                _RESTORE_SCRIPT,
                6,
                *self._keys(),
                *args,
            )
        except Exception:
            logger.warning(
                "mcp tool call metrics checkpoint restore failed (redis kept)",
                exc_info=True,
            )
            return False
        return bool(restored)

    @staticmethod
    def _restore_args(payload: Dict[str, Any]) -> tuple[Any, ...]:
        total = int(payload.get("total_calls", 0))
        if total < 0:
            raise ValueError("MCP metrics total_calls must be non-negative")
        since = payload.get("since", "")
        if not isinstance(since, str):
            raise ValueError("MCP metrics since must be a string")
        if since:
            datetime.fromisoformat(since)

        args: list[Any] = [total, since]
        for field in ("tools", "clients"):
            entries = payload.get(field, {})
            if not isinstance(entries, dict):
                raise ValueError(f"MCP metrics {field} must be an object")
            normalized: list[tuple[str, int, str]] = []
            for name in sorted(entries):
                entry = entries[name]
                if not isinstance(name, str) or not isinstance(entry, dict):
                    raise ValueError(f"MCP metrics {field} entry is invalid")
                calls = int(entry.get("calls", 0))
                last = entry.get("last_called_at", "")
                if calls <= 0 or not isinstance(last, str) or not last:
                    raise ValueError(f"MCP metrics {field} entry is invalid")
                datetime.fromisoformat(last)
                normalized.append((name, calls, last))
            args.append(len(normalized))
            for entry in normalized:
                args.extend(entry)
        return tuple(args)

    @staticmethod
    def _seed_args(
        payload: Dict[str, Any], known_names: Container[str]
    ) -> Optional[tuple[Any, ...]]:
        """把 JSON 载荷平铺成 _SEED_SCRIPT 的 ARGV；无有效内容时返回 None。

        未知名在此重新归桶（bucket 特性上线前的旧文件可能含原始工具名），
        同桶计数合并、last_called_at 取最大；复用 shadow 的宽容水合语义，
        坏条目跳过。
        """
        tools = _merge_seed_entries(payload.get("tools"), known_names)
        clients = _merge_seed_entries(payload.get("clients"), None)
        since_raw = payload.get("since")
        since = ""
        if isinstance(since_raw, str):
            try:
                datetime.fromisoformat(since_raw)
                since = since_raw
            except ValueError:
                since = ""
        total = sum(calls for calls, _ in tools.values())
        if not tools and not clients and not since:
            return None
        args: list[Any] = [since, total, len(tools)]
        for name, (calls, last) in tools.items():
            args.extend([name, calls, last])
        args.append(len(clients))
        for name, (calls, last) in clients.items():
            args.extend([name, calls, last])
        return tuple(args)


def _merge_seed_entries(
    payload: Any, known_names: Container[str] | None
) -> Dict[str, tuple[int, str]]:
    """水合 + 归桶一类条目（tools 或 clients），返回 {桶名: (计数, 最大last)}。"""
    counts, lasts = McpToolCallMetrics._hydrate_entries(payload)
    merged: Dict[str, tuple[int, str]] = {}
    for name, calls in counts.items():
        bucket = (
            bucket_tool_name(name, known_names) if known_names is not None else name
        )
        last_iso = lasts[name].isoformat()
        existing = merged.get(bucket)
        if existing is None:
            merged[bucket] = (calls, last_iso)
        else:
            merged[bucket] = (
                existing[0] + calls,
                max(existing[1], last_iso),
            )
    return merged


def create_redis_mcp_tool_call_metrics(
    redis: Redis,
    seed_store: McpToolCallStore,
    seed_id: str,
    *,
    shadow: McpToolCallMetrics | None = None,
) -> RedisMcpToolCallMetrics:
    """lifespan 绑定入口：包装共享 JSON shadow 单例，挂上 Redis 聚合层。"""
    return RedisMcpToolCallMetrics(
        redis,
        shadow if shadow is not None else MCP_TOOL_CALL_METRICS,
        seed_store=seed_store,
        seed_id=seed_id,
    )


# 模块级默认服务：Redis 未绑定（启动失败、测试不经 lifespan）时，
# 各读取/分派路径回退到它——行为与 Redis 化之前的 JSON 单例完全一致。
MCP_TOOL_CALL_METRICS_SERVICE: McpToolCallMetricsRecorder = LocalMcpToolCallMetrics(
    MCP_TOOL_CALL_METRICS
)


def resolve_tool_call_metrics_for_app(app: Any) -> McpToolCallMetricsRecorder:
    """按 app 解析计数服务：优先 app.state（lifespan 绑定的 Redis 聚合），
    缺省回退模块级 JSON 门面。无请求上下文的常驻任务（live-stats 广播
    的 MCP diff tick）与请求路径共用同一解析口径。"""
    service = getattr(app.state, "mcp_tool_call_metrics", None)
    if service is None:
        return MCP_TOOL_CALL_METRICS_SERVICE
    return service


def resolve_tool_call_metrics(request: Any) -> McpToolCallMetricsRecorder:
    """按请求解析计数服务：优先 app.state（lifespan 绑定的 Redis 聚合），
    缺省回退模块级 JSON 门面。TestClient 不跑 lifespan 的契约测试走后者。"""
    return resolve_tool_call_metrics_for_app(request.app)
