from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Protocol

from backend.app.core.config import settings
from backend.app.repositories.document_vector_repo import (
    DocumentVector,
    DocumentVectorRepository,
)

logger = logging.getLogger(__name__)

# 文本拼装规则的版本；改动 document_semantic_text 时递增，存量向量随指纹失配重嵌入。
DOCUMENT_TEXT_VERSION = "t1"
_MAX_TEXT_CHARS = 2000
_MIN_MEANINGFUL_CHARS = 4
_DIGEST_PAGE = 5000
_SOURCE_BATCH = 128
# 采集渠道/周期标签对语义没有贡献，只会把同渠道文档彼此拉近。
_NOISE_TAGS = {"x", "daily", "weekly", "monthly", "techmeme"}
_DAY_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
# pymilvus query_iterator 按主键翻页时不转义字符串主键，含引号/反斜杠的 id
# 会让整次枚举报错；这类 id 不进索引（生产 id 均为 hex/arXiv 号）。
_UNSAFE_ID_CHARS = ('"', "\\")


class DocumentSemanticSource(Protocol):
    def list_document_digests(self, *, after_id: str = "", limit: int = 5000) -> list[dict[str, Any]]: ...

    def get_document_semantic_sources(self, doc_ids: list[str]) -> list[dict[str, Any]]: ...


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _tags(value: Any) -> list[str]:
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except ValueError:
        return []
    if not isinstance(parsed, list):
        return []
    return [tag for tag in (_clean(item) for item in parsed) if tag and tag.lower() not in _NOISE_TAGS]


def document_semantic_body(document: dict[str, Any]) -> str:
    """标题 + 正文 + 中文译文。X 的标题是正文前缀截断，重复时只留正文。"""
    title = _clean(document.get("title"))
    summary = _clean(document.get("summary"))
    parts: list[str] = []
    if title and not summary.startswith(title.rstrip("….").rstrip()):
        parts.append(title)
    if summary:
        parts.append(summary)
    translation = _clean(document.get("translation_zh"))
    if translation and translation != summary:
        parts.append(translation)
    return "\n".join(parts)


def document_semantic_text(document: dict[str, Any]) -> str:
    body = document_semantic_body(document)
    tags = _tags(document.get("tags"))
    text = body + (f"\nTags: {', '.join(tags)}" if tags else "")
    return text.strip()[:_MAX_TEXT_CHARS]


def is_meaningful(document: dict[str, Any]) -> bool:
    """纯表情/符号的推文嵌入后是噪声向量，不进索引。"""
    return sum(1 for char in document_semantic_body(document) if char.isalnum()) >= _MIN_MEANINGFUL_CHARS


def published_day(value: Any) -> int:
    match = _DAY_RE.match(str(value or "").strip())
    return int("".join(match.groups())) if match else 0


