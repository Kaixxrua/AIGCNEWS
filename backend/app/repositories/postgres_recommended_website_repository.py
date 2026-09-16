from __future__ import annotations

from typing import Any

from psycopg.errors import UniqueViolation

from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.repositories.recommended_website_repository import DuplicateRecommendedWebsiteError

_COLUMNS = "id, title, url, description, category, sort_order, created_at, updated_at"


class PostgresRecommendedWebsiteRepository:
    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def list_websites(self) -> list[dict[str, Any]]:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {_COLUMNS} FROM recommended_websites ORDER BY sort_order, created_at DESC, id DESC"
                )
                return list(cursor.fetchall())

    def create_website(
        self, *, title: str, url: str, description: str, category: str, sort_order: int,
    ) -> dict[str, Any]:
        try:
            with self._database.transaction() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""INSERT INTO recommended_websites (title, url, description, category, sort_order)
                            VALUES (%s, %s, %s, %s, %s) RETURNING {_COLUMNS}""",
                        (title, url, description, category, sort_order),
                    )
                    return dict(cursor.fetchone())
        except UniqueViolation as error:
            raise DuplicateRecommendedWebsiteError from error

    def update_website(
        self, website_id: int, *, title: str, url: str, description: str, category: str, sort_order: int,
    ) -> dict[str, Any] | None:
        try:
            with self._database.transaction() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""UPDATE recommended_websites SET title=%s, url=%s, description=%s,
                            category=%s, sort_order=%s, updated_at=CURRENT_TIMESTAMP
                            WHERE id=%s RETURNING {_COLUMNS}""",
                        (title, url, description, category, sort_order, website_id),
                    )
                    row = cursor.fetchone()
                    return dict(row) if row else None
        except UniqueViolation as error:
            raise DuplicateRecommendedWebsiteError from error

    def delete_website(self, website_id: int) -> bool:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM recommended_websites WHERE id=%s RETURNING id", (website_id,))
                return cursor.fetchone() is not None
