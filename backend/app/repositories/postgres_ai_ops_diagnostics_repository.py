"""Bounded local diagnostic reads, separate from public monitoring contracts."""
from datetime import datetime, timedelta, timezone

from backend.app.services.ai_ops_diagnostics import aggregate_errors


class PostgresAiOpsDiagnosticsRepository:
    def __init__(self, database):
        self.database = database

    def errors(self):
        with self.database.transaction() as conn:
            conn.execute("SET LOCAL statement_timeout = '5s'")
            total = conn.execute("SELECT count(*) AS n FROM error_events "
                                 "WHERE occurred_at > now()-interval '24 hours'").fetchone()["n"]
            rows = conn.execute(
                "SELECT occurred_at, logger_name, exception_type, left(message,8000) AS message, "
                "left(stack_trace,16000) AS stack_trace FROM error_events "
                "WHERE occurred_at > now()-interval '24 hours' ORDER BY occurred_at DESC LIMIT 1000").fetchall()
        return aggregate_errors(rows, total)

    def source_trends(self):
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        with self.database.transaction() as conn:
            conn.execute("SET LOCAL statement_timeout = '5s'")
            rows = conn.execute("""
                WITH recent AS (
                    SELECT split_part(task_name,':',2) AS source, status, item_count,
                           CASE WHEN pg_input_is_valid(started_at,'timestamptz')
                                THEN started_at::timestamptz END AS started,
                           CASE WHEN pg_input_is_valid(finished_at,'timestamptz')
                                THEN finished_at::timestamptz END AS finished
                    FROM ingestion_tasks WHERE started_at >= %s AND task_name LIKE 'single:%%'
                )
                SELECT source,
                    count(*) FILTER (WHERE started>now()-interval '24 hours') AS total_24h,
                    count(*) FILTER (WHERE started>now()-interval '24 hours' AND status='failed') AS failed_24h,
                    count(*) FILTER (WHERE started<=now()-interval '24 hours') AS total_previous_24h,
                    count(*) FILTER (WHERE started<=now()-interval '24 hours' AND status='failed') AS failed_previous_24h,
                    count(*) FILTER (WHERE status='running') AS running,
                    count(*) FILTER (WHERE status='success' AND item_count=0) AS zero_output_success_48h,
                    max(finished) FILTER (WHERE status='success') AS last_success_in_window,
                    max(finished) FILTER (WHERE status='failed') AS last_failure_in_window,
                    coalesce(sum(item_count) FILTER (WHERE started>now()-interval '24 hours' AND status='success'),0) AS items_24h
                FROM recent WHERE started > now()-interval '48 hours'
                GROUP BY source ORDER BY source LIMIT 20
            """, (cutoff[:10],)).fetchall()
        known = {"x", "arxiv", "github", "news", "hackernews", "dailyhot", "producthunt"}
        return {"window_hours": 48, "sources": [dict(r) for r in rows if r["source"] in known],
                "scope": "任务成功不等于 PDF、译文或投递成功；窗口内无成功不等于从未成功。"}

    def database_status(self):
        with self.database.transaction() as conn:
            conn.execute("SET LOCAL statement_timeout = '5s'")
            row = conn.execute("""
                SELECT count(*) AS connections,
                    count(*) FILTER (WHERE state='active') AS active,
                    count(*) FILTER (WHERE wait_event_type='Lock') AS lock_waiting,
                    count(*) FILTER (WHERE state='idle in transaction') AS idle_in_transaction,
                    coalesce(max(extract(epoch FROM now()-query_start)) FILTER (WHERE state='active'),0)::int AS longest_active_seconds
                FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()
            """).fetchone()
        return {**dict(row), "scope": "当前数据库连接摘要，不含 SQL、参数、用户或主机信息"}

    def investigation_history(self):
        with self.database.transaction() as conn:
            conn.execute("SET LOCAL statement_timeout = '5s'")
            counts = conn.execute("SELECT status,count(*) AS n FROM ai_ops_runs "
                                  "WHERE started_at>now()-interval '24 hours' GROUP BY status").fetchall()
            stages = conn.execute("""
                SELECT stage, count(*) AS n FROM (
                    SELECT (SELECT e->>'title' FROM jsonb_array_elements(r.events) WITH ORDINALITY ev(e,ord)
                            WHERE e->>'kind' IN ('model','tool_start') ORDER BY ord DESC LIMIT 1) AS stage
                    FROM ai_ops_runs r WHERE started_at>now()-interval '24 hours' AND status='failed'
                ) f GROUP BY stage
            """).fetchall()
        allowed = {"生成调查报告", "选择修复动作", "选择下一项查证"}
        return {"window_hours": 24, "statuses": {r["status"]: r["n"] for r in counts},
                "failures": [{"stage": r["stage"] if r["stage"] in allowed else "证据采集", "count": r["n"]}
                             for r in stages]}
