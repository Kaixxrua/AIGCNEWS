from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date as DateType
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.app.api.dependencies import (
    get_ingestion_task_repository,
    get_mysql_repository,
)
from backend.app.core.auth import RequireAdmin
from backend.app.repositories.mysql_repo import MySQLRepository
from backend.app.repositories.task_repository import IngestionTaskAdminRepository

router = APIRouter()
logger = logging.getLogger(__name__)


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


class ToolWebsiteAddRequest(BaseModel):
    url: str = Field(default="", max_length=1024)


class ToolWebsiteManualAddRequest(BaseModel):
    url: str = Field(default="", max_length=1024)
    title: str = Field(default="", max_length=512)
    description_zh: str = Field(default="", max_length=512)
    category_slug: str = Field(default="other", max_length=64)
    subcategory_slug: str = Field(default="", max_length=64)
    tags: list[str] = Field(default_factory=list, max_length=8)


class ToolWebsiteAddResponse(BaseModel):
    status: str
    message: str
    duplicate: bool = False
    item: Optional[Dict[str, Any]] = None


class ToolWebsiteDeleteResponse(BaseModel):
    status: str
    message: str
    deleted: bool = False
    website_id: int


class ProjectTaxonomyItem(BaseModel):
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


def _mask_api_key(api_key: Optional[str]) -> Optional[str]:
    if not api_key:
        return None
    if len(api_key) <= 8:
        return "****"
    return f"{api_key[:4]}****{api_key[-4:]}"


def _provider_config_response(row: Optional[dict], provider: str) -> ProviderConfigResponse:
    api_key = row.get("api_key") if row else None
    updated_at = row.get("updated_at") if row else None
    return ProviderConfigResponse(
        provider=(row.get("provider") if row else provider),
        base_url=(row.get("base_url") if row else "") or "",
        model_name=(row.get("model_name") if row else "") or "",
        api_key_configured=bool(api_key),
        api_key_masked=_mask_api_key(api_key),
        updated_at=str(updated_at) if updated_at else None,
    )


def _parse_mcp_tools(raw_value: Any) -> list[McpToolSummary]:
    if not raw_value:
        return []
    if isinstance(raw_value, list):
        data = raw_value
    else:
        try:
            data = json.loads(str(raw_value))
        except (TypeError, json.JSONDecodeError):
            data = []
    if not isinstance(data, list):
        return []

    tools: list[McpToolSummary] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        tools.append(McpToolSummary(name=name, description=str(item.get("description") or "").strip()))
    return tools


def _mcp_server_config_response(row: dict) -> McpServerConfigResponse:
    auth_token = row.get("auth_token") or ""
    last_test_at = row.get("last_test_at")
    created_at = row.get("created_at")
    updated_at = row.get("updated_at")
    return McpServerConfigResponse(
        id=int(row.get("id") or 0),
        server_key=(row.get("server_key") or ""),
        display_name=(row.get("display_name") or ""),
        description=(row.get("description") or ""),
        url=(row.get("url") or ""),
        transport=(row.get("transport") or "streamable_http"),
        auth_type=(row.get("auth_type") or "none"),
        auth_token_configured=bool(auth_token),
        auth_token_masked=_mask_api_key(auth_token),
        enabled=bool(row.get("enabled")),
        last_test_status=(row.get("last_test_status") or "unknown"),
        last_test_message=(row.get("last_test_message") or ""),
        last_test_at=str(last_test_at) if last_test_at else None,
        tools=_parse_mcp_tools(row.get("last_tools_json")),
        created_at=str(created_at) if created_at else None,
        updated_at=str(updated_at) if updated_at else None,
    )


def _mcp_payload(request: McpServerConfigRequest) -> dict[str, Any]:
    server_key = request.server_key.strip().lower()
    if not re.fullmatch(r"[a-z0-9_-]{2,64}", server_key):
        raise HTTPException(status_code=400, detail="server_key 仅支持 2-64 位小写字母、数字、下划线和短横线")
    display_name = request.display_name.strip()
    if not display_name:
        raise HTTPException(status_code=400, detail="请填写 MCP Server 名称")

    from backend.app.services.mcp_connection_tester import McpConnectionTestError, validate_mcp_http_url

    try:
        url = validate_mcp_http_url(request.url)
    except McpConnectionTestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "server_key": server_key,
        "display_name": display_name,
        "description": request.description.strip(),
        "url": url,
        "transport": request.transport,
        "auth_type": request.auth_type,
        "auth_token": request.auth_token,
        "clear_auth_token": request.clear_auth_token,
        "enabled": request.enabled,
    }


