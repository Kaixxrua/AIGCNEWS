from __future__ import annotations

import asyncio
import logging
import re
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.app.api.dependencies import (
    get_briefing_admin_service,
    get_dashboard_cache_admin_service,
    get_data_cleanup_admin_service,
    get_document_repository,
    get_github_project_admin_service,
    get_github_project_crawl_admin_service,
    get_github_project_recommendation_admin_service,
    get_ingestion_admin_service,
    get_mcp_admin_service,
    get_operations_runtime,
    get_ops_diagnostics_service,
    get_runtime_provider_admin_service,
    get_scheduler_admin_service,
    get_scheduler_config_admin_service,
    get_x_credential_admin_service,
    get_x_watch_account_repository,
    get_x_watch_admin_service,
)
from backend.app.core.auth import RequireAdmin
from backend.app.core.operations import ApplicationOperationsRuntime
from backend.app.models.schema_ops import (
    BulkDocumentDeleteRequest,
    BulkDocumentDeleteResponse,
    ClearDataResponse,
    DocumentDeleteResponse,
    GitHubProjectRecommendRequest,
    GitHubProjectRecommendResponse,
    GitHubProjectsCrawlRequest,
    GitHubProjectsCrawlResponse,
    GitHubProjectsCrawlStatusResponse,
    GitHubProjectsEnrichRequest,
    GitHubProjectsEnrichResponse,
    GitHubProjectsMetricsRecomputeRequest,
    GitHubProjectsMetricsRequest,
    IngestByDateRequest,
    IngestRequest,
    IngestResponse,
    McpServerConfigListResponse,
    McpServerConfigRequest,
    McpServerConfigResponse,
    McpServerDeleteResponse,
    McpServerTestResponse,
    ProjectTaxonomyResponse,
    ProviderConfigRequest,
    ProviderConfigResponse,
    SchedulerConfigListResponse,
    SchedulerConfigUpdateRequest,
    SchedulerConfigUpdateResponse,
    SchedulerJobConfigItem,
    XCredentialDeleteResponse,
    XCredentialListResponse,
    XCredentialRequest,
    XCredentialResponse,
    XCredentialTestResponse,
    XWatchAccountDeleteResponse,
    XWatchAccountListResponse,
    XWatchAccountRequest,
    XWatchAccountResponse,
    XWatchAccountTestResponse,
)
from backend.app.models.schema_projects import (
    ToolWebsiteAddRequest,
    ToolWebsiteAddResponse,
    ToolWebsiteDeleteResponse,
    ToolWebsiteManualAddRequest,
)
from backend.app.repositories.document_repository import DocumentRepository
from backend.app.repositories.x_watch_repository import XWatchAccountRepository
from backend.app.services.briefing_admin import BriefingAdminService
from backend.app.services.dashboard_cache_admin import DashboardCacheAdminService
from backend.app.services.data_cleanup_admin import DataCleanupAdminService
from backend.app.services.github_project_admin import GitHubProjectAdminService
from backend.app.services.github_project_crawl_admin import (
    GitHubProjectCrawlAdminService,
    plan_crawl,
)
from backend.app.services.github_project_recommendation_admin import (
    GitHubProjectAdminNotFoundError,
    GitHubProjectAdminValidationError,
    GitHubProjectRecommendationAdminService,
)
from backend.app.services.ingestion.cache_invalidation import clear_dashboard_cache_safely
from backend.app.services.ingestion_admin import VALID_SOURCES, IngestionAdminService
from backend.app.services.mcp.admin_service import (
    McpAdminConflictError,
    McpAdminNotFoundError,
    McpAdminService,
    McpAdminValidationError,
    SafeMcpServerProjection,
)
from backend.app.services.ops_diagnostics import OpsDiagnosticsService
from backend.app.services.runtime_provider.admin_service import (
    RuntimeProviderAdminService,
)
from backend.app.services.scheduler_admin import SchedulerAdminService
from backend.app.services.scheduler_config_admin import SchedulerConfigAdminService
from backend.app.services.x_credentials.admin_service import (
    SafeXCredentialProjection,
    XCredentialAdminNotFoundError,
    XCredentialAdminService,
    XCredentialAdminValidationError,
)
from backend.app.services.x_watch.admin_service import (
    SafeXWatchAccountProjection,
    XWatchAdminConflictError,
    XWatchAdminNotFoundError,
    XWatchAdminService,
    XWatchAdminValidationError,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _mcp_server_config_response(
    projection: SafeMcpServerProjection,
) -> McpServerConfigResponse:
    return McpServerConfigResponse.model_validate(projection, from_attributes=True)


# ── 后台任务包装 ─────────────────────────────────────────────────────────────


# ── 运行时模型配置 ─────────────────────────────────────────────────────────────


@router.get("/ops/provider-config", response_model=ProviderConfigResponse, tags=["Ops"])
async def get_provider_config(
    _: dict = Depends(RequireAdmin),
    service: RuntimeProviderAdminService = Depends(
        get_runtime_provider_admin_service
    ),
) -> ProviderConfigResponse:
    """读取唯一的运行时模型配置。响应只返回密钥是否已配置与脱敏值。"""
    projection = await service.get_config()
    return ProviderConfigResponse.model_validate(projection, from_attributes=True)


@router.put("/ops/provider-config", response_model=ProviderConfigResponse, tags=["Ops"])
async def update_provider_config(
    request: ProviderConfigRequest,
    _: dict = Depends(RequireAdmin),
    service: RuntimeProviderAdminService = Depends(
        get_runtime_provider_admin_service
    ),
) -> ProviderConfigResponse:
    """更新唯一的运行时模型配置。api_key 留空时保留原值，clear_api_key=true 时清空。"""
    projection = await service.update_config(request.model_dump())
    return ProviderConfigResponse.model_validate(projection, from_attributes=True)


# ── MCP Server 配置 ──────────────────────────────────────────────────────────


@router.get("/ops/mcp-servers", response_model=McpServerConfigListResponse, tags=["Ops"])
async def list_mcp_servers(
    _: dict = Depends(RequireAdmin),
    service: McpAdminService = Depends(get_mcp_admin_service),
) -> McpServerConfigListResponse:
    """列出 MCP Server 配置。响应不会返回明文 Token。"""
    projections = await service.list_servers()
    items = [_mcp_server_config_response(item) for item in projections]
    return McpServerConfigListResponse(items=items, total=len(items))


@router.post("/ops/mcp-servers", response_model=McpServerConfigResponse, tags=["Ops"])
async def create_mcp_server(
    request: McpServerConfigRequest,
    _: dict = Depends(RequireAdmin),
    service: McpAdminService = Depends(get_mcp_admin_service),
) -> McpServerConfigResponse:
    """创建 MCP Server 配置。auth_token 只写入，不明文返回。"""
    try:
        projection = await service.create_server(request.model_dump())
    except McpAdminValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except McpAdminConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _mcp_server_config_response(projection)


@router.put("/ops/mcp-servers/{server_id}", response_model=McpServerConfigResponse, tags=["Ops"])
async def update_mcp_server(
    server_id: int,
    request: McpServerConfigRequest,
    _: dict = Depends(RequireAdmin),
    service: McpAdminService = Depends(get_mcp_admin_service),
) -> McpServerConfigResponse:
    """更新 MCP Server 配置。auth_token 留空时保留，clear_auth_token=true 时清空。"""
    try:
        projection = await service.update_server(server_id, request.model_dump())
    except McpAdminValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except McpAdminConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except McpAdminNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _mcp_server_config_response(projection)


@router.delete("/ops/mcp-servers/{server_id}", response_model=McpServerDeleteResponse, tags=["Ops"])
async def delete_mcp_server(
    server_id: int,
    _: dict = Depends(RequireAdmin),
    service: McpAdminService = Depends(get_mcp_admin_service),
) -> McpServerDeleteResponse:
    """删除 MCP Server 配置。"""
    try:
        await service.delete_server(server_id)
    except McpAdminNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return McpServerDeleteResponse(status="succeeded", message="MCP Server 配置已删除。", deleted=True, id=server_id)


@router.post("/ops/mcp-servers/{server_id}/test", response_model=McpServerTestResponse, tags=["Ops"])
async def test_mcp_server(
    server_id: int,
    _: dict = Depends(RequireAdmin),
    service: McpAdminService = Depends(get_mcp_admin_service),
) -> McpServerTestResponse:
    """测试 MCP Server 连通性，只执行 initialize / tools/list，不调用任意工具。"""
    try:
        outcome = await service.test_server(server_id)
    except McpAdminNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    assert isinstance(outcome.server, SafeMcpServerProjection)
    server = _mcp_server_config_response(outcome.server)
    return McpServerTestResponse(
        status=outcome.result.get("status", "failed"),
        message=outcome.result.get("message", ""),
        server=server,
        tools=server.tools,
    )


# ── X 关注账号 ───────────────────────────────────────────────────────────────


def _x_watch_account_response(
    projection: SafeXWatchAccountProjection,
) -> XWatchAccountResponse:
    return XWatchAccountResponse.model_validate(projection, from_attributes=True)


@router.get("/ops/x-watch-accounts", response_model=XWatchAccountListResponse, tags=["Ops"])
async def list_x_watch_accounts(
    _: dict = Depends(RequireAdmin),
    service: XWatchAdminService = Depends(get_x_watch_admin_service),
) -> XWatchAccountListResponse:
    """列出 X 采集关注账号（数据库 watchlist，空表时按 env 句柄自举）。"""
    projections = await service.list_accounts()
    items = [_x_watch_account_response(item) for item in projections]
    return XWatchAccountListResponse(items=items, total=len(items))


@router.post("/ops/x-watch-accounts", response_model=XWatchAccountResponse, tags=["Ops"])
async def create_x_watch_account(
    request: XWatchAccountRequest,
    _: dict = Depends(RequireAdmin),
    service: XWatchAdminService = Depends(get_x_watch_admin_service),
) -> XWatchAccountResponse:
    """新增 X 关注账号。screen_name 归一化为小写无 @ 形式。"""
    try:
        projection = await service.create_account(request.model_dump())
    except XWatchAdminValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except XWatchAdminConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _x_watch_account_response(projection)


@router.put("/ops/x-watch-accounts/{account_id}", response_model=XWatchAccountResponse, tags=["Ops"])
async def update_x_watch_account(
    account_id: int,
    request: XWatchAccountRequest,
    _: dict = Depends(RequireAdmin),
    service: XWatchAdminService = Depends(get_x_watch_admin_service),
) -> XWatchAccountResponse:
    """整体更新 X 关注账号（handle/开关/排序）。"""
    try:
        projection = await service.update_account(account_id, request.model_dump())
    except XWatchAdminValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except XWatchAdminConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except XWatchAdminNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _x_watch_account_response(projection)


@router.delete("/ops/x-watch-accounts/{account_id}", response_model=XWatchAccountDeleteResponse, tags=["Ops"])
async def delete_x_watch_account(
    account_id: int,
    _: dict = Depends(RequireAdmin),
    service: XWatchAdminService = Depends(get_x_watch_admin_service),
) -> XWatchAccountDeleteResponse:
    """删除 X 关注账号。"""
    try:
        await service.delete_account(account_id)
    except XWatchAdminNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return XWatchAccountDeleteResponse(status="succeeded", message="X 关注账号已删除。", deleted=True, id=account_id)


@router.post("/ops/x-watch-accounts/{account_id}/test", response_model=XWatchAccountTestResponse, tags=["Ops"])
async def test_x_watch_account_route(
    account_id: int,
    _: dict = Depends(RequireAdmin),
    service: XWatchAdminService = Depends(get_x_watch_admin_service),
) -> XWatchAccountTestResponse:
    """探测单个 X 账号：拉取近期推文，同时验证 handle 有效性与 cookie 凭据。"""
    try:
        outcome = await service.test_account(account_id)
    except XWatchAdminNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    assert isinstance(outcome.account, SafeXWatchAccountProjection)
    return XWatchAccountTestResponse(
        status=outcome.result.get("status", "failed"),
        message=outcome.result.get("message", ""),
        account=_x_watch_account_response(outcome.account),
    )


# ── X 账号凭证 ───────────────────────────────────────────────────────────────


def _x_credential_response(
    projection: SafeXCredentialProjection,
) -> XCredentialResponse:
    return XCredentialResponse.model_validate(projection, from_attributes=True)


@router.get("/ops/x-credentials", response_model=XCredentialListResponse, tags=["Ops"])
async def list_x_credentials(
    _: dict = Depends(RequireAdmin),
    service: XCredentialAdminService = Depends(get_x_credential_admin_service),
) -> XCredentialListResponse:
    """列出 X 采集凭证（仅返回配置状态与脱敏值，不返回明文 cookie）。"""
    projections = await service.list_credentials()
    items = [_x_credential_response(item) for item in projections]
    return XCredentialListResponse(items=items, total=len(items))


@router.post("/ops/x-credentials", response_model=XCredentialResponse, tags=["Ops"])
async def create_x_credential(
    request: XCredentialRequest,
    _: dict = Depends(RequireAdmin),
    service: XCredentialAdminService = Depends(get_x_credential_admin_service),
) -> XCredentialResponse:
    """新增 X 采集凭证。auth_token 与 ct0 只写入，不明文返回。"""
    try:
        projection = await service.create_credential(request.model_dump())
    except XCredentialAdminValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _x_credential_response(projection)


@router.put("/ops/x-credentials/{credential_id}", response_model=XCredentialResponse, tags=["Ops"])
async def update_x_credential(
    credential_id: int,
    request: XCredentialRequest,
    _: dict = Depends(RequireAdmin),
    service: XCredentialAdminService = Depends(get_x_credential_admin_service),
) -> XCredentialResponse:
    """更新 X 采集凭证。两个 secret 留空表示保留当前值，不能更新为半残 pair。"""
    try:
        projection = await service.update_credential(credential_id, request.model_dump())
    except XCredentialAdminValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except XCredentialAdminNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _x_credential_response(projection)


@router.delete("/ops/x-credentials/{credential_id}", response_model=XCredentialDeleteResponse, tags=["Ops"])
async def delete_x_credential(
    credential_id: int,
    _: dict = Depends(RequireAdmin),
    service: XCredentialAdminService = Depends(get_x_credential_admin_service),
) -> XCredentialDeleteResponse:
    """删除 X 采集凭证。"""
    try:
        await service.delete_credential(credential_id)
    except XCredentialAdminNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return XCredentialDeleteResponse(
        status="succeeded",
        message="X 凭证已删除。",
        deleted=True,
        id=credential_id,
    )


@router.post("/ops/x-credentials/{credential_id}/test", response_model=XCredentialTestResponse, tags=["Ops"])
async def test_x_credential_route(
    credential_id: int,
    _: dict = Depends(RequireAdmin),
    service: XCredentialAdminService = Depends(get_x_credential_admin_service),
    watch_repository: XWatchAccountRepository = Depends(get_x_watch_account_repository),
) -> XCredentialTestResponse:
    """测试单个 X 凭证：使用第一个启用 watch handle 做真实请求，不允许 fallback。"""
    handle = _first_enabled_x_handle(watch_repository)
    try:
        outcome = await service.test_credential(credential_id, handle)
    except XCredentialAdminNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    assert isinstance(outcome.credential, SafeXCredentialProjection)
    return XCredentialTestResponse(
        status=outcome.result.get("status", "failed"),
        message=outcome.result.get("message", ""),
        credential=_x_credential_response(outcome.credential),
    )


def _first_enabled_x_handle(watch_repository: XWatchAccountRepository) -> str:
    """返回第一个启用的 X watch handle；没有时让 probe 返回稳定失败标记。"""
    handles = watch_repository.list_enabled_x_handles()
    if handles:
        return str(handles[0] or "")
    return ""


# ── 路由 ─────────────────────────────────────────────────────────────────────


@router.post("/ops/ingest", response_model=IngestResponse, tags=["Ops"])
async def trigger_ingest(
    request: IngestRequest,
    _: dict = Depends(RequireAdmin),
    operations: ApplicationOperationsRuntime = Depends(get_operations_runtime),
    service: IngestionAdminService = Depends(get_ingestion_admin_service),
) -> IngestResponse:
    """
    手动触发数据采集任务。

    - **force=false**（默认）：智能模式，检测落后天数后补录（最多 3 天）。
    - **force=true**：强制模式，直接抓取最新数据，不做日期检测。
    """
    if request.force:
        operations.submit(service.force_ingest, request.limit)
        logger.info("[Ops] 强制采集任务已加入后台队列，limit=%d", request.limit)
        return IngestResponse(
            status="queued",
            message=f"强制采集任务已提交（limit={request.limit}），后台执行中。",
        )
    else:
        operations.submit(service.smart_ingest, request.limit)
        logger.info("[Ops] 智能采集任务已加入后台队列，limit=%d", request.limit)
        return IngestResponse(
            status="queued",
            message=f"智能采集任务已提交（limit={request.limit}），后台执行中。",
        )


@router.post("/ops/ingest-by-date", response_model=IngestResponse, tags=["Ops"])
async def ingest_by_date(
    request: IngestByDateRequest,
    _: dict = Depends(RequireAdmin),
    operations: ApplicationOperationsRuntime = Depends(get_operations_runtime),
    service: IngestionAdminService = Depends(get_ingestion_admin_service),
) -> IngestResponse:
    """
    按指定日期触发数据采集。

    - **target_date**：目标日期，格式 YYYY-MM-DD。
    - **limit**：每个数据源的抓取数量上限（默认 30）。
    """

    if not re.match(r"^\d{4}-\d{2}-\d{2}$", request.target_date):
        raise HTTPException(
            status_code=400, detail="target_date 格式错误，应为 YYYY-MM-DD"
        )

    operations.submit(service.ingest_by_date, request.target_date, request.limit)
    logger.info(
        "[Ops] 按日期采集任务已加入后台队列：date=%s, limit=%d",
        request.target_date,
        request.limit,
    )
    return IngestResponse(
        status="queued",
        message=f"按日期采集任务已提交（date={request.target_date}, limit={request.limit}），后台执行中。",
    )


@router.post("/ops/clear-data", response_model=ClearDataResponse, tags=["Ops"])
async def clear_all_data(
    _: dict = Depends(RequireAdmin),
    service: DataCleanupAdminService = Depends(get_data_cleanup_admin_service),
) -> ClearDataResponse:
    """
    清空所有已存储数据：

    - SQLite documents 表
    - SQLite ingestion_tasks 表
    - Milvus Collection（向量索引）

    ⚠️ 此操作不可逆，请谨慎使用。
    """
    result = await service.clear_all()
    deleted_docs = int(result["deleted_documents"])
    deleted_tasks = int(result["deleted_tasks"])
    milvus_ok = bool(result["vector_dropped"])
    return ClearDataResponse(
        status="success",
        message=f"已清空 {deleted_docs} 条文档、{deleted_tasks} 条任务记录，Milvus 集合{'已删除' if milvus_ok else '清空失败（已跳过）'}。",
        deleted_documents=deleted_docs,
        deleted_tasks=deleted_tasks,
        milvus_dropped=milvus_ok,
    )


@router.delete("/ops/documents/{doc_id}", response_model=DocumentDeleteResponse, tags=["Ops"])
async def delete_document(
    doc_id: str,
    _: dict = Depends(RequireAdmin),
    documents: DocumentRepository = Depends(get_document_repository),
) -> DocumentDeleteResponse:
    """按 doc_id 删除文档及其排行快照；删除失败返回 404。"""
    deleted = await asyncio.to_thread(documents.delete_document, doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")
    await clear_dashboard_cache_safely()
    return DocumentDeleteResponse(
        status="success",
        message=f"已删除文档 {doc_id}",
        doc_id=doc_id,
        deleted=True,
    )


@router.post("/ops/documents/bulk-delete", response_model=BulkDocumentDeleteResponse, tags=["Ops"])
async def bulk_delete_documents(
    request: BulkDocumentDeleteRequest,
    _: dict = Depends(RequireAdmin),
    documents: DocumentRepository = Depends(get_document_repository),
) -> BulkDocumentDeleteResponse:
    """批量删除文档及其排行快照；返回实际删除与未找到的计数。"""
    deleted_ids: list[str] = []
    not_found_ids: list[str] = []

    def _delete_all() -> None:
        for doc_id in request.doc_ids:
            if documents.delete_document(doc_id):
                deleted_ids.append(doc_id)
            else:
                not_found_ids.append(doc_id)

    await asyncio.to_thread(_delete_all)
    await clear_dashboard_cache_safely()
    return BulkDocumentDeleteResponse(
        status="success",
        message=f"已删除 {len(deleted_ids)} 条文档，{len(not_found_ids)} 条未找到",
        doc_ids=deleted_ids,
        deleted_count=len(deleted_ids),
        not_found_count=len(not_found_ids),
    )


@router.post("/ops/github-hot/refresh", response_model=IngestResponse, tags=["Ops"])
async def refresh_github_hot(
    limit: int = Query(default=80, ge=20, le=200),
    _: dict = Depends(RequireAdmin),
    operations: ApplicationOperationsRuntime = Depends(get_operations_runtime),
    service: GitHubProjectAdminService = Depends(get_github_project_admin_service),
) -> IngestResponse:
    """手动刷新 GitHub 热榜候选池与快照。"""
    operations.submit(service.refresh_hot, limit)
    logger.info("[Ops] GitHub 热榜刷新任务已加入后台队列，limit=%d", limit)
    return IngestResponse(
        status="queued",
        message=f"GitHub 热榜刷新任务已提交（limit={limit}），后台执行中。",
    )


@router.post(
    "/ops/tool-websites",
    response_model=ToolWebsiteAddResponse,
    tags=["Ops"],
)
async def add_tool_website(
    request: ToolWebsiteAddRequest,
    user: dict = Depends(RequireAdmin),
) -> ToolWebsiteAddResponse:
    """公共网页收藏已下线；网页收藏只允许用户添加到个人收藏夹。"""
    raise HTTPException(status_code=410, detail="公共网页收藏已下线，请在我的收藏中添加个人网页收藏")


@router.post(
    "/ops/tool-websites/manual",
    response_model=ToolWebsiteAddResponse,
    tags=["Ops"],
)
async def add_tool_website_manual(
    request: ToolWebsiteManualAddRequest,
    user: dict = Depends(RequireAdmin),
) -> ToolWebsiteAddResponse:
    """公共网页收藏已下线；网页收藏只允许用户手动添加到个人收藏夹。"""
    raise HTTPException(status_code=410, detail="公共网页收藏已下线，请在我的收藏中手动添加个人网页收藏")


@router.delete(
    "/ops/tool-websites/{website_id}",
    response_model=ToolWebsiteDeleteResponse,
    tags=["Ops"],
)
async def delete_tool_website(
    website_id: int,
    _: dict = Depends(RequireAdmin),
) -> ToolWebsiteDeleteResponse:
    """公共网页收藏已下线；用户只能移出自己的个人网页收藏。"""
    raise HTTPException(status_code=410, detail="公共网页收藏已下线，请从个人收藏夹移出网页收藏")


@router.get(
    "/ops/project-taxonomy",
    response_model=ProjectTaxonomyResponse,
    tags=["Ops"],
)
async def get_project_taxonomy(
    _: dict = Depends(RequireAdmin),
    service: OpsDiagnosticsService = Depends(get_ops_diagnostics_service),
) -> ProjectTaxonomyResponse:
    """返回管理员手动添加工具网页时可选的分类体系。"""
    return ProjectTaxonomyResponse(items=service.project_taxonomy())


@router.post(
    "/ops/github-projects/enrich",
    response_model=GitHubProjectsEnrichResponse,
    tags=["Ops"],
)
async def enrich_github_project_library(
    request: GitHubProjectsEnrichRequest,
    _: dict = Depends(RequireAdmin),
    operations: ApplicationOperationsRuntime = Depends(get_operations_runtime),
    service: GitHubProjectAdminService = Depends(get_github_project_admin_service),
) -> GitHubProjectsEnrichResponse:
    """手动触发 GitHub 项目库 AI 分类与中文描述富化。"""
    limit = max(1, min(int(request.limit or 50), 500))
    if request.dry_run:
        result = await asyncio.to_thread(
            service.enrich,
            limit=limit,
            force=request.force,
            dry_run=True,
            retry_failed=request.retry_failed,
            refresh_changed=request.refresh_changed,
        )
        return GitHubProjectsEnrichResponse(
            status="dry_run",
            message=f"GitHub 项目库富化 dry-run 完成，候选 {result.get('candidates', 0)} 个。",
            result=result,
        )

    operations.submit(
        service.enrich,
        limit,
        request.force,
        False,
        request.retry_failed,
        request.refresh_changed,
    )
    logger.info(
        "[Ops] GitHub 项目库富化任务已加入后台队列，limit=%d force=%s retry_failed=%s refresh_changed=%s",
        limit,
        request.force,
        request.retry_failed,
        request.refresh_changed,
    )
    return GitHubProjectsEnrichResponse(
        status="queued",
        message=f"GitHub 项目库富化任务已提交（limit={limit}），后台执行中。",
    )


@router.post(
    "/ops/github-projects/crawl",
    response_model=GitHubProjectsCrawlResponse,
    tags=["Ops"],
)
async def crawl_github_project_library(
    request: GitHubProjectsCrawlRequest,
    _: dict = Depends(RequireAdmin),
    operations: ApplicationOperationsRuntime = Depends(get_operations_runtime),
    service: GitHubProjectCrawlAdminService = Depends(get_github_project_crawl_admin_service),
) -> GitHubProjectsCrawlResponse:
    """手动触发 GitHub 搜索爬取（可选爬完后自动富化本次新抓项目）。"""
    try:
        plan = plan_crawl(
            min_stars=request.min_stars,
            max_stars=request.max_stars,
            limit=request.limit,
            created_start=date.fromisoformat(request.created_start),
            created_end=(
                date.fromisoformat(request.created_end)
                if request.created_end
                else date.today()
            ),
            pushed_after=request.pushed_after or "",
            enrich=request.enrich,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if request.dry_run:
        result = await asyncio.to_thread(service.crawl_dry_run, plan)
        return GitHubProjectsCrawlResponse(
            status="dry_run",
            message=(
                f"GitHub 搜索爬取 dry-run 完成：分片 {len(result.get('shards') or {})} 个，"
                f"可抓取约 {result.get('total_available', 0)} 个仓库。"
            ),
            channel=plan["channel"],
            first_seen_after=plan["first_seen_after"],
            result=result,
        )

    if not service.try_acquire_crawl():
        raise HTTPException(
            status_code=409,
            detail="已有 GitHub 搜索爬取任务在执行中，请等待其完成后再触发。",
        )
    if not operations.submit(service.crawl_and_enrich, plan):
        service.release_crawl()
        raise HTTPException(
            status_code=503, detail="后台执行器正在停止，暂时无法接受新任务。"
        )
    logger.info(
        "[Ops] GitHub 搜索爬取任务已提交 channel=%s enrich=%s limit=%d",
        plan["channel"],
        plan["enrich"],
        plan["limit"],
    )
    return GitHubProjectsCrawlResponse(
        status="queued",
        message=f"GitHub 搜索爬取任务已提交（channel={plan['channel']}），后台执行中。",
        channel=plan["channel"],
        first_seen_after=plan["first_seen_after"],
    )


@router.get(
    "/ops/github-projects/crawl/status",
    response_model=GitHubProjectsCrawlStatusResponse,
    tags=["Ops"],
)
async def github_projects_crawl_status(
    _: dict = Depends(RequireAdmin),
    channel: str = Query(default="", max_length=255),
    first_seen_after: str = Query(default="", max_length=64),
    min_stars: Optional[int] = Query(default=None, ge=0),
    service: GitHubProjectCrawlAdminService = Depends(get_github_project_crawl_admin_service),
) -> GitHubProjectsCrawlStatusResponse:
    """查询某次（默认最近一次）GitHub 搜索爬取运行的任务状态与实时计数。"""
    try:
        status = await asyncio.to_thread(
            service.crawl_status,
            channel=channel,
            first_seen_after=first_seen_after,
            min_stars=min_stars,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return GitHubProjectsCrawlStatusResponse(**status)


@router.post(
    "/ops/github-projects/recommendations",
    response_model=GitHubProjectRecommendResponse,
    tags=["Ops"],
)
async def recommend_github_project(
    request: GitHubProjectRecommendRequest,
    user: dict = Depends(RequireAdmin),
    service: GitHubProjectRecommendationAdminService = Depends(
        get_github_project_recommendation_admin_service
    ),
) -> GitHubProjectRecommendResponse:
    """将 GitHub 项目加入站长推荐。"""
    try:
        outcome = await service.recommend(
            repo_id=request.repo_id,
            full_name=request.full_name,
            admin_identity=user,
        )
    except GitHubProjectAdminValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GitHubProjectAdminNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return GitHubProjectRecommendResponse(
        status="succeeded",
        message=outcome.message,
        **outcome.result,
    )


@router.delete(
    "/ops/github-projects/recommendations",
    response_model=GitHubProjectRecommendResponse,
    tags=["Ops"],
)
async def unrecommend_github_project(
    request: GitHubProjectRecommendRequest,
    _: dict = Depends(RequireAdmin),
    service: GitHubProjectRecommendationAdminService = Depends(
        get_github_project_recommendation_admin_service
    ),
) -> GitHubProjectRecommendResponse:
    """取消 GitHub 项目的站长推荐。"""
    try:
        outcome = await service.unrecommend(
            repo_id=request.repo_id,
            full_name=request.full_name,
        )
    except GitHubProjectAdminValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GitHubProjectAdminNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return GitHubProjectRecommendResponse(
        status="succeeded",
        message=outcome.message,
        **outcome.result,
    )


@router.get("/ops/github-projects/enrichment-status", tags=["Ops"])
async def github_project_enrichment_status(
    _: dict = Depends(RequireAdmin),
    service: GitHubProjectRecommendationAdminService = Depends(
        get_github_project_recommendation_admin_service
    ),
):
    """查看 GitHub 项目库富化进度。"""
    return await service.get_enrichment_status()


@router.post(
    "/ops/github-projects/metrics/refresh",
    response_model=GitHubProjectsEnrichResponse,
    tags=["Ops"],
)
async def refresh_github_project_metrics(
    request: GitHubProjectsMetricsRequest,
    _: dict = Depends(RequireAdmin),
    operations: ApplicationOperationsRuntime = Depends(get_operations_runtime),
    service: GitHubProjectAdminService = Depends(get_github_project_admin_service),
) -> GitHubProjectsEnrichResponse:
    """手动刷新 GitHub 项目每日快照，并在非 dry-run 时重算热度分。"""
    min_stars = max(0, int(request.min_stars or 0))
    limit = max(0, min(int(request.limit or 0), 20000))
    if request.dry_run:
        result = await asyncio.to_thread(
            service.refresh_metrics,
            min_stars=min_stars,
            limit=limit,
            metric_date=request.metric_date,
            dry_run=True,
        )
        return GitHubProjectsEnrichResponse(status="dry_run", message="GitHub 项目每日指标 dry-run 完成。", result=result)

    operations.submit(
        service.refresh_metrics,
        min_stars=min_stars,
        limit=limit,
        metric_date=request.metric_date,
        dry_run=False,
    )
    return GitHubProjectsEnrichResponse(status="queued", message="GitHub 项目每日指标刷新任务已提交，后台执行中。")


@router.post(
    "/ops/github-projects/metrics/recompute",
    response_model=GitHubProjectsEnrichResponse,
    tags=["Ops"],
)
async def recompute_github_project_metrics(
    request: GitHubProjectsMetricsRecomputeRequest,
    _: dict = Depends(RequireAdmin),
    service: GitHubProjectAdminService = Depends(get_github_project_admin_service),
) -> GitHubProjectsEnrichResponse:
    """基于连续快照或同日 Trending 日榜值，重算某天增长和热度分。"""
    result = await asyncio.to_thread(
        service.recompute_metrics,
        metric_date=request.metric_date,
        min_stars=max(0, int(request.min_stars or 0)),
    )
    return GitHubProjectsEnrichResponse(status="succeeded", message="GitHub 项目每日热度指标已重算。", result=result)


@router.post("/ops/ingest-source", response_model=IngestResponse, tags=["Ops"])
async def ingest_single_source(
    source: str = Query(
        ..., description="数据源名称：arxiv / github / news / producthunt / hackernews"
    ),
    limit: int = Query(default=20, ge=5, le=100),
    _: dict = Depends(RequireAdmin),
    operations: ApplicationOperationsRuntime = Depends(get_operations_runtime),
    service: IngestionAdminService = Depends(get_ingestion_admin_service),
) -> IngestResponse:
    """
    按数据源独立采集（单源模式）。

    前端监测页面可为每个数据源提供独立的"采集"按钮，
    调用此接口时仅采集指定源，不影响其他源。

    - **source**：数据源名称（arxiv / github / news / producthunt / hackernews / x）
    - **limit**：每源最多抓取条数（默认 20）
    """
    source_lower = source.strip().lower()
    if source_lower not in VALID_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=f"未知数据源 '{source}'，可选值：{', '.join(sorted(VALID_SOURCES))}",
        )

    operations.submit(service.ingest_source, source_lower, limit)
    logger.info(
        "[Ops] 单源采集任务已加入后台队列：source=%s, limit=%d", source_lower, limit
    )
    return IngestResponse(
        status="queued",
        message=f"「{source_lower}」采集任务已提交（limit={limit}），后台执行中。",
    )


@router.get("/ops/ingest-source/list", tags=["Ops"])
async def list_available_sources(_: dict = Depends(RequireAdmin)):
    """返回所有可用的数据源名称列表（前端下拉 / 按钮渲染用）。"""
    return {
        "sources": sorted(VALID_SOURCES),
    }


@router.get("/ops/project-catalog/readiness", tags=["Ops"])
async def project_catalog_readiness(
    _: dict = Depends(RequireAdmin),
    service: OpsDiagnosticsService = Depends(get_ops_diagnostics_service),
):
    return await service.project_catalog_readiness()


@router.get("/ops/project-search/shadow-status", tags=["Ops"])
async def project_search_shadow_status(
    _: dict = Depends(RequireAdmin),
    service: OpsDiagnosticsService = Depends(get_ops_diagnostics_service),
):
    """返回不含查询文本或候选 ID 的项目搜索 shadow 诊断。"""
    return service.project_search_shadow_status()


@router.post("/ops/project-shadow/finalize", tags=["Ops"])
async def finalize_project_shadow(
    _: dict = Depends(RequireAdmin),
    service: OpsDiagnosticsService = Depends(get_ops_diagnostics_service),
):
    """停止接收新搜索 shadow 调用，排空并返回具名 epoch 的最终证据。"""
    return await service.finalize_project_shadow()


@router.get("/ops/scheduler/status", tags=["Ops"])
async def scheduler_status(
    _: dict = Depends(RequireAdmin),
    service: SchedulerAdminService = Depends(get_scheduler_admin_service),
):
    """查询 APScheduler 当前状态与已注册任务列表。"""
    return service.status()


@router.post("/ops/scheduler/trigger", tags=["Ops"])
async def trigger_scheduled_job(
    job_id: str = Query(default="daily_smart_ingestion"),
    _: dict = Depends(RequireAdmin),
    service: SchedulerAdminService = Depends(get_scheduler_admin_service),
):
    """立即触发指定的定时任务（用于调试）。"""
    return service.trigger(job_id)


@router.get(
    "/ops/scheduler/config",
    response_model=SchedulerConfigListResponse,
    tags=["Ops"],
)
async def list_scheduler_configs(
    _: dict = Depends(RequireAdmin),
    service: SchedulerConfigAdminService = Depends(get_scheduler_config_admin_service),
) -> SchedulerConfigListResponse:
    """列出所有可配置定时任务的起止时间与轮询间隔。

    未保存过配置的任务返回硬编码默认值。
    """
    projections = await asyncio.to_thread(service.list_configs)
    items = [
        SchedulerJobConfigItem.model_validate(projection, from_attributes=True)
        for projection in projections
    ]
    return SchedulerConfigListResponse(items=items, total=len(items))


@router.put(
    "/ops/scheduler/config/{job_id}",
    response_model=SchedulerConfigUpdateResponse,
    tags=["Ops"],
)
async def update_scheduler_config(
    job_id: str,
    request: SchedulerConfigUpdateRequest,
    _: dict = Depends(RequireAdmin),
    service: SchedulerConfigAdminService = Depends(get_scheduler_config_admin_service),
) -> SchedulerConfigUpdateResponse:
    """更新单个定时任务的时间窗口与轮询间隔。

    修改在调度器重启后生效；当前运行中的任务仍按旧触发器执行。
    """
    try:
        projection = await asyncio.to_thread(
            service.update_config,
            job_id,
            start_time=request.start_time,
            end_time=request.end_time,
            interval_minutes=request.interval_minutes,
            enabled=request.enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return SchedulerConfigUpdateResponse(
        status="success",
        message=f"定时任务 {job_id} 配置已保存，重启后生效。",
        item=SchedulerJobConfigItem.model_validate(projection, from_attributes=True),
    )


# ── 每日简报生成 ─────────────────────────────────────────────────────────────

@router.post("/ops/briefing/generate-all", response_model=IngestResponse, tags=["Ops"])
async def generate_all_briefings(
    force_regenerate: bool = Query(
        default=True, description="是否强制重新生成（忽略缓存）"
    ),
    _: dict = Depends(RequireAdmin),
    operations: ApplicationOperationsRuntime = Depends(get_operations_runtime),
    service: BriefingAdminService = Depends(get_briefing_admin_service),
) -> IngestResponse:
    """
    手动触发全维度每日简报生成。

    后台依次生成 all / arxiv / github / news / producthunt / hackernews
    六个维度的今日简报，并持久化到数据库。

    - **force_regenerate=true**（默认）：强制重新生成，忽略已有缓存。
    - **force_regenerate=false**：已生成过则跳过，避免重复消耗 LLM。
    """
    operations.submit(service.generate_all, force_regenerate)
    logger.info(
        "[Ops] 全维度简报生成任务已加入后台队列，force_regenerate=%s", force_regenerate
    )
    return IngestResponse(
        status="queued",
        message=f"全维度每日简报生成任务已提交（force_regenerate={force_regenerate}），后台执行中。",
    )


@router.post("/ops/cache/clear-dashboard", response_model=IngestResponse, tags=["Ops"])
async def clear_dashboard_cache(
    _: dict = Depends(RequireAdmin),
    service: DashboardCacheAdminService = Depends(get_dashboard_cache_admin_service),
) -> IngestResponse:
    """手动清除 dashboard Redis 缓存，强制下次请求重新查询数据库。"""
    total_deleted = await service.clear()
    logger.info("[Ops] dashboard cache 清除完成，共删除 %d keys。", total_deleted)
    return IngestResponse(
        status="ok",
        message=f"Dashboard 缓存已清除（共删除 {total_deleted} 个 Redis key），下次请求将重新查询数据库。",
    )
