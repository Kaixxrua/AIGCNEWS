"""Durable, idempotent observation of admitted actions; never replays work."""
from datetime import datetime, timedelta, timezone
from time import monotonic

from psycopg.types.json import Jsonb


def record_followup(conn, run_id, action_id, action, target, baseline):
    conn.execute("""
        INSERT INTO ai_ops_followups (id,run_id,action,target,baseline,runtime_sha)
        VALUES (%s,%s,%s,%s,%s, (
            SELECT e->'data'->'result'->>'active_sha'
            FROM ai_ops_runs r CROSS JOIN LATERAL jsonb_array_elements(r.events) WITH ORDINALITY ev(e,ord)
            WHERE r.id=%s AND e->>'kind'='tool_result' AND e->>'title'='delivery'
              AND e->'data'->'result'->>'status'='ok'
              AND e->'data'->'result'->>'active_sha' ~ '^[a-f0-9]{40,64}$'
            ORDER BY ord DESC LIMIT 1)) ON CONFLICT (id) DO NOTHING
    """, (action_id, run_id, action, target, Jsonb(baseline), run_id))


class PostgresAiOpsFollowupRepository:
    def __init__(self, database):
        self.database = database

    def recent(self):
        with self.database.transaction() as conn:
            rows = conn.execute("SELECT id,action,target,policy_version,runtime_sha,status,created_at,checked_at, "
                                "next_check_at,deadline_at,evidence "
                                "FROM ai_ops_followups ORDER BY created_at DESC LIMIT 20").fetchall()
        return [dict(r) for r in rows]

    def cases(self):
        with self.database.transaction() as conn:
            rows = conn.execute("SELECT id,action,target,baseline - 'task_ids' AS baseline,policy_version,runtime_sha, "
                                "status,created_at,checked_at,evidence "
                                "FROM ai_ops_followups WHERE status IN ('verified','not_recovered') "
                                "ORDER BY checked_at DESC LIMIT 50").fetchall()
        return [dict(r) for r in rows]

    def translation_cohort(self, limit=200):
        with self.database.transaction() as conn:
            rows = conn.execute("SELECT id FROM x_translation_tasks WHERE status IN ('pending','failed') "
                                "ORDER BY updated_at,id LIMIT %s", (min(200, max(0, limit)),)).fetchall()
        return [r["id"] for r in rows]

    def review(self):
        """Row locks make concurrent workers append each terminal result only once."""
        stop_at, reviewed = monotonic() + 15, 0
        with self.database.transaction() as conn:
            conn.execute("SET LOCAL statement_timeout = '5s'")
            rows = conn.execute("SELECT * FROM ai_ops_followups WHERE status='pending' AND next_check_at<=now() "
                                "ORDER BY next_check_at LIMIT 20 FOR UPDATE SKIP LOCKED").fetchall()
            for row in rows:
                if monotonic() >= stop_at:
                    break
                evidence, observed = self._observe(conn, row)
                now = datetime.now(timezone.utc)
                expired = row["deadline_at"] <= now
                status = "pending"
                if now > row["deadline_at"] + timedelta(minutes=5):
                    # A stopped controller cannot retroactively prove recovery
                    # within the observation window from today's healthy state.
                    status = "inconclusive"
                    evidence["reason"] = "observation_window_missed"
                elif observed is True:
                    status = "verified"
                elif expired:
                    status = "not_recovered" if observed is False else "inconclusive"
                conn.execute("UPDATE ai_ops_followups SET status=%s,evidence=%s,checked_at=now(), "
                             "next_check_at=now()+interval '2 minutes' WHERE id=%s",
                             (status, Jsonb(evidence), row["id"]))
                if status != "pending":
                    event = {"kind": "followup_result", "title": "修复回访",
                             "at": datetime.now(timezone.utc).isoformat(),
                             "data": {"id": str(row["id"]), "action": row["action"], "status": status, **evidence}}
                    # A cancelled/finished investigation must retain the real outcome.
                    conn.execute("UPDATE ai_ops_runs SET events=events || %s WHERE id=%s", (Jsonb([event]), row["run_id"]))
                reviewed += 1
        return reviewed

    @staticmethod
    def _observe(conn, row):
        action, baseline = row["action"], row["baseline"]
        if action in {"x_translation_retry", "ingestion_orphan_close"}:
            ids = baseline.get("task_ids", [])
            if not ids:
                return {"scope": "目标任务", "reason": "missing_cohort"}, None
            if action == "x_translation_retry":
                tasks = conn.execute("SELECT id,status,NULLIF(BTRIM(translation_zh),'') IS NOT NULL AS has_output "
                                     "FROM x_translation_tasks WHERE id=ANY(%s)", (ids,)).fetchall()
                good = sum(t["status"] == "succeeded" and t["has_output"] for t in tasks)
                scope = "目标译文任务恢复；页面呈现未验证"
            else:
                tasks = conn.execute("SELECT id,status,error_msg LIKE 'orphaned:%%' AS closed "
                                     "FROM ingestion_tasks WHERE id=ANY(%s)", (ids,)).fetchall()
                good = sum(t["status"] == "failed" and bool(t["closed"]) for t in tasks)
                scope = "目标僵死任务已收尾；采集恢复未验证"
            evidence = {"scope": scope, "expected": len(ids), "found": len(tasks), "recovered": good}
            complete = len(tasks) == len(ids)
            return evidence, (good == len(ids)) if complete else None
        if action == "briefing_regenerate":
            key = baseline.get("cache_key")
            if not key:
                return {"scope": "简报生成", "reason": "missing_cache_key"}, None
            found = conn.execute("SELECT id, NULLIF(BTRIM(content),'') IS NOT NULL AS has_output "
                                 "FROM briefings WHERE date=%s", (key,)).fetchone()
            return {"scope": "简报生成；邮件投递未验证", "briefing_id": found["id"] if found else None}, bool(found and found["has_output"])
        # Same-source success must start after submission, not merely have a newer ID.
        task = conn.execute("""
            SELECT id,status,item_count FROM ingestion_tasks WHERE task_name=%s AND id>%s
              AND CASE WHEN pg_input_is_valid(started_at,'timestamptz') THEN started_at::timestamptz END >= %s
            ORDER BY id DESC LIMIT 1
        """, (row["target"], baseline["task_id"], row["created_at"])).fetchone()
        evidence = {"scope": "同源后续采集恢复；不能归因于某次补跑", "task": dict(task) if task else None}
        if not task or task["status"] in {"running", "pending"}:
            return evidence, None
        return evidence, task["status"] == "success" and (task["item_count"] or 0) > 0