# ── 后台任务包装 ─────────────────────────────────────────────────────────────


def _bg_smart_ingest(limit: int) -> None:
    """在线程中运行 run_smart_ingestion（同步函数）。"""
    from backend.app.services.ingestion.pipeline import run_smart_ingestion

    run_smart_ingestion(limit=limit)


def _bg_force_ingest(limit: int) -> None:
    """强制触发一次完整 pipeline，不做日期检测。"""
    from backend.app.services.ingestion.pipeline import run_ingestion_pipeline

    run_ingestion_pipeline(limit=limit)


def _bg_ingest_by_date(target_date: str, limit: int) -> None:
    """按指定日期触发采集（在目标日期范围内的数据）。

    pipeline 内部会自行创建 task 记录，此处直接调用即可。
    """
    import re
    from backend.app.services.ingestion.pipeline import run_ingestion_pipeline

    logger.info("[Ops] 开始按日期采集：target_date=%s, limit=%d", target_date, limit)
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", target_date):
        logger.error("[Ops] 日期格式错误：%s", target_date)
        return

    try:
        result = run_ingestion_pipeline(limit=limit, target_date=target_date)
        ingested = result.get("ingested_total", 0) if isinstance(result, dict) else 0
        logger.info("[Ops] 按日期采集完成：date=%s, ingested=%d", target_date, ingested)
    except Exception as exc:
        logger.exception("[Ops] 按日期采集失败：date=%s", target_date)


# 可用的单源名称（与 IngestionOrchestrator 注册的爬虫 source_name 一致）
_VALID_SOURCES = {"arxiv", "github", "news", "producthunt", "hackernews"}


def _bg_single_source_ingest(source_name: str, limit: int) -> None:
    """在线程中运行 run_single_source_pipeline（同步函数）。"""
    from backend.app.services.ingestion.pipeline import run_single_source_pipeline

    run_single_source_pipeline(source_name=source_name, limit=limit)


def _bg_refresh_github_hot(limit: int) -> None:
    """刷新 GitHub 候选池 / Trending / 快照数据并同步当日指标。"""
    from backend.app.services.ingestion.github_hot_service import (
        refresh_github_hot_candidates,
    )
    from backend.app.services.ingestion.github_project_metrics_service import (
        compute_github_daily_metrics,
    )

    refresh_result = refresh_github_hot_candidates(limit=limit)
    compute_github_daily_metrics(
        metric_date=refresh_result.get("date"),
        repo_ids=refresh_result.get("daily_repo_ids") or None,
    )


def _bg_enrich_github_projects(
    limit: int,
    force: bool,
    dry_run: bool,
    retry_failed: bool = True,
    refresh_changed: bool = False,
) -> None:
    """富化 GitHub 项目库分类与中文描述。"""
    from backend.app.services.ingestion.github_project_enricher import (
        enrich_github_projects,
    )

    result = enrich_github_projects(
        limit=limit,
        force=force,
        dry_run=dry_run,
        retry_failed=retry_failed,
        refresh_changed=refresh_changed,
    )
    logger.info("[Ops] GitHub 项目库富化任务完成：%s", result)


def _bg_refresh_github_project_metrics(
    *,
    min_stars: int,
    limit: int,
    metric_date: Optional[str],
    dry_run: bool,
) -> None:
    """刷新 GitHub 项目轻量指标快照并重算每日热度。"""
    from backend.app.services.ingestion.github_project_metrics_service import (
        refresh_and_compute_github_project_metrics,
    )

    result = refresh_and_compute_github_project_metrics(
        min_stars=min_stars,
        limit=limit,
        metric_date=metric_date,
        dry_run=dry_run,
    )
    logger.info("[Ops] GitHub 项目每日指标刷新任务完成：%s", result)


# ── 运行时模型配置 ─────────────────────────────────────────────────────────────


