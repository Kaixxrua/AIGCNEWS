from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.app.domain.project_assessment import ProjectAssessment

GitHubProjectSort = Literal["hot", "stars", "updated", "recent", "name"]
PublicProjectSort = Literal["hot", "stars", "updated", "recent", "name", "relevance"]
ProjectSource = Literal["all", "github", "website"]
# Legacy screened requests remain accepted and resolve to the full catalog.
ProjectScope = Literal["all", "today", "recommended", "screened"]


class GitHubProjectItem(BaseModel):
    id: str | None = None
    source: str = "github"
    repo_id: str | int | None = None
    website_id: str | int | None = None
    full_name: str
    title: str | None = None
    url: str | None = None
    domain: str | None = None
    image_url: str | None = None
    description: str | None = None
    description_zh: str | None = None
    description_en: str | None = None
    assessment: ProjectAssessment | None = None
    category_slug: str | None = None
    category_name: str | None = None
    category_name_zh: str | None = None
    category_name_en: str | None = None
    subcategory_slug: str | None = None
    subcategory_name: str | None = None
    subcategory_name_zh: str | None = None
    subcategory_name_en: str | None = None
    tags: list[str] = Field(default_factory=list)
    tags_zh: list[str] = Field(default_factory=list)
    tags_en: list[str] = Field(default_factory=list)
    tags_origin: Literal["system", "user"] = "system"
    language: str | None = None
    topics: list[str] = Field(default_factory=list)
    stars: int = 0
    forks: int = 0
    watchers: int = 0
    open_issues: int = 0
    created_at: str | None = None
    pushed_at: str | None = None
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    last_snapshot_at: str | None = None
    availability_status: str = "active"
    snapshot_date: str | None = None
    captured_at: str | None = None
    rank_in_period: int | None = None
    raw_score: float = 0.0
    score: float = 0.0
    daily_star_growth: int = 0
    daily_growth_available: bool = False
    daily_growth_source: str = "unavailable"
    daily_growth_observed_at: str | None = None
    rolling_24h_star_growth: int | None = None
    rolling_24h_growth_source: str | None = None
    rolling_24h_observed_at: str | None = None
    daily_growth_date: str | None = None
    previous_snapshot_date: str | None = None
    hot_score: float = 0.0
    scale_corrected_growth_score: float = 0.0
    growth_acceleration_score: float = 0.0
    absolute_growth_score: float = 0.0
    maintenance_activity_score: float = 0.0
    community_engagement_score: float = 0.0
    growth_suspicion_score: float = 0.0
    growth_suspicion_signals: str = "[]"
    growth_corroborated: bool = False
    confidence: float = 0.0
    is_favorited: bool = False
    favorited_at: str | None = None
    is_recommended: bool = False
    recommended_at: str | None = None
    user_added: bool = False
    user_added_at: str | None = None


class GitHubProjectsResponse(BaseModel):
    items: list[GitHubProjectItem]
    total: int
    page: int
    page_size: int
    has_next: bool
    min_stars: int
    scope: str = "all"
    category: str = ""
    subcategory: str = ""
    q: str = ""
    sort: str = "stars"
    source: str = "github"


class GitHubProjectSubcategory(BaseModel):
    slug: str
    name: str
    name_zh: str = ""
    name_en: str = ""
    count: int


class GitHubProjectCategory(BaseModel):
    slug: str
    name: str
    name_zh: str = ""
    name_en: str = ""
    count: int
    kind: str = "category"
    scope: str | None = None
    children: list[GitHubProjectSubcategory] = Field(default_factory=list)


class GitHubProjectCategoriesResponse(BaseModel):
    items: list[GitHubProjectCategory]
    total: int
    today_count: int = 0
    recommended_count: int = 0
    min_stars: int
    source: str = "github"


class GitHubProjectTrendPoint(BaseModel):
    date: str
    stars: int
    # None: that day has no trustworthy daily gain (no earlier snapshot), not zero.
    gain: int | None = None


class GitHubProjectTrend(BaseModel):
    points: list[GitHubProjectTrendPoint] = Field(default_factory=list)
    # Rank on the previous day's hot list (top 200); None when not on it. Only sent with ranks=true.
    previous_rank: int | None = None


class GitHubProjectTrendsResponse(BaseModel):
    metric_date: str
    previous_date: str | None = None
    days: int
    items: dict[str, GitHubProjectTrend]


