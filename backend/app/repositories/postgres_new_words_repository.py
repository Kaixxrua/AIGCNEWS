from __future__ import annotations

from datetime import date, datetime
from typing import Any

from psycopg.types.json import Jsonb

from backend.app.core.postgres_database import PostgresDatabaseLifecycle

# Publication dates only: a newly imported old document is never new evidence.
_PUBLISHED = "COALESCE(NULLIF(published_at, ''), NULLIF(published_date, ''))"
_PROJECTION = "id, source, title, summary, url, published_at, published_date, retweeted_by"


class PostgresNewWordsRepository:
    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def recent_documents(self, since: date, until: date, sources: list[str]) -> list[dict[str, Any]]:
        with self._database.transaction() as conn:
            rows = conn.execute(
                f"""SELECT {_PROJECTION} FROM (
                    SELECT {_PROJECTION},
                        row_number() OVER (PARTITION BY source ORDER BY {_PUBLISHED} DESC, id) AS n
                    FROM documents WHERE source = ANY(%s)
                        AND LEFT({_PUBLISHED}, 10) >= %s AND LEFT({_PUBLISHED}, 10) < %s
                ) ranked WHERE n <= 120 ORDER BY source, n""",
                (sources, since.isoformat(), until.isoformat()),
            ).fetchall()
        return [dict(row) for row in rows]

    def historical_mentions(self, aliases: list[str], before: date, sources: list[str]) -> list[dict[str, Any]]:
        # Parameterized literal matching: model-generated %, _ and SQL are not patterns.
        with self._database.transaction() as conn:
            rows = conn.execute(
                f"""SELECT {_PROJECTION} FROM documents
                    WHERE source = ANY(%s) AND LEFT({_PUBLISHED}, 10) < %s
                    AND EXISTS (SELECT 1 FROM unnest(%s::text[]) AS term
                        WHERE strpos(lower(COALESCE(title, '') || ' ' || COALESCE(summary, '')), lower(term)) > 0)
                    ORDER BY {_PUBLISHED} LIMIT 200""",
                (sources, before.isoformat(), aliases),
            ).fetchall()
        return [dict(row) for row in rows]

    def existing_ids(self, ids: list[str], sources: list[str]) -> set[str]:
        with self._database.transaction() as conn:
            rows = conn.execute(
                "SELECT id FROM documents WHERE id = ANY(%s) AND source = ANY(%s)", (ids, sources),
            ).fetchall()
        return {str(row["id"]) for row in rows}

    def get_snapshot(self, day: date) -> dict[str, Any] | None:
        with self._database.transaction() as conn:
            row = conn.execute(
                "SELECT items, generated_at FROM dashboard_new_words WHERE snapshot_date = %s", (day,),
            ).fetchone()
        return dict(row) if row else None

    def snapshot_dates(self, before: date, limit: int) -> list[date]:
        with self._database.transaction() as conn:
            rows = conn.execute(
                """SELECT snapshot_date FROM dashboard_new_words
                    WHERE snapshot_date < %s AND jsonb_array_length(items) > 0
                    ORDER BY snapshot_date DESC LIMIT %s""", (before, limit),
            ).fetchall()
        return [row["snapshot_date"] for row in rows]

    def save_snapshot(self, day: date, items: list[dict[str, Any]], generated_at: datetime) -> None:
        with self._database.transaction() as conn:
            conn.execute(
                """INSERT INTO dashboard_new_words (snapshot_date, items, generated_at) VALUES (%s, %s, %s)
                    ON CONFLICT (snapshot_date) DO UPDATE
                    SET items = EXCLUDED.items, generated_at = EXCLUDED.generated_at
                    WHERE dashboard_new_words.generated_at < EXCLUDED.generated_at""",
                (day, Jsonb(items), generated_at),
            )