@router.get("/ops/provider-config", response_model=ProviderConfigResponse, tags=["Ops"])
async def get_provider_config(
    _: dict = Depends(RequireAdmin),
) -> ProviderConfigResponse:
    """读取唯一的运行时模型配置。响应只返回密钥是否已配置与脱敏值。"""
    from backend.app.repositories.mysql_repo import MySQLRepository

    db = MySQLRepository()
    row = await asyncio.to_thread(db.get_runtime_provider_setting)
    return _provider_config_response(row, "openai")


@router.put("/ops/provider-config", response_model=ProviderConfigResponse, tags=["Ops"])
async def update_provider_config(
    request: ProviderConfigRequest,
    _: dict = Depends(RequireAdmin),
) -> ProviderConfigResponse:
    """更新唯一的运行时模型配置。api_key 留空时保留原值，clear_api_key=true 时清空。"""
    from backend.app.repositories.mysql_repo import MySQLRepository

    db = MySQLRepository()
    row = await asyncio.to_thread(
        db.upsert_runtime_provider_setting,
        request.provider,
        request.base_url,
        request.api_key,
        request.clear_api_key,
        request.model_name,
    )
    return _provider_config_response(row, request.provider)


# ── MCP Server 配置 ──────────────────────────────────────────────────────────


@router.get("/ops/mcp-servers", response_model=McpServerConfigListResponse, tags=["Ops"])
async def list_mcp_servers(_: dict = Depends(RequireAdmin)) -> McpServerConfigListResponse:
    """列出 MCP Server 配置。响应不会返回明文 Token。"""
    from backend.app.repositories.mysql_repo import MySQLRepository

    db = MySQLRepository()
    rows = await asyncio.to_thread(db.list_mcp_server_configs)
    items = [_mcp_server_config_response(row) for row in rows]
    return McpServerConfigListResponse(items=items, total=len(items))


@router.post("/ops/mcp-servers", response_model=McpServerConfigResponse, tags=["Ops"])
async def create_mcp_server(
    request: McpServerConfigRequest,
    _: dict = Depends(RequireAdmin),
) -> McpServerConfigResponse:
    """创建 MCP Server 配置。auth_token 只写入，不明文返回。"""
    from pymysql.err import IntegrityError

    from backend.app.repositories.mysql_repo import MySQLRepository

    db = MySQLRepository()
    payload = _mcp_payload(request)
    try:
        row = await asyncio.to_thread(db.create_mcp_server_config, payload)
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="server_key 已存在，请换一个标识") from exc
    return _mcp_server_config_response(row)


@router.put("/ops/mcp-servers/{server_id}", response_model=McpServerConfigResponse, tags=["Ops"])
async def update_mcp_server(
    server_id: int,
    request: McpServerConfigRequest,
    _: dict = Depends(RequireAdmin),
) -> McpServerConfigResponse:
    """更新 MCP Server 配置。auth_token 留空时保留，clear_auth_token=true 时清空。"""
    from pymysql.err import IntegrityError

    from backend.app.repositories.mysql_repo import MySQLRepository

    db = MySQLRepository()
    payload = _mcp_payload(request)
    try:
        row = await asyncio.to_thread(db.update_mcp_server_config, server_id, payload)
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="server_key 已存在，请换一个标识") from exc
    if not row:
        raise HTTPException(status_code=404, detail="MCP Server 配置不存在")
    return _mcp_server_config_response(row)


@router.delete("/ops/mcp-servers/{server_id}", response_model=McpServerDeleteResponse, tags=["Ops"])
async def delete_mcp_server(
    server_id: int,
    _: dict = Depends(RequireAdmin),
) -> McpServerDeleteResponse:
    """删除 MCP Server 配置。"""
    from backend.app.repositories.mysql_repo import MySQLRepository

    db = MySQLRepository()
    deleted = await asyncio.to_thread(db.delete_mcp_server_config, server_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="MCP Server 配置不存在")
    return McpServerDeleteResponse(status="succeeded", message="MCP Server 配置已删除。", deleted=True, id=server_id)