def document_semantic_fingerprint(digest: str) -> str:
    payload = {
        "digest": digest,
        "text_version": DOCUMENT_TEXT_VERSION,
        "index_version": settings.document_semantic_index_version,
        "embedding_provider": settings.embedding_provider,
        "embedding_model": settings.embedding_model_name,
        "embedding_dimension": settings.milvus_dimension,
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class DocumentSemanticIndexer:
    def __init__(
        self,
        *,
        db: DocumentSemanticSource,
        vectors: DocumentVectorRepository | None = None,
        embeddings: Any = None,
    ) -> None:
        self.db = db
        self.vectors = vectors
        self.embeddings = embeddings

    def _vectors(self) -> DocumentVectorRepository:
        if self.vectors is None:
            self.vectors = DocumentVectorRepository()
        return self.vectors

    def _embeddings(self):
        if self.embeddings is None:
            from backend.app.core.model_factory import get_embedding_model

            self.embeddings = get_embedding_model()
        return self.embeddings

    def _scan(self) -> tuple[list[dict[str, Any]], dict[str, str], set[str]]:
        """全表指纹核对：返回待重嵌入行（新文档优先）、已有指纹与全部文档 id。"""
        stale: list[dict[str, Any]] = []
        existing: dict[str, str] = {}
        seen: set[str] = set()
        after_id = ""
        while True:
            page = self.db.list_document_digests(after_id=after_id, limit=_DIGEST_PAGE)
            if not page:
                break
            after_id = str(page[-1]["id"])
            found = self._vectors().fetch_fingerprints(str(row["id"]) for row in page)
            existing.update(found)
            for row in page:
                doc_id = str(row["id"])
                seen.add(doc_id)
                if any(char in doc_id for char in _UNSAFE_ID_CHARS):
                    continue
                fingerprint = document_semantic_fingerprint(str(row.get("digest") or ""))
                if found.get(doc_id) != fingerprint:
                    stale.append({"id": doc_id, "created_at": str(row.get("created_at") or ""), "fingerprint": fingerprint})
            if len(page) < _DIGEST_PAGE:
                break
        stale.sort(key=lambda item: (item["created_at"], item["id"]), reverse=True)
        return stale, existing, seen

    def _embed_batch(self, rows: list[tuple[dict[str, Any], str]]) -> list[DocumentVector]:
        texts = [document_semantic_text(document) for document, _ in rows]
        embedded = self._embeddings().embed_documents(texts)
        return [
            DocumentVector(
                doc_id=str(document["id"]),
                source=str(document.get("source") or "")[:64],
                published_day=published_day(document.get("published_date")),
                fingerprint=fingerprint,
                embedding=[float(value) for value in vector],
            )
            for (document, fingerprint), vector in zip(rows, embedded, strict=True)
        ]

    def sync(self, *, max_embed: int | None = None, prune: bool = True, dry_run: bool = False) -> dict[str, Any]:
        stale, existing, seen = self._scan()
        limit = len(stale) if max_embed is None or max_embed <= 0 else min(len(stale), max_embed)
        selected = stale[:limit]
        counts = {"embedded": 0, "skipped": 0, "failed": 0, "pruned": 0}
        orphans: list[str] = []
        if prune:
            try:
                orphans = sorted(self._vectors().list_doc_ids() - seen)
            except Exception as exc:
                logger.warning("Document semantic orphan scan skipped: %s", exc)
        if dry_run:
            return {
                "status": "dry_run",
                "documents": len(seen),
                "stale": len(stale),
                "selected": len(selected),
                "orphans": len(orphans),
            }

        batch_size = max(1, min(int(settings.document_semantic_embed_batch_size), 256))
        dropped: list[str] = []
        for start in range(0, len(selected), _SOURCE_BATCH):
            chunk = selected[start : start + _SOURCE_BATCH]
            fingerprints = {item["id"]: item["fingerprint"] for item in chunk}
            documents = self.db.get_document_semantic_sources(list(fingerprints))
            pending: list[tuple[dict[str, Any], str]] = []
            for document in documents:
                doc_id = str(document["id"])
                if is_meaningful(document):
                    pending.append((document, fingerprints[doc_id]))
                else:
                    counts["skipped"] += 1
                    if doc_id in existing:
                        dropped.append(doc_id)
            for offset in range(0, len(pending), batch_size):
                rows = pending[offset : offset + batch_size]
                try:
                    counts["embedded"] += self._vectors().upsert_documents(self._embed_batch(rows))
                except Exception as exc:
                    counts["failed"] += len(rows)
                    logger.warning("Document semantic embedding batch failed (%d docs): %s", len(rows), exc)
        counts["pruned"] = self._vectors().delete_documents([*orphans, *dropped])
        if counts["embedded"] or counts["pruned"]:
            self._vectors().flush()
        attempted = counts["embedded"] + counts["failed"]
        return {
            "status": "failed" if attempted and not counts["embedded"] else "success",
            "documents": len(seen),
            "stale": len(stale),
            "remaining": len(stale) - len(selected),
            **counts,
        }


def sync_document_semantic_index(
    *,
    db: DocumentSemanticSource,
    force: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    if not settings.document_semantic_indexing_enabled and not force:
        return {"status": "disabled"}
    indexer = DocumentSemanticIndexer(db=db)
    try:
        return indexer.sync(**kwargs)
    finally:
        if indexer.vectors is not None:
            indexer.vectors.close()
