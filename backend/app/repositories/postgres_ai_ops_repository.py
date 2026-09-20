from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from psycopg.types.json import Jsonb


class PostgresAiOpsRepository:
    def __init__(self, database):
        self.database = database

    def config(self):
        with self.database.transaction() as conn, conn.cursor() as cur:
            cur.execute("SELECT enabled, interval_minutes FROM ai_ops_config WHERE id = 1")
            return dict(cur.fetchone())

    def configure(self, enabled, interval_minutes):
        with self.database.transaction() as conn, conn.cursor() as cur:
            cur.execute("UPDATE ai_ops_config SET enabled=%s, interval_minutes=%s WHERE id=1",
                        (enabled, interval_minutes))

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
