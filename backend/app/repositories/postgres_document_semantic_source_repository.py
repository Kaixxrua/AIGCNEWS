from __future__ import annotations

from typing import Any

from backend.app.core.postgres_database import PostgresDatabaseLifecycle

# digest 覆盖进入向量文本与标量过滤的全部列：任一列变化即触发重嵌入。
# chr(31)（单元分隔符）不会出现在正文里，避免列边界拼接歧义。
_DIGEST_SQL = """
    SELECT id, created_at,
           md5(concat_ws(chr(31),
               COALESCE(source, ''), COALESCE(published_date, ''),
               COALESCE(title, ''), COALESCE(summary, ''),
               COALESCE(tags, ''), COALESCE(translation_zh, ''))) AS digest
    FROM documents
    WHERE id COLLATE "C" > %s COLLATE "C"
    ORDER BY id COLLATE "C" ASC
    LIMIT %s
"""


class PostgresDocumentSemanticSourceRepository:
    """文档语义索引的只读来源：指纹摘要分页扫描 + 按 id 取嵌入所需列。"""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def list_document_digests(self, *, after_id: str = "", limit: int = 5000) -> list[dict[str, Any]]:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(_DIGEST_SQL, (after_id, max(1, min(int(limit), 20000))))
                return [dict(row) for row in cursor.fetchall()]

    def get_document_semantic_sources(self, doc_ids: list[str]) -> list[dict[str, Any]]:
        if not doc_ids:
            return []
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, source, published_date, title, summary, tags, translation_zh
                    FROM documents
                    WHERE id = ANY(%s)
                    """,
                    (list(doc_ids),),
                )
                return [dict(row) for row in cursor.fetchall()]
