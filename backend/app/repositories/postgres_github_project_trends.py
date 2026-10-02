"""项目库榜单行的星标走势（只读）。

榜单每一行画近两周的日增火花线，详情栏画一个月的星标曲线：都按
github_repo_daily_metrics 的主键 (repo_id, metric_date) 批量取，一页最多几十个仓库。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.app.core.config import settings
from backend.app.core.postgres_database import (
    PostgresDatabaseLifecycle,
    postgres_database,
)

# 一次最多几十个仓库、几十天：正常几毫秒，超过这个时限宁可让这一行不画线。
_STATEMENT_TIMEOUT_MS = 3000


def business_today() -> date:
    """业务时区（scheduler_timezone，默认 Asia/Shanghai）的今天，与今日热榜同一日历。"""
    zone = getattr(settings, "scheduler_timezone", "Asia/Shanghai") or "Asia/Shanghai"
    return datetime.now(ZoneInfo(zone)).date()


class PostgresGitHubProjectTrendRepository:
    def __init__(self, database: PostgresDatabaseLifecycle = postgres_database) -> None:
        self._database = database

    def _read(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        with self._database.transaction() as connection, connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(_STATEMENT_TIMEOUT_MS),),
            )
            cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]

    def latest_metric_date(self, *, start: str, end: str) -> str | None:
        """[start, end] 内最近一个有日度指标的日期，没有则为 None。"""
        rows = self._read(
            "SELECT MAX(metric_date) AS metric_date FROM github_repo_daily_metrics"
            " WHERE metric_date BETWEEN %s AND %s",
            (start, end),
        )
        value = rows[0].get("metric_date") if rows else None
        return str(value) if value else None

    def daily_points(self, repo_ids: list[str], *, start: str, end: str) -> list[dict[str, Any]]:
        """这些仓库在 [start, end] 内每天的星标与日增，按仓库、日期升序。"""
        if not repo_ids:
            return []
        return self._read(
            "SELECT repo_id, metric_date, stars, daily_star_growth, daily_growth_available"
            " FROM github_repo_daily_metrics"
            " WHERE repo_id = ANY(%s) AND metric_date BETWEEN %s AND %s"
            " ORDER BY repo_id, metric_date",
            (list(repo_ids), start, end),
        )