@router.post("/ops/mcp-servers/{server_id}/test", response_model=McpServerTestResponse, tags=["Ops"])
async def test_mcp_server(
    server_id: int,
    _: dict = Depends(RequireAdmin),
) -> McpServerTestResponse:
    """测试 MCP Server 连通性，只执行 initialize / tools/list，不调用任意工具。"""
    from backend.app.repositories.mysql_repo import MySQLRepository
    from backend.app.services.mcp_connection_tester import test_mcp_server_connection

    db = MySQLRepository()
    row = await asyncio.to_thread(db.get_mcp_server_config, server_id)
    if not row:
        raise HTTPException(status_code=404, detail="MCP Server 配置不存在")

    result = await asyncio.to_thread(test_mcp_server_connection, row)
    updated = await asyncio.to_thread(db.update_mcp_server_test_result, server_id, result)
    server = _mcp_server_config_response(updated or row)
    return McpServerTestResponse(status=result.get("status", "failed"), message=result.get("message", ""), server=server, tools=server.tools)


# ── 路由 ─────────────────────────────────────────────────────────────────────


@router.post("/ops/ingest", response_model=IngestResponse, tags=["Ops"])
async def trigger_ingest(
    request: IngestRequest,
    background_tasks: BackgroundTasks,
    _: dict = Depends(RequireAdmin),
) -> IngestResponse:
    """
    手动触发数据采集任务。

    - **force=false**（默认）：智能模式，检测落后天数后补录（最多 3 天）。
    - **force=true**：强制模式，直接抓取最新数据，不做日期检测。
    """
    if request.force:
        background_tasks.add_task(_bg_force_ingest, request.limit)
        logger.info("[Ops] 强制采集任务已加入后台队列，limit=%d", request.limit)
        return IngestResponse(
            status="queued",
            message=f"强制采集任务已提交（limit={request.limit}），后台执行中。",
        )
    else:
        background_tasks.add_task(_bg_smart_ingest, request.limit)
        logger.info("[Ops] 智能采集任务已加入后台队列，limit=%d", request.limit)
        return IngestResponse(
            status="queued",
            message=f"智能采集任务已提交（limit={request.limit}），后台执行中。",
        )


@router.post("/ops/ingest-by-date", response_model=IngestResponse, tags=["Ops"])
async def ingest_by_date(
    request: IngestByDateRequest,
    background_tasks: BackgroundTasks,
    _: dict = Depends(RequireAdmin),
) -> IngestResponse:
    """
    按指定日期触发数据采集。

    - **target_date**：目标日期，格式 YYYY-MM-DD。
    - **limit**：每个数据源的抓取数量上限（默认 30）。
    """
    import re

    if not re.match(r"^\d{4}-\d{2}-\d{2}$", request.target_date):
        raise HTTPException(
            status_code=400, detail="target_date 格式错误，应为 YYYY-MM-DD"
        )

    background_tasks.add_task(_bg_ingest_by_date, request.target_date, request.limit)
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
    db: MySQLRepository = Depends(get_mysql_repository),
    task_repository: IngestionTaskAdminRepository = Depends(
        get_ingestion_task_repository
    ),
) -> ClearDataResponse:
    """
    清空所有已存储数据：

    - SQLite documents 表
    - SQLite ingestion_tasks 表
    - Milvus Collection（向量索引）

    ⚠️ 此操作不可逆，请谨慎使用。
    """
    from backend.app.repositories.milvus_repo import MilvusRepository

    # 1. 清空 SQLite
    deleted_docs = await asyncio.to_thread(db.clear_all_documents)
    deleted_tasks = await asyncio.to_thread(task_repository.clear_all_tasks)
    logger.info(
        "[Ops] 已清空 SQLite：documents=%d, tasks=%d", deleted_docs, deleted_tasks
    )

    # 2. 清空 Milvus
    milvus_ok = False
    try:
        milvus_repo = MilvusRepository()
        milvus_ok = await asyncio.to_thread(milvus_repo.drop_collection)
        logger.info("[Ops] Milvus 集合已删除：%s", milvus_ok)
    except Exception as exc:
        logger.warning("[Ops] Milvus 清空失败（可能尚未初始化）：%s", exc)

    return ClearDataResponse(
        status="success",
        message=f"已清空 {deleted_docs} 条文档、{deleted_tasks} 条任务记录，Milvus 集合{'已删除' if milvus_ok else '清空失败（已跳过）'}。",
        deleted_documents=deleted_docs,
        deleted_tasks=deleted_tasks,
        milvus_dropped=milvus_ok,
    )


