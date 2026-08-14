from __future__ import annotations

import asyncio
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend.app.api import (
    routes_ops_email_pool,
    routes_ops_github,
    routes_ops_mcp,
    routes_ops_site,
    routes_ops_smtp,
    routes_ops_x,
)
from backend.app.api.dependencies import (
    get_briefing_admin_service,
    get_dashboard_cache_admin_service,
    get_data_cleanup_admin_service,
    get_document_repository,
    get_ingestion_admin_service,
    get_operations_runtime,
    get_ops_diagnostics_service,
    get_runtime_provider_admin_service,
    get_scheduler_admin_service,
    get_scheduler_config_admin_service,
)
from backend.app.core.auth import RequireAdmin
from backend.app.core.operations import ApplicationOperationsRuntime
from backend.app.models.schema_ops import (
    BulkDocumentDeleteRequest,
    BulkDocumentDeleteResponse,
    ClearDataResponse,
    DocumentDeleteResponse,
    IngestByDateRequest,
    IngestRequest,
    IngestResponse,
    ProjectTaxonomyResponse,
    ProviderConfigRequest,
    ProviderConfigResponse,
    ProviderConfigTestResponse,
    SchedulerConfigListResponse,
    SchedulerConfigUpdateRequest,
    SchedulerConfigUpdateResponse,
    SchedulerJobConfigItem,
)
from backend.app.models.schema_projects import (
    ToolWebsiteAddRequest,
    ToolWebsiteAddResponse,
    ToolWebsiteDeleteResponse,
    ToolWebsiteManualAddRequest,
)
from backend.app.repositories.document_repository import DocumentRepository
from backend.app.services.briefing_admin import BriefingAdminService
from backend.app.services.dashboard_cache_admin import DashboardCacheAdminService
from backend.app.services.data_cleanup_admin import DataCleanupAdminService
from backend.app.services.ingestion.cache_invalidation import clear_dashboard_cache_safely
from backend.app.services.ingestion_admin import VALID_SOURCES, IngestionAdminService
from backend.app.services.ops_diagnostics import OpsDiagnosticsService
from backend.app.services.runtime_provider.admin_service import (
    InvalidProviderBaseUrl,
    RuntimeProviderAdminService,
)
from backend.app.services.scheduler_admin import SchedulerAdminService
from backend.app.services.scheduler_config_admin import SchedulerConfigAdminService

router = APIRouter()
logger = logging.getLogger(__name__)


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
    try:
        projection = await service.update_config(request.model_dump())
    except InvalidProviderBaseUrl as exc:
        # SSRF 防护（渗透审计 SSRF-2）：Base URL 必须指向公网 http/https 地址
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ProviderConfigResponse.model_validate(projection, from_attributes=True)


@router.post(
    "/ops/provider-config/test",
    response_model=ProviderConfigTestResponse,
    tags=["Ops"],
)
async def test_provider_config(
    _: dict = Depends(RequireAdmin),
    service: RuntimeProviderAdminService = Depends(
        get_runtime_provider_admin_service
    ),
) -> ProviderConfigTestResponse:
    """用当前保存的模型配置发起一次最小调用，验证 Base URL/Key/模型连通性。"""
    result = await service.test_connection()
    return ProviderConfigTestResponse(**result)


# ── 按资源域拆分的子路由（mcp-servers / x-* / github-* / smtp）────────────────

router.include_router(routes_ops_mcp.router)
router.include_router(routes_ops_x.router)
router.include_router(routes_ops_smtp.router)
router.include_router(routes_ops_email_pool.router)
router.include_router(routes_ops_site.router)


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

    - PostgreSQL documents 表
    - PostgreSQL ingestion_tasks 表
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
    """批量删除文档及其排行快照（单事务原子）；返回实际删除与未找到的计数。"""
    requested_ids = list(dict.fromkeys(request.doc_ids))
    deleted_ids = await asyncio.to_thread(documents.delete_documents, requested_ids)
    not_found_count = len(requested_ids) - len(deleted_ids)
    await clear_dashboard_cache_safely()
    return BulkDocumentDeleteResponse(
        status="success",
        message=f"已删除 {len(deleted_ids)} 条文档，{not_found_count} 条未找到",
        doc_ids=deleted_ids,
        deleted_count=len(deleted_ids),
        not_found_count=not_found_count,
    )


# ── GitHub 热榜与项目库 ──────────────────────────────────────────────────────

router.include_router(routes_ops_github.router)


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
    raw_request: Request,
    _: dict = Depends(RequireAdmin),
    service: SchedulerConfigAdminService = Depends(get_scheduler_config_admin_service),
) -> SchedulerConfigUpdateResponse:
    """更新单个定时任务的时间窗口与轮询间隔。

    保存后立即应用到运行中的调度器；调度器未运行时，配置在下次启动时生效。
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

    applied = False
    runtime = getattr(raw_request.app.state, "scheduler_runtime", None)
    if runtime is not None:
        try:
            applied = bool(runtime.apply_config_update(projection))
        except Exception as exc:
            logger.warning(
                "[Ops] 调度器配置即时应用失败（已持久化，重启后生效）: %s", exc
            )

    message = (
        f"定时任务 {job_id} 配置已保存并即时生效。"
        if applied
        else f"定时任务 {job_id} 配置已保存，重启后生效。"
    )
    return SchedulerConfigUpdateResponse(
        status="success",
        message=message,
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
