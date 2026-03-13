from __future__ import annotations

import asyncio
import re
from typing import Iterable, List

from langchain_core.documents import Document

from backend.app.core.model_factory import get_chat_model, get_embedding_model
from backend.app.repositories.graph_repo import GraphRepository
from backend.app.repositories.milvus_repo import MilvusRepository
from backend.app.repositories.mysql_repo import MySQLRepository


class HybridRetriever:
    def __init__(
        self,
        milvus_repo: MilvusRepository,
        graph_repo: GraphRepository,
        mysql_repo: MySQLRepository | None = None,
    ) -> None:
        self._milvus_repo = milvus_repo
        self._graph_repo = graph_repo
        self._mysql_repo = mysql_repo or MySQLRepository()
        self._embeddings = get_embedding_model()
        self._llm = get_chat_model()

    @staticmethod
    def _extract_keywords(query: str, max_keywords: int = 2) -> List[str]:
        tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*", query.lower())
        stopwords = {
            "the",
            "a",
            "an",
            "in",
            "on",
            "of",
            "and",
            "or",
            "to",
            "for",
            "with",
            "by",
            "from",
            "is",
            "are",
            "be",
            "as",
            "at",
            "it",
            "this",
            "that",
            "these",
            "those",
            "into",
        }
        keywords: List[str] = []
        for token in tokens:
            if token in stopwords:
                continue
            if token not in keywords:
                keywords.append(token)
            if len(keywords) >= max_keywords:
                break
        if not keywords and query.strip():
            keywords = [query.strip().split()[0].lower()]
        return keywords

    @staticmethod
    def _merge_documents(*groups: Iterable[Document]) -> List[Document]:
        merged: List[Document] = []
        seen: set[str] = set()
        for group in groups:
            for doc in group:
                meta = dict(doc.metadata or {})
                doc.metadata = meta
                # 优先用 id/source_id，再用 url，再用 title+source，最后用内容前200字符
                _id = meta.get("id") or meta.get("source_id")
                _url = meta.get("url")
                _title_src = (
                    f"{meta.get('title', '')}::{meta.get('source', '')}"
                    if meta.get("title")
                    else None
                )
                key = str(_id or _url or _title_src or doc.page_content[:200])
                if key in seen:
                    continue
                seen.add(key)
                # 保留已有的 retriever 标记（vector/source_fallback/sqlite_fallback）
                # 只有未设置时才标记为 hybrid
                if not meta.get("retriever"):
                    doc.metadata["retriever"] = "hybrid"
                merged.append(doc)
        return merged

    def _sqlite_fallback_documents(
        self, query: str = "", top_k: int = 10
    ) -> List[Document]:
        rows = self._mysql_repo.get_top_documents(limit=max(top_k * 5, 30))
        query_lc = query.lower().strip()
        query_tokens = [t for t in re.findall(r"[A-Za-z0-9_-]+", query_lc) if t]

        scored_rows = []
        for row in rows:
            title = str(row.get("title") or "")
            summary = str(row.get("summary") or "")
            haystack = f"{title} {summary}".lower()
            match_score = 0
            if query_lc and query_lc in haystack:
                match_score += 100
            for token in query_tokens:
                if token in haystack:
                    match_score += 20
            match_score += int(float(row.get("score") or 0.0))
            scored_rows.append((match_score, row))

        scored_rows.sort(key=lambda x: x[0], reverse=True)

        docs: List[Document] = []
        for match_score, row in scored_rows[: max(top_k * 3, 15)]:
            title = str(row.get("title") or "")
            summary = str(row.get("summary") or title)
            metadata = {
                "id": str(row.get("id") or ""),
                "source": str(row.get("source") or "sqlite"),
                "title": title,
                "url": str(row.get("url") or ""),
                "published_date": str(row.get("published_date") or ""),
                "score": float(row.get("score") or 0.0),
                "retriever": "sqlite_fallback",
                "keyword_score": float(match_score),
            }
            docs.append(Document(page_content=summary, metadata=metadata))
        return docs

    async def search(self, query: str, top_k: int = 5) -> List[Document]:
        keywords = self._extract_keywords(query, max_keywords=5)

        if not self._milvus_repo.is_available():
            graph_docs = await asyncio.to_thread(
                self._graph_repo.search, keywords, top_k
            )
            sqlite_docs = await asyncio.to_thread(
                self._sqlite_fallback_documents, query, top_k
            )
            return self._merge_documents(sqlite_docs, graph_docs)

        milvus_k = max(top_k * 3, 15)
        vector_task = asyncio.to_thread(self._milvus_repo.search, query, milvus_k)
        graph_task = asyncio.to_thread(self._graph_repo.search, keywords, top_k)
        arxiv_task = asyncio.to_thread(self._milvus_repo.search_by_source, "arxiv", 5)
        news_task = asyncio.to_thread(self._milvus_repo.search_by_source, "news", 3)
        github_task = asyncio.to_thread(self._milvus_repo.search_by_source, "github", 3)

        vector_docs, graph_docs, arxiv_fallback, news_fallback, github_fallback = (
            await asyncio.gather(
                vector_task, graph_task, arxiv_task, news_task, github_task
            )
        )

        # 向量检索文档按 source 均衡采样（round-robin）
        source_buckets: dict[str, List[Document]] = {}
        for doc in vector_docs:
            doc.metadata = dict(doc.metadata or {})
            doc.metadata["retriever"] = "vector"
            src = str(doc.metadata.get("source", "unknown"))
            bucket = source_buckets.setdefault(src, [])
            if len(bucket) < top_k:
                bucket.append(doc)

        round_robin: List[Document] = []
        max_len = max((len(v) for v in source_buckets.values()), default=0)
        buckets_list = list(source_buckets.values())
        for i in range(max_len):
            for bucket in buckets_list:
                if i < len(bucket):
                    round_robin.append(bucket[i])

        # 标记 fallback 文档（不参与相关性展示）
        for doc in arxiv_fallback + news_fallback + github_fallback + list(graph_docs):
            doc.metadata = dict(doc.metadata or {})
            doc.metadata["retriever"] = "source_fallback"

        merged = self._merge_documents(
            round_robin, arxiv_fallback, news_fallback, github_fallback, graph_docs
        )
        sqlite_docs = await asyncio.to_thread(
            self._sqlite_fallback_documents, query, top_k
        )
        # sqlite fallback 保持自己的 keyword_score，不覆盖 retriever 标记
        return self._merge_documents(sqlite_docs, merged, graph_docs)


if __name__ == "__main__":
    retriever = HybridRetriever(
        MilvusRepository(), GraphRepository(), MySQLRepository()
    )
    results = asyncio.run(
        retriever.search("Agents in Multi-modal environments", top_k=5)
    )
    print(f"[HybridRetriever] Retrieved {len(results)} documents.")
    for doc in results[:2]:
        print("-" * 80)
        print(doc.page_content)
