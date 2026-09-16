from __future__ import annotations

from datetime import date, datetime
from typing import Any

from psycopg.types.json import Jsonb

from backend.app.core.postgres_database import PostgresDatabaseLifecycle


class CopyLimitExceeded(Exception):
    pass


class CopyRequestConflict(Exception):
    pass


class PostgresUiLibraryRepository:
    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def engagement(self, user_id: int | None, since: datetime, now: datetime) -> list[dict[str, Any]]:
        with self._database.transaction() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT template_id, count(*) FILTER (WHERE active) AS likes,
                  count(*) FILTER (WHERE active AND first_liked_at > %s AND first_liked_at <= %s) AS score,
                  bool_or(user_id = %s AND active) AS liked
                FROM ui_template_likes GROUP BY template_id
            """, (since, now, user_id or 0))
            return list(cur.fetchall())

    def set_like(self, user_id: int, template_id: str, active: bool) -> None:
        with self._database.transaction() as conn, conn.cursor() as cur:
            if not active:
                cur.execute("UPDATE ui_template_likes SET active=FALSE WHERE user_id=%s AND template_id=%s", (user_id, template_id))
                return
            cur.execute("""
                INSERT INTO ui_template_likes (user_id, template_id, active)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, template_id) DO UPDATE SET active = EXCLUDED.active
            """, (user_id, template_id, active))

    def copy_usage(self, user_id: int, day: date) -> int:
        with self._database.transaction() as conn, conn.cursor() as cur:
            cur.execute("SELECT used FROM ui_copy_daily_usage WHERE user_id=%s AND usage_date=%s", (user_id, day))
            row = cur.fetchone()
            return int(row['used']) if row else 0

    def consume_copy(self, user_id: int, template_id: str, kind: str, request_id: str,
                     day: date, limit: int | None) -> int:
        # The per-account transaction lock also serializes idempotency checks.
        # It prevents parallel requests/tabs from exceeding the daily allowance.
        with self._database.transaction() as conn, conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(7419, %s)", (user_id,))
            cur.execute("SELECT template_id, kind FROM ui_copy_receipts WHERE user_id=%s AND request_id=%s",
                        (user_id, request_id))
            previous = cur.fetchone()
            if previous and (previous['template_id'] != template_id or previous['kind'] != kind):
                raise CopyRequestConflict()
            cur.execute("SELECT used FROM ui_copy_daily_usage WHERE user_id=%s AND usage_date=%s", (user_id, day))
            row = cur.fetchone()
            used = int(row['used']) if row else 0
            if previous:
                return used
            if limit is not None and used >= limit:
                raise CopyLimitExceeded()
            cur.execute("""
                INSERT INTO ui_copy_daily_usage(user_id, usage_date, used) VALUES (%s, %s, 1)
                ON CONFLICT(user_id, usage_date) DO UPDATE SET used=ui_copy_daily_usage.used+1
                RETURNING used
            """, (user_id, day))
            used = int(cur.fetchone()['used'])
            cur.execute("INSERT INTO ui_copy_receipts(user_id, request_id, template_id, kind) VALUES (%s,%s,%s,%s)",
                        (user_id, request_id, template_id, kind))
            return used

    def source_state(self, source_id: str) -> dict[str, Any] | None:
        with self._database.transaction() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM ui_discovery_sources WHERE source_id=%s", (source_id,))
            return cur.fetchone()

    def list_source_configs(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM ui_discovery_source_configs"
        if enabled_only:
            query += " WHERE enabled=TRUE"
        query += " ORDER BY name, id"
        with self._database.transaction() as conn, conn.cursor() as cur:
            cur.execute(query)
            return list(cur.fetchall())

    def create_source_config(self, values: dict[str, Any]) -> dict[str, Any]:
        with self._database.transaction() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ui_discovery_source_configs
                    (name, kind, repository, path_patterns, feed_url, enabled, x_auto_publish)
                VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *
            """, (
                values['name'], values['kind'], values.get('repository'),
                values.get('path_patterns') or [], values.get('feed_url'), values['enabled'],
                values.get('x_auto_publish', False),
            ))
            return cur.fetchone()

    def update_source_config(self, config_id: int, values: dict[str, Any]) -> dict[str, Any] | None:
        with self._database.transaction() as conn, conn.cursor() as cur:
            cur.execute("""
                UPDATE ui_discovery_source_configs SET
                    name=%s, kind=%s, repository=%s, path_patterns=%s,
                    feed_url=%s, enabled=%s, x_auto_publish=%s, updated_at=now()
                WHERE id=%s RETURNING *
            """, (
                values['name'], values['kind'], values.get('repository'),
                values.get('path_patterns') or [], values.get('feed_url'), values['enabled'],
                values.get('x_auto_publish', False), config_id,
            ))
            return cur.fetchone()

    def delete_source_config(self, config_id: int) -> bool:
        with self._database.transaction() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM ui_discovery_source_configs WHERE id=%s", (config_id,))
            return cur.rowcount > 0

    def source_candidates(self, source_id: str) -> list[dict[str, Any]]:
        with self._database.transaction() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT c.payload FROM ui_discovery_candidates c
                JOIN ui_discovery_sources s ON s.source_id=c.source_id
                WHERE c.source_id=%s AND c.payload->>'source_revision'=s.revision
                ORDER BY c.candidate_id
            """, (source_id,))
            return [row['payload'] for row in cur.fetchall()]

    def record_discovery(self, source_id: str, revision: str,
                         candidates: list[dict[str, Any]]) -> dict[str, int]:
        counts = {'baseline': 0, 'new': 0, 'updated': 0}
        with self._database.transaction() as conn, conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ('ui-discovery:' + source_id,))
            cur.execute("SELECT last_success_at FROM ui_discovery_sources WHERE source_id=%s", (source_id,))
            state = cur.fetchone()
            baseline = not state or not state['last_success_at']
            for item in candidates:
                cur.execute("SELECT revision FROM ui_discovery_candidates WHERE candidate_id=%s", (item['id'],))
                old = cur.fetchone()
                if old and old['revision'] == item['revision']:
                    continue
                change = 'updated' if old else 'baseline' if baseline else 'new'
                cur.execute("""
                    INSERT INTO ui_discovery_candidates(candidate_id, source_id, revision, payload, change_kind)
                    VALUES (%s,%s,%s,%s,%s) ON CONFLICT(candidate_id) DO UPDATE SET
                    revision=EXCLUDED.revision, payload=EXCLUDED.payload, change_kind=EXCLUDED.change_kind,
                    updated_at=now(), review_status='pending'
                """, (item['id'], source_id, item['revision'], Jsonb(item), change))
                counts[change] += 1
            cur.execute("""
                INSERT INTO ui_discovery_sources(source_id, revision, last_success_at) VALUES (%s,%s,now())
                ON CONFLICT(source_id) DO UPDATE SET revision=EXCLUDED.revision, checked_at=now(),
                last_success_at=now(), error=NULL
            """, (source_id, revision))
        return counts

    def record_failure(self, source_id: str, error: str) -> None:
        with self._database.transaction() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ui_discovery_sources(source_id, error) VALUES (%s,%s)
                ON CONFLICT(source_id) DO UPDATE SET checked_at=now(), error=EXCLUDED.error
            """, (source_id, error))

    def discovery_report(self, limit: int = 100) -> dict[str, Any]:
        with self._database.transaction() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM ui_discovery_sources ORDER BY source_id")
            sources = list(cur.fetchall())
            cur.execute("SELECT * FROM ui_discovery_candidates ORDER BY updated_at DESC, candidate_id LIMIT %s", (limit,))
            candidates = list(cur.fetchall())
            cur.execute("SELECT count(*) AS n FROM ui_discovery_candidates")
            return {'sources': sources, 'candidates': candidates, 'total': cur.fetchone()['n']}
