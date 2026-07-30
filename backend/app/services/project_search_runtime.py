from __future__ import annotations

"""Application-owned project discovery readers and diagnostic resources."""

import asyncio
import logging
from threading import Lock
from typing import Any, Callable

from backend.app.core.config import settings
from backend.app.services.ingestion.source_github_mcp import (
    search_github_projects_fallback,
)
from backend.app.services.project_discovery import search_projects
from backend.app.services.project_reranker import ProjectReranker
from backend.app.services.project_search_shadow import ProjectSearchShadowManager
from backend.app.services.project_semantic_search import ProjectSemanticSearch

logger = logging.getLogger(__name__)


class ApplicationProjectSearchRuntime:
    """Lazily own project semantic search, reranking, and shadow comparison."""

    def __init__(
        self,
        *,
        config: Any = settings,
        repository_factory: Callable[[], Any] | None = None,
        fallback_search: Callable[..., Any] = search_github_projects_fallback,
        semantic_search_factory: Callable[[], ProjectSemanticSearch] = (
            ProjectSemanticSearch
        ),
        reranker_factory: Callable[[], ProjectReranker] = ProjectReranker,
        shadow_manager_factory: Callable[[], ProjectSearchShadowManager]
        | None = None,
    ) -> None:
        self._config = config
        self._repository_factory = repository_factory
        self._fallback_search = fallback_search
        self._semantic_search_factory = semantic_search_factory
        self._reranker_factory = reranker_factory
        self._shadow_manager_factory = (
            shadow_manager_factory or self._create_shadow_manager
        )
        self._resource_lock = Lock()
        self._warmup_lock = Lock()
        self._semantic_search: ProjectSemanticSearch | None = None
        self._reranker: ProjectReranker | None = None
        self._shadow_manager: ProjectSearchShadowManager | None = None

    def _get_semantic_search(self) -> ProjectSemanticSearch:
        with self._resource_lock:
            if self._semantic_search is None:
                self._semantic_search = self._semantic_search_factory()
            return self._semantic_search

    def _get_reranker(self) -> ProjectReranker:
        with self._resource_lock:
            if self._reranker is None:
                self._reranker = self._reranker_factory()
            return self._reranker

    def _create_shadow_manager(self) -> ProjectSearchShadowManager:
        return ProjectSearchShadowManager(
            workers=int(
                getattr(self._config, "project_search_shadow_workers", 2)
            ),
            capacity=int(
                getattr(self._config, "project_search_shadow_capacity", 8)
            ),
            sample_rate=float(
                getattr(self._config, "project_search_shadow_sample_rate", 0.0)
            ),
            timeout_seconds=float(
                getattr(
                    self._config,
                    "project_search_shadow_timeout_seconds",
                    1.0,
                )
            ),
            recent_case_limit=int(
                getattr(
                    self._config,
                    "project_search_shadow_recent_case_limit",
                    20,
                )
            ),
            epoch_name=str(
                getattr(self._config, "project_search_shadow_epoch", "default")
            ),
        )

    def _get_shadow_manager(self) -> ProjectSearchShadowManager:
        with self._resource_lock:
            if self._shadow_manager is None:
                self._shadow_manager = self._shadow_manager_factory()
            return self._shadow_manager

    async def search_projects(self, **arguments: Any) -> dict[str, Any]:
        options = dict(arguments)
        options.update(
            fallback_search=self._fallback_search,
            semantic_search_factory=self._get_semantic_search,
            reranker_factory=self._get_reranker,
            shadow_manager_factory=self._get_shadow_manager,
        )
        if self._repository_factory is not None:
            options["repository_factory"] = self._repository_factory
        return await search_projects(**options)

    def warmup_semantic_search(self) -> dict[str, Any]:
        if not bool(
            getattr(self._config, "project_semantic_search_enabled", False)
        ):
            return {"status": "disabled"}
        if not self._warmup_lock.acquire(blocking=False):
            return {"status": "already_running"}
        try:
            self._get_semantic_search().warmup()
            return {"status": "success"}
        except Exception as exc:
            logger.warning("Project semantic search warmup failed: %s", exc)
            return {"status": "failed", "error": str(exc)}
        finally:
            self._warmup_lock.release()

    def project_search_shadow_snapshot(self) -> dict[str, Any]:
        with self._resource_lock:
            manager = self._shadow_manager
        if manager is None:
            return {
                "enabled": False,
                "epoch": None,
                "lifecycle": "disabled",
                "in_flight": 0,
                "accounting": {
                    "attempted": 0,
                    "submitted": 0,
                    "completed": 0,
                    "skipped": 0,
                    "submit_errors": 0,
                },
                "counts": {},
                "recent_cases": [],
            }
        return manager.snapshot()

    def finalize_project_search_shadow(
        self,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        with self._resource_lock:
            manager = self._shadow_manager
        if manager is None:
            return self.project_search_shadow_snapshot()
        timeout = (
            float(timeout_seconds)
            if timeout_seconds is not None
            else float(
                getattr(
                    self._config,
                    "project_search_shadow_shutdown_timeout_seconds",
                    5.0,
                )
            )
        )
        manager.close(timeout)
        return manager.snapshot()

    def _detach_resources(
        self,
    ) -> tuple[
        ProjectSemanticSearch | None,
        ProjectReranker | None,
        ProjectSearchShadowManager | None,
    ]:
        with self._warmup_lock:
            with self._resource_lock:
                resources = (
                    self._semantic_search,
                    self._reranker,
                    self._shadow_manager,
                )
                self._semantic_search = None
                self._reranker = None
                self._shadow_manager = None
                return resources

    async def close(self) -> None:
        semantic_search, reranker, shadow_manager = await asyncio.to_thread(
            self._detach_resources
        )
        if semantic_search is not None:
            try:
                await asyncio.to_thread(semantic_search.close)
            except Exception as exc:
                logger.warning("Project semantic search close failed: %s", exc)
        if reranker is not None:
            try:
                await reranker.close()
            except Exception as exc:
                logger.warning("Project reranker close failed: %s", exc)
        if shadow_manager is not None:
            try:
                await asyncio.to_thread(
                    shadow_manager.close,
                    float(
                        getattr(
                            self._config,
                            "project_search_shadow_shutdown_timeout_seconds",
                            5.0,
                        )
                    ),
                )
            except Exception as exc:
                logger.warning("Project search shadow close failed: %s", exc)
