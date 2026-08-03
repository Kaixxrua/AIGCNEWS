from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any, Iterable

from backend.app.core.config import settings


class ProjectVectorUnavailableError(RuntimeError):
    pass


class ProjectVectorSchemaError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProjectVectorChunk:
    chunk_id: str
    repo_id: str
    chunk_kind: str
    chunk_index: int
    source_fingerprint: str
    content: str
    embedding: list[float]


@dataclass(frozen=True)
class ProjectVectorHit:
    repo_id: str
    score: float


class ProjectVectorRepository:
    def __init__(self, *, collection_name: str | None = None, dimension: int | None = None) -> None:
        self.collection_name = collection_name or settings.project_semantic_collection_name
        self.dimension = int(dimension or settings.milvus_dimension)
        self._alias = "project_semantic"
        self._connected = False
        self._collection = None
        self._loaded = False
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
                raise ProjectVectorUnavailableError(str(exc)) from exc

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
                self._collection = collection
                return collection

            schema = CollectionSchema(
                fields=[
                    FieldSchema("chunk_id", DataType.VARCHAR, is_primary=True, auto_id=False, max_length=64),
                    FieldSchema("repo_id", DataType.VARCHAR, max_length=255),
                    FieldSchema("chunk_kind", DataType.VARCHAR, max_length=16),
                    FieldSchema("chunk_index", DataType.INT64),
                    FieldSchema("source_fingerprint", DataType.VARCHAR, max_length=64),
                    FieldSchema("content", DataType.VARCHAR, max_length=16_384),
                    FieldSchema("embedding", DataType.FLOAT_VECTOR, dim=self.dimension),
                ],
                description="AIGCNEWS GitHub project semantic index",
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
            collection.load()
            self._collection = collection
            self._loaded = True
            return collection

    def _load_collection(self):
        with self._state_lock:
            collection = self.ensure_collection()
            if not self._loaded:
                try:
                    collection.load()
                    self._loaded = True
                except Exception as exc:
                    raise ProjectVectorUnavailableError(str(exc)) from exc
            return collection

    def _validate_collection(self, collection) -> None:
        fields = {field.name: field for field in collection.schema.fields}
        required = {"chunk_id", "repo_id", "chunk_kind", "chunk_index", "source_fingerprint", "content", "embedding"}
        if set(fields) != required or fields["chunk_id"].auto_id:
            raise ProjectVectorSchemaError(f"unexpected schema for {self.collection_name}")
        params = fields["embedding"].params or {}
        if int(params.get("dim") or 0) != self.dimension:
            raise ProjectVectorSchemaError(
                f"embedding dimension mismatch: collection={params.get('dim')} configured={self.dimension}"
            )

    @staticmethod
    def _quoted(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    def upsert_project_chunks(self, repo_id: str, chunks: Iterable[ProjectVectorChunk]) -> int:
        collection = self.ensure_collection()
        chunk_list = list(chunks)
        if any(len(chunk.embedding) != self.dimension for chunk in chunk_list):
            raise ProjectVectorSchemaError("embedding dimension mismatch")
        if chunk_list:
            collection.upsert([chunk.__dict__ for chunk in chunk_list])
        keep_ids = {chunk.chunk_id for chunk in chunk_list}
        existing = collection.query(
            expr=f'repo_id == "{self._quoted(repo_id)}"',
            output_fields=["chunk_id"],
            limit=16_384,
        )
        obsolete = [row["chunk_id"] for row in existing if row.get("chunk_id") not in keep_ids]
        if obsolete:
            quoted = ", ".join(f'"{self._quoted(chunk_id)}"' for chunk_id in obsolete)
            collection.delete(f"chunk_id in [{quoted}]")
        collection.flush()
        return len(chunk_list)

    def count_project_chunks(self, repo_id: str) -> int:
        collection = self.ensure_collection()
        rows = collection.query(
            expr=f'repo_id == "{self._quoted(repo_id)}"',
            output_fields=["chunk_id"],
            limit=16_384,
        )
        return len(rows)

    def delete_project(self, repo_id: str) -> None:
        collection = self.ensure_collection()
        collection.delete(f'repo_id == "{self._quoted(repo_id)}"')
        collection.flush()

    def search_repo_ids(
        self,
        query_vector: list[float],
        *,
        chunk_limit: int,
        repo_limit: int,
        min_score: float,
    ) -> list[ProjectVectorHit]:
        if len(query_vector) != self.dimension:
            raise ProjectVectorSchemaError("query embedding dimension mismatch")
        collection = self._load_collection()
        results = collection.search(
            data=[query_vector],
            anns_field="embedding",
            param={"metric_type": settings.milvus_metric_type, "params": {"ef": max(64, chunk_limit)}},
            limit=chunk_limit,
            output_fields=["repo_id"],
        )
        scores: dict[str, float] = {}
        for hit in results[0] if results else []:
            repo_id = str(hit.entity.get("repo_id") or "")
            score = float(hit.score)
            if repo_id and score >= min_score:
                scores[repo_id] = max(scores.get(repo_id, float("-inf")), score)
        return [
            ProjectVectorHit(repo_id=repo_id, score=score)
            for repo_id, score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:repo_limit]
        ]

    def stats(self) -> dict[str, Any]:
        collection = self.ensure_collection()
        return {"collection": self.collection_name, "entities": int(collection.num_entities)}

    def close(self) -> None:
        with self._state_lock:
            if not self._connected:
                self._collection = None
                self._loaded = False
                return
            from pymilvus import connections

            connections.disconnect(self._alias)
            self._connected = False
            self._collection = None
            self._loaded = False
