from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class ProjectLexicalConcept:
    concept_id: str
    primary_terms: tuple[str, ...]
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectLexicalRetrievalPlan:
    normalized_query: str
    strict_terms: tuple[str, ...]
    concepts: tuple[ProjectLexicalConcept, ...] = ()


@dataclass(frozen=True)
class ProjectLexicalCandidate:
    repo_id: str
    lane: Literal["strict", "relaxed"]
    term_coverage: int = 0
    match_strength: int = 0


@dataclass(frozen=True)
class ProjectLexicalCandidateLanes:
    strict: tuple[ProjectLexicalCandidate, ...] = ()
    relaxed: tuple[ProjectLexicalCandidate, ...] = ()


class ProjectCatalogRepository(Protocol):
    """Read boundary for the public project catalog."""

    def find_lexical_candidate_repo_ids(
        self,
        *,
        q: str,
        category: str = "",
        subcategory: str = "",
        language: str = "",
        tag: str = "",
        min_stars: int = 500,
        enriched_only: bool = True,
        limit: int = 200,
    ) -> list[str]: ...

    def find_lexical_candidate_lanes(
        self,
        *,
        q: str | ProjectLexicalRetrievalPlan,
        category: str = "",
        subcategory: str = "",
        language: str = "",
        tag: str = "",
        min_stars: int = 500,
        enriched_only: bool = True,
        strict_limit: int = 150,
        relaxed_limit: int = 150,
    ) -> ProjectLexicalCandidateLanes: ...

    def find_repo_ids_by_name_segment(
        self,
        *,
        name: str,
        limit: int = 2,
    ) -> list[str]: ...

    def get_project_stars_map(self, repo_ids: list[str]) -> dict[str, int]: ...

    def get_project_heat_map(
        self, repo_ids: list[str]
    ) -> dict[str, tuple[float, int, int]]: ...

    def list_github_hot_for_date(
        self,
        *,
        metric_date: str,
        limit: int,
        min_stars: int = 500,
        enriched_only: bool = True,
    ) -> list[dict[str, Any]]: ...

    def list_github_hot_dates(self, *, limit: int = 60) -> list[str]: ...

    def list_projects(
        self,
        *,
        source: str = "all",
        scope: str = "all",
        category: str = "",
        subcategory: str = "",
        q: str = "",
        language: str = "",
        tag: str = "",
        page: int = 1,
        page_size: int = 24,
        sort: str = "stars",
        min_stars: int = 500,
        enriched_only: bool = True,
        user_id: int | None = None,
        favorites_only: bool = False,
        candidate_repo_ids: list[str] | None = None,
    ) -> dict[str, Any]: ...

    def get_project_categories(
        self,
        *,
        source: str = "all",
        min_stars: int = 500,
        enriched_only: bool = True,
        user_id: int | None = None,
        favorites_only: bool = False,
    ) -> dict[str, Any]: ...
