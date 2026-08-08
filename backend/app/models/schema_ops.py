from __future__ import annotations

from datetime import time
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


class DocumentDeleteResponse(BaseModel):
    status: str
    message: str
    doc_id: str
    deleted: bool


class BulkDocumentDeleteRequest(BaseModel):
    doc_ids: list[str] = Field(min_length=1, max_length=100)


class BulkDocumentDeleteResponse(BaseModel):
    status: str
    message: str
    doc_ids: list[str]
    deleted_count: int
    not_found_count: int


class GitHubProjectsEnrichRequest(BaseModel):
    limit: int = 50
    force: bool = False
    dry_run: bool = False
    retry_failed: bool = True
    refresh_changed: bool = False
    # 富化并发度：1-10，超出范围直接 422；默认 1 保持原有节流行为
    concurrency: int = Field(default=1, ge=1, le=10)


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


class GitHubProjectsEnrichCancelResponse(BaseModel):
    """终止富化结果：cancelling=已发出终止信号；not_running=当前无运行中的批次。"""

    status: str
    message: str


class GitHubProjectsCrawlRequest(BaseModel):
    """GitHub 搜索爬取触发参数；max_stars=0 表示不封顶。"""

    min_stars: int = Field(default=500, ge=0)
    max_stars: int = Field(default=0, ge=0)
    created_start: str = Field(default="2008-01-01", pattern=r"^\d{4}-\d{2}-\d{2}$")
    created_end: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    pushed_after: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    limit: int = Field(default=5000, ge=1, le=20000)
    enrich: bool = True
    dry_run: bool = False


class GitHubProjectsCrawlResponse(BaseModel):
    status: str
    message: str
    channel: str = ""
    first_seen_after: str = ""
    result: Optional[Dict[str, Any]] = None


class GitHubProjectsCrawlStatusResponse(BaseModel):
    """爬取运行状态 + 实时计数（无任务时 status=idle）。"""

    status: str = "idle"
    channel: str = ""
    first_seen_after: str = ""
    task_id: Optional[int] = None
    task_status: str = ""
    item_count: int = 0
    error_msg: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    candidates_upserted: int = 0
    scope_total: int = 0
    enriched_succeeded: int = 0
    enriched_failed: int = 0


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
    # 自填自由文本（原样透传给服务商）；归一规则见 control_plane.normalize_reasoning_effort
    reasoning_effort: str = ""


class ProviderConfigResponse(BaseModel):
    provider: str
    base_url: str
    model_name: str
    api_key_configured: bool
    api_key_masked: Optional[str] = None
    updated_at: Optional[str] = None
    reasoning_effort: str = ""


class ProviderConfigTestResponse(BaseModel):
    """连接测试结果：HTTP 恒 200，status=success/failed 表达业务结果。"""

    status: str
    message: str
    provider: str = ""
    base_url: str = ""
    model_name: str = ""
    latency_ms: Optional[int] = None


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


class XWatchAccountRequest(BaseModel):
    screen_name: str = Field(default="", max_length=64)
    display_name: str = Field(default="", max_length=128)
    note: str = Field(default="", max_length=2000)
    enabled: bool = True
    sort_order: int = 0


class XWatchAccountResponse(BaseModel):
    id: int
    screen_name: str
    display_name: str = ""
    note: str = ""
    enabled: bool
    sort_order: int = 0
    last_test_status: str = "unknown"
    last_test_message: str = ""
    last_test_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class XWatchAccountListResponse(BaseModel):
    items: list[XWatchAccountResponse]
    total: int


class XWatchAccountDeleteResponse(BaseModel):
    status: str
    message: str
    deleted: bool
    id: int


class XWatchAccountTestResponse(BaseModel):
    status: str
    message: str
    account: XWatchAccountResponse


class XSnapshotRebuildRequest(BaseModel):
    target_date: Optional[str] = None  # YYYY-MM-DD；空 = 重建全部历史日期


class XSnapshotRebuildResultItem(BaseModel):
    date: str
    upserted: int


class XSnapshotRebuildResponse(BaseModel):
    status: str
    message: str
    results: list[XSnapshotRebuildResultItem]
    skipped_no_date: int


class XCredentialRequest(BaseModel):
    display_name: str = Field(default="", max_length=128)
    note: str = Field(default="", max_length=2000)
    enabled: bool = True
    sort_order: int = 0
    auth_token: Optional[str] = Field(default=None, max_length=8192)
    ct0: Optional[str] = Field(default=None, max_length=8192)


class XCredentialResponse(BaseModel):
    id: int
    display_name: str = ""
    note: str = ""
    enabled: bool
    sort_order: int = 0
    auth_token_configured: bool
    auth_token_masked: Optional[str] = None
    ct0_configured: bool
    ct0_masked: Optional[str] = None
    last_test_status: str = "unknown"
    last_test_message: str = ""
    last_test_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class XCredentialListResponse(BaseModel):
    items: list[XCredentialResponse]
    total: int


class XCredentialDeleteResponse(BaseModel):
    status: str
    message: str
    deleted: bool
    id: int


class XCredentialTestResponse(BaseModel):
    status: str
    message: str
    credential: XCredentialResponse


class SchedulerJobConfigItem(BaseModel):
    job_id: str
    name: str
    start_time: time
    end_time: time
    interval_minutes: int = Field(..., ge=1)
    enabled: bool = True


class SchedulerConfigListResponse(BaseModel):
    items: list[SchedulerJobConfigItem]
    total: int


class SchedulerConfigUpdateRequest(BaseModel):
    start_time: time
    end_time: time
    interval_minutes: int = Field(..., ge=1)
    enabled: bool = True


class SchedulerConfigUpdateResponse(BaseModel):
    status: str
    message: str
    item: SchedulerJobConfigItem
