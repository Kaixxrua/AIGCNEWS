from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.app.api.dependencies import (
    get_github_project_admin_service,
    get_github_project_crawl_admin_service,
    get_github_project_recommendation_admin_service,
    get_operations_runtime,
    get_runtime_provider_admin_service,
)
from backend.app.core.auth import RequireAdmin
from backend.app.core.operations import ApplicationOperationsRuntime
from backend.app.models.schema_ops import (
    EnrichmentConfigRequest,
    EnrichmentConfigResponse,
    GitHubProjectRecommendRequest,
    GitHubProjectRecommendResponse,
    GitHubProjectsCrawlRequest,
    GitHubProjectsCrawlResponse,
    GitHubProjectsCrawlStatusResponse,
    GitHubProjectsEnrichCancelResponse,
    GitHubProjectsEnrichRequest,
    GitHubProjectsEnrichResponse,
    GitHubProjectsMetricsRecomputeRequest,
    GitHubProjectsMetricsRequest,
    IngestResponse,
)
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
from backend.app.services.runtime_provider.admin_service import (
    RuntimeProviderAdminService,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ── GitHub 热榜 ──────────────────────────────────────────────────────────────


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


# ── GitHub 项目库 ────────────────────────────────────────────────────────────


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
            concurrency=request.concurrency,
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
        request.concurrency,
    )
    logger.info(
        "[Ops] GitHub 项目库富化任务已加入后台队列，limit=%d force=%s retry_failed=%s refresh_changed=%s concurrency=%d",
        limit,
        request.force,
        request.retry_failed,
        request.refresh_changed,
        request.concurrency,
    )
    return GitHubProjectsEnrichResponse(
        status="queued",
        message=f"GitHub 项目库富化任务已提交（limit={limit}，并发={request.concurrency}），后台执行中。",
    )


@router.post(
    "/ops/github-projects/enrich-cancel",
    response_model=GitHubProjectsEnrichCancelResponse,
    tags=["Ops"],
)
async def cancel_github_project_enrichment(
    _: dict = Depends(RequireAdmin),
) -> GitHubProjectsEnrichCancelResponse:
    """协作式终止富化批处理：进行中的项目跑完即停，未启动的保持待处理、不记失败。"""
    from backend.app.services.ingestion.github_project_enricher import (
        request_github_enrichment_cancel,
    )

    if request_github_enrichment_cancel():
        logger.info("[Ops] 已请求终止 GitHub 项目库富化批处理")
        return GitHubProjectsEnrichCancelResponse(
            status="cancelling",
            message="已请求终止富化：进行中的项目会跑完，剩余项目保持待处理。",
        )
    return GitHubProjectsEnrichCancelResponse(
        status="not_running",
        message="当前没有正在运行的富化任务。",
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


@router.get("/ops/github-projects/enrichment-project-pages", tags=["Ops"])
async def github_project_enrichment_project_pages(
    unprocessable_page: int = Query(default=1, ge=1),
    retained_page: int = Query(default=1, ge=1),
    page_size: int = Query(default=15, ge=1, le=100),
    _: dict = Depends(RequireAdmin),
    service: GitHubProjectRecommendationAdminService = Depends(
        get_github_project_recommendation_admin_service
    ),
):
    """分页查看无法处理及已退出执行队列的 GitHub 项目。"""
    return await service.get_enrichment_pages(
        unprocessable_page=unprocessable_page,
        retained_page=retained_page,
        page_size=page_size,
    )


@router.get(
    "/ops/github-projects/enrichment-config",
    response_model=EnrichmentConfigResponse,
    tags=["Ops"],
)
async def get_github_enrichment_config(
    _: dict = Depends(RequireAdmin),
    service: RuntimeProviderAdminService = Depends(
        get_runtime_provider_admin_service
    ),
) -> EnrichmentConfigResponse:
    """读取富化任务专用推理强度；空串表示跟随模型服务配置。"""
    projection = await service.get_enrichment_config()
    return EnrichmentConfigResponse.model_validate(projection)


@router.put(
    "/ops/github-projects/enrichment-config",
    response_model=EnrichmentConfigResponse,
    tags=["Ops"],
)
async def update_github_enrichment_config(
    request: EnrichmentConfigRequest,
    _: dict = Depends(RequireAdmin),
    service: RuntimeProviderAdminService = Depends(
        get_runtime_provider_admin_service
    ),
) -> EnrichmentConfigResponse:
    """更新富化任务专用推理强度；不影响模型服务配置，下一批富化生效。"""
    projection = await service.update_enrichment_config(request.model_dump())
    return EnrichmentConfigResponse.model_validate(projection)


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


@router.post(
    "/ops/github-projects/metrics/backfill-suspicion",
    response_model=GitHubProjectsEnrichResponse,
    tags=["Ops"],
)
async def backfill_github_growth_suspicion(
    days: int = 30,
    min_stars: int = 500,
    _: dict = Depends(RequireAdmin),
    service: GitHubProjectAdminService = Depends(get_github_project_admin_service),
) -> GitHubProjectsEnrichResponse:
    """回放近 N 天反作弊打标（一二层信号 + 跨渠道佐证），并按当前算法重算 hot_score。"""
    result = await asyncio.to_thread(
        service.backfill_suspicion,
        days=max(1, min(int(days or 30), 90)),
        min_stars=max(0, int(min_stars or 0)),
    )
    return GitHubProjectsEnrichResponse(status="succeeded", message="GitHub 反作弊打标回放完成。", result=result)
