from __future__ import annotations

import json
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.app.api import routes_dashboard
from backend.app.monitoring import mcp_redis_metrics, metrics as monitor_metrics
from backend.app.monitoring.mcp_redis_metrics import (
    _RECORD_SCRIPT,
    _RESTORE_SCRIPT,
    _SEED_SCRIPT,
    LocalMcpToolCallMetrics,
    RedisMcpToolCallMetrics,
    create_redis_mcp_tool_call_metrics,
)
from backend.app.monitoring.mcp_tools import (
    DSH_PLUGIN_CLIENT,
    MAX_TOOL_NAME_LENGTH,
    MCP_TOOL_NAMES,
    UNKNOWN_TOOL_NAME,
    JsonMcpToolCallStore,
    McpToolCallMetrics,
    bucket_client_name,
    bucket_tool_name,
    is_benchmark_user_agent,
)
from backend.app.repositories.briefing_repository import BriefingReader
from backend.app.repositories.document_repository import DocumentStatisticsReader
from backend.app.repositories.evaluation_repository import EvaluationSummaryReader
from backend.app.repositories.task_repository import RecentTaskReader


class BenchmarkUserAgentUnitTests(unittest.TestCase):
    """压测打标：仅 mcp-latency-bench/ 前缀（含版本斜杠）命中免计数。"""

    def test_bench_prefix_hits(self) -> None:
        self.assertTrue(is_benchmark_user_agent("mcp-latency-bench/0.1"))
        self.assertTrue(is_benchmark_user_agent("mcp-latency-bench/9.9 extra"))
        self.assertTrue(is_benchmark_user_agent("  mcp-latency-bench/0.1  "))

    def test_non_bench_user_agents_miss(self) -> None:
        # 前缀边界：缺斜杠、前缀拼写偏差均不命中
        self.assertFalse(is_benchmark_user_agent("mcp-latency-bench"))
        self.assertFalse(is_benchmark_user_agent("mcp-latency-benchx/0.1"))
        self.assertFalse(is_benchmark_user_agent("Mcp-Latency-Bench/0.1"))
        self.assertFalse(is_benchmark_user_agent("dsh-aigc-radar/1.0"))
        self.assertFalse(is_benchmark_user_agent("testclient"))
        self.assertFalse(is_benchmark_user_agent(""))

    def test_non_string_user_agents_miss(self) -> None:
        self.assertFalse(is_benchmark_user_agent(None))
        self.assertFalse(is_benchmark_user_agent(123))
        self.assertFalse(is_benchmark_user_agent(b"mcp-latency-bench/0.1"))


class BucketToolNameUnitTests(unittest.TestCase):
    """工具名基数封顶：仅注册表已知名单独统计，其余归固定桶。"""

    def test_known_names_pass_through(self) -> None:
        for name in MCP_TOOL_NAMES:
            with self.subTest(name=name):
                self.assertEqual(bucket_tool_name(name, MCP_TOOL_NAMES), name)

    def test_unknown_names_land_in_fixed_bucket(self) -> None:
        self.assertEqual(
            bucket_tool_name("definitely_unknown_tool", MCP_TOOL_NAMES),
            UNKNOWN_TOOL_NAME,
        )

    def test_blank_and_oversized_names_land_in_fixed_bucket(self) -> None:
        self.assertEqual(bucket_tool_name("", MCP_TOOL_NAMES), UNKNOWN_TOOL_NAME)
        self.assertEqual(bucket_tool_name("   ", MCP_TOOL_NAMES), UNKNOWN_TOOL_NAME)
        oversized = "x" * (MAX_TOOL_NAME_LENGTH + 100)
        self.assertEqual(
            bucket_tool_name(oversized, MCP_TOOL_NAMES),
            UNKNOWN_TOOL_NAME,
        )

    def test_truncation_precedes_registry_lookup(self) -> None:
        # 注册表判定在截断之后：拼接到超长再截断无法伪造出已知名
        padded = "search_papers" + " " * MAX_TOOL_NAME_LENGTH
        self.assertEqual(
            bucket_tool_name(padded, MCP_TOOL_NAMES),
            "search_papers",
        )
        long_suffix = "search_papers" + "x" * MAX_TOOL_NAME_LENGTH
        self.assertEqual(
            bucket_tool_name(long_suffix, MCP_TOOL_NAMES),
            UNKNOWN_TOOL_NAME,
        )


