"""MCP 每日用量汇总读取端（mcpusage:*，写入端在 mcp-go/internal/usage）。

键名与字段格式是跨语言契约：这里的字面量与 Go 侧 usage_test.go 对钉。
"""

from __future__ import annotations

import unittest
from datetime import date
from typing import Any, Dict, List, Set, Tuple
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_monitor
from backend.app.core.auth import RequireAdmin, RequireUser
from backend.app.monitoring.mcp_daily_usage import (
    MAX_CLIENT_NAME_ROWS,
    read_mcp_daily_usage,
    read_mcp_daily_usage_safely,
)


class _FakePipeline:
    def __init__(self, redis: "_FakeRedis") -> None:
        self._redis = redis
        self._ops: List[Tuple[str, Tuple[str, ...]]] = []

    def get(self, key: str) -> "_FakePipeline":
        self._ops.append(("get", (key,)))
        return self

    def hgetall(self, key: str) -> "_FakePipeline":
        self._ops.append(("hgetall", (key,)))
        return self

    def pfcount(self, *keys: str) -> "_FakePipeline":
        self._ops.append(("pfcount", keys))
        return self

    async def execute(self) -> List[Any]:
        if self._redis.fail:
            raise ConnectionError("redis down")
        return [getattr(self._redis, f"_{op}")(*args) for op, args in self._ops]


class _FakeRedis:
    """按 decode_responses=False 的形状回 bytes；HLL 用集合做精确去重。"""

    def __init__(self) -> None:
        self.strings: Dict[str, str] = {}
        self.hashes: Dict[str, Dict[str, str]] = {}
        self.hlls: Dict[str, Set[str]] = {}
        self.pipeline_transactions: List[bool] = []
        self.fail = False

    def pipeline(self, transaction: bool = True) -> _FakePipeline:
        self.pipeline_transactions.append(transaction)
        return _FakePipeline(self)

    def hincr(self, key: str, field: str, amount: int = 1) -> None:
        bucket = self.hashes.setdefault(key, {})
        bucket[field] = str(int(bucket.get(field, "0")) + amount)

    def pfadd(self, key: str, *members: str) -> None:
        self.hlls.setdefault(key, set()).update(members)

    def _get(self, key: str) -> Any:
        value = self.strings.get(key)
        return value.encode() if value is not None else None

    def _hgetall(self, key: str) -> Dict[bytes, bytes]:
        return {field.encode(): value.encode() for field, value in self.hashes.get(key, {}).items()}

    def _pfcount(self, *keys: str) -> int:
        union: Set[str] = set()
        for key in keys:
            union |= self.hlls.get(key, set())
        return len(union)


END = date(2026, 10, 5)


def _seeded_redis() -> _FakeRedis:
    redis = _FakeRedis()
    redis.strings["mcpusage:since"] = "2026-10-04"
    # 10-05
    redis.hincr("mcpusage:2026-10-05:calls", "anonymous|search_papers", 3)
    redis.hincr("mcpusage:2026-10-05:calls", "free|search_papers", 2)
    redis.hincr("mcpusage:2026-10-05:calls", "member|get_top_items", 1)
    redis.hincr("mcpusage:2026-10-05:limited", "anonymous|daily", 2)
    redis.hincr("mcpusage:2026-10-05:limited", "free|burst", 1)
    redis.hincr("mcpusage:2026-10-05:client_names", "anonymous|cursor", 1)
    redis.hincr("mcpusage:2026-10-05:client_names", "free|claude code", 2)
    redis.hincr("mcpusage:2026-10-05:client_names", "member|claude code", 1)
    redis.pfadd("mcpusage:2026-10-05:clients:anonymous", "a:1", "a:2")
    redis.pfadd("mcpusage:2026-10-05:clients:free", "u:7")
    redis.pfadd("mcpusage:2026-10-05:clients:member", "u:9")
    redis.pfadd("mcpusage:2026-10-05:name_clients:anonymous|cursor", "a:1")
    redis.pfadd("mcpusage:2026-10-05:name_clients:free|claude code", "u:7")
    redis.pfadd("mcpusage:2026-10-05:name_clients:member|claude code", "u:9")
    # 10-04
    redis.hincr("mcpusage:2026-10-04:calls", "free|search_papers", 1)
    redis.hincr("mcpusage:2026-10-04:calls", "free|__unknown__", 1)
    redis.hincr("mcpusage:2026-10-04:limited", "free|monthly", 1)
    redis.hincr("mcpusage:2026-10-04:client_names", "free|claude code", 1)
    redis.hincr("mcpusage:2026-10-04:client_names", "free|__other__", 1)
    redis.pfadd("mcpusage:2026-10-04:clients:free", "u:7", "u:8")
    redis.pfadd("mcpusage:2026-10-04:name_clients:free|claude code", "u:7")
    redis.pfadd("mcpusage:2026-10-04:name_clients:free|__other__", "u:8")
    return redis


