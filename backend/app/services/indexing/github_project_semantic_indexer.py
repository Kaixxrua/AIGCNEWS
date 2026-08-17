from __future__ import annotations

import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Lock
from typing import Any

import httpx

from backend.app.core.config import settings
from backend.app.repositories.project_vector_repo import (
    ProjectVectorChunk,
    ProjectVectorRepository,
)
from backend.app.repositories.project_write_repository import (
    GitHubProjectSemanticSourceRepository,
)
from backend.app.services.ingestion.source_github import fetch_github_readme_snapshot

logger = logging.getLogger(__name__)
_vector_write_lock = Lock()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    return [str(item) for item in parsed if str(item).strip()] if isinstance(parsed, list) else []


def _project_list(project: dict[str, Any], key: str) -> list[str]:
    if key in project:
        return _json_list(project.get(key))
    return _json_list(project.get(f"{key}_json"))


def project_semantic_fingerprint(project: dict[str, Any], readme_sha256: str) -> str:
    payload = {
        "repo_id": project.get("repo_id") or "",
        "full_name": project.get("full_name") or "",
        "title": project.get("title") or "",
        "description": project.get("description") or "",
        "description_zh": project.get("description_zh") or "",
        "category_slug": project.get("category_slug") or "",
        "category_name": project.get("category_name") or "",
        "subcategory_slug": project.get("subcategory_slug") or "",
        "subcategory_name": project.get("subcategory_name") or "",
        "tags": sorted(_project_list(project, "tags")),
        "topics": sorted(_project_list(project, "topics")),
        "language": project.get("language") or "",
        "readme_sha256": readme_sha256,
        "index_version": settings.project_semantic_index_version,
        "embedding_provider": settings.embedding_provider,
        "embedding_model": settings.embedding_model_name,
        "embedding_dimension": settings.milvus_dimension,
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_project_semantic_chunks(project: dict[str, Any], readme: str) -> list[tuple[str, int, str]]:
    lines = [
        f"Repository: {project.get('full_name') or project.get('title') or ''}",
        f"Title: {project.get('title') or ''}",
        f"Description: {project.get('description') or ''}",
        f"Chinese description: {project.get('description_zh') or ''}",
        f"Category: {project.get('category_name') or project.get('category_slug') or ''}",
        f"Subcategory: {project.get('subcategory_name') or project.get('subcategory_slug') or ''}",
        f"Tags: {', '.join(_project_list(project, 'tags'))}",
        f"Topics: {', '.join(_project_list(project, 'topics'))}",
        f"Language: {project.get('language') or ''}",
    ]
    chunks: list[tuple[str, int, str]] = [("profile", 0, "\n".join(line for line in lines if not line.endswith(": ")))]
    if readme:
        prefix = f"Repository: {project.get('full_name') or project.get('title') or ''}\nREADME:\n"
        start = 0
        for index in range(12):
            text = readme[start : start + 1200].strip()
            if not text:
                break
            chunks.append(("readme", index, prefix + text))
            if start + 1200 >= len(readme):
                break
            start += 1080
    return chunks


class GitHubProjectSemanticIndexer:
    def __init__(
        self,
        *,
        db: GitHubProjectSemanticSourceRepository,
        vectors: ProjectVectorRepository | None = None,
        embeddings: Any = None,
    ) -> None:
        self.db = db
        self.vectors = vectors
        self.embeddings = embeddings

    def _vectors(self) -> ProjectVectorRepository:
        if self.vectors is None:
            self.vectors = ProjectVectorRepository()
        return self.vectors

    def _embeddings(self):
        if self.embeddings is None:
            from backend.app.core.model_factory import get_embedding_model

            self.embeddings = get_embedding_model()
        return self.embeddings

    def _readme_snapshot(self, project: dict[str, Any], *, fetch_readme: bool) -> dict[str, Any]:
        existing_text = str(project.get("readme_text") or "")
        existing_hash = str(project.get("readme_sha256") or "")
        existing_etag = str(project.get("readme_etag") or "")
        if not fetch_readme:
            return {
                "text": existing_text,
                "sha256": existing_hash,
                "etag": existing_etag,
                "status": str(project.get("readme_status") or "pending"),
                "error": "",
            }
        with httpx.Client(timeout=15, follow_redirects=True, trust_env=False) as client:
            snapshot = fetch_github_readme_snapshot(
                str(project.get("full_name") or ""),
                client,
                etag=existing_etag,
                max_chars=settings.project_semantic_readme_max_chars,
            )
        if snapshot.status == "not_modified":
            return {"text": existing_text, "sha256": existing_hash, "etag": snapshot.etag or existing_etag, "status": "succeeded", "error": ""}
        if snapshot.status == "succeeded":
            return {"text": snapshot.text, "sha256": snapshot.sha256, "etag": snapshot.etag, "status": "succeeded", "error": ""}
        if snapshot.status == "not_found":
            return {"text": "", "sha256": "", "etag": "", "status": "not_found", "error": ""}
        return {"text": existing_text, "sha256": existing_hash, "etag": existing_etag, "status": snapshot.status, "error": snapshot.error}

    def sync_project(self, project: dict[str, Any], *, fetch_readme: bool = True, dry_run: bool = False) -> dict[str, Any]:
        readme = self._readme_snapshot(project, fetch_readme=fetch_readme)
        fingerprint = project_semantic_fingerprint(project, readme["sha256"])
        if fingerprint == str(project.get("indexed_fingerprint") or ""):
            # 内容未变也要推进 readme_repo_pushed_at 水位，否则选择查询的
            # pushed_at 比较会让这批项目永远被重复选中（活锁）。
            self.db.mark_github_project_semantic_snapshot_current(
                str(project.get("repo_id") or ""),
                repo_pushed_at=str(project.get("pushed_at") or ""),
                checked_at=_utcnow(),
            )
            return {"repo_id": project.get("repo_id"), "status": "unchanged", "chunk_count": 0}
        chunks = build_project_semantic_chunks(project, readme["text"])
        if dry_run:
            return {"repo_id": project.get("repo_id"), "status": "dry_run", "chunk_count": len(chunks)}
        now = _utcnow()
        base = {
            "repo_id": project.get("repo_id"),
            "readme_text": readme["text"],
            "readme_sha256": readme["sha256"],
            "readme_etag": readme["etag"],
            "readme_status": readme["status"],
            "readme_checked_at": now,
            "readme_fetched_at": now if readme["status"] == "succeeded" else project.get("readme_fetched_at"),
            "readme_repo_pushed_at": project.get("pushed_at"),
            "readme_error": readme["error"],
            "source_fingerprint": fingerprint,
            "indexed_fingerprint": project.get("indexed_fingerprint") or "",
            "index_version": settings.project_semantic_index_version,
            "embedding_provider": settings.embedding_provider,
            "embedding_model": settings.embedding_model_name,
            "embedding_dimension": settings.milvus_dimension,
            "index_status": "indexing",
            "updated_at": now,
        }
        self.db.upsert_github_project_semantic_source(base)
        try:
            vectors = self._embeddings().embed_documents([text for _, _, text in chunks])
            repo_id = str(project.get("repo_id") or "")
            vector_chunks = [
                ProjectVectorChunk(
                    chunk_id=hashlib.sha256(
                        f"github-project:{settings.project_semantic_index_version}|{repo_id}|{kind}|{index}".encode("utf-8")
                    ).hexdigest(),
                    repo_id=repo_id,
                    chunk_kind=kind,
                    chunk_index=index,
                    source_fingerprint=fingerprint,
                    content=text,
                    embedding=list(vector),
                )
                for (kind, index, text), vector in zip(chunks, vectors, strict=True)
            ]
            with _vector_write_lock:
                count = self._vectors().upsert_project_chunks(repo_id, vector_chunks, flush=False)
            self.db.upsert_github_project_semantic_source(
                {**base, "indexed_fingerprint": fingerprint, "chunk_count": count, "index_status": "succeeded", "index_error": None, "indexed_at": _utcnow()}
            )
            return {"repo_id": repo_id, "status": "succeeded", "chunk_count": count}
        except Exception as exc:
            self.db.upsert_github_project_semantic_source(
                {**base, "index_status": "failed", "index_error": str(exc)[:2000], "index_retry_count": int(project.get("index_retry_count") or 0) + 1}
            )
            logger.warning("GitHub project semantic indexing failed for %s: %s", project.get("repo_id"), exc)
            return {"repo_id": project.get("repo_id"), "status": "failed", "error": str(exc)}

    def sync_batch(
        self,
        *,
        limit: int | None = None,
        min_stars: int = 500,
        after_repo_id: str = "",
        fetch_readme: bool = True,
        concurrency: int | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        limit = int(limit or settings.project_semantic_sync_batch_size)
        concurrency = max(
            1,
            min(int(concurrency or settings.project_semantic_sync_concurrency), 20),
        )
        projects = self.db.list_github_projects_for_semantic_sync(
            limit=limit,
            min_stars=min_stars,
            after_repo_id=after_repo_id,
        )

        def sync_one(project: dict[str, Any]) -> dict[str, Any]:
            try:
                return self.sync_project(project, fetch_readme=fetch_readme, dry_run=dry_run)
            except Exception as exc:
                logger.warning(
                    "GitHub project semantic sync aborted for %s: %s",
                    project.get("repo_id"),
                    exc,
                )
                return {
                    "repo_id": project.get("repo_id"),
                    "status": "failed",
                    "error": str(exc),
                }

        if concurrency == 1 or len(projects) < 2:
            results = [sync_one(project) for project in projects]
        else:
            if not dry_run:
                self._embeddings()
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                results = list(executor.map(sync_one, projects))
        if not dry_run and self.vectors is not None and any(
            result.get("status") == "succeeded" for result in results
        ):
            # 逐项目 flush 会把吞吐钉死在 ~20/min；按批一次落盘即可被检索。
            try:
                self._vectors().flush()
            except Exception as exc:
                logger.warning("GitHub project semantic batch flush failed: %s", exc)
        counts: dict[str, int] = {}
        for result in results:
            status = str(result.get("status") or "unknown")
            counts[status] = counts.get(status, 0) + 1
        failed = counts.get("failed", 0)
        return {
            "status": (
                "dry_run"
                if dry_run
                else ("failed" if failed == len(projects) and projects else "success")
            ),
            "selected": len(projects),
            "counts": counts,
            "last_repo_id": projects[-1].get("repo_id") if projects else after_repo_id,
        }


def sync_github_project_semantic_index(
    *,
    db: GitHubProjectSemanticSourceRepository,
    **kwargs: Any,
) -> dict[str, Any]:
    force = bool(kwargs.pop("force", False))
    if not settings.project_semantic_indexing_enabled and not force:
        return {"status": "disabled", "selected": 0, "counts": {}}
    return GitHubProjectSemanticIndexer(db=db).sync_batch(**kwargs)
