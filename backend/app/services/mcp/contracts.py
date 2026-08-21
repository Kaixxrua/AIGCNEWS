from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)

from backend.app.domain.project_taxonomy import (
    CATEGORY_BY_SLUG,
    SUBCATEGORY_BY_CATEGORY_SLUG,
)
from backend.app.domain.search_semantics import (
    ProjectIntentClass,
    ProjectQueryLanguage,
    build_client_project_search_intent,
)

SourceChoice = Literal["all", "arxiv", "github", "news", "producthunt", "hackernews", "x"]
PeriodChoice = Literal["daily", "weekly", "monthly"]
ProjectScope = Literal["all", "today", "recommended"]
ProjectSort = Literal["hot", "stars", "updated", "recent", "name"]
ProjectDiscoverySort = Literal["hot", "stars", "updated", "recent", "name", "relevance"]
ProjectResponseLang = Literal["zh", "en"]
IntentText30 = Annotated[StrictStr, StringConstraints(min_length=1, max_length=30)]
IntentText40 = Annotated[StrictStr, StringConstraints(min_length=1, max_length=40)]
IntentText120 = Annotated[StrictStr, StringConstraints(min_length=1, max_length=120)]

# 这些值表示查询/内容语言，而非 GitHub 仓库编程语言，
# 传给顶层 language 会产生误导性零结果。
_FORBIDDEN_REPO_LANGUAGE_VALUES = {
    "zh",
    "en",
    "mixed",
    "und",
    "中文",
    "英文",
    "chinese",
    "english",
}


def _validate_repo_language(value: str) -> str:
    """Reject query/content-language values masquerading as repository language filters."""
    normalized = value.strip().casefold()
    # Locale forms such as zh-CN, en-US, zh-TW, en-GB should also be rejected.
    base_locale = normalized.split("-", 1)[0]
    if normalized in _FORBIDDEN_REPO_LANGUAGE_VALUES or base_locale in {"zh", "en"}:
        raise ValueError(
            "language must be a GitHub repository programming language filter "
            "(e.g. Python, C++, JavaScript). Do not pass query/content-language "
            "values such as zh, en, 中文, or 英文; use intent.language for "
            "zh/en/mixed/und query language."
        )
    return value


RepositoryLanguage = Annotated[
    StrictStr,
    StringConstraints(max_length=64),
    AfterValidator(_validate_repo_language),
]

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
    q: StrictStr = Field(
        min_length=1,
        max_length=120,
        description=(
            "Concise terms distilled from a project discovery request for software, repositories, "
            "open-source implementations, SDKs, frameworks, components, templates, examples, or tutorials."
        ),
    )
    language: RepositoryLanguage = Field(
        default="",
        max_length=64,
        description=(
            "Optional GitHub repository programming language filter, such as Python, C++, "
            "JavaScript, or Jupyter Notebook. Do not use query-language values such as "
            "zh, en, 中文, or 英文."
        ),
    )
    sort: ProjectDiscoverySort | None = Field(
        default=None,
        description=(
            "Omit to rank non-empty queries by relevance via hybrid lexical and semantic retrieval; "
            "explicit stars, hot, updated, recent, or name sorts remain authoritative."
        ),
    )
    lang: ProjectResponseLang = Field(
        default="zh",
        description=(
            "Response language for curated text fields (description, category names, tags). "
            "'zh' (default) returns the bilingual payload with Chinese-preferred generic fields; "
            "'en' folds English text into the generic fields and omits the *_zh fields. "
            "Set to 'en' when the user speaks English."
        ),
    )
    page: StrictInt = Field(default=1, ge=1)
    limit: StrictInt = Field(default=10, ge=1, le=20)


class ClientProjectSearchIntentInput(McpInputModel):
    schema_version: Literal["project-search-intent-client-v1"]
    language: ProjectQueryLanguage = Field(
        description="Query language: zh, en, mixed, or und. This is independent of the top-level repository language filter."
    )
    intent_class: ProjectIntentClass = "general_discovery"
    lexical_terms: list[IntentText40] = Field(min_length=1, max_length=8)
    semantic_queries: list[IntentText120] = Field(min_length=1, max_length=3)
    topics: list[IntentText40] = Field(default_factory=list, max_length=6)
    languages: list[IntentText30] = Field(default_factory=list, max_length=3)
    artifact_types: list[IntentText40] = Field(default_factory=list, max_length=6)
    must_have: list[IntentText40] = Field(default_factory=list, max_length=6)
    should_have: list[IntentText40] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def validate_values(self) -> "ClientProjectSearchIntentInput":
        build_client_project_search_intent(
            "",
            self.model_dump(exclude={"schema_version"}),
        )
        return self