def _stats(clients: int, connections: int, calls: int, limited: int) -> Dict[str, int]:
    return {"clients": clients, "connections": connections, "calls": calls, "limited": limited}


class ReadMcpDailyUsageTests(unittest.IsolatedAsyncioTestCase):
    async def test_daily_rows_newest_first_with_audience_split(self) -> None:
        redis = _seeded_redis()

        usage = await read_mcp_daily_usage(redis, end_date=END, days=3)

        self.assertTrue(usage["available"])
        self.assertEqual(usage["timezone"], "Asia/Shanghai")
        self.assertEqual((usage["start_date"], usage["end_date"]), ("2026-10-03", "2026-10-05"))
        self.assertEqual(usage["since"], "2026-10-04")
        self.assertEqual([row["date"] for row in usage["daily"]], ["2026-10-05", "2026-10-04", "2026-10-03"])
        today = usage["daily"][0]
        self.assertTrue(today["tracked"])
        self.assertEqual(today["anonymous"], _stats(2, 1, 3, 2))
        self.assertEqual(today["free"], _stats(1, 2, 2, 1))
        self.assertEqual(today["member"], _stats(1, 1, 1, 0))
        self.assertEqual(today["total"], _stats(4, 4, 6, 3))
        yesterday = usage["daily"][1]
        self.assertEqual(yesterday["free"], _stats(2, 2, 2, 1))
        self.assertEqual(yesterday["total"], _stats(2, 2, 2, 1))
        # since 之前的日子标为未统计，而不是「当天没人用」。
        self.assertFalse(usage["daily"][2]["tracked"])
        self.assertEqual(usage["daily"][2]["total"], _stats(0, 0, 0, 0))
        # 两轮读取都走非事务 pipeline。
        self.assertEqual(redis.pipeline_transactions, [False, False])

    async def test_window_distinct_clients_are_unions_not_sums(self) -> None:
        usage = await read_mcp_daily_usage(_seeded_redis(), end_date=END, days=3)

        summary = usage["summary"]
        # u:7 两天都来过，窗口里只算一次。
        self.assertEqual(summary["free"], _stats(2, 4, 4, 2))
        self.assertEqual(summary["anonymous"], _stats(2, 1, 3, 2))
        self.assertEqual(summary["member"], _stats(1, 1, 1, 0))
        self.assertEqual(summary["total"], _stats(5, 6, 8, 4))

    async def test_tool_limited_and_client_name_tables(self) -> None:
        usage = await read_mcp_daily_usage(_seeded_redis(), end_date=END, days=3)

        self.assertEqual(
            usage["tools"],
            [
                {"tool": "search_papers", "anonymous": 3, "free": 3, "member": 0, "total": 6},
                {"tool": "__unknown__", "anonymous": 0, "free": 1, "member": 0, "total": 1},
                {"tool": "get_top_items", "anonymous": 0, "free": 0, "member": 1, "total": 1},
            ],
        )
        self.assertEqual(
            usage["limited"],
            [
                {"kind": "burst", "anonymous": 0, "free": 1, "member": 0, "total": 1},
                {"kind": "daily", "anonymous": 2, "free": 0, "member": 0, "total": 2},
                {"kind": "monthly", "anonymous": 0, "free": 1, "member": 0, "total": 1},
            ],
        )
        self.assertEqual(
            usage["client_names"],
            [
                {
                    "name": "claude code",
                    "connections": {"anonymous": 0, "free": 3, "member": 1, "total": 4},
                    "clients": {"anonymous": 0, "free": 1, "member": 1, "total": 2},
                },
                {
                    "name": "__other__",
                    "connections": {"anonymous": 0, "free": 1, "member": 0, "total": 1},
                    "clients": {"anonymous": 0, "free": 1, "member": 0, "total": 1},
                },
                {
                    "name": "cursor",
                    "connections": {"anonymous": 1, "free": 0, "member": 0, "total": 1},
                    "clients": {"anonymous": 1, "free": 0, "member": 0, "total": 1},
                },
            ],
        )
        self.assertFalse(usage["client_names_truncated"])

    async def test_malformed_fields_are_ignored(self) -> None:
        redis = _FakeRedis()
        redis.strings["mcpusage:since"] = "2026-10-05"
        for field in ("nofield", "admin|search_papers", "free|", "|search_papers"):
            redis.hincr("mcpusage:2026-10-05:calls", field)
        redis.hashes["mcpusage:2026-10-05:calls"]["free|get_paper_detail"] = "abc"
        redis.hincr("mcpusage:2026-10-05:calls", "member|search_papers", 4)

        usage = await read_mcp_daily_usage(redis, end_date=END, days=1)

        self.assertEqual(
            usage["tools"],
            [{"tool": "search_papers", "anonymous": 0, "free": 0, "member": 4, "total": 4}],
        )
        self.assertEqual(usage["daily"][0]["total"]["calls"], 4)

    async def test_client_name_table_keeps_top_rows(self) -> None:
        redis = _FakeRedis()
        for index in range(MAX_CLIENT_NAME_ROWS + 5):
            name = f"client-{index:02d}"
            redis.hincr("mcpusage:2026-10-05:client_names", f"free|{name}", index + 1)
            redis.pfadd(f"mcpusage:2026-10-05:name_clients:free|{name}", f"u:{index}")

        usage = await read_mcp_daily_usage(redis, end_date=END, days=1)

        self.assertTrue(usage["client_names_truncated"])
        self.assertEqual(len(usage["client_names"]), MAX_CLIENT_NAME_ROWS)
        self.assertEqual(usage["client_names"][0]["name"], f"client-{MAX_CLIENT_NAME_ROWS + 4:02d}")
        # 汇总里的连接次数仍按全部名字计。
        total = sum(index + 1 for index in range(MAX_CLIENT_NAME_ROWS + 5))
        self.assertEqual(usage["summary"]["free"]["connections"], total)

    async def test_unwired_or_failing_redis_returns_zero_shape(self) -> None:
        unwired = await read_mcp_daily_usage_safely(None, end_date=END, days=14)
        failing_redis = _seeded_redis()
        failing_redis.fail = True
        failing = await read_mcp_daily_usage_safely(failing_redis, end_date=END, days=14)

        for usage in (unwired, failing):
            self.assertFalse(usage["available"])
            self.assertEqual(len(usage["daily"]), 14)
            self.assertEqual(usage["start_date"], "2026-09-22")
            self.assertEqual(usage["summary"]["total"], _stats(0, 0, 0, 0))
            self.assertEqual([row["kind"] for row in usage["limited"]], ["burst", "daily", "monthly"])
            self.assertEqual(usage["tools"], [])
            self.assertEqual(usage["client_names"], [])
        # 零值结构与正常结构同形，前端不必分支。
        healthy = await read_mcp_daily_usage(_FakeRedis(), end_date=END, days=14)
        self.assertEqual(set(unwired), set(healthy))
        self.assertEqual(set(unwired["daily"][0]), set(healthy["daily"][0]))


