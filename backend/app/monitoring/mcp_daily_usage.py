"""MCP 每日用量汇总的读取端；写入端是 mcp-go/internal/usage。

Go MCP 服务按北京时间自然日记录每个 /api/mcp 请求（管理员与压测 UA
不记，原始 IP 不进 Redis，匿名按「日期 + IP」摘要去重）：

- ``mcpusage:since``                                首次记录的日期
- ``mcpusage:{day}:clients:{audience}``             HLL，当天去重客户端
- ``mcpusage:{day}:calls``                          HASH ``{audience}|{tool}`` → tools/call 次数
- ``mcpusage:{day}:limited``                        HASH ``{audience}|{kind}`` → 429 次数
- ``mcpusage:{day}:client_names``                   HASH ``{audience}|{name}`` → initialize 次数
- ``mcpusage:{day}:name_clients:{audience}|{name}`` HLL，该客户端名的去重客户端

audience 为 anonymous / free / member；kind 为 burst / daily / monthly。
跨天的去重客户端用多键 PFCOUNT 求并集，不能逐日相加。本模块只读。
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger(__name__)

NAMESPACE = "mcpusage"
TIMEZONE = "Asia/Shanghai"
AUDIENCES: Tuple[str, ...] = ("anonymous", "free", "member")
LIMIT_KINDS: Tuple[str, ...] = ("burst", "daily", "monthly")
# 客户端名表最多列这么多行（按连接次数取前若干）。
MAX_CLIENT_NAME_ROWS = 50

_COUNTER_FIELDS = ("connections", "calls", "limited")


def _day_key(day: str, suffix: str) -> str:
    return f"{NAMESPACE}:{day}:{suffix}"


def _decode(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _count(value: Any) -> int:
    try:
        return int(_decode(value)) if value is not None else 0
    except ValueError:
        return 0


def _split_counters(raw: Optional[dict]) -> Dict[Tuple[str, str], int]:
    """把 ``{audience}|{name}`` 计数哈希拆成 (audience, name) → 次数；坏字段跳过。"""
    counters: Dict[Tuple[str, str], int] = {}
    for key, value in (raw or {}).items():
        audience, separator, name = _decode(key).partition("|")
        if not separator or not name or audience not in AUDIENCES:
            continue
        try:
            count = int(_decode(value))
        except ValueError:
            continue
        counters[(audience, name)] = counters.get((audience, name), 0) + count
    return counters


def _sum_for(counters: Dict[Tuple[str, str], int], audience: str) -> int:
    return sum(count for (owner, _), count in counters.items() if owner == audience)


def _stats(clients: int = 0, connections: int = 0, calls: int = 0, limited: int = 0) -> Dict[str, int]:
    return {"clients": clients, "connections": connections, "calls": calls, "limited": limited}


def _with_total(per_audience: Dict[str, Dict[str, int]], total_clients: int) -> Dict[str, Dict[str, int]]:
    """补上 total：次数逐受众相加，去重客户端取调用方给的并集值。"""
    total = _stats(clients=total_clients)
    for field in _COUNTER_FIELDS:
        total[field] = sum(per_audience[audience][field] for audience in AUDIENCES)
    return {**per_audience, "total": total}


def _audience_row(counts: Dict[str, int]) -> Dict[str, int]:
    row = {audience: counts.get(audience, 0) for audience in AUDIENCES}
    row["total"] = sum(row.values())
    return row


def _window_dates(end_date: date, days: int) -> List[date]:
    """含 end_date 在内往前 days 天，新的在前。"""
    return [end_date - timedelta(days=offset) for offset in range(days)]


def empty_mcp_daily_usage(end_date: date, days: int, *, available: bool) -> Dict[str, Any]:
    """零值结构：Redis 未接线或读取失败时照样返回同一形状。"""
    dates = _window_dates(end_date, days)
    zero = {audience: _stats() for audience in AUDIENCES}
    return {
        "available": available,
        "timezone": TIMEZONE,
        "days": days,
        "start_date": dates[-1].isoformat(),
        "end_date": end_date.isoformat(),
        "since": None,
        "summary": _with_total(zero, 0),
        "daily": [{"date": day.isoformat(), "tracked": False, **_with_total(zero, 0)} for day in dates],
        "tools": [],
        "client_names": [],
        "client_names_truncated": False,
        "limited": [{"kind": kind, **_audience_row({})} for kind in LIMIT_KINDS],
    }


async def read_mcp_daily_usage(redis: Any, *, end_date: date, days: int) -> Dict[str, Any]:
    """读取含 end_date 在内最近 days 天的用量汇总（两轮 pipeline）。"""
    dates = _window_dates(end_date, days)
    day_strings = [day.isoformat() for day in dates]

    pipe = redis.pipeline(transaction=False)
    pipe.get(f"{NAMESPACE}:since")
    for day in day_strings:
        pipe.hgetall(_day_key(day, "calls"))
        pipe.hgetall(_day_key(day, "limited"))
        pipe.hgetall(_day_key(day, "client_names"))
        for audience in AUDIENCES:
            pipe.pfcount(_day_key(day, f"clients:{audience}"))
        pipe.pfcount(*(_day_key(day, f"clients:{audience}") for audience in AUDIENCES))
    for audience in AUDIENCES:
        pipe.pfcount(*(_day_key(day, f"clients:{audience}") for day in day_strings))
    pipe.pfcount(*(_day_key(day, f"clients:{audience}") for day in day_strings for audience in AUDIENCES))
    results: Iterator[Any] = iter(await pipe.execute())

    since_raw = next(results)
    since = _decode(since_raw) if since_raw is not None else None

    window = {audience: _stats() for audience in AUDIENCES}
    tool_counts: Dict[str, Dict[str, int]] = {}
    limit_counts: Dict[str, Dict[str, int]] = {}
    name_connections: Dict[str, Dict[str, int]] = {}
    name_days: Dict[Tuple[str, str], List[str]] = {}
    daily: List[Dict[str, Any]] = []

    for day in day_strings:
        calls = _split_counters(next(results))
        limited = _split_counters(next(results))
        names = _split_counters(next(results))
        per_audience: Dict[str, Dict[str, int]] = {}
        for audience in AUDIENCES:
            per_audience[audience] = _stats(
                clients=_count(next(results)),
                connections=_sum_for(names, audience),
                calls=_sum_for(calls, audience),
                limited=_sum_for(limited, audience),
            )
            for field in _COUNTER_FIELDS:
                window[audience][field] += per_audience[audience][field]
        day_total_clients = _count(next(results))
        daily.append(
            {
                "date": day,
                "tracked": since is not None and day >= since,
                **_with_total(per_audience, day_total_clients),
            }
        )
        for (audience, tool), count in calls.items():
            bucket = tool_counts.setdefault(tool, {})
            bucket[audience] = bucket.get(audience, 0) + count
        for (audience, kind), count in limited.items():
            bucket = limit_counts.setdefault(kind, {})
            bucket[audience] = bucket.get(audience, 0) + count
        for (audience, name), count in names.items():
            bucket = name_connections.setdefault(name, {})
            bucket[audience] = bucket.get(audience, 0) + count
            name_days.setdefault((audience, name), []).append(day)

    for audience in AUDIENCES:
        window[audience]["clients"] = _count(next(results))
    window_total_clients = _count(next(results))

    tools = sorted(
        ({"tool": tool, **_audience_row(counts)} for tool, counts in tool_counts.items()),
        key=lambda row: (-row["total"], row["tool"]),
    )
    extra_kinds = sorted(kind for kind in limit_counts if kind not in LIMIT_KINDS)
    limited_rows = [
        {"kind": kind, **_audience_row(limit_counts.get(kind, {}))} for kind in (*LIMIT_KINDS, *extra_kinds)
    ]

    ranked_names = sorted(name_connections, key=lambda name: (-sum(name_connections[name].values()), name))
    truncated = len(ranked_names) > MAX_CLIENT_NAME_ROWS
    ranked_names = ranked_names[:MAX_CLIENT_NAME_ROWS]
    client_names = await _read_client_name_rows(redis, ranked_names, name_connections, name_days)

    return {
        "available": True,
        "timezone": TIMEZONE,
        "days": days,
        "start_date": dates[-1].isoformat(),
        "end_date": end_date.isoformat(),
        "since": since,
        "summary": _with_total(window, window_total_clients),
        "daily": daily,
        "tools": tools,
        "client_names": client_names,
        "client_names_truncated": truncated,
        "limited": limited_rows,
    }


async def _read_client_name_rows(
    redis: Any,
    names: List[str],
    connections: Dict[str, Dict[str, int]],
    name_days: Dict[Tuple[str, str], List[str]],
) -> List[Dict[str, Any]]:
    """第二轮：每个客户端名按受众求窗口内去重客户端（只数该名出现过的那几天）。"""
    if not names:
        return []
    pipe = redis.pipeline(transaction=False)
    for name in names:
        all_keys: List[str] = []
        for audience in AUDIENCES:
            keys = [_day_key(day, f"name_clients:{audience}|{name}") for day in name_days.get((audience, name), [])]
            if keys:
                pipe.pfcount(*keys)
                all_keys.extend(keys)
        pipe.pfcount(*all_keys)
    results: Iterator[Any] = iter(await pipe.execute())

    rows: List[Dict[str, Any]] = []
    for name in names:
        clients: Dict[str, int] = {}
        for audience in AUDIENCES:
            if name_days.get((audience, name)):
                clients[audience] = _count(next(results))
        row_clients = {audience: clients.get(audience, 0) for audience in AUDIENCES}
        row_clients["total"] = _count(next(results))
        rows.append(
            {
                "name": name,
                "connections": _audience_row(connections[name]),
                "clients": row_clients,
            }
        )
    return rows


async def read_mcp_daily_usage_safely(redis: Any, *, end_date: date, days: int) -> Dict[str, Any]:
    """监控页入口：Redis 未接线或出错时返回 available=false 的零值结构。"""
    if redis is None:
        return empty_mcp_daily_usage(end_date, days, available=False)
    try:
        return await read_mcp_daily_usage(redis, end_date=end_date, days=days)
    except Exception:  # noqa: BLE001 - 监控读路径 fail-soft，只记日志
        logger.warning("[Monitor] MCP daily usage read failed", exc_info=True)
        return empty_mcp_daily_usage(end_date, days, available=False)
