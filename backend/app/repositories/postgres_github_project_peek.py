"""项目库悬停速览的取数（只读）：仓库在不在公开项目库里、在 GitHub 上叫什么、还在不在。

公开口径与项目库列表一致：富化成功、不是改名留下的旧名（github_repo_aliases 里的别名行）。
"""

from __future__ import annotations

from typing import Any

from backend.app.core.postgres_database import (
    PostgresDatabaseLifecycle,
    postgres_database,
)

# 按主键查一行：正常一毫秒，超过这个时限宁可这次速览不出。
_STATEMENT_TIMEOUT_MS = 2000


class PostgresGitHubProjectPeekRepository:
    def __init__(self, database: PostgresDatabaseLifecycle = postgres_database) -> None:
        self._database = database

    def peek_source(self, repo_id: str) -> dict[str, Any] | None:
        """公开项目库里的这个仓库（repo_id、full_name、availability_status）；不在库里返回 None。"""
        with self._database.transaction() as connection, connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(_STATEMENT_TIMEOUT_MS),),
            )
            cursor.execute(
                "SELECT c.repo_id, c.full_name, c.availability_status"
                " FROM github_repo_candidates c"
                " JOIN github_repo_enrichments ge ON ge.repo_id = c.repo_id AND ge.status = 'succeeded'"
                " WHERE c.repo_id = %s"
                " AND NOT EXISTS (SELECT 1 FROM github_repo_aliases ga"
                " WHERE ga.alias_repo_id = c.repo_id AND ga.canonical_repo_id <> c.repo_id)",
                (repo_id,),
            )
            row = cursor.fetchone()
        return dict(row) if row else None
