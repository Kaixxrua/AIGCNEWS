from __future__ import annotations

from typing import List

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Milvus
from langchain_core.documents import Document

from backend.app.core.config import settings
from backend.app.core.model_factory import get_embedding_model


class MilvusRepository:
    def __init__(self) -> None:
        self._embeddings = get_embedding_model()
        self._connection_args = {
            "host": settings.milvus_host,
            "port": settings.milvus_port,
            "user": settings.milvus_user or None,
            "password": settings.milvus_password or None,
            "db_name": settings.milvus_db_name,
        }
        self._collection_name = settings.milvus_collection_name

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
            print(f"[Milvus] unavailable: {exc}")
            return False

    def add_documents(self, docs: List[Document], already_split: bool = False) -> None:
        try:
            if not docs:
                print("[Milvus] No documents to add.")
                return

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
                )
                vector_store.add_documents(docs)
            except Exception as exc:
                err_str = str(exc)
                # Schema 不匹配时（字段数量变化），自动重建 Collection
                if (
                    "DataNotMatchException" in err_str
                    or "doesn't match with schema" in err_str
                ):
                    print(f"[Milvus] Schema 不匹配，重建 Collection: {exc}")
                    vector_store = Milvus(
                        embedding_function=self._embeddings,
                        collection_name=self._collection_name,
                        connection_args=self._connection_args,
                        consistency_level="Strong",
                        auto_id=True,
                        drop_old=True,
                    )
                    vector_store.add_documents(docs)
                else:
                    raise
            print(
                f"[Milvus] Inserted {len(docs)} chunks into '{self._collection_name}'."
            )
        except Exception as exc:
            print(f"[Milvus] Failed to add documents: {exc}")

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
                print(f"[Milvus] Collection '{self._collection_name}' 已删除。")
            else:
                print(f"[Milvus] Collection '{self._collection_name}' 不存在，跳过。")
            return True
        except Exception as exc:
            print(f"[Milvus] 删除 Collection 失败: {exc}")
            return False

    def search(self, query: str, top_k: int = 5) -> List[Document]:
        try:
            vector_store = Milvus(
                embedding_function=self._embeddings,
                collection_name=self._collection_name,
                connection_args=self._connection_args,
                consistency_level="Strong",
                auto_id=True,
                drop_old=False,
            )
            # HNSW 要求 ef >= k，否则会报 out of range 错误
            # ef 越大结果越准确，建议 ef = max(k, 64)
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
        except Exception as exc:
            print(f"[Milvus] Failed to search documents: {exc}")
            return []

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
            expr = f'source == "{source}"'
            results = coll.query(
                expr=expr,
                output_fields=[
                    "pk",
                    "text",
                    "source",
                    "title",
                    "url",
                    "published_date",
                    "stars",
                    "language",
                    "pdf_url",
                    "source_channel",
                    "raw_score",
                ],
                limit=top_k,
            )
            docs: List[Document] = []
            for r in results:
                page_content = r.get("text", "")
                metadata = {k: v for k, v in r.items() if k != "text"}
                metadata.setdefault("source", source)
                if "pk" in metadata:
                    metadata["id"] = str(metadata["pk"])
                doc = Document(page_content=page_content, metadata=metadata)
                docs.append(doc)
            return docs
        except Exception as exc:
            print(f"[Milvus] search_by_source failed ({source}): {exc}")
            return []
