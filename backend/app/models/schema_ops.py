from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
    limit: int = 20
    force: bool = False  # True = 忽略日期检测，强制抓取


class IngestResponse(BaseModel):
    status: str
    message: str
    task_id: Optional[int] = None


class IngestByDateRequest(BaseModel):
    target_date: str  # YYYY-MM-DD
    limit: int = 30


class ClearDataResponse(BaseModel):
    status: str
    message: str
    deleted_documents: int
    deleted_tasks: int
    milvus_dropped: bool


class GitHubProjectsEnrichRequest(BaseModel):
    limit: int = 50
    force: bool = False
    dry_run: bool = False
    retry_failed: bool = True
    refresh_changed: bool = False


class GitHubProjectsMetricsRequest(BaseModel):
    min_stars: int = 500
    limit: int = 0
    metric_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    dry_run: bool = False


class GitHubProjectsMetricsRecomputeRequest(BaseModel):
    min_stars: int = 500
    metric_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class GitHubProjectRecommendRequest(BaseModel):
    repo_id: Optional[str | int] = None
    full_name: str = Field(default="", max_length=255)


class GitHubProjectRecommendResponse(BaseModel):
    status: str
    message: str
    repo_id: str
    full_name: str = ""
    is_recommended: bool = True
    recommended_at: Optional[str] = None
    removed: bool = False


class GitHubProjectsEnrichResponse(BaseModel):
    status: str
    message: str
    result: Optional[Dict[str, Any]] = None


class ProjectTaxonomyItem(BaseModel):
    """管理端诊断投影：只暴露 slug/name/children（线格式与面向用户的多语种分类不同）。"""

    slug: str
    name: str
    children: list[Dict[str, str]] = Field(default_factory=list)


class ProjectTaxonomyResponse(BaseModel):
    items: list[ProjectTaxonomyItem]


class ProviderConfigRequest(BaseModel):
    provider: Literal["openai", "anthropic"] = "openai"
    base_url: str = ""
    model_name: str = ""
    api_key: Optional[str] = None
    clear_api_key: bool = False


class ProviderConfigResponse(BaseModel):
    provider: str
    base_url: str
    model_name: str
    api_key_configured: bool
    api_key_masked: Optional[str] = None
    updated_at: Optional[str] = None


class McpServerConfigRequest(BaseModel):
    server_key: str = Field(default="", max_length=64)
    display_name: str = Field(default="", max_length=128)
    description: str = Field(default="", max_length=2000)
    url: str = Field(default="", max_length=1024)
    transport: Literal["streamable_http"] = "streamable_http"
    auth_type: Literal["none", "bearer"] = "none"
    auth_token: Optional[str] = Field(default=None, max_length=4096)
    clear_auth_token: bool = False
    enabled: bool = True


class McpToolSummary(BaseModel):
    name: str
    description: str = ""


class McpServerConfigResponse(BaseModel):
    id: int
    server_key: str
    display_name: str
    description: str = ""
    url: str
    transport: str
    auth_type: str
    auth_token_configured: bool
    auth_token_masked: Optional[str] = None
    enabled: bool
    last_test_status: str = "unknown"
    last_test_message: str = ""
    last_test_at: Optional[str] = None
    tools: list[McpToolSummary] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class McpServerConfigListResponse(BaseModel):
    items: list[McpServerConfigResponse]
    total: int


class McpServerDeleteResponse(BaseModel):
    status: str
    message: str
    deleted: bool
    id: int


class McpServerTestResponse(BaseModel):
    status: str
    message: str
    server: McpServerConfigResponse
    tools: list[McpToolSummary] = Field(default_factory=list)