class GitHubProjectPeekCommit(BaseModel):
    sha: str
    # First line of the commit message.
    message: str
    # GitHub login, or the git author name when the commit is not linked to an account.
    author: str = ""
    committed_at: str
    url: str


class GitHubProjectPeekResponse(BaseModel):
    repo_id: str
    # ok: read from GitHub (possibly an earlier copy); unavailable: GitHub could not be read and there is no copy.
    status: Literal["ok", "unavailable"]
    has_readme: bool = False
    # The README's opening paragraphs as plain text; empty when it opens with no prose.
    readme: list[str] = Field(default_factory=list)
    # The README goes on past these paragraphs.
    readme_more: bool = False
    # Latest commit on the default branch; None for an empty repository or when unavailable.
    commit: GitHubProjectPeekCommit | None = None


class ToolWebsiteAddRequest(BaseModel):
    url: str = Field(default="", max_length=1024)


class ToolWebsiteManualAddRequest(BaseModel):
    url: str = Field(default="", max_length=1024)
    title: str = Field(default="", max_length=512)
    description_zh: str = Field(default="", max_length=512)
    description_en: str = Field(default="", max_length=512)
    category_slug: str = Field(default="other", max_length=64)
    subcategory_slug: str = Field(default="", max_length=64)
    tags: list[str] = Field(default_factory=list, max_length=8)


class PersonalWebsiteQuotaResponse(BaseModel):
    tier: Literal["free", "member"]
    unlimited: bool
    limit: int | None = None
    used: int = 0
    remaining: int | None = None
    window_seconds: int = 86400
    reset_at: str | None = None


class ToolWebsiteAddResponse(BaseModel):
    status: str
    message: str
    duplicate: bool = False
    item: dict[str, Any] | None = None


class ToolWebsiteUpdateRequest(BaseModel):
    title: str = Field(default="", max_length=512)
    description: str = Field(default="", max_length=2000)
    description_zh: str = Field(default="", max_length=512)
    description_en: str = Field(default="", max_length=512)
    category_slug: str = Field(default="other", max_length=64)
    subcategory_slug: str = Field(default="", max_length=64)
    tags: list[str] = Field(default_factory=list, max_length=8)
    image_url: str = Field(default="", max_length=1024)


class ToolWebsiteUpdateResponse(BaseModel):
    status: str
    message: str
    item: dict[str, Any] | None = None


class GitHubProjectTag(BaseModel):
    """A personal tag with a stable filter value and localized labels."""

    label: str
    value: str = ""
    label_zh: str = ""
    label_en: str = ""
    count: int = 0
    tags_origin: Literal["system", "user"] = "system"


class GitHubProjectTagsResponse(BaseModel):
    items: list[GitHubProjectTag]
    total: int
    source: str = "github"


class ToolWebsiteDeleteResponse(BaseModel):
    status: str
    message: str
    deleted: bool = False
    website_id: int


class ProjectFavoriteRequest(BaseModel):
    source: Literal["github", "website"]
    repo_id: str | int | None = None
    website_id: str | int | None = None


class ProjectFavoriteResponse(BaseModel):
    status: str
    message: str
    source: str
    repo_id: str | int | None = None
    website_id: str | int | None = None
    is_favorited: bool = False
    favorited_at: str | None = None
    deleted: bool = False


class ProjectTaxonomyItem(BaseModel):
    slug: str
    name: str
    name_zh: str
    name_en: str
    children: list[dict[str, str]] = Field(default_factory=list)


class ProjectTaxonomyResponse(BaseModel):
    items: list[ProjectTaxonomyItem]


ProjectAdoptionDecision = Literal["adopted", "reference_only", "declined"]


class ProjectAdoptionRequest(BaseModel):
    project_full_name: str = Field(min_length=3, max_length=200)
    decision: ProjectAdoptionDecision
    reason: str = Field(default="", max_length=500)
    query: str = Field(default="", max_length=200)


class ProjectAdoptionReceipt(BaseModel):
    id: int
    project_full_name: str
    decision: str
    created_at: str


class ProjectAdoptionStats(BaseModel):
    window_days: int
    window: dict[str, int]
    total: dict[str, int]
    window_adoption_rate: float
    total_adoption_rate: float


class ProjectAdoptionResponse(BaseModel):
    receipt: ProjectAdoptionReceipt
    stats: ProjectAdoptionStats