@router.post("/ops/github-hot/refresh", response_model=IngestResponse, tags=["Ops"])
async def refresh_github_hot(
    limit: int = Query(default=80, ge=20, le=200),
    background_tasks: BackgroundTasks = None,
    _: dict = Depends(RequireAdmin),
) -> IngestResponse:
    """手动刷新 GitHub 热榜候选池与快照。"""
    assert background_tasks is not None
    background_tasks.add_task(_bg_refresh_github_hot, limit)
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
    from backend.app.repositories.mysql_repo import MySQLRepository

    db = MySQLRepository()
    deleted = await asyncio.to_thread(db.delete_tool_website, website_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="工具网站不存在或已删除")
    return ToolWebsiteDeleteResponse(
        status="succeeded",
        message="工具网站已删除。",
        deleted=True,
        website_id=website_id,
    )


@router.get(
    "/ops/project-taxonomy",
    response_model=ProjectTaxonomyResponse,
    tags=["Ops"],
)
async def get_project_taxonomy(_: dict = Depends(RequireAdmin)) -> ProjectTaxonomyResponse:
    """返回管理员手动添加工具网页时可选的分类体系。"""
    from backend.app.services.ingestion.project_taxonomy import WEBSITE_TAXONOMY

    items = []
    for category in WEBSITE_TAXONOMY:
        items.append(
            {
                "slug": category["slug"],
                "name": category["name"],
                "children": [
                    {"slug": child["slug"], "name": child["name"]}
                    for child in category.get("children", [])
                ],
            }
        )
    return ProjectTaxonomyResponse(items=items)


