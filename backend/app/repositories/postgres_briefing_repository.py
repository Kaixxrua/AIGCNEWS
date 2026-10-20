from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.domain.search_semantics import escape_like_literal

# 站内速查读的正文列：与 select_briefing_content 同一回退顺序（缺译读另一语言），只有空白不算有内容。
_SEARCH_BODY_COLUMNS = {
    "zh-CN": ("content_zh", "content", "content_en"),
    "en": ("content_en", "content", "content_zh"),
}


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

    def list_briefing_index(
        self, *, since: str, until: str, limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Published issue metadata only: never select full or preview bodies."""
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT date, created_at,
                           btrim(COALESCE(NULLIF(btrim(content_zh), ''), content, '')) <> '' AS has_zh,
                           btrim(COALESCE(content_en, '')) <> '' AS has_en
                    FROM briefings
                    WHERE LEFT(date, 10) BETWEEN %s AND %s
                    ORDER BY date DESC
                    LIMIT %s
                    """,
                    (since, until, max(1, min(limit, 1000))),
                )
                return [dict(row) for row in cursor.fetchall()]

    def search_briefings(
        self,
        terms: list[str],
        *,
        locale: str,
        limit: int = 5,
        exclude_suffixes: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """站内速查：正文里每个关键词都出现（不分大小写）的各期简报，新的一期在前。

        按 locale 选正文列；同一天综合报排在模块报前面。exclude_suffixes 是要排除的
        期键后缀（如 X 源关闭时的 '_0800_x'）。返回本页条目（id、date、body）与命中期数。
        """
        clean_terms = [term for term in terms if term]
        if not clean_terms:
            return {"items": [], "total": 0}
        columns = _SEARCH_BODY_COLUMNS["en" if locale == "en" else "zh-CN"]
        body = "CASE " + " ".join(f"WHEN btrim(COALESCE({column}, '')) <> '' THEN {column}" for column in columns) + " ELSE '' END"
        where_parts = ["body ILIKE %s ESCAPE '='"] * len(clean_terms)
        params: list[Any] = [f"%{escape_like_literal(term)}%" for term in clean_terms]
        for suffix in exclude_suffixes:
            where_parts.append("date NOT LIKE %s ESCAPE '='")
            params.append(f"%{escape_like_literal(suffix)}")
        params.append(max(1, min(int(limit), 20)))
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT id, date, body, COUNT(*) OVER () AS total
                    FROM (SELECT id, date, {body} AS body FROM briefings) AS picked
                    WHERE {' AND '.join(where_parts)}
                    ORDER BY LEFT(date, 10) DESC, position('_' in date) = 0 DESC, id DESC
                    LIMIT %s
                    """,
                    tuple(params),
                )
                rows = [dict(row) for row in cursor.fetchall()]
        return {
            "items": [{"id": row["id"], "date": row["date"], "body": row["body"]} for row in rows],
            "total": int(rows[0]["total"]) if rows else 0,
        }

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
