from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from psycopg.types.json import Jsonb

RECOVERY_JOBS = {"single:news": "news_techmeme", "single:hackernews": "hackernews",
                 "single:dailyhot": "dailyhot_hotlists"}

class PostgresAiOpsRepository:
    def __init__(self, database):
        self.database = database

    def config(self):
        with self.database.transaction() as conn, conn.cursor() as cur:
            cur.execute("SELECT enabled, interval_minutes, recovery_enabled FROM ai_ops_config WHERE id = 1")
            return dict(cur.fetchone())

    def configure(self, enabled, interval_minutes, recovery_enabled=None):
        with self.database.transaction() as conn, conn.cursor() as cur:
            cur.execute("UPDATE ai_ops_config SET enabled=%s, interval_minutes=%s, "
                        "recovery_enabled=COALESCE(%s,recovery_enabled) WHERE id=1",
                        (enabled, interval_minutes, recovery_enabled))

    def reserve_recovery(self, run_id, task_name, job_id, eligible):
        if RECOVERY_JOBS.get(task_name) != job_id:
            return None
        with self.database.transaction() as conn, conn.cursor() as cur:
            cur.execute("SELECT recovery_enabled FROM ai_ops_config WHERE id=1 FOR UPDATE")
            if not cur.fetchone()["recovery_enabled"]:
                return None
            cur.execute("SELECT status FROM ai_ops_runs WHERE id=%s FOR UPDATE", (run_id,))
            run = cur.fetchone()
            if not run or run["status"] != "running":
                return None
            cur.execute("SELECT COUNT(*) AS daily, COUNT(*) FILTER "
                        "(WHERE created_at > now()-interval '1 hour') AS hourly "
                        "FROM ai_ops_recovery_actions WHERE created_at > now()-interval '24 hours'")
            budget = cur.fetchone()
            if budget["daily"] >= 3 or budget["hourly"]:
                return None
            cur.execute("SELECT 1 FROM ingestion_tasks WHERE starts_with(task_name,%s) "
                        "AND status IN ('running','pending') LIMIT 1", (task_name,))
            if cur.fetchone():
                return None
            cur.execute("SELECT * FROM ingestion_tasks WHERE task_name=%s ORDER BY id DESC LIMIT 1",
                        (task_name,))
            task = cur.fetchone()
            if not eligible(task, datetime.now(timezone.utc)):
                return None
            action = {"id": str(uuid4()), "task_id": task["id"], "job_id": job_id}
            cur.execute("INSERT INTO ai_ops_recovery_actions (id,run_id,task_id,job_id,status) "
                        "VALUES (%s,%s,%s,%s,'reserved') ON CONFLICT (task_id) DO NOTHING",
                        (action["id"], run_id, task["id"], job_id))
            if not cur.rowcount:
                return None
            event = {"at": datetime.now(timezone.utc).isoformat(), "kind": "action_start",
                     "title": "公共资讯补跑", "data": action}
            cur.execute("UPDATE ai_ops_runs SET events=events || %s, updated_at=now() WHERE id=%s",
                        (Jsonb([event]), run_id))
            return action

    def finish_recovery(self, run_id, action, status):
        if status not in {"scheduled", "uncertain"}:
            raise ValueError("invalid_recovery_status")
        with self.database.transaction() as conn, conn.cursor() as cur:
            cur.execute("UPDATE ai_ops_recovery_actions SET status=%s WHERE id=%s AND run_id=%s "
                        "AND status='reserved'", (status, action["id"], run_id))
            if not cur.rowcount:
                return
            event = {"at": datetime.now(timezone.utc).isoformat(), "kind": "action_result",
                     "title": "公共资讯补跑", "data": {**action, "status": status}}
            # Preserve an admitted action's outcome even if the investigation was cancelled.
            cur.execute("UPDATE ai_ops_runs SET events=events || %s, updated_at=now() WHERE id=%s",
                        (Jsonb([event]), run_id))

    def create(self, trigger, *, scheduled=False):
        with self.database.transaction() as conn, conn.cursor() as cur:
            # One admission lock across workers; leases outlive the bounded 5-minute run.
            cur.execute("SELECT pg_advisory_xact_lock(760076)")
            cur.execute("UPDATE ai_ops_runs SET status='interrupted', updated_at=now() "
                        "WHERE status='running' AND started_at < now() - interval '6 minutes'")
            cur.execute("SELECT id FROM ai_ops_runs WHERE status='running'")
            if cur.fetchone():
                return None
            if scheduled:
                cur.execute("SELECT 1 FROM ai_ops_config c WHERE id=1 AND enabled AND NOT EXISTS "
                            "(SELECT 1 FROM ai_ops_runs WHERE started_at > now() - "
                            "make_interval(mins => c.interval_minutes))")
                if not cur.fetchone():
                    return None
            run_id = str(uuid4())
            cur.execute("INSERT INTO ai_ops_runs (id, trigger, status) VALUES (%s,%s,'running')",
                        (run_id, trigger))
            cur.execute("DELETE FROM ai_ops_runs WHERE status <> 'running' "
                        "AND started_at < now() - interval '30 days'")
            return run_id

    def list(self):
        with self.database.transaction() as conn, conn.cursor() as cur:
            cur.execute("SELECT id, trigger, status, started_at, updated_at FROM ai_ops_runs "
                        "ORDER BY started_at DESC LIMIT 50")
            return [dict(row) for row in cur.fetchall()]

    def get(self, run_id):
        with self.database.transaction() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM ai_ops_runs WHERE id=%s", (run_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def event(self, run_id, kind, title, data=None):
        event = {"at": datetime.now(timezone.utc).isoformat(), "kind": kind,
                 "title": title, "data": data}
        with self.database.transaction() as conn, conn.cursor() as cur:
            cur.execute("UPDATE ai_ops_runs SET events=events || %s, updated_at=now() "
                        "WHERE id=%s AND status='running'", (Jsonb([event]), run_id))
            return cur.rowcount == 1

    def finish(self, run_id, status, report=""):
        with self.database.transaction() as conn, conn.cursor() as cur:
            cur.execute("UPDATE ai_ops_runs SET status=%s, report=%s, updated_at=now() "
                        "WHERE id=%s AND status='running'", (status, report, run_id))
