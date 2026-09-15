from __future__ import annotations

import logging
import threading
from typing import Any, List

from langchain_text_splitters import RecursiveCharacterTextSplitter

try:
    from langchain_community.vectorstores import Milvus
except ImportError:
    try:
        from langchain_community.vectorstores.milvus import Milvus
    except ImportError:
        from langchain_milvus import Milvus
from langchain_core.documents import Document

from backend.app.core.config import settings
from backend.app.core.model_factory import (
    get_embedding_model,
    model_provider_runtime_is_configured,
)

logger = logging.getLogger(__name__)

# 元数据统一收进单个 JSON 列（langchain Milvus 的 metadata_field 参数）。
# 否则 langchain 按每批首文档的元数据键集推断显式列：主管线与 arxiv PDF
# 切片两条写入路径键集不同，轮流触发 DataNotMatch → drop_old 重建，
# 整日反复清空 aigc_docs（实测单日 20 次重建，RAG 向量只残存最后一批）。
# JSON 列让 schema 恒定（metadata + text + pk + vector），两路径共存；
# 首个写入轮次对旧显式列 collection 仍会 mismatch，由既有重建逻辑一次性
# 迁移到 JSON schema。
_METADATA_FIELD = "metadata"


class MilvusRepository:
    def __init__(self, embeddings: Any | None = None) -> None:
        self._owns_embeddings = embeddings is None and not model_provider_runtime_is_configured()
        self._embeddings = embeddings if embeddings is not None else get_embedding_model()
        self._connection_args = {
            "host": settings.milvus_host,
            "port": settings.milvus_port,
            "user": settings.milvus_user or None,
            "password": settings.milvus_password or None,
            "db_name": settings.milvus_db_name,
        }
        self._collection_name = settings.milvus_collection_name
        self._close_lock = threading.Lock()
        self._closed = False

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            if not self._owns_embeddings:
                return
            http_client = getattr(self._embeddings, "http_client", None)
            if http_client is not None:
                http_client.close()

    def is_available(self) -> bool:
        try:
            from pymilvus import connections

            connections.connect(
                alias="default",
                host=self._connection_args["host"],
                port=self._connection_args["port"],
                user=self._connection_args.get("user") or "",
                password=self._connection_args.get("password") or "",
                db_name=self._connection_args.get("db_name") or "default",
            )
            return True
        except Exception as exc:
            logger.warning("[Milvus] unavailable: %s", exc)
            return False

    @staticmethod
    def _enrich_github_content(docs: List[Document]) -> List[Document]:
        """对 GitHub 来源的文档，在 page_content 末尾追加结构化字段（stars/forks/language），
        使向量化时能感知这些数值型信息，提升 GitHub stars 相关查询的召回率。"""
        enriched: List[Document] = []
        for doc in docs:
            meta = doc.metadata or {}
            if str(meta.get("source") or "").lower() == "github":
                stars = meta.get("stars") or meta.get("raw_score") or 0
                forks = meta.get("forks") or 0
                language = meta.get("language") or ""
                extra_parts = [f"Stars: {int(stars)}"]
                if forks:
                    extra_parts.append(f"Forks: {int(forks)}")
                if language:
                    extra_parts.append(f"Language: {language}")
                extra_line = " | ".join(extra_parts)
                new_content = (
                    f"{doc.page_content}\n{extra_line}"
                    if doc.page_content
                    else extra_line
                )
                enriched.append(Document(page_content=new_content, metadata=meta))
            else:
                enriched.append(doc)
        return enriched

    def add_documents(self, docs: List[Document], already_split: bool = False) -> bool:
        try:
            if not docs:
                logger.info("[Milvus] No documents to add.")
                return True

            # 在切分之前先对 GitHub 文档追加结构化字段，
            # 这样切分后的每个 chunk 也都包含 stars/forks/language 信息
            docs = self._enrich_github_content(docs)

            if not already_split:
                splitter = RecursiveCharacterTextSplitter(
                    chunk_size=800,
                    chunk_overlap=100,
                )
                docs = splitter.split_documents(docs)

            try:
                vector_store = Milvus(
                    embedding_function=self._embeddings,
                    collection_name=self._collection_name,
                    connection_args=self._connection_args,
                    consistency_level="Strong",
                    auto_id=True,
                    drop_old=False,
                    metadata_field=_METADATA_FIELD,
                )
                vector_store.add_documents(docs)
            except Exception as exc:
                err_str = str(exc)
                # Schema 不匹配时（字段数量变化），自动重建 Collection
                if (
                    "DataNotMatchException" in err_str
                    or "doesn't match with schema" in err_str
                ):
                    logger.warning("[Milvus] Schema 不匹配，重建 Collection: %s", exc)
                    vector_store = Milvus(
                        embedding_function=self._embeddings,
                        collection_name=self._collection_name,
                        connection_args=self._connection_args,
                        consistency_level="Strong",
                        auto_id=True,
                        drop_old=True,
                        metadata_field=_METADATA_FIELD,
                    )
                    vector_store.add_documents(docs)
                else:
                    raise
            logger.info(
                "[Milvus] Inserted %s chunks into '%s'.",
                len(docs),
                self._collection_name,
            )
            return True
        except Exception as exc:
            logger.warning("[Milvus] Failed to add documents: %s", exc)
            return False

    def drop_collection(self) -> bool:
        """删除（清空）整个 Milvus Collection，返回是否成功。"""
        try:
            from pymilvus import connections, utility

            connections.connect(
                alias="default",
                host=self._connection_args["host"],
                port=self._connection_args["port"],
                user=self._connection_args.get("user") or "",
                password=self._connection_args.get("password") or "",
                db_name=self._connection_args.get("db_name") or "default",
            )
            if utility.has_collection(self._collection_name):
                utility.drop_collection(self._collection_name)
                logger.info("[Milvus] Collection '%s' 已删除。", self._collection_name)
            else:
                logger.info("[Milvus] Collection '%s' 不存在，跳过。", self._collection_name)
            return True
        except Exception as exc:
            logger.warning("[Milvus] 删除 Collection 失败: %s", exc)
            return False

    def _search_documents(self, query: str, top_k: int = 5) -> List[Document]:
        vector_store = Milvus(
            embedding_function=self._embeddings,
            collection_name=self._collection_name,
            connection_args=self._connection_args,
            consistency_level="Strong",
            auto_id=True,
            drop_old=False,
            metadata_field=_METADATA_FIELD,
        )
        # HNSW 要求 ef >= k，否则会报 out of range 错误
        ef = max(top_k, 64)
        results = vector_store.similarity_search_with_score(
            query, k=top_k, param={"ef": ef}
        )
        docs: List[Document] = []
        for doc, score in results:
            doc.metadata = dict(doc.metadata or {})
            doc.metadata.setdefault("source", "milvus")
            doc.metadata["score"] = float(score)
            docs.append(doc)
        return docs

    def search(self, query: str, top_k: int = 5) -> List[Document]:
        try:
            return self._search_documents(query, top_k)
        except Exception as exc:
            logger.warning("[Milvus] Failed to search documents: %s", exc)
            return []

    def search_with_status(
        self, query: str, top_k: int = 5
    ) -> tuple[List[Document], str | None]:
        """Return semantic hits plus an explicit runtime error, if any.

        ``search`` predates the dashboard contract and intentionally remains
        fail-open.  New callers that must distinguish an empty result from an
        unavailable vector runtime use this method instead.
        """
        try:
            return self._search_documents(query, top_k), None
        except Exception as exc:
            logger.warning("[Milvus] Failed to search documents: %s", exc)
            return [], str(exc)

    def search_by_source(self, source: str, top_k: int = 3) -> List[Document]:
        """按 source 字段过滤，返回该来源的 top_k 条文档（用于保证每源都有代表）。"""
        try:
            from pymilvus import Collection, connections, utility

            connections.connect(
                alias="default",
                host=self._connection_args["host"],
                port=self._connection_args["port"],
                user=self._connection_args.get("user") or "",
                password=self._connection_args.get("password") or "",
                db_name=self._connection_args.get("db_name") or "default",
            )
            if not utility.has_collection(self._collection_name):
                return []

            coll = Collection(self._collection_name)
            coll.load()
            # 元数据在 JSON 列里，按键路径过滤；旧显式列 collection 在未迁移前
            # 查询会报错，由下方 except 兜底返回空，首个写入轮自动重建后恢复。
            expr = f'{_METADATA_FIELD}["source"] == "{source}"'
            results = coll.query(
                expr=expr,
                output_fields=["pk", "text", _METADATA_FIELD],
                limit=top_k,
            )
            docs: List[Document] = []
            for r in results:
                page_content = r.get("text", "")
                metadata = dict(r.get(_METADATA_FIELD) or {})
                metadata.setdefault("source", source)
                if "pk" in r:
                    metadata["id"] = str(r["pk"])
                doc = Document(page_content=page_content, metadata=metadata)
                docs.append(doc)
            return docs
        except Exception as exc:
            logger.warning("[Milvus] search_by_source failed (%s): %s", source, exc)
            return []
