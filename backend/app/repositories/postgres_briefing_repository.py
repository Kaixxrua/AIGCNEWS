from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.app.core.postgres_database import PostgresDatabaseLifecycle


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class PostgresBriefingRepository:
    """PostgreSQL persistence for generated briefing content."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def save_briefing(
        self,
        date_str: str,
        content: str,
        *,
        content_zh: str = "",
        content_en: str = "",
    ) -> int:
        content_zh = content_zh or content
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                # 按 date 幂等（uq_briefings_date，迁移 0033）：同一期重复生成
                # 原地覆盖而不是插入重复行，id 保持稳定，订阅投递标记
                # （last_delivered_briefing_id）的单调语义不受影响。
                cursor.execute(
                    """
                    INSERT INTO briefings (date, content, created_at, content_zh, content_en)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (date) DO UPDATE SET
                        content = EXCLUDED.content,
                        content_zh = EXCLUDED.content_zh,
                        content_en = EXCLUDED.content_en,
                        created_at = EXCLUDED.created_at
                    RETURNING id
                    """,
                    (date_str, content_zh, _utcnow(), content_zh, content_en),
                )
                row = cursor.fetchone()
                if row is None:
                    raise RuntimeError("PostgreSQL briefing upsert did not return an id")
                return int(row["id"])

    def get_latest_briefing(self) -> dict[str, Any] | None:
        return self._fetchone(
            """
            SELECT * FROM briefings
            ORDER BY id DESC
            LIMIT 1
            """
        )

    def get_briefing_by_date(self, date_str: str) -> dict[str, Any] | None:
        return self._fetchone(
            "SELECT * FROM briefings WHERE date = %s",
            (date_str,),
        )

    def get_briefing(self, briefing_id: int) -> dict[str, Any] | None:
        return self._fetchone(
            "SELECT * FROM briefings WHERE id = %s",
            (briefing_id,),
        )

    def list_briefings(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, date, created_at,
                           SUBSTRING(content FROM 1 FOR 100) AS content_preview
                    FROM briefings
                    ORDER BY id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                return [dict(row) for row in cursor.fetchall()]

    def list_recent_daily_briefings(self, limit: int = 7) -> list[dict[str, Any]]:
        """近 N 期综合日报（含全文 content_zh），按日期新到旧。

        date 列混合两种键：裸日期（'2026-08-27'，综合报）与 '{date}_{module}'
        （模块报）。简报 RSS 只出综合报——模块报是综合报的原料，且部分模块
        当日可能缺席；以下划线出现与否区分两种键，比 LIKE 转义更直白。
        """
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, date, created_at, content_zh, content_en
                    FROM briefings
                    WHERE position('_' in date) = 0
                    ORDER BY date DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                return [dict(row) for row in cursor.fetchall()]

    def _fetchone(
        self,
        sql: str,
        params: tuple[Any, ...] = (),
    ) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                row = cursor.fetchone()
                return dict(row) if row else None