class BucketClientNameUnitTests(unittest.TestCase):
    """客户端桶：仅 UA 前缀命中已知客户端，其余一律空桶不计数。"""

    def test_dsh_plugin_user_agent_hits_bucket(self) -> None:
        self.assertEqual(
            bucket_client_name("dsh-aigc-radar/0.1.0"), DSH_PLUGIN_CLIENT
        )
        self.assertEqual(
            bucket_client_name("  dsh-aigc-radar/1.2.3  "), DSH_PLUGIN_CLIENT
        )

    def test_unrelated_and_lookalike_user_agents_miss(self) -> None:
        self.assertEqual(bucket_client_name("Mozilla/5.0"), "")
        # 无版本斜杠与前缀不一致的相似串均不命中
        self.assertEqual(bucket_client_name("dsh-aigc-radar"), "")
        self.assertEqual(bucket_client_name("not-dsh-aigc-radar/1.0"), "")
        self.assertEqual(bucket_client_name(""), "")

    def test_non_string_user_agent_misses(self) -> None:
        self.assertEqual(bucket_client_name(None), "")
        self.assertEqual(bucket_client_name(123), "")


class McpToolCallMetricsUnitTests(unittest.TestCase):
    def test_snapshot_starts_empty_with_parseable_since(self) -> None:
        snapshot = McpToolCallMetrics().snapshot()

        self.assertEqual(snapshot["total_calls"], 0)
        self.assertEqual(snapshot["tools"], {})
        datetime.fromisoformat(snapshot["since"])

    def test_record_accumulates_counts_and_last_called_per_tool(self) -> None:
        metrics = McpToolCallMetrics()

        metrics.record("get_project_categories")
        metrics.record("search_github_ai_projects")
        metrics.record("get_project_categories")

        snapshot = metrics.snapshot()
        self.assertEqual(snapshot["total_calls"], 3)
        self.assertEqual(
            list(snapshot["tools"]),
            ["get_project_categories", "search_github_ai_projects"],
        )
        self.assertEqual(snapshot["tools"]["get_project_categories"]["calls"], 2)
        self.assertEqual(snapshot["tools"]["search_github_ai_projects"]["calls"], 1)
        for entry in snapshot["tools"].values():
            datetime.fromisoformat(entry["last_called_at"])

    def test_instances_are_isolated(self) -> None:
        first = McpToolCallMetrics()
        second = McpToolCallMetrics()

        first.record("get_top_items")

        self.assertEqual(second.snapshot()["total_calls"], 0)

    def test_snapshot_clients_start_empty(self) -> None:
        snapshot = McpToolCallMetrics().snapshot()

        self.assertEqual(snapshot["clients"], {})

    def test_record_with_client_accumulates_client_bucket(self) -> None:
        metrics = McpToolCallMetrics()

        metrics.record("search_github_ai_projects", client=DSH_PLUGIN_CLIENT)
        metrics.record("search_github_ai_projects")  # 空客户端桶不计入 clients
        metrics.record("get_top_items", client=DSH_PLUGIN_CLIENT)

        snapshot = metrics.snapshot()
        self.assertEqual(snapshot["total_calls"], 3)
        self.assertEqual(list(snapshot["clients"]), [DSH_PLUGIN_CLIENT])
        self.assertEqual(snapshot["clients"][DSH_PLUGIN_CLIENT]["calls"], 2)
        datetime.fromisoformat(
            snapshot["clients"][DSH_PLUGIN_CLIENT]["last_called_at"]
        )


class McpToolCallPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "nested" / "mcp_tool_calls.json"
        self.store = JsonMcpToolCallStore(str(self.path))

    def test_new_instance_recovers_counts_and_since_across_restart(self) -> None:
        first = McpToolCallMetrics(store=self.store)
        first.record("get_project_categories")
        first.record("search_github_ai_projects")
        first.record("get_project_categories")
        original_since = first.snapshot()["since"]

        restarted = McpToolCallMetrics(store=self.store)
        snapshot = restarted.snapshot()

        self.assertEqual(snapshot["total_calls"], 3)
        self.assertEqual(snapshot["tools"]["get_project_categories"]["calls"], 2)
        self.assertEqual(
            snapshot["tools"]["search_github_ai_projects"]["calls"], 1
        )
        self.assertEqual(snapshot["since"], original_since)

        restarted.record("get_project_categories")
        self.assertEqual(
            restarted.snapshot()["tools"]["get_project_categories"]["calls"], 3
        )

    def test_persisted_file_matches_snapshot_shape_without_tmp_leftover(self) -> None:
        metrics = McpToolCallMetrics(store=self.store)
        metrics.record("search_papers")

        persisted = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(set(persisted), {"since", "total_calls", "tools", "clients"})
        self.assertEqual(persisted["total_calls"], 1)
        self.assertEqual(persisted["tools"]["search_papers"]["calls"], 1)
        self.assertEqual(persisted["clients"], {})
        datetime.fromisoformat(persisted["since"])
        datetime.fromisoformat(
            persisted["tools"]["search_papers"]["last_called_at"]
        )
        self.assertFalse(self.path.with_name(self.path.name + ".tmp").exists())

    def test_new_instance_recovers_client_counts_across_restart(self) -> None:
        first = McpToolCallMetrics(store=self.store)
        first.record("get_top_items", client=DSH_PLUGIN_CLIENT)
        first.record("get_top_items", client=DSH_PLUGIN_CLIENT)
        first.record("search_papers")

        restarted = McpToolCallMetrics(store=self.store)
        snapshot = restarted.snapshot()

        self.assertEqual(snapshot["total_calls"], 3)
        self.assertEqual(snapshot["clients"][DSH_PLUGIN_CLIENT]["calls"], 2)
        datetime.fromisoformat(
            snapshot["clients"][DSH_PLUGIN_CLIENT]["last_called_at"]
        )

        restarted.record("get_top_items", client=DSH_PLUGIN_CLIENT)
        self.assertEqual(
            restarted.snapshot()["clients"][DSH_PLUGIN_CLIENT]["calls"], 3
        )

    def test_legacy_payload_without_clients_hydrates_empty(self) -> None:
        # 旧版落盘文件无 clients 键：升级后首次加载客户端桶为空，不报错
        self.path.parent.mkdir(parents=True)
        self.path.write_text(
            json.dumps(
                {
                    "since": "2026-08-04T00:00:00+00:00",
                    "total_calls": 2,
                    "tools": {
                        "get_top_items": {
                            "calls": 2,
                            "last_called_at": "2026-08-04T01:00:00+00:00",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        metrics = McpToolCallMetrics(store=self.store)

        snapshot = metrics.snapshot()
        self.assertEqual(snapshot["total_calls"], 2)
        self.assertEqual(snapshot["clients"], {})

    def test_invalid_client_entries_are_skipped_on_load(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text(
            json.dumps(
                {
                    "since": "2026-08-04T00:00:00+00:00",
                    "tools": {},
                    "clients": {
                        DSH_PLUGIN_CLIENT: {
                            "calls": 4,
                            "last_called_at": "2026-08-04T01:00:00+00:00",
                        },
                        "zero_calls": {
                            "calls": 0,
                            "last_called_at": "2026-08-04T01:00:00+00:00",
                        },
                        "bad_timestamp": {"calls": 5, "last_called_at": "n/a"},
                        "not_a_mapping": "oops",
                    },
                }
            ),
            encoding="utf-8",
        )
        metrics = McpToolCallMetrics(store=self.store)

        snapshot = metrics.snapshot()
        self.assertEqual(list(snapshot["clients"]), [DSH_PLUGIN_CLIENT])
        self.assertEqual(snapshot["clients"][DSH_PLUGIN_CLIENT]["calls"], 4)

    def test_missing_file_starts_empty(self) -> None:
        metrics = McpToolCallMetrics(store=self.store)

        self.assertEqual(metrics.snapshot()["total_calls"], 0)
        self.assertFalse(self.path.exists())

    def test_corrupt_file_starts_empty_and_recovers_on_record(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{not json", encoding="utf-8")
        metrics = McpToolCallMetrics(store=self.store)

        self.assertEqual(metrics.snapshot()["total_calls"], 0)

        metrics.record("get_top_items")
        persisted = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["tools"]["get_top_items"]["calls"], 1)

    def test_invalid_entries_are_skipped_on_load(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text(
            json.dumps(
                {
                    "since": "2026-08-04T00:00:00+00:00",
                    "total_calls": 99,
                    "tools": {
                        "valid_tool": {
                            "calls": 2,
                            "last_called_at": "2026-08-04T01:00:00+00:00",
                        },
                        "zero_calls": {
                            "calls": 0,
                            "last_called_at": "2026-08-04T01:00:00+00:00",
                        },
                        "bad_timestamp": {"calls": 5, "last_called_at": "n/a"},
                        "not_a_mapping": "oops",
                    },
                }
            ),
            encoding="utf-8",
        )
        metrics = McpToolCallMetrics(store=self.store)

        snapshot = metrics.snapshot()
        self.assertEqual(list(snapshot["tools"]), ["valid_tool"])
        self.assertEqual(snapshot["total_calls"], 2)
        self.assertEqual(snapshot["since"], "2026-08-04T00:00:00+00:00")

    def test_save_failure_does_not_break_record(self) -> None:
        failing_store = MagicMock()
        failing_store.load.return_value = None
        failing_store.save.side_effect = OSError("disk full")
        metrics = McpToolCallMetrics(store=failing_store)

        with self.assertLogs("backend.app.monitoring.mcp_tools", level="ERROR"):
            metrics.record("get_project_categories")

        snapshot = metrics.snapshot()
        self.assertEqual(snapshot["total_calls"], 1)
        self.assertEqual(snapshot["tools"]["get_project_categories"]["calls"], 1)

    def test_snapshot_does_not_write_to_store(self) -> None:
        metrics = McpToolCallMetrics(store=self.store)

        metrics.snapshot()

        self.assertFalse(self.path.exists())


class CollectMetricsMcpToolCallsTests(unittest.TestCase):
    def _readers(self) -> dict:
        task_reader = MagicMock(spec=RecentTaskReader)
        task_reader.get_recent_tasks.return_value = []
        evaluation_reader = MagicMock(spec=EvaluationSummaryReader)
        evaluation_reader.get_eval_summary.return_value = {}
        document_statistics = MagicMock(spec=DocumentStatisticsReader)
        document_statistics.get_document_count.return_value = 1
        briefing_reader = MagicMock(spec=BriefingReader)
        briefing_reader.list_briefings.return_value = []
        return {
            "task_reader": task_reader,
            "evaluation_reader": evaluation_reader,
            "document_statistics": document_statistics,
            "briefing_reader": briefing_reader,
        }

    def test_collect_metrics_includes_injected_mcp_tool_calls(self) -> None:
        tool_calls = McpToolCallMetrics()
        tool_calls.record("get_project_categories")

        result = monitor_metrics.collect_metrics(
            **self._readers(), mcp_tool_calls=tool_calls
        )

        section = result["mcp_tool_calls"]
        self.assertEqual(section["total_calls"], 1)
        self.assertEqual(section["tools"]["get_project_categories"]["calls"], 1)
        datetime.fromisoformat(section["since"])

    def test_collect_metrics_defaults_to_shared_singleton(self) -> None:
        isolated = McpToolCallMetrics()
        isolated.record("search_papers")

        with patch.object(monitor_metrics, "MCP_TOOL_CALL_METRICS", isolated):
            result = monitor_metrics.collect_metrics(**self._readers())

        self.assertEqual(result["mcp_tool_calls"]["total_calls"], 1)
        self.assertEqual(
            result["mcp_tool_calls"]["tools"]["search_papers"]["calls"], 1
        )



class FakeRedis:
    """最小内存 Redis 仿真：字符串/哈希原语 + 本模块 Lua 脚本的语义回放。

    eval 按脚本对象身份分发（_RECORD_SCRIPT / _SEED_SCRIPT），在 Python 侧
    复刻 Lua 的原子语义；fail=True 时所有操作抛 ConnectionError 模拟故障。
    """

    def __init__(self) -> None:
        self.strings: dict[bytes, bytes] = {}
        self.hashes: dict[bytes, dict[bytes, bytes]] = {}
        self.fail = False

    @staticmethod
    def _b(value: object) -> bytes:
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            return value.encode("utf-8")
        return str(value).encode("utf-8")

    def _check(self) -> None:
        if self.fail:
            raise ConnectionError("redis down")

    async def set(self, key: object, value: object, nx: bool = False) -> object:
        self._check()
        k, v = self._b(key), self._b(value)
        if nx and k in self.strings:
            return None
        self.strings[k] = v
        return True

    async def get(self, key: object) -> bytes | None:
        self._check()
        return self.strings.get(self._b(key))

    async def delete(self, *keys: object) -> int:
        self._check()
        removed = 0
        for key in keys:
            k = self._b(key)
            removed += self.strings.pop(k, None) is not None
            removed += self.hashes.pop(k, None) is not None
        return removed

    async def hgetall(self, key: object) -> dict[bytes, bytes]:
        self._check()
        return dict(self.hashes.get(self._b(key), {}))

    def _incr(self, key: bytes, by: int) -> None:
        self.strings[key] = str(int(self.strings.get(key, b"0")) + by).encode()

    def _hincrby(self, key: bytes, field: bytes, by: int) -> None:
        h = self.hashes.setdefault(key, {})
        h[field] = str(int(h.get(field, b"0")) + by).encode()

    def _hset_max(self, key: bytes, field: bytes, value: bytes) -> None:
        h = self.hashes.setdefault(key, {})
        cur = h.get(field)
        if cur is None or value > cur:
            h[field] = value

    async def eval(self, script: str, numkeys: int, *args: object) -> int:
        self._check()
        keys = [self._b(k) for k in args[:numkeys]]
        argv = [self._b(a) for a in args[numkeys:]]
        total, since, tool_calls, tool_last, client_calls, client_last = keys
        if script == _RECORD_SCRIPT:
            tool, client, now = argv
            self._incr(total, 1)
            self.strings.setdefault(since, now)
            self._hincrby(tool_calls, tool, 1)
            self._hset_max(tool_last, tool, now)
            if client:
                self._hincrby(client_calls, client, 1)
                self._hset_max(client_last, client, now)
            return 1
        if script == _SEED_SCRIPT:
            since_v = argv[0]
            if since_v:
                cur = self.strings.get(since)
                if cur is None or since_v < cur:
                    self.strings[since] = since_v
            total_v = int(argv[1])
            if total_v > 0:
                self._incr(total, total_v)
            i = 2
            for calls_key, last_key in (
                (tool_calls, tool_last),
                (client_calls, client_last),
            ):
                n = int(argv[i])
                i += 1
                for _ in range(n):
                    name, calls, last = argv[i], int(argv[i + 1]), argv[i + 2]
                    i += 3
                    if calls > 0:
                        self._hincrby(calls_key, name, calls)
                    if last:
                        self._hset_max(last_key, name, last)
            return 1
        if script == _RESTORE_SCRIPT:
            incoming = int(argv[0])
            current = int(self.strings.get(total, b"-1"))
            if current > incoming:
                return 0
            self.strings[total] = str(incoming).encode()
            if argv[1]:
                self.strings[since] = argv[1]
            else:
                self.strings.pop(since, None)
            for key in (tool_calls, tool_last, client_calls, client_last):
                self.hashes.pop(key, None)
            i = 2
            for calls_key, last_key in (
                (tool_calls, tool_last),
                (client_calls, client_last),
            ):
                n = int(argv[i])
                i += 1
                for _ in range(n):
                    name, calls, last = argv[i], argv[i + 1], argv[i + 2]
                    i += 3
                    self.hashes.setdefault(calls_key, {})[name] = calls
                    self.hashes.setdefault(last_key, {})[name] = last
            return 1
        raise AssertionError(f"unexpected lua script: {script!r}")


class RedisMcpToolCallMetricsRecordTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "mcp_tool_calls.json"
        self.store = JsonMcpToolCallStore(str(self.path))
        self.shadow = McpToolCallMetrics(store=self.store)
        self.redis = FakeRedis()
        self.metrics = create_redis_mcp_tool_call_metrics(
            self.redis, self.store, "test-src", shadow=self.shadow
        )

    async def test_record_writes_total_since_tool_and_client(self) -> None:
        await self.metrics.record("search_papers", client=DSH_PLUGIN_CLIENT)
        await self.metrics.record("search_papers", client=DSH_PLUGIN_CLIENT)
        await self.metrics.record("get_top_items")

        self.assertEqual(self.redis.strings[b"mcpmetrics:total"], b"3")
        since = self.redis.strings[b"mcpmetrics:since"].decode()
        datetime.fromisoformat(since)
        self.assertEqual(
            self.redis.hashes[b"mcpmetrics:tool_calls"],
            {b"search_papers": b"2", b"get_top_items": b"1"},
        )
        tool_last = self.redis.hashes[b"mcpmetrics:tool_last"]
        datetime.fromisoformat(tool_last[b"search_papers"].decode())
        self.assertEqual(
            self.redis.hashes[b"mcpmetrics:client_calls"],
            {DSH_PLUGIN_CLIENT.encode(): b"2"},
        )

    async def test_record_without_client_skips_client_keys(self) -> None:
        await self.metrics.record("get_top_items")

        self.assertEqual(self.redis.strings[b"mcpmetrics:total"], b"1")
        self.assertNotIn(b"mcpmetrics:client_calls", self.redis.hashes)

    async def test_record_dual_writes_json_shadow(self) -> None:
        await self.metrics.record("get_top_items", client=DSH_PLUGIN_CLIENT)

        persisted = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["total_calls"], 1)
        self.assertEqual(persisted["tools"]["get_top_items"]["calls"], 1)
        self.assertEqual(persisted["clients"][DSH_PLUGIN_CLIENT]["calls"], 1)

    async def test_redis_failure_keeps_shadow_and_never_raises(self) -> None:
        self.redis.fail = True

        with self.assertLogs(
            "backend.app.monitoring.mcp_redis_metrics", level="WARNING"
        ):
            await self.metrics.record("get_top_items")

        self.assertEqual(self.shadow.snapshot()["total_calls"], 1)


class RedisMcpToolCallMetricsSnapshotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "mcp_tool_calls.json"
        self.store = JsonMcpToolCallStore(str(self.path))
        self.shadow = McpToolCallMetrics(store=self.store)
        self.redis = FakeRedis()
        self.metrics = create_redis_mcp_tool_call_metrics(
            self.redis, self.store, "test-src", shadow=self.shadow
        )

    async def test_snapshot_reads_redis_aggregate_in_shadow_shape(self) -> None:
        # 另一进程（或 Go 侧）直接写 Redis 的计数也必须出现在快照里
        self.redis.strings[b"mcpmetrics:total"] = b"5"
        self.redis.strings[b"mcpmetrics:since"] = b"2026-08-01T00:00:00+00:00"
        self.redis.hashes[b"mcpmetrics:tool_calls"] = {
            b"search_papers": b"3",
            b"get_top_items": b"2",
        }
        self.redis.hashes[b"mcpmetrics:tool_last"] = {
            b"search_papers": b"2026-08-02T00:00:00+00:00",
            b"get_top_items": b"2026-08-01T12:00:00+00:00",
        }
        self.redis.hashes[b"mcpmetrics:client_calls"] = {DSH_PLUGIN_CLIENT.encode(): b"4"}
        self.redis.hashes[b"mcpmetrics:client_last"] = {
            DSH_PLUGIN_CLIENT.encode(): b"2026-08-02T00:00:00+00:00"
        }

        snapshot = await self.metrics.snapshot()

        self.assertEqual(snapshot["total_calls"], 5)
        self.assertEqual(snapshot["since"], "2026-08-01T00:00:00+00:00")
        self.assertEqual(list(snapshot["tools"]), ["get_top_items", "search_papers"])
        self.assertEqual(
            snapshot["tools"]["search_papers"],
            {"calls": 3, "last_called_at": "2026-08-02T00:00:00+00:00"},
        )
        self.assertEqual(snapshot["clients"][DSH_PLUGIN_CLIENT]["calls"], 4)

    async def test_snapshot_falls_back_to_shadow_when_redis_never_written(self) -> None:
        self.shadow.record("get_top_items")

        snapshot = await self.metrics.snapshot()

        self.assertEqual(snapshot["total_calls"], 1)
        self.assertIn("get_top_items", snapshot["tools"])

    async def test_snapshot_falls_back_to_shadow_on_redis_error(self) -> None:
        self.shadow.record("get_top_items")
        self.redis.fail = True

        with self.assertLogs(
            "backend.app.monitoring.mcp_redis_metrics", level="WARNING"
        ):
            snapshot = await self.metrics.snapshot()

        self.assertEqual(snapshot["total_calls"], 1)

    async def test_snapshot_skips_malformed_redis_entries(self) -> None:
        self.redis.strings[b"mcpmetrics:total"] = b"2"
        self.redis.hashes[b"mcpmetrics:tool_calls"] = {
            b"good": b"2",
            b"no_last": b"1",
        }
        self.redis.hashes[b"mcpmetrics:tool_last"] = {
            b"good": b"2026-08-02T00:00:00+00:00",
        }

        snapshot = await self.metrics.snapshot()

        self.assertEqual(list(snapshot["tools"]), ["good"])
        # total 以 Redis 计数器为准（聚合口径），不因坏条目回退
        self.assertEqual(snapshot["total_calls"], 2)


class RedisMcpToolCallMetricsRestoreTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.redis = FakeRedis()
        self.metrics = RedisMcpToolCallMetrics(self.redis, McpToolCallMetrics())
        self.payload = {
            "since": "2026-08-04T05:28:50+00:00",
            "total_calls": 4149,
            "tools": {
                "search_papers": {
                    "calls": 4149,
                    "last_called_at": "2026-09-11T09:49:33+00:00",
                }
            },
            "clients": {
                DSH_PLUGIN_CLIENT: {
                    "calls": 423,
                    "last_called_at": "2026-09-11T09:49:33+00:00",
                }
            },
        }

    async def test_restore_replaces_older_redis_snapshot(self) -> None:
        self.redis.strings[b"mcpmetrics:total"] = b"4041"

        restored = await self.metrics.restore_if_newer(self.payload)
        snapshot = await self.metrics.snapshot()

        self.assertTrue(restored)
        self.assertEqual(snapshot["total_calls"], 4149)
        self.assertEqual(snapshot["clients"][DSH_PLUGIN_CLIENT]["calls"], 423)

    async def test_restore_never_overwrites_newer_redis(self) -> None:
        self.redis.strings[b"mcpmetrics:total"] = b"4200"

        restored = await self.metrics.restore_if_newer(self.payload)

        self.assertFalse(restored)
        self.assertEqual(self.redis.strings[b"mcpmetrics:total"], b"4200")

    async def test_restore_repairs_missing_dsh_hash_when_total_is_equal(self) -> None:
        self.redis.strings[b"mcpmetrics:total"] = b"4149"

        restored = await self.metrics.restore_if_newer(self.payload)
        snapshot = await self.metrics.snapshot()

        self.assertTrue(restored)
        self.assertEqual(snapshot["clients"][DSH_PLUGIN_CLIENT]["calls"], 423)


class RedisMcpToolCallMetricsSeedTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "mcp_tool_calls.json"
        self.store = JsonMcpToolCallStore(str(self.path))
        self.shadow = McpToolCallMetrics(store=self.store)
        self.redis = FakeRedis()
        self.metrics = create_redis_mcp_tool_call_metrics(
            self.redis, self.store, "test-src", shadow=self.shadow
        )

    def _write_payload(self, payload: dict) -> None:
        self.path.write_text(json.dumps(payload), encoding="utf-8")

    async def test_seed_merges_json_payload_into_redis_once(self) -> None:
        self._write_payload(
            {
                "since": "2026-08-01T00:00:00+00:00",
                "total_calls": 5,
                "tools": {
                    "search_papers": {
                        "calls": 3,
                        "last_called_at": "2026-08-02T00:00:00+00:00",
                    },
                    "get_top_items": {
                        "calls": 2,
                        "last_called_at": "2026-08-01T12:00:00+00:00",
                    },
                },
                "clients": {
                    DSH_PLUGIN_CLIENT: {
                        "calls": 4,
                        "last_called_at": "2026-08-02T00:00:00+00:00",
                    }
                },
            }
        )

        await self.metrics.seed_from_json(MCP_TOOL_NAMES)
        snapshot = await self.metrics.snapshot()

        self.assertEqual(snapshot["total_calls"], 5)
        self.assertEqual(snapshot["since"], "2026-08-01T00:00:00+00:00")
        self.assertEqual(snapshot["tools"]["search_papers"]["calls"], 3)
        self.assertEqual(snapshot["clients"][DSH_PLUGIN_CLIENT]["calls"], 4)

        # 幂等：marker 已认领，第二次种子不重复累加
        await self.metrics.seed_from_json(MCP_TOOL_NAMES)
        self.assertEqual((await self.metrics.snapshot())["total_calls"], 5)

    async def test_seed_rebuckets_legacy_unknown_tool_names(self) -> None:
        # bucket 特性上线前的旧文件可能含原始工具名：种子时归入固定桶并合并
        self._write_payload(
            {
                "since": "2026-08-01T00:00:00+00:00",
                "total_calls": 5,
                "tools": {
                    "old_random_tool_a": {
                        "calls": 2,
                        "last_called_at": "2026-08-01T01:00:00+00:00",
                    },
                    "old_random_tool_b": {
                        "calls": 3,
                        "last_called_at": "2026-08-01T02:00:00+00:00",
                    },
                },
            }
        )

        await self.metrics.seed_from_json(MCP_TOOL_NAMES)
        snapshot = await self.metrics.snapshot()

        self.assertEqual(list(snapshot["tools"]), [UNKNOWN_TOOL_NAME])
        self.assertEqual(snapshot["tools"][UNKNOWN_TOOL_NAME]["calls"], 5)
        self.assertEqual(
            snapshot["tools"][UNKNOWN_TOOL_NAME]["last_called_at"],
            "2026-08-01T02:00:00+00:00",
        )

    async def test_seed_keeps_earliest_since_and_latest_last_called(self) -> None:
        # 另一源已种子/计数：since 取更早者，last 取更晚者，计数累加
        self.redis.strings[b"mcpmetrics:total"] = b"10"
        self.redis.strings[b"mcpmetrics:since"] = b"2026-07-01T00:00:00+00:00"
        self.redis.hashes[b"mcpmetrics:tool_calls"] = {b"search_papers": b"10"}
        self.redis.hashes[b"mcpmetrics:tool_last"] = {
            b"search_papers": b"2026-08-05T00:00:00+00:00"
        }
        self._write_payload(
            {
                "since": "2026-08-01T00:00:00+00:00",
                "total_calls": 3,
                "tools": {
                    "search_papers": {
                        "calls": 3,
                        "last_called_at": "2026-08-02T00:00:00+00:00",
                    }
                },
            }
        )

        await self.metrics.seed_from_json(MCP_TOOL_NAMES)
        snapshot = await self.metrics.snapshot()

        self.assertEqual(snapshot["since"], "2026-07-01T00:00:00+00:00")
        self.assertEqual(snapshot["total_calls"], 13)
        self.assertEqual(
            snapshot["tools"]["search_papers"]["last_called_at"],
            "2026-08-05T00:00:00+00:00",
        )

    async def test_seed_releases_marker_on_write_failure_for_retry(self) -> None:
        self._write_payload(
            {
                "since": "2026-08-01T00:00:00+00:00",
                "total_calls": 2,
                "tools": {
                    "get_top_items": {
                        "calls": 2,
                        "last_called_at": "2026-08-01T01:00:00+00:00",
                    }
                },
            }
        )

        # 认领标记成功、种子写失败：标记被释放，恢复后重试可成功
        class FlakyEvalRedis(FakeRedis):
            async def eval(self, script: str, numkeys: int, *args: object) -> int:
                raise ConnectionError("eval boom")

        flaky = FlakyEvalRedis()
        service = create_redis_mcp_tool_call_metrics(
            flaky, self.store, "test-src", shadow=self.shadow
        )
        with self.assertLogs(
            "backend.app.monitoring.mcp_redis_metrics", level="WARNING"
        ):
            await service.seed_from_json(MCP_TOOL_NAMES)
        self.assertNotIn(b"mcpmetrics:seeded:test-src", flaky.strings)

        recovered = create_redis_mcp_tool_call_metrics(
            self.redis, self.store, "test-src", shadow=self.shadow
        )
        await recovered.seed_from_json(MCP_TOOL_NAMES)
        self.assertEqual((await recovered.snapshot())["total_calls"], 2)

    async def test_seed_marker_claim_failure_is_non_fatal(self) -> None:
        self.redis.fail = True
        with self.assertLogs(
            "backend.app.monitoring.mcp_redis_metrics", level="WARNING"
        ):
            await self.metrics.seed_from_json(MCP_TOOL_NAMES)

    async def test_seed_with_missing_json_claims_marker_without_writes(self) -> None:
        await self.metrics.seed_from_json(MCP_TOOL_NAMES)

        self.assertIn(b"mcpmetrics:seeded:test-src", self.redis.strings)
        self.assertNotIn(b"mcpmetrics:total", self.redis.strings)
        # 幂等：再次调用提前返回
        await self.metrics.seed_from_json(MCP_TOOL_NAMES)


class McpToolCallModuleDefaultFallbackTests(unittest.TestCase):
    """app.state 未绑定（不经 lifespan）时回退模块级 JSON 门面。"""

    def test_resolve_falls_back_to_module_default(self) -> None:
        isolated = McpToolCallMetrics()
        request = types.SimpleNamespace(
            app=types.SimpleNamespace(state=types.SimpleNamespace())
        )
        with patch.object(
            mcp_redis_metrics,
            "MCP_TOOL_CALL_METRICS_SERVICE",
            LocalMcpToolCallMetrics(isolated),
        ):
            service = mcp_redis_metrics.resolve_tool_call_metrics(request)
        self.assertIsInstance(service, LocalMcpToolCallMetrics)
        self.assertIs(service.shadow, isolated)

    def test_resolve_prefers_app_state_binding(self) -> None:
        bound = LocalMcpToolCallMetrics(McpToolCallMetrics())
        request = types.SimpleNamespace(
            app=types.SimpleNamespace(
                state=types.SimpleNamespace(mcp_tool_call_metrics=bound)
            )
        )
        self.assertIs(mcp_redis_metrics.resolve_tool_call_metrics(request), bound)


class DashboardMcpCallCountsTests(unittest.IsolatedAsyncioTestCase):
    def _app(self, service: object) -> object:
        return types.SimpleNamespace(
            state=types.SimpleNamespace(mcp_tool_call_metrics=service)
        )

    async def test_counts_come_from_bound_service_snapshot(self) -> None:
        redis = FakeRedis()
        shadow = McpToolCallMetrics()
        service = RedisMcpToolCallMetrics(redis, shadow)
        await service.record("get_top_items", client=DSH_PLUGIN_CLIENT)
        await service.record("search_papers")

        total, dsh = await routes_dashboard._get_mcp_call_counts(
            self._app(service)
        )

        self.assertEqual(total, 2)
        self.assertEqual(dsh, 1)

    async def test_snapshot_failure_silently_returns_zero_pair(self) -> None:
        class BoomService:
            async def snapshot(self) -> dict:
                raise RuntimeError("boom")

        total, dsh = await routes_dashboard._get_mcp_call_counts(
            self._app(BoomService())
        )

        self.assertEqual((total, dsh), (0, 0))


class CollectMetricsSnapshotParamTests(unittest.TestCase):
    def test_collect_metrics_prefers_prepassed_snapshot(self) -> None:
        task_reader = MagicMock(spec=RecentTaskReader)
        task_reader.get_recent_tasks.return_value = []
        evaluation_reader = MagicMock(spec=EvaluationSummaryReader)
        evaluation_reader.get_eval_summary.return_value = {}
        document_statistics = MagicMock(spec=DocumentStatisticsReader)
        document_statistics.get_document_count.return_value = 1
        briefing_reader = MagicMock(spec=BriefingReader)
        briefing_reader.list_briefings.return_value = []

        local = McpToolCallMetrics()
        local.record("search_papers")
        redis_snapshot = {
            "since": "2026-08-01T00:00:00+00:00",
            "total_calls": 42,
            "tools": {},
            "clients": {},
        }

        result = monitor_metrics.collect_metrics(
            task_reader=task_reader,
            evaluation_reader=evaluation_reader,
            document_statistics=document_statistics,
            briefing_reader=briefing_reader,
            mcp_tool_calls=local,
            mcp_tool_calls_snapshot=redis_snapshot,
        )

        # 预取好的 Redis 聚合快照优先于本地同步计数器
        self.assertEqual(result["mcp_tool_calls"]["total_calls"], 42)


if __name__ == "__main__":
    unittest.main()