class McpUsageRouteTests(unittest.TestCase):
    """GET /api/monitor/mcp-usage：管理员专属。"""

    @staticmethod
    def _build_app(redis: Any = None, *, admin: bool = True) -> FastAPI:
        app = FastAPI()
        app.include_router(routes_monitor.router, prefix="/api")
        if admin:
            app.dependency_overrides[RequireAdmin] = lambda: {"role": "admin"}
        app.state.redis = redis
        return app

    def test_requires_admin_before_reading_redis(self) -> None:
        redis = MagicMock()
        app = self._build_app(redis, admin=False)

        response = TestClient(app).get("/api/monitor/mcp-usage")

        self.assertIn(response.status_code, (401, 403))
        redis.pipeline.assert_not_called()

    def test_rejects_authenticated_non_admin(self) -> None:
        redis = MagicMock()
        app = self._build_app(redis, admin=False)
        app.dependency_overrides[RequireUser] = lambda: {"role": "user"}

        response = TestClient(app).get("/api/monitor/mcp-usage")

        self.assertEqual(response.status_code, 403)
        redis.pipeline.assert_not_called()

    def test_reads_window_ending_today(self) -> None:
        app = self._build_app(_seeded_redis())

        with patch.object(routes_monitor, "cst_today", return_value=END):
            response = TestClient(app).get("/api/monitor/mcp-usage", params={"days": 3})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["available"])
        self.assertEqual(body["days"], 3)
        self.assertEqual(body["end_date"], "2026-10-05")
        self.assertEqual(body["summary"]["total"], _stats(5, 6, 8, 4))

    def test_default_window_is_14_days(self) -> None:
        app = self._build_app(_FakeRedis())

        with patch.object(routes_monitor, "cst_today", return_value=END):
            response = TestClient(app).get("/api/monitor/mcp-usage")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["daily"]), 14)

    def test_invalid_days_is_422(self) -> None:
        redis = MagicMock()
        app = self._build_app(redis)

        for days in ("0", "32", "-1", "week"):
            with self.subTest(days=days):
                response = TestClient(app).get("/api/monitor/mcp-usage", params={"days": days})
                self.assertEqual(response.status_code, 422)
        redis.pipeline.assert_not_called()

    def test_missing_redis_reports_unavailable(self) -> None:
        app = self._build_app(None)

        response = TestClient(app).get("/api/monitor/mcp-usage", params={"days": 7})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["available"])
        self.assertEqual(len(body["daily"]), 7)


if __name__ == "__main__":
    unittest.main()
