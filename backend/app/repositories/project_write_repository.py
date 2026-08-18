from __future__ import annotations

from typing import Any, Protocol

from backend.app.repositories.runtime_provider_repository import (
    RuntimeProviderSettingReader,
)


class GitHubProjectIngestionRepository(Protocol):
    def upsert_github_repo_candidate(self, repo: dict[str, Any]) -> None: ...

    def get_github_repo_source_channels(
        self, repo_ids: list[str]
    ) -> dict[str, str]: ...

    def mark_github_repo_available(
        self, full_name: str, *, checked_at: str
    ) -> bool: ...

    def record_github_repo_not_found(
        self, full_name: str, *, checked_at: str
    ) -> bool: ...

    def ensure_github_repo_candidate(self, repo: dict[str, Any]) -> str: ...

    def insert_github_repo_snapshot(self, snapshot: dict[str, Any]) -> None: ...

    def upsert_github_repo_metric_observations(
        self,
        observations: list[dict[str, Any]],
        *,
        checked_at: str,
    ) -> int: ...

    def upsert_github_trending_hit(self, hit: dict[str, Any]) -> str: ...

    def get_github_hot_repos(
        self, period: str, limit: int = 10
    ) -> list[dict[str, Any]]: ...

    def get_github_snapshot_count(self) -> int: ...

    def list_github_project_metric_targets(
        self, *, min_stars: int = 500, limit: int = 0
    ) -> list[dict[str, Any]]: ...

    def list_github_identity_sweep_targets(
        self, *, after_full_name: str = "", limit: int = 500
    ) -> list[dict[str, Any]]: ...

    def get_github_metric_refresh_status(
        self, *, metric_date: str, min_stars: int = 500, limit: int = 0
    ) -> dict[str, Any]: ...

    def get_github_daily_metric_inputs(
        self,
        *,
        metric_date: str,
        previous_date: str,
        baseline_start_date: str,
        min_stars: int = 500,
        repo_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]: ...

    def upsert_github_daily_metrics(self, metrics: list[dict[str, Any]]) -> int: ...


class GitHubProjectEnrichmentRepository(Protocol):
    @property
    def runtime_provider_settings(self) -> RuntimeProviderSettingReader: ...

    def get_github_projects_needing_enrichment(
        self,
        *,
        limit: int = 50,
        min_stars: int = 500,
        prompt_version: str = "v1",
        force: bool = False,
        retry_failed: bool = True,
        refresh_changed: bool = False,
    ) -> list[dict[str, Any]]: ...

    def upsert_github_repo_enrichment(self, payload: dict[str, Any]) -> None: ...

    def list_github_projects_needing_bilingual_tags(
        self, *, after_repo_id: str = "", limit: int = 50, min_stars: int = 500,
    ) -> list[dict[str, Any]]: ...

    def update_github_repo_system_tags(
        self, *, repo_id: str, tags_zh_json: str, tags_en_json: str,
        prompt_version: str, model_provider: str = "", model_name: str = "",
    ) -> None: ...

    def list_github_projects_needing_english_description(
        self, *, after_repo_id: str = "", limit: int = 200,
    ) -> list[dict[str, Any]]: ...

    def update_github_repo_description_en(
        self, *, repo_id: str, description_en: str,
        prompt_version: str, model_provider: str = "", model_name: str = "",
    ) -> None: ...

    def mark_github_repo_enrichment_failed(
        self,
        repo_id: str,
        *,
        source_fingerprint: str,
        prompt_version: str,
        error_msg: str,
        model_provider: str = "",
        model_name: str = "",
    ) -> None: ...

    def get_github_project_enrichment_status(
        self, *, min_stars: int = 500
    ) -> dict[str, Any]: ...

    def count_github_run_enrichment_candidates(
        self, *, channel: str, first_seen_after: str, min_stars: int = 500
    ) -> int: ...

    def list_github_run_enrichment_candidates(
        self,
        *,
        channel: str,
        first_seen_after: str,
        min_stars: int = 500,
        after_repo_id: str = "",
        limit: int = 200,
    ) -> list[dict[str, Any]]: ...

    def get_github_run_crawl_status(
        self, *, channel: str, first_seen_after: str, min_stars: int = 500
    ) -> dict[str, Any]: ...


