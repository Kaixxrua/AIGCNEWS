from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

from backend.app.services.ingestion.project_taxonomy import (
    CATEGORY_BY_SLUG,
    SUBCATEGORY_BY_CATEGORY_SLUG,
)

SourceChoice = Literal["all", "arxiv", "github", "news", "producthunt", "hackernews"]
PeriodChoice = Literal["daily", "weekly", "monthly"]
ProjectScope = Literal["all", "today", "recommended"]
ProjectSort = Literal["hot", "stars", "updated", "recent", "name"]
ProjectDiscoverySort = Literal["relevance", "hot", "stars", "updated", "recent", "name"]

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_iso_date(value: str, *, field_name: str = "date") -> str:
    if not _DATE_RE.fullmatch(value):
        raise ValueError(f"{field_name} must use YYYY-MM-DD format")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{field_name} must be a valid calendar date") from None
    if parsed.isoformat() != value:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format")
    return value


class McpInputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class SearchPapersInput(McpInputModel):
    q: StrictStr = Field(min_length=1, max_length=200, description="Concise paper query using established technical terms.")
    page: StrictInt = Field(default=1, ge=1, description="One-based result page.")
    limit: StrictInt = Field(default=10, ge=1, le=20, description="Maximum results per page.")


class SearchDocumentsInput(McpInputModel):
    q: StrictStr = Field(min_length=1, max_length=200, description="Concise query for indexed AIGC_NEWS records.")
    source: SourceChoice = Field(default="all", description="Optional indexed source filter.")
    page: StrictInt = Field(default=1, ge=1, description="One-based result page.")
    limit: StrictInt = Field(default=10, ge=1, le=20, description="Maximum results per page.")


class GetPaperDetailInput(McpInputModel):
    paper_id: StrictStr = Field(min_length=1, max_length=128, description="Document id returned by a search or ranking tool.")


class GetTopItemsInput(McpInputModel):
    source: SourceChoice = "all"
    period: PeriodChoice = "daily"
    date: StrictStr | None = Field(default=None, min_length=10, max_length=10, description="Snapshot date in YYYY-MM-DD format.")
    limit: StrictInt = Field(default=10, ge=1, le=20)

    @model_validator(mode="after")
    def validate_date(self) -> "GetTopItemsInput":
        if self.date:
            validate_iso_date(self.date)
        return self


class SearchGitHubProjectsInput(McpInputModel):
    q: StrictStr = Field(min_length=1, max_length=120, description="Concise GitHub project search terms.")
    language: StrictStr = Field(default="", max_length=64)
    sort: ProjectSort = "stars"
    page: StrictInt = Field(default=1, ge=1)
    limit: StrictInt = Field(default=10, ge=1, le=20)


class SearchGitHubAIProjectsInput(McpInputModel):
    q: StrictStr = Field(default="", max_length=120)
    category: StrictStr = Field(default="", max_length=64)
    subcategory: StrictStr = Field(default="", max_length=64)
    language: StrictStr = Field(default="", max_length=64)
    scope: ProjectScope = "all"
    sort: ProjectDiscoverySort | None = Field(
        default=None,
        description=(
            "Omit to rank non-empty queries by relevance; queryless defaults are all=stars, "
            "today=hot, recommended=recent. Today always uses hot."
        ),
    )
    page: StrictInt = Field(default=1, ge=1)
    limit: StrictInt = Field(default=10, ge=1, le=20)

    @model_validator(mode="after")
    def validate_taxonomy(self) -> "SearchGitHubAIProjectsInput":
        category = self.category
        subcategory = self.subcategory
        if category and category not in CATEGORY_BY_SLUG:
            raise ValueError("category must be a valid AIGC_NEWS category slug")
        if not subcategory:
            return self
        if category:
            if subcategory not in SUBCATEGORY_BY_CATEGORY_SLUG.get(category, {}):
                raise ValueError("subcategory must belong to category")
            return self
        parents = [slug for slug, children in SUBCATEGORY_BY_CATEGORY_SLUG.items() if subcategory in children]
        if len(parents) != 1:
            raise ValueError("subcategory requires an unambiguous category")
        self.category = parents[0]
        return self


class GetProjectCategoriesInput(McpInputModel):
    pass


class SearchMyProjectFavoritesInput(McpInputModel):
    q: StrictStr = Field(default="", max_length=120)
    category: StrictStr = Field(default="", max_length=64)
    subcategory: StrictStr = Field(default="", max_length=64)
    language: StrictStr = Field(default="", max_length=64)
    tag: StrictStr = Field(default="", max_length=64)
    sort: ProjectSort = "recent"
    limit: StrictInt = Field(default=10, ge=1, le=20)
    marker: StrictStr = Field(default="", max_length=128)


TOOL_INPUT_MODELS: dict[str, type[McpInputModel]] = {
    "search_papers": SearchPapersInput,
    "search_documents": SearchDocumentsInput,
    "get_paper_detail": GetPaperDetailInput,
    "get_top_items": GetTopItemsInput,
    "search_github_projects": SearchGitHubProjectsInput,
    "search_github_ai_projects": SearchGitHubAIProjectsInput,
    "get_project_library": SearchGitHubAIProjectsInput,
    "get_project_categories": GetProjectCategoriesInput,
    "search_my_project_favorites": SearchMyProjectFavoritesInput,
}


def input_schema(tool_name: str) -> dict:
    return TOOL_INPUT_MODELS[tool_name].model_json_schema()
