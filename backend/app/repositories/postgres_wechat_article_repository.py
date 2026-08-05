from __future__ import annotations

import json
import logging
from typing import Any

from psycopg import errors

from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.repositories.wechat_article_repository import WeChatArticleRepository

logger = logging.getLogger(__name__)


class WeChatArticleConflictError(Exception):
    """A unique article key conflicts with another row for this account."""


class PostgresWeChatArticleRepository(WeChatArticleRepository):
    """PostgreSQL persistence for idempotent WeChat article metadata."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    @staticmethod
    def _select_sql() -> str:
        return """
            SELECT id, account_id, stable_article_key, message_id, itemidx,
                   title, digest, author, article_url, cover_url, source_url,
                   published_at, raw_metadata, created_at, updated_at
            FROM wechat_articles
        """

    def list_wechat_articles(
        self,
        owner_id: int,
        account_id: int,
        *,
        offset: int = 0,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        # Owner isolation is enforced via the account foreign key.
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    {self._select_sql()}
                    WHERE account_id = %s
                    ORDER BY published_at DESC NULLS LAST, id DESC
                    LIMIT %s OFFSET %s
                    """,
                    (account_id, limit, offset),
                )
                return [dict(row) for row in cursor.fetchall()]

    def count_wechat_articles(self, owner_id: int, account_id: int) -> int:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*) AS n
                    FROM wechat_articles
                    WHERE account_id = %s
                    """,
                    (account_id,),
                )
                row = cursor.fetchone()
                value = row["n"] if isinstance(row, dict) else row[0]
                return int(value) if value else 0

    def upsert_wechat_articles(
        self,
        owner_id: int,
        account_id: int,
        articles: list[dict[str, Any]],
    ) -> int:
        if not articles:
            return 0

        rows = []
        for article in articles:
            rows.append(
                (
                    account_id,
                    str(article["stable_article_key"]),
                    str(article.get("message_id") or ""),
                    int(article.get("itemidx") or 1),
                    str(article.get("title") or "").strip(),
                    str(article.get("digest") or "").strip(),
                    str(article.get("author") or "").strip(),
                    str(article.get("article_url") or "").strip(),
                    str(article.get("cover_url") or "").strip(),
                    str(article.get("source_url") or "").strip(),
                    article.get("published_at"),
                    json.dumps(article.get("raw_metadata") or {}),
                )
            )

        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                try:
                    cursor.executemany(
                        """
                        INSERT INTO wechat_articles (
                            account_id, stable_article_key, message_id, itemidx,
                            title, digest, author, article_url, cover_url,
                            source_url, published_at, raw_metadata
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                        ON CONFLICT (account_id, stable_article_key) DO UPDATE SET
                            message_id = EXCLUDED.message_id,
                            itemidx = EXCLUDED.itemidx,
                            title = EXCLUDED.title,
                            digest = EXCLUDED.digest,
                            author = EXCLUDED.author,
                            article_url = EXCLUDED.article_url,
                            cover_url = EXCLUDED.cover_url,
                            source_url = EXCLUDED.source_url,
                            published_at = EXCLUDED.published_at,
                            raw_metadata = EXCLUDED.raw_metadata,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        rows,
                    )
                except errors.UniqueViolation as exc:
                    constraint = getattr(getattr(exc, "diag", None), "constraint_name", "")
                    if "uq_wechat_articles_account_stable_key" in (constraint or ""):
                        raise WeChatArticleConflictError(
                            "Article stable key conflict"
                        ) from exc
                    raise
                return cursor.rowcount