@router.post(
    "/ops/github-projects/enrich",
    response_model=GitHubProjectsEnrichResponse,
    tags=["Ops"],
)
async def enrich_github_project_library(
    request: GitHubProjectsEnrichRequest,
    background_tasks: BackgroundTasks = None,
    _: dict = Depends(RequireAdmin),
) -> GitHubProjectsEnrichResponse:
    """手动触发 GitHub 项目库 AI 分类与中文描述富化。"""
    limit = max(1, min(int(request.limit or 50), 500))
    if request.dry_run:
        from backend.app.services.ingestion.github_project_enricher import (
            enrich_github_projects,
        )

        result = await asyncio.to_thread(
            enrich_github_projects,
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

    assert background_tasks is not None
    background_tasks.add_task(
        _bg_enrich_github_projects,
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
    "/ops/github-projects/recommendations",
    response_model=GitHubProjectRecommendResponse,
    tags=["Ops"],
)
async def recommend_github_project(
    request: GitHubProjectRecommendRequest,
    user: dict = Depends(RequireAdmin),
) -> GitHubProjectRecommendResponse:
    """将 GitHub 项目加入站长推荐。"""
    from backend.app.repositories.mysql_repo import MySQLRepository

    raw_user_id = user.get("user_id") or user.get("id") or user.get("sub") if isinstance(user, dict) else None
    try:
        admin_user_id = int(raw_user_id) if raw_user_id else None
    except (TypeError, ValueError):
        admin_user_id = None

    db = MySQLRepository()
    try:
        result = await asyncio.to_thread(
            db.recommend_github_project,
            repo_id=request.repo_id,
            full_name=request.full_name,
            recommended_by_user_id=admin_user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return GitHubProjectRecommendResponse(status="succeeded", message="已加入站长推荐。", **result)


@router.delete(
    "/ops/github-projects/recommendations",
    response_model=GitHubProjectRecommendResponse,
    tags=["Ops"],
)
async def unrecommend_github_project(
    request: GitHubProjectRecommendRequest,
    _: dict = Depends(RequireAdmin),
) -> GitHubProjectRecommendResponse:
    """取消 GitHub 项目的站长推荐。"""
    from backend.app.repositories.mysql_repo import MySQLRepository

    db = MySQLRepository()
    try:
        result = await asyncio.to_thread(
            db.unrecommend_github_project,
            repo_id=request.repo_id,
            full_name=request.full_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    message = "已取消站长推荐。" if result.get("removed") else "该项目当前不是站长推荐。"
    return GitHubProjectRecommendResponse(status="succeeded", message=message, **result)


@router.get("/ops/github-projects/enrichment-status", tags=["Ops"])
async def github_project_enrichment_status(_: dict = Depends(RequireAdmin)):
    """查看 GitHub 项目库富化进度。"""
    from backend.app.repositories.mysql_repo import MySQLRepository

    db = MySQLRepository()
    return await asyncio.to_thread(db.get_github_project_enrichment_status)


@router.post(
    "/ops/github-projects/metrics/refresh",
    response_model=GitHubProjectsEnrichResponse,
    tags=["Ops"],
)
async def refresh_github_project_metrics(
    request: GitHubProjectsMetricsRequest,
    background_tasks: BackgroundTasks = None,
    _: dict = Depends(RequireAdmin),
) -> GitHubProjectsEnrichResponse:
    """手动刷新 GitHub 项目每日快照，并在非 dry-run 时重算热度分。"""
    min_stars = max(0, int(request.min_stars or 0))
    limit = max(0, min(int(request.limit or 0), 20000))
    if request.dry_run:
        from backend.app.services.ingestion.github_project_metrics_service import (
            refresh_and_compute_github_project_metrics,
        )

        result = await asyncio.to_thread(
            refresh_and_compute_github_project_metrics,
            min_stars=min_stars,
            limit=limit,
            metric_date=request.metric_date,
            dry_run=True,
        )
        return GitHubProjectsEnrichResponse(status="dry_run", message="GitHub 项目每日指标 dry-run 完成。", result=result)

    assert background_tasks is not None
    background_tasks.add_task(
        _bg_refresh_github_project_metrics,
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
) -> GitHubProjectsEnrichResponse:
    """基于连续快照或同日 Trending 日榜值，重算某天增长和热度分。"""
    from backend.app.services.ingestion.github_project_metrics_service import compute_github_daily_metrics

    result = await asyncio.to_thread(
        compute_github_daily_metrics,
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
    background_tasks: BackgroundTasks = None,  # type: ignore[assignment]
    _: dict = Depends(RequireAdmin),
) -> IngestResponse:
    """
    按数据源独立采集（单源模式）。

    前端监测页面可为每个数据源提供独立的"采集"按钮，
    调用此接口时仅采集指定源，不影响其他源。

    - **source**：数据源名称（arxiv / github / news / producthunt / hackernews）
    - **limit**：每源最多抓取条数（默认 20）
    """
    source_lower = source.strip().lower()
    if source_lower not in _VALID_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=f"未知数据源 '{source}'，可选值：{', '.join(sorted(_VALID_SOURCES))}",
        )

    assert background_tasks is not None
    background_tasks.add_task(_bg_single_source_ingest, source_lower, limit)
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
        "sources": sorted(_VALID_SOURCES),
    }


@router.get("/ops/scheduler/status", tags=["Ops"])
async def scheduler_status(_: dict = Depends(RequireAdmin)):
    """查询 APScheduler 当前状态与已注册任务列表。"""
    from backend.app.core.scheduler import get_scheduler

    scheduler = get_scheduler()
    jobs = []
    for job in scheduler.get_jobs():
        next_run = job.next_run_time.isoformat() if job.next_run_time else None
        jobs.append(
            {
                "id": job.id,
                "name": job.name,
                "next_run_time": next_run,
                "trigger": str(job.trigger),
            }
        )
    return {
        "running": scheduler.running,
        "jobs": jobs,
        "job_count": len(jobs),
    }


@router.post("/ops/scheduler/trigger", tags=["Ops"])
async def trigger_scheduled_job(
    job_id: str = Query(default="daily_smart_ingestion"),
    _: dict = Depends(RequireAdmin),
):
    """立即触发指定的定时任务（用于调试）。"""
    from backend.app.core.scheduler import get_scheduler

    scheduler = get_scheduler()
    job = scheduler.get_job(job_id)
    if job is None:
        return {"status": "error", "message": f"Job '{job_id}' 不存在。"}

    job.modify(next_run_time=None)
    scheduler.wakeup()
    return {"status": "triggered", "message": f"Job '{job_id}' 已触发执行。"}


# ── 每日简报生成 ─────────────────────────────────────────────────────────────

_BRIEFING_TASKS = [
    {"source": "all", "period": "daily"},
    {"source": "arxiv", "period": "daily"},
    {"source": "github", "period": "daily"},
    {"source": "news", "period": "daily"},
    {"source": "producthunt", "period": "daily"},
    {"source": "hackernews", "period": "daily"},
]


async def _bg_generate_all_briefings(force_regenerate: bool) -> None:
    """后台生成全维度每日简报（与 scheduler 中的逻辑一致）。"""
    from backend.app.services.briefing.daily_briefing import DailyBriefingService

    success = 0
    for task in _BRIEFING_TASKS:
        source = task["source"]
        period = task["period"]
        try:
            service = DailyBriefingService()
            async for _ in service.stream_generate(
                target_date=None,
                source=source,
                period=period,
                force_regenerate=force_regenerate,
            ):
                pass
            success += 1
            logger.info("[Ops] 简报生成完成: source=%s period=%s", source, period)
        except Exception as exc:
            logger.error(
                "[Ops] 简报生成失败: source=%s period=%s error=%s",
                source,
                period,
                exc,
                exc_info=True,
            )
    logger.info("[Ops] 全维度简报生成完毕，%d/%d 成功。", success, len(_BRIEFING_TASKS))


def _run_briefings_sync(force_regenerate: bool) -> None:
    """在线程中运行异步简报生成。"""
    import asyncio

    asyncio.run(_bg_generate_all_briefings(force_regenerate))


@router.post("/ops/briefing/generate-all", response_model=IngestResponse, tags=["Ops"])
async def generate_all_briefings(
    force_regenerate: bool = Query(
        default=True, description="是否强制重新生成（忽略缓存）"
    ),
    background_tasks: BackgroundTasks = None,  # type: ignore[assignment]
    _: dict = Depends(RequireAdmin),
) -> IngestResponse:
    """
    手动触发全维度每日简报生成。

    后台依次生成 all / arxiv / github / news / producthunt / hackernews
    六个维度的今日简报，并持久化到数据库。

    - **force_regenerate=true**（默认）：强制重新生成，忽略已有缓存。
    - **force_regenerate=false**：已生成过则跳过，避免重复消耗 LLM。
    """
    assert background_tasks is not None
    background_tasks.add_task(_run_briefings_sync, force_regenerate)
    logger.info(
        "[Ops] 全维度简报生成任务已加入后台队列，force_regenerate=%s", force_regenerate
    )
    return IngestResponse(
        status="queued",
        message=f"全维度每日简报生成任务已提交（force_regenerate={force_regenerate}），后台执行中。",
    )


@router.post("/ops/cache/clear-dashboard", response_model=IngestResponse, tags=["Ops"])
async def clear_dashboard_cache(_: dict = Depends(RequireAdmin)) -> IngestResponse:
    """手动清除 dashboard Redis 缓存，强制下次请求重新查询数据库。

    使用多种 pattern 兜底，确保 aigc-cache:dashboard:* 等所有相关 key 被删除。
    """
    from fastapi_cache import FastAPICache
    from redis.asyncio import Redis as AsyncRedis

    from backend.app.core.config import settings

    redis_client = AsyncRedis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        password=settings.redis_password or None,
        decode_responses=False,
    )
    total_deleted = 0
    try:
        _raw_prefix = getattr(FastAPICache, "_prefix", "") or ""
        patterns = list(
            dict.fromkeys(
                [
                    "aigc-cache:dashboard:*",
                    f"{_raw_prefix}dashboard:*",
                    "dashboard:*",
                    "*:dashboard:*",
                ]
            )
        )
        for pattern in patterns:
            keys = await redis_client.keys(pattern)
            if keys:
                await redis_client.delete(*keys)
                total_deleted += len(keys)
                logger.info(
                    "[Ops] cache clear: pattern=%r 删除 %d keys", pattern, len(keys)
                )
    finally:
        close_method = getattr(redis_client, "aclose", None)
        if close_method:
            await close_method()
        else:
            await redis_client.close()

    logger.info("[Ops] dashboard cache 清除完成，共删除 %d keys。", total_deleted)
    return IngestResponse(
        status="ok",
        message=f"Dashboard 缓存已清除（共删除 {total_deleted} 个 Redis key），下次请求将重新查询数据库。",
    )