class SearchGitHubAIProjectsInput(McpInputModel):
    q: StrictStr = Field(default="", max_length=120)
    category: StrictStr = Field(default="", max_length=64)
    subcategory: StrictStr = Field(default="", max_length=64)
    language: RepositoryLanguage = Field(
        default="",
        max_length=64,
        description=(
            "Optional GitHub repository programming language filter, such as Python, C++, "
            "JavaScript, or Jupyter Notebook. Do not use query-language values such as "
            "zh, en, 中文, or 英文; for query language use intent.language (zh/en/mixed/und)."
        ),
    )
    intent: ClientProjectSearchIntentInput | None = Field(
        default=None,
        description="Optional host-generated relevance intent; explicit top-level filters remain authoritative.",
    )
    lang: ProjectResponseLang = Field(
        default="zh",
        description=(
            "Response language for curated text fields (description, category names, tags). "
            "'zh' (default) returns the bilingual payload with Chinese-preferred generic fields; "
            "'en' folds English text into the generic fields and omits the *_zh fields. "
            "Set to 'en' when the user speaks English."
        ),
    )
    scope: ProjectScope = "all"
    sort: ProjectDiscoverySort | None = Field(
        default=None,
        description=(
            "Omit to rank non-empty queries by relevance; queryless defaults are all=stars, "
            "today=hot, recommended=recent. Scope 'today' is exploratory discovery of newly hot "
            "projects, not an official ranking; for rankings, leaderboards, or top-N lists, "
            "call get_top_items instead."
        ),
    )
    page: StrictInt = Field(default=1, ge=1)
    limit: StrictInt = Field(default=10, ge=1, le=20)

    @model_validator(mode="after")
    def validate_taxonomy(self) -> "SearchGitHubAIProjectsInput":
        if self.intent is not None:
            build_client_project_search_intent(
                self.q,
                self.intent.model_dump(exclude={"schema_version"}),
            )
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


AdoptionDecision = Literal["adopted", "reference_only", "declined"]
AdoptionSource = Literal["mcp", "rest", "plugin", "hook"]


class SubmitProjectAdoptionInput(McpInputModel):
    project_full_name: StrictStr = Field(
        min_length=3,
        max_length=200,
        description="GitHub repository full name (owner/repo) the decision applies to.",
    )
    decision: AdoptionDecision = Field(
        description=(
            "The reuse outcome: 'adopted' (the project was integrated or depended on), "
            "'reference_only' (used as design reference only), or 'declined' (rejected, "
            "build-from-scratch chosen)."
        ),
    )
    reason: StrictStr = Field(
        default="",
        max_length=500,
        description="Optional short reason for the decision; keep under one sentence.",
    )
    query: StrictStr = Field(
        default="",
        max_length=200,
        description="Optional search query that surfaced this project, for recall-quality review.",
    )
    source: AdoptionSource = Field(
        default="mcp",
        description="Receipt origin: mcp (default), rest, plugin, or hook.",
    )


class SearchMyProjectFavoritesInput(McpInputModel):
    q: StrictStr = Field(default="", max_length=120)
    category: StrictStr = Field(default="", max_length=64)
    subcategory: StrictStr = Field(default="", max_length=64)
    language: RepositoryLanguage = Field(
        default="",
        max_length=64,
        description=(
            "Optional GitHub repository programming language filter, such as Python, C++, "
            "JavaScript, or Jupyter Notebook. Do not use query-language values such as "
            "zh, en, 中文, or 英文."
        ),
    )
    tag: StrictStr = Field(default="", max_length=64)
    lang: ProjectResponseLang = Field(
        default="zh",
        description=(
            "Response language for curated text fields (description, category names, tags). "
            "'zh' (default) returns the bilingual payload with Chinese-preferred generic fields; "
            "'en' folds English text into the generic fields and omits the *_zh fields. "
            "Set to 'en' when the user speaks English."
        ),
    )
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
    "get_project_categories": GetProjectCategoriesInput,
    "submit_project_adoption": SubmitProjectAdoptionInput,
    "search_my_project_favorites": SearchMyProjectFavoritesInput,
}


def input_schema(tool_name: str) -> dict:
    return TOOL_INPUT_MODELS[tool_name].model_json_schema()