class ToolWebsiteEnrichmentRepository(Protocol):
    @property
    def runtime_provider_settings(self) -> RuntimeProviderSettingReader: ...

    def get_tool_website_by_hash(
        self, normalized_url_hash: str
    ) -> dict[str, Any] | None: ...

    def upsert_tool_website(
        self, payload: dict[str, Any], *, update_existing: bool = True
    ) -> dict[str, Any]: ...

    def get_tool_website_enrichment(
        self, website_id: int
    ) -> dict[str, Any] | None: ...

    def get_tool_website_item(self, website_id: int) -> dict[str, Any] | None: ...

    def list_tool_websites_needing_bilingual_enrichment(
        self, *, after_website_id: int = 0, limit: int = 50,
        prompt_version: str = "v1", retry_failed: bool = True,
    ) -> list[dict[str, Any]]: ...

    def upsert_tool_website_enrichment(self, payload: dict[str, Any]) -> None: ...

    def list_tool_websites_needing_bilingual_tags(
        self, *, after_website_id: int = 0, limit: int = 50,
    ) -> list[dict[str, Any]]: ...

    def update_tool_website_system_tags(
        self, *, website_id: int, tags_zh_json: str, tags_en_json: str,
        prompt_version: str, model_provider: str = "", model_name: str = "",
    ) -> None: ...

    def mark_tool_website_enrichment_failed(
        self,
        website_id: int,
        *,
        source_fingerprint: str,
        prompt_version: str,
        error_msg: str,
        model_provider: str = "",
        model_name: str = "",
    ) -> None: ...

    def mark_tool_website_enrichment_blocked(
        self,
        website_id: int,
        *,
        source_fingerprint: str,
        prompt_version: str,
        reason: str,
        model_provider: str = "",
        model_name: str = "",
    ) -> None: ...


class PersonalWebsiteQuotaLimitReached(RuntimeError):
    def __init__(self, usage: dict[str, Any]) -> None:
        super().__init__("personal website quota exceeded")
        self.usage = usage


class UserProjectCollectionRepository(Protocol):
    def get_personal_website_quota_usage(
        self, *, user_id: int, window_seconds: int
    ) -> dict[str, Any]: ...

    def add_project_favorite(
        self,
        *,
        user_id: int,
        source: str,
        repo_id: Any = None,
        website_id: Any = None,
        website_quota_enabled: bool = False,
        website_quota_limit: int | None = None,
        website_quota_window_seconds: int = 86400,
    ) -> dict[str, Any]: ...

    def remove_project_favorite(
        self,
        *,
        user_id: int,
        source: str,
        repo_id: Any = None,
        website_id: Any = None,
    ) -> bool: ...

    def link_user_tool_website(
        self,
        *,
        user_id: int,
        website_id: int,
        added_via: str = "auto",
        quota_enabled: bool = False,
        quota_limit: int | None = None,
        quota_window_seconds: int = 86400,
    ) -> dict[str, Any]: ...

    def unlink_user_tool_website(self, *, user_id: int, website_id: int) -> bool: ...

    def get_tool_website_item_for_user(
        self, *, user_id: int, website_id: int
    ) -> dict[str, Any] | None: ...

    def upsert_user_tool_website_override(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]: ...

    def list_user_project_collection(
        self, *, user_id: int, **kwargs: Any
    ) -> dict[str, Any]: ...

    def get_user_project_categories(
        self,
        *,
        user_id: int,
        source: str = "all",
        min_stars: int = 500,
        enriched_only: bool = True,
    ) -> dict[str, Any]: ...

    def get_user_project_tags(
        self,
        *,
        user_id: int,
        source: str = "github",
        min_stars: int = 500,
        enriched_only: bool = True,
    ) -> dict[str, Any]: ...


class GitHubProjectRecommendationRepository(Protocol):
    def recommend_github_project(
        self,
        *,
        repo_id: Any = None,
        full_name: str = "",
        recommended_by_user_id: int | None = None,
    ) -> dict[str, Any]: ...

    def unrecommend_github_project(
        self, *, repo_id: Any = None, full_name: str = ""
    ) -> dict[str, Any]: ...


class GitHubProjectSemanticSourceRepository(Protocol):
    def list_github_projects_for_semantic_sync(
        self,
        *,
        limit: int = 100,
        min_stars: int = 500,
        after_repo_id: str = "",
        retry_failed: bool = True,
    ) -> list[dict[str, Any]]: ...

    def upsert_github_project_semantic_source(
        self, payload: dict[str, Any]
    ) -> None: ...

    def mark_github_project_semantic_snapshot_current(
        self,
        repo_id: str,
        *,
        repo_pushed_at: str,
        checked_at: str,
    ) -> None: ...

    def get_github_project_semantic_status(
        self, *, min_stars: int = 500
    ) -> dict[str, Any]: ...
