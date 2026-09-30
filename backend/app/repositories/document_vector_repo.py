from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any, Iterable

from backend.app.core.config import settings

# Milvus 表达式里 `in [...]` 的单批上限：远低于 gRPC 消息上限，又能把 2 万级
# 文档的指纹核对压到几十次往返。
_ID_BATCH = 500


class DocumentVectorUnavailableError(RuntimeError):
    pass


class DocumentVectorSchemaError(RuntimeError):
    pass


@dataclass(frozen=True)
class DocumentVector:
    doc_id: str
    source: str
    published_day: int
    fingerprint: str
    embedding: list[float]


class DocumentVectorRepository:
    """一文一向量的文档语义索引（主键即 documents.id，天然去重）。

    与 aigc_docs（langchain 自增主键、每轮采集重复写入）不同，这里 upsert
    覆盖同一文档，Go 侧 search_documents 语义通道按 source/published_day
    标量过滤后检索、再回 Postgres 取行。
    """

    def __init__(self, *, collection_name: str | None = None, dimension: int | None = None) -> None:
        self.collection_name = collection_name or settings.document_semantic_collection_name
        self.dimension = int(dimension or settings.milvus_dimension)
        self._alias = "document_semantic"
        self._connected = False
        self._collection = None
        self._state_lock = RLock()
        self._connection_args = {
            "host": settings.milvus_host,
            "port": settings.milvus_port,
            "user": settings.milvus_user or "",
            "password": settings.milvus_password or "",
            "db_name": settings.milvus_db_name or "default",
        }

    def _connect(self) -> None:
        with self._state_lock:
            if self._connected:
                return
            try:
                from pymilvus import connections

                connections.connect(alias=self._alias, **self._connection_args)
                self._connected = True
            except Exception as exc:
                raise DocumentVectorUnavailableError(str(exc)) from exc

    def ensure_collection(self):
        with self._state_lock:
            if self._collection is not None:
                return self._collection
            self._connect()
            from pymilvus import (
                Collection,
                CollectionSchema,
                DataType,
                FieldSchema,
                utility,
            )

            if utility.has_collection(self.collection_name, using=self._alias):
                collection = Collection(self.collection_name, using=self._alias)
                self._validate_collection(collection)
            else:
                schema = CollectionSchema(
                    fields=[
                        FieldSchema("doc_id", DataType.VARCHAR, is_primary=True, auto_id=False, max_length=255),
                        FieldSchema("source", DataType.VARCHAR, max_length=64),
                        FieldSchema("published_day", DataType.INT64),
                        FieldSchema("fingerprint", DataType.VARCHAR, max_length=64),
                        FieldSchema("embedding", DataType.FLOAT_VECTOR, dim=self.dimension),
                    ],
                    description="AIGCNEWS document semantic index (one vector per document)",
                    enable_dynamic_field=False,
                )
                collection = Collection(self.collection_name, schema=schema, using=self._alias)
                collection.create_index(
                    "embedding",
                    {
                        "index_type": settings.milvus_index_type,
                        "metric_type": settings.milvus_metric_type,
                        "params": {"M": 16, "efConstruction": 200},
                    },
                )
            try:
                collection.load()
            except Exception as exc:
                raise DocumentVectorUnavailableError(str(exc)) from exc
            self._collection = collection
            return collection

    def _validate_collection(self, collection) -> None:
        fields = {field.name: field for field in collection.schema.fields}
        required = {"doc_id", "source", "published_day", "fingerprint", "embedding"}
        if set(fields) != required or fields["doc_id"].auto_id:
            raise DocumentVectorSchemaError(f"unexpected schema for {self.collection_name}")
        params = fields["embedding"].params or {}
        if int(params.get("dim") or 0) != self.dimension:
            raise DocumentVectorSchemaError(
                f"embedding dimension mismatch: collection={params.get('dim')} configured={self.dimension}"
            )

    @staticmethod
    def _quoted_list(values: Iterable[str]) -> str:
        return ", ".join('"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"' for value in values)

    def fetch_fingerprints(self, doc_ids: Iterable[str]) -> dict[str, str]:
        collection = self.ensure_collection()
        ids = [doc_id for doc_id in dict.fromkeys(doc_ids) if doc_id]
        found: dict[str, str] = {}
        for start in range(0, len(ids), _ID_BATCH):
            batch = ids[start : start + _ID_BATCH]
            rows = collection.query(
                expr=f"doc_id in [{self._quoted_list(batch)}]",
                output_fields=["doc_id", "fingerprint"],
                limit=len(batch),
            )
            for row in rows:
                found[str(row.get("doc_id") or "")] = str(row.get("fingerprint") or "")
        return found

    def list_doc_ids(self) -> set[str]:
        collection = self.ensure_collection()
        iterator = collection.query_iterator(batch_size=1000, expr='doc_id != ""', output_fields=["doc_id"])
        ids: set[str] = set()
        try:
            while True:
                rows = iterator.next()
                if not rows:
                    break
                ids.update(str(row.get("doc_id") or "") for row in rows)
        finally:
            iterator.close()
        ids.discard("")
        return ids

    def upsert_documents(self, vectors: Iterable[DocumentVector]) -> int:
        rows = list(vectors)
        if any(len(row.embedding) != self.dimension for row in rows):
            raise DocumentVectorSchemaError("embedding dimension mismatch")
        if rows:
            self.ensure_collection().upsert([row.__dict__ for row in rows])
        return len(rows)

    def delete_documents(self, doc_ids: Iterable[str]) -> int:
        ids = [doc_id for doc_id in dict.fromkeys(doc_ids) if doc_id]
        if not ids:
            return 0
        collection = self.ensure_collection()
        for start in range(0, len(ids), _ID_BATCH):
            collection.delete(f"doc_id in [{self._quoted_list(ids[start : start + _ID_BATCH])}]")
        return len(ids)

    def flush(self) -> None:
        self.ensure_collection().flush()

    def stats(self) -> dict[str, Any]:
        collection = self.ensure_collection()
        return {"collection": self.collection_name, "entities": int(collection.num_entities)}

    def close(self) -> None:
        with self._state_lock:
            if self._connected:
                from pymilvus import connections

                connections.disconnect(self._alias)
            self._connected = False
            self._collection = None
