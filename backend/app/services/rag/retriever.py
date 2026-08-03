from __future__ import annotations

import asyncio
import re
from typing import Iterable, List

from langchain_core.documents import Document

from backend.app.repositories.document_repository import (
    DocumentFeedReader,
    DocumentRetrievalReader,
)
from backend.app.services.rag.ports import GraphRetrievalReader, VectorRetrievalReader


class HybridRetriever:
    def __init__(
        self,
        milvus_repo: VectorRetrievalReader,
        graph_repo: GraphRetrievalReader,
        document_feed: DocumentFeedReader,
        document_retrieval: DocumentRetrievalReader,
    ) -> None:
        self._milvus_repo = milvus_repo
        self._graph_repo = graph_repo
        self._document_feed = document_feed
        self._document_retrieval = document_retrieval

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

    @staticmethod
    def _extract_explicit_document_ids(query: str) -> List[str]:
        """从用户问题/论文页上下文中提取 MySQL documents.id。"""
        doc_ids: List[str] = []
        for item in re.findall(r"\b[a-fA-F0-9]{32}\b", query or ""):
            normalized = item.lower()
            if normalized not in doc_ids:
                doc_ids.append(normalized)
        return doc_ids

    def _mysql_id_match_documents(
        self, query: str = "", top_k: int = 5
    ) -> List[Document]:
        """按 documents.id 精确召回当前论文。

        论文阅读页会把当前 paper_id 传给后端；用户如果只问“详细讲一下这篇论文”，
        query 中没有标题关键词，纯向量/标题检索都容易漏掉目标论文。因此只要问题里出现
        32 位文档 ID，就必须优先从 MySQL 精确取回该论文元数据，并尽可能补充本地 PDF 正文。
        """
        doc_ids = self._extract_explicit_document_ids(query)
        if not doc_ids:
            return []

        rows = self._document_retrieval.get_documents_by_ids(doc_ids, limit=top_k)

        docs: List[Document] = []
        for row in rows:
            title = str(row.get("title") or "")
            summary = str(row.get("summary") or "")
            local_pdf_path = str(row.get("local_pdf_path") or "")
            pdf_excerpt = ""
            if local_pdf_path and str(row.get("source") or "").lower() == "arxiv":
                try:
                    from backend.app.services.ingestion.arxiv_pdf_downloader import (
                        _extract_text_from_local_pdf,
                    )

                    pdf_text = _extract_text_from_local_pdf(local_pdf_path)
                    if pdf_text:
                        pdf_excerpt = pdf_text[:20000].strip()
                except Exception as exc:
                    print(
                        f"[HybridRetriever] failed to load local PDF excerpt "
                        f"{local_pdf_path}: {exc}"
                    )

            metadata = {
                "id": str(row.get("id") or ""),
                "source": str(row.get("source") or "mysql"),
                "title": title,
                "url": str(row.get("url") or ""),
                "published_date": str(row.get("published_date") or ""),
                "score": float(row.get("score") or 0.0),
                "raw_score": float(row.get("raw_score") or 0.0),
                "rank_in_period": int(row.get("rank_in_period") or 9999),
                "retriever": "hybrid",
                "match_type": "mysql_id",
                "keyword_score": 100.0,
                "rerank_score": 10.0,
                "force_include": True,
            }
            content = f"Document ID: {metadata['id']}\nTitle: {title}"
            if summary:
                content += f"\nSummary (metadata excerpt): {summary}"
            if pdf_excerpt:
                content += f"\nFull paper excerpt from local PDF:\n{pdf_excerpt}"
            docs.append(Document(page_content=content, metadata=metadata))
        return docs

    def _mysql_title_match_documents(
        self, query: str = "", top_k: int = 5
    ) -> List[Document]:
        """按标题关键词从 MySQL 精确/近似召回文档。

        这条路径用于补足纯向量检索的短板：当用户直接输入论文标题时，
        即使对应 PDF 分块尚未写入 Milvus、或向量相似度排序不靠前，也应优先把
        MySQL 中已收录的文档元数据和摘要注入 RAG 上下文。
        """
        raw_tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*", query.lower())
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
            "paper",
            "papers",
            "article",
            "tell",
            "about",
        }
        tokens: List[str] = []
        for token in raw_tokens:
            if token in stopwords:
                continue
            if len(token) <= 1:
                continue
            if token not in tokens:
                tokens.append(token)
            if len(tokens) >= 8:
                break

        if len(tokens) < 3:
            return []

        min_match_count = min(3, len(tokens))
        rows = self._document_retrieval.get_documents_by_title_tokens(
            tokens,
            min_matches=min_match_count,
            limit=top_k,
        )

        docs: List[Document] = []
        for row in rows:
            title = str(row.get("title") or "")
            summary = str(row.get("summary") or "")
            keyword_score = float(row.get("keyword_score") or 0.0)
            local_pdf_path = str(row.get("local_pdf_path") or "")
            pdf_excerpt = ""
            # MySQL documents.summary 只保存元数据摘要，历史数据可能只有 500 字符。
            # 当标题高度命中且本地 PDF 已落盘时，补充 PDF 正文前段，避免 LLM
            # 只能看到被截断的 Summary 后误判“摘要被截断”。
            if (
                local_pdf_path
                and str(row.get("source") or "").lower() == "arxiv"
                and keyword_score >= min(5, len(tokens))
            ):
                try:
                    from backend.app.services.ingestion.arxiv_pdf_downloader import (
                        _extract_text_from_local_pdf,
                    )

                    pdf_text = _extract_text_from_local_pdf(local_pdf_path)
                    if pdf_text:
                        pdf_excerpt = pdf_text[:6000].strip()
                except Exception as exc:
                    print(
                        f"[HybridRetriever] failed to load local PDF excerpt "
                        f"{local_pdf_path}: {exc}"
                    )

            metadata = {
                "id": str(row.get("id") or ""),
                "source": str(row.get("source") or "mysql"),
                "title": title,
                "url": str(row.get("url") or ""),
                "published_date": str(row.get("published_date") or ""),
                "score": float(row.get("score") or 0.0),
                "raw_score": float(row.get("raw_score") or 0.0),
                "rank_in_period": int(row.get("rank_in_period") or 9999),
                "retriever": "hybrid",
                "match_type": "mysql_title",
                "keyword_score": keyword_score,
                # 若后续因向量分数过高跳过 reranker，也让标题命中文档排在来源前列。
                "rerank_score": min(10.0, round(keyword_score * 1.5, 1)),
            }
            content = f"Title: {title}"
            if summary:
                content += f"\nSummary (metadata excerpt): {summary}"
            if pdf_excerpt:
                content += f"\nFull paper excerpt from local PDF:\n{pdf_excerpt}"
            docs.append(Document(page_content=content, metadata=metadata))
        return docs

    def _sqlite_fallback_documents(
        self, query: str = "", top_k: int = 10
    ) -> List[Document]:
        rows = self._document_feed.get_top_documents(limit=max(top_k * 5, 30))
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
        id_docs = await asyncio.to_thread(
            self._mysql_id_match_documents, query, max(top_k, 5)
        )
        if id_docs:
            matched_titles = " ".join(
                str((doc.metadata or {}).get("title") or "") for doc in id_docs
            ).strip()
            retrieval_query = f"{matched_titles}\n{query}" if matched_titles else query
        else:
            retrieval_query = query
        keywords = self._extract_keywords(retrieval_query, max_keywords=5)

        if not self._milvus_repo.is_available():
            title_docs = await asyncio.to_thread(
                self._mysql_title_match_documents, retrieval_query, max(top_k, 5)
            )
            graph_docs = await asyncio.to_thread(
                self._graph_repo.search, keywords, top_k
            )
            sqlite_docs = await asyncio.to_thread(
                self._sqlite_fallback_documents, retrieval_query, top_k
            )
            return self._merge_documents(id_docs, title_docs, sqlite_docs, graph_docs)

        milvus_k = max(top_k * 3, 15)
        title_task = asyncio.to_thread(
            self._mysql_title_match_documents, retrieval_query, max(top_k, 5)
        )
        vector_task = asyncio.to_thread(
            self._milvus_repo.search, retrieval_query, milvus_k
        )
        graph_task = asyncio.to_thread(self._graph_repo.search, keywords, top_k)
        arxiv_task = asyncio.to_thread(self._milvus_repo.search_by_source, "arxiv", 5)
        news_task = asyncio.to_thread(self._milvus_repo.search_by_source, "news", 3)
        github_task = asyncio.to_thread(self._milvus_repo.search_by_source, "github", 3)

        (
            title_docs,
            vector_docs,
            graph_docs,
            arxiv_fallback,
            news_fallback,
            github_fallback,
        ) = await asyncio.gather(
            title_task,
            vector_task,
            graph_task,
            arxiv_task,
            news_task,
            github_task,
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
            id_docs,
            title_docs,
            round_robin,
            arxiv_fallback,
            news_fallback,
            github_fallback,
            graph_docs,
        )
        sqlite_docs = await asyncio.to_thread(
            self._sqlite_fallback_documents, retrieval_query, top_k
        )
        # sqlite fallback 保持自己的 keyword_score，不覆盖 retriever 标记
        return self._merge_documents(
            id_docs, title_docs, sqlite_docs, merged, graph_docs
        )
