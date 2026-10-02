from __future__ import annotations

import re
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response

from backend.app.api.dependencies import (
    get_personal_projects_service,
    get_project_adoption_service,
    get_project_catalog_query_service,
    get_project_trends_service,
)
from backend.app.core.auth import OptionalUser, RequireUser, extract_user_id
from backend.app.models.schema_projects import (
    GitHubProjectCategoriesResponse,
    GitHubProjectSort,
    GitHubProjectsResponse,
    GitHubProjectTagsResponse,
    GitHubProjectTrendsResponse,
    PersonalWebsiteQuotaResponse,
    ProjectAdoptionReceipt,
    ProjectAdoptionRequest,
    ProjectAdoptionResponse,
    ProjectAdoptionStats,
    ProjectFavoriteRequest,
    ProjectFavoriteResponse,
    ProjectScope,
    ProjectSource,
    ProjectTaxonomyResponse,
    PublicProjectSort,
    ToolWebsiteAddRequest,
    ToolWebsiteAddResponse,
    ToolWebsiteDeleteResponse,
    ToolWebsiteManualAddRequest,
    ToolWebsiteUpdateRequest,
    ToolWebsiteUpdateResponse,
)
from backend.app.services.personal_projects import (
    InvalidPersonalProjectRequest,
    PersonalProjectNotFound,
    PersonalProjectsService,
    PersonalWebsiteOperationFailed,
    PersonalWebsiteQuotaExceeded,
    WebsiteContentBlockedError,
)
from backend.app.services.project_adoptions import ProjectAdoptionService
from backend.app.services.project_catalog.query_service import (
    PUBLIC_PROJECT_MIN_STARS,
    ProjectCatalogQueryService,
)
from backend.app.services.project_catalog.trends_service import (
    TRENDS_MAX_REPOS,
    ProjectTrendsService,
)

router = APIRouter()

_REPO_ID_PATTERN = re.compile(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+")


def get_github_logo_repository():
    from backend.app.repositories.postgres_github_logo_repository import PostgresGitHubLogoRepository

    return PostgresGitHubLogoRepository()


@router.get("/projects/github/logo/{owner}/{repo}")
def github_project_logo(
    owner: str, repo: str, request: Request,
    repository: Any = Depends(get_github_logo_repository),
) -> Response:
    if not _REPO_ID_PATTERN.fullmatch(f"{owner}/{repo}"):
        raise HTTPException(404, "Logo not found")
    row = repository.get(f"{owner}/{repo}")
    if not row:
        raise HTTPException(404, "Logo not found")
    etag = f'"{row["sha256"]}"'
    headers = {
        "ETag": etag, "Cache-Control": "public, max-age=3600",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; style-src 'none'; sandbox",
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=bytes(row["content"]), media_type=row["content_type"], headers=headers)


@router.get(
    "/projects/github/trends",
    response_model=GitHubProjectTrendsResponse,
    tags=["Projects"],
)
async def github_project_trends(
    response: Response,
    repos: str = Query(..., min_length=3, max_length=4000),
    days: int = Query(default=14, ge=7, le=30),
    ranks: bool = Query(default=False),
    trends: ProjectTrendsService = Depends(get_project_trends_service),
) -> GitHubProjectTrendsResponse:
    """项目库榜单行情：每个仓库近 days 天的星标与日增；ranks=true 时附今日热榜的昨日名次。

    repos 是逗号分隔的 owner/repo，一次最多一页榜单（TRENDS_MAX_REPOS）。只读公开指标，可缓存两分钟。
    """
    repo_ids = list(dict.fromkeys(part.strip() for part in repos.split(",") if part.strip()))
    if not repo_ids or len(repo_ids) > TRENDS_MAX_REPOS or not all(
        _REPO_ID_PATTERN.fullmatch(repo_id) for repo_id in repo_ids
    ):
        raise HTTPException(
            status_code=422,
            detail=f"repos 须为 1–{TRENDS_MAX_REPOS} 个逗号分隔的 owner/repo",
        )
    result = await trends.trends(repo_ids, days=days, with_ranks=ranks)
    response.headers["Cache-Control"] = "public, max-age=120"
    return GitHubProjectTrendsResponse(**result)


def _membership_inputs(user: dict[str, Any]) -> dict[str, str]:
    return {
        "membership_tier": str(user.get("membership_tier") or "free"),
        "role": str(user.get("role") or "user"),
    }


def _raise_website_quota_exceeded(exc: PersonalWebsiteQuotaExceeded) -> None:
    quota = dict(exc.quota)
    retry_after = 1
    reset_at = quota.get("reset_at")
    if reset_at:
        from datetime import datetime, timezone

        try:
            reset = datetime.fromisoformat(str(reset_at))
            if reset.tzinfo is None:
                reset = reset.replace(tzinfo=timezone.utc)
            retry_after = max(1, int((reset - datetime.now(timezone.utc)).total_seconds()))
        except ValueError:
            pass
    raise HTTPException(
        status_code=429,
        detail={
            "error": "personal_website_quota_exceeded",
            "message": str(exc),
            **quota,
            "retry_after": retry_after,
        },
        headers={"Retry-After": str(retry_after)},
    ) from exc


def _favorite_request_from_inputs(
    request: ProjectFavoriteRequest | None,
    *,
    source: str | None = None,
    repo_id: str | None = None,
    website_id: str | None = None,
) -> ProjectFavoriteRequest:
    if request is not None:
        return request
    clean_source = (source or "").strip().lower()
    if clean_source not in {"github", "website"}:
        raise ValueError("source 只能是 github 或 website")
    return ProjectFavoriteRequest(source=clean_source, repo_id=repo_id, website_id=website_id)


def _categories_response(result: dict[str, Any], *, min_stars: int, source: str) -> GitHubProjectCategoriesResponse:
    total = int(result.get("total") or 0)
    today_count = int(result.get("today_count") or 0)
    recommended_count = int(result.get("recommended_count") or 0)
    category_items = result.get("items") or []
    today_label = "今日添加" if source == "website" else "今日暴涨"
    scope_items = [
        {"slug": "all", "name": "全部", "name_zh": "全部", "name_en": "All", "count": total, "kind": "scope", "scope": "all", "children": []},
    ]
    if source != "website":
        scope_items.append({"slug": "recommended", "name": "站长推荐", "name_zh": "站长推荐", "name_en": "Recommended", "count": recommended_count, "kind": "scope", "scope": "recommended", "children": []})
    scope_items.append({"slug": "today", "name": today_label, "name_zh": today_label, "name_en": "Added Today" if source == "website" else "Trending Today", "count": today_count, "kind": "scope", "scope": "today", "children": []})
    return GitHubProjectCategoriesResponse(
        items=[
            *scope_items,
            *category_items,
        ],
        total=total,
        today_count=today_count,
        recommended_count=recommended_count,
        min_stars=min_stars,
        source=source,
    )


def _projects_response(
    result: dict[str, Any],
    *,
    min_stars: int,
    source: str,
    scope: str,
    category: str,
    subcategory: str,
    q: str,
    sort: str,
) -> GitHubProjectsResponse:
    return GitHubProjectsResponse(
        items=result["items"],
        total=int(result["total"]),
        page=int(result["page"]),
        page_size=int(result["page_size"]),
        has_next=int(result["page"]) * int(result["page_size"]) < int(result["total"]),
        min_stars=min_stars,
        scope=scope,
        category=category,
        subcategory=subcategory,
        q=q,
        sort=sort,
        source=source,
    )


def _taxonomy_items() -> list[dict[str, Any]]:
    from backend.app.domain.project_taxonomy import WEBSITE_TAXONOMY

    return [
        {
            "slug": category["slug"],
            "name": category["name_zh"],
            "name_zh": category["name_zh"],
            "name_en": category["name_en"],
            "children": [
                {"slug": child["slug"], "name": child["name_zh"], "name_zh": child["name_zh"], "name_en": child["name_en"]}
                for child in category.get("children", [])
            ],
        }
        for category in WEBSITE_TAXONOMY
    ]


@router.get("/projects", response_model=GitHubProjectsResponse, tags=["Projects"])
async def list_projects(
    source: ProjectSource = Query(default="all"),
    scope: ProjectScope = Query(default="all"),
    category: str = Query(default="", max_length=64),
    subcategory: str = Query(default="", max_length=64),
    q: str = Query(default="", max_length=120),
    language: str = Query(default="", max_length=64),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=60),
    sort: PublicProjectSort | None = Query(default=None),
    user: dict[str, Any] | None = Depends(OptionalUser),
    catalog: ProjectCatalogQueryService = Depends(get_project_catalog_query_service),
) -> GitHubProjectsResponse:
    """公共 AI 项目库：只展示 GitHub 项目；网页收藏只存在于个人收藏夹。"""
    user_id = extract_user_id(user)
    if source == "website":
        raise HTTPException(status_code=404, detail="网页收藏仅在个人收藏夹中可见")
    clean_category = category.strip()
    clean_subcategory = subcategory.strip()
    clean_q = q.strip()
    page_result = await catalog.list_public_projects(
        scope=scope,
        category=clean_category,
        subcategory=clean_subcategory,
        q=clean_q,
        language=language.strip(),
        page=page,
        page_size=page_size,
        sort=sort,
        user_id=user_id,
    )
    return _projects_response(
        page_result.result,
        min_stars=catalog.min_stars,
        source=source,
        scope=scope,
        category=clean_category,
        subcategory=clean_subcategory,
        q=clean_q,
        sort=page_result.effective_sort,
    )


@router.get(
    "/projects/categories",
    response_model=GitHubProjectCategoriesResponse,
    tags=["Projects"],
)
async def list_project_categories(
    source: ProjectSource = Query(default="all"),
    user: dict[str, Any] | None = Depends(OptionalUser),
    catalog: ProjectCatalogQueryService = Depends(get_project_catalog_query_service),
) -> GitHubProjectCategoriesResponse:
    """返回公共 GitHub 项目库分类及数量；个人网页分类使用 /projects/me/categories。"""
    if source == "website":
        raise HTTPException(status_code=404, detail="网页收藏分类仅在个人收藏夹中可见")
    result = await catalog.get_public_categories()
    return _categories_response(result, min_stars=catalog.min_stars, source=source)


@router.get("/projects/me/collection", response_model=GitHubProjectsResponse, tags=["Projects"])
async def list_my_project_collection(
    source: ProjectSource = Query(default="all"),
    scope: ProjectScope = Query(default="all"),
    category: str = Query(default="", max_length=64),
    subcategory: str = Query(default="", max_length=64),
    q: str = Query(default="", max_length=120),
    language: str = Query(default="", max_length=64),
    tag: str = Query(default="", max_length=64),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=60),
    sort: GitHubProjectSort = Query(default="recent"),
    user: dict[str, Any] = Depends(RequireUser),
    service: PersonalProjectsService = Depends(get_personal_projects_service),
) -> GitHubProjectsResponse:
    """当前登录用户的个人收藏夹；默认只返回 GitHub 项目收藏，source=website 返回个人网页。"""
    user_id = extract_user_id(user)
    if not user_id:
        raise HTTPException(status_code=401, detail="用户身份无效")
    min_stars = PUBLIC_PROJECT_MIN_STARS
    clean_category = category.strip()
    clean_subcategory = subcategory.strip()
    clean_q = q.strip()
    clean_tag = tag.strip()
    result = await service.list_collection(
        user_id=user_id,
        source="github" if source == "all" else source,
        scope=scope,
        category=clean_category,
        subcategory=clean_subcategory,
        q=clean_q,
        language=language.strip(),
        tag=clean_tag,
        page=page,
        page_size=page_size,
        sort=sort,
        min_stars=min_stars,
        enriched_only=True,
    )
    return _projects_response(
        result,
        min_stars=min_stars,
        source=source,
        scope=scope,
        category=clean_category,
        subcategory=clean_subcategory,
        q=clean_q,
        sort=sort,
    )


@router.get("/projects/me/categories", response_model=GitHubProjectCategoriesResponse, tags=["Projects"])
async def list_my_project_categories(
    source: ProjectSource = Query(default="all"),
    user: dict[str, Any] = Depends(RequireUser),
    service: PersonalProjectsService = Depends(get_personal_projects_service),
) -> GitHubProjectCategoriesResponse:
    """当前登录用户个人收藏夹分类；默认只统计 GitHub 收藏，source=website 统计个人网页。"""
    user_id = extract_user_id(user)
    if not user_id:
        raise HTTPException(status_code=401, detail="用户身份无效")
    min_stars = PUBLIC_PROJECT_MIN_STARS
    result = await service.get_categories(
        user_id=user_id,
        source="github" if source == "all" else source,
        min_stars=min_stars,
        enriched_only=True,
    )
    return _categories_response(result, min_stars=min_stars, source=source)


@router.get("/projects/me/tags", response_model=GitHubProjectTagsResponse, tags=["Projects"])
async def list_my_project_tags(
    source: ProjectSource = Query(default="github"),
    user: dict[str, Any] = Depends(RequireUser),
    service: PersonalProjectsService = Depends(get_personal_projects_service),
) -> GitHubProjectTagsResponse:
    """当前登录用户个人收藏夹真实标签；不返回预制分类或默认标签。"""
    user_id = extract_user_id(user)
    if not user_id:
        raise HTTPException(status_code=401, detail="用户身份无效")
    effective_source = "website" if source == "website" else "github"
    result = await service.get_tags(
        user_id=user_id,
        source=effective_source,
        min_stars=PUBLIC_PROJECT_MIN_STARS,
        enriched_only=True,
    )
    return GitHubProjectTagsResponse(
        items=result.get("items") or [],
        total=int(result.get("total") or 0),
        source=effective_source,
    )


@router.post("/projects/me/favorites", response_model=ProjectFavoriteResponse, tags=["Projects"])
async def favorite_project(
    request: ProjectFavoriteRequest,
    user: dict[str, Any] = Depends(RequireUser),
    service: PersonalProjectsService = Depends(get_personal_projects_service),
) -> ProjectFavoriteResponse:
    """收藏 GitHub 项目或工具网站到当前用户收藏夹。"""
    user_id = extract_user_id(user)
    if not user_id:
        raise HTTPException(status_code=401, detail="用户身份无效")
    try:
        result = await service.add_favorite(
            user_id=user_id,
            source=request.source,
            repo_id=request.repo_id,
            website_id=request.website_id,
            **_membership_inputs(user),
        )
    except PersonalWebsiteQuotaExceeded as exc:
        _raise_website_quota_exceeded(exc)
    except InvalidPersonalProjectRequest as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PersonalProjectNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ProjectFavoriteResponse(status="succeeded", message="已加入我的收藏。", **result)


@router.delete("/projects/me/favorites", response_model=ProjectFavoriteResponse, tags=["Projects"])
async def unfavorite_project(
    request: ProjectFavoriteRequest | None = Body(default=None),
    source: Literal["github", "website"] | None = Query(default=None),
    repo_id: str | None = Query(default=None),
    website_id: str | None = Query(default=None),
    user: dict[str, Any] = Depends(RequireUser),
    service: PersonalProjectsService = Depends(get_personal_projects_service),
) -> ProjectFavoriteResponse:
    """从当前用户收藏夹取消收藏 GitHub 项目或工具网站。"""
    user_id = extract_user_id(user)
    if not user_id:
        raise HTTPException(status_code=401, detail="用户身份无效")
    try:
        favorite_request = _favorite_request_from_inputs(
            request,
            source=source,
            repo_id=repo_id,
            website_id=website_id,
        )
        deleted = await service.remove_favorite(
            user_id=user_id,
            source=favorite_request.source,
            repo_id=favorite_request.repo_id,
            website_id=favorite_request.website_id,
        )
    except (ValueError, InvalidPersonalProjectRequest) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PersonalProjectNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ProjectFavoriteResponse(
        status="succeeded",
        message="已取消收藏。" if deleted else "此前未收藏。",
        source=favorite_request.source,
        repo_id=favorite_request.repo_id if favorite_request.source == "github" else None,
        website_id=favorite_request.website_id if favorite_request.source == "website" else None,
        is_favorited=False,
        deleted=deleted,
    )


@router.get(
    "/projects/me/tool-websites/quota",
    response_model=PersonalWebsiteQuotaResponse,
    tags=["Projects"],
)
async def get_my_tool_website_quota(
    user: dict[str, Any] = Depends(RequireUser),
    service: PersonalProjectsService = Depends(get_personal_projects_service),
) -> PersonalWebsiteQuotaResponse:
    user_id = extract_user_id(user)
    if not user_id:
        raise HTTPException(status_code=401, detail="用户身份无效")
    quota = await service.get_website_quota(
        user_id=user_id,
        **_membership_inputs(user),
    )
    return PersonalWebsiteQuotaResponse(**quota)


@router.post("/projects/me/tool-websites", response_model=ToolWebsiteAddResponse, tags=["Projects"])
async def add_my_tool_website(
    request: ToolWebsiteAddRequest,
    user: dict[str, Any] = Depends(RequireUser),
    service: PersonalProjectsService = Depends(get_personal_projects_service),
) -> ToolWebsiteAddResponse:
    """普通用户自动添加工具网站到自己的收藏夹。"""
    user_id = extract_user_id(user)
    if not user_id:
        raise HTTPException(status_code=401, detail="用户身份无效")
    try:
        result = await service.add_tool_website(
            user_id=user_id,
            url=request.url,
            **_membership_inputs(user),
        )
    except PersonalWebsiteQuotaExceeded as exc:
        _raise_website_quota_exceeded(exc)
    except WebsiteContentBlockedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except InvalidPersonalProjectRequest as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PersonalWebsiteOperationFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ToolWebsiteAddResponse(**result)


@router.post("/projects/me/tool-websites/manual", response_model=ToolWebsiteAddResponse, tags=["Projects"])
async def add_my_tool_website_manual(
    request: ToolWebsiteManualAddRequest,
    user: dict[str, Any] = Depends(RequireUser),
    service: PersonalProjectsService = Depends(get_personal_projects_service),
) -> ToolWebsiteAddResponse:
    """普通用户手动添加工具网站到自己的收藏夹。"""
    user_id = extract_user_id(user)
    if not user_id:
        raise HTTPException(status_code=401, detail="用户身份无效")
    try:
        result = await service.add_tool_website_manual(
            user_id=user_id,
            url=request.url,
            title=request.title,
            description_zh=request.description_zh,
            description_en=request.description_en,
            category_slug=request.category_slug,
            subcategory_slug=request.subcategory_slug,
            tags=request.tags,
            **_membership_inputs(user),
        )
    except PersonalWebsiteQuotaExceeded as exc:
        _raise_website_quota_exceeded(exc)
    except WebsiteContentBlockedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except InvalidPersonalProjectRequest as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PersonalWebsiteOperationFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ToolWebsiteAddResponse(**result)


@router.patch("/projects/me/tool-websites/{website_id}", response_model=ToolWebsiteUpdateResponse, tags=["Projects"])
async def update_my_tool_website(
    website_id: int,
    request: ToolWebsiteUpdateRequest,
    user: dict[str, Any] = Depends(RequireUser),
    service: PersonalProjectsService = Depends(get_personal_projects_service),
) -> ToolWebsiteUpdateResponse:
    """手动编辑当前用户自己的网页收藏卡片信息，不修改全局网站元数据。"""
    user_id = extract_user_id(user)
    if not user_id:
        raise HTTPException(status_code=401, detail="用户身份无效")
    try:
        item = await service.update_tool_website(
            user_id=user_id,
            website_id=website_id,
            title=request.title,
            description=request.description,
            description_zh=request.description_zh,
            description_en=request.description_en,
            category_slug=request.category_slug,
            subcategory_slug=request.subcategory_slug,
            tags=request.tags,
            image_url=request.image_url,
        )
    except InvalidPersonalProjectRequest as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PersonalProjectNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ToolWebsiteUpdateResponse(status="succeeded", message="网页收藏信息已更新。", item=item)


@router.delete("/projects/me/tool-websites/{website_id}", response_model=ToolWebsiteDeleteResponse, tags=["Projects"])
async def remove_my_tool_website(
    website_id: int,
    user: dict[str, Any] = Depends(RequireUser),
    service: PersonalProjectsService = Depends(get_personal_projects_service),
) -> ToolWebsiteDeleteResponse:
    """只把工具网站移出当前用户收藏夹，不删除全局工具库。"""
    user_id = extract_user_id(user)
    if not user_id:
        raise HTTPException(status_code=401, detail="用户身份无效")
    deleted = await service.remove_tool_website(
        user_id=user_id,
        website_id=website_id,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="该工具网站不在你的收藏夹中")
    return ToolWebsiteDeleteResponse(status="succeeded", message="已移出我的收藏。", deleted=True, website_id=website_id)


@router.get("/projects/taxonomy", response_model=ProjectTaxonomyResponse, tags=["Projects"])
async def get_project_taxonomy() -> ProjectTaxonomyResponse:
    """返回普通用户手动添加工具网站时可选的分类体系。"""
    return ProjectTaxonomyResponse(items=_taxonomy_items())


@router.post(
    "/projects/adoptions",
    response_model=ProjectAdoptionResponse,
    tags=["Projects"],
)
async def submit_project_adoption(
    payload: ProjectAdoptionRequest,
    service: ProjectAdoptionService = Depends(get_project_adoption_service),
) -> ProjectAdoptionResponse:
    """写入一条采纳回执（复用决策：adopted / reference_only / declined）。

    公开端点：回执是闭环度量的数据来源，agent 侧（MCP/插件/hook）通常无账号；
    字段均有界且仅追加，decision 枚举由 pydantic 与服务层双重校验。
    """
    try:
        recorded = service.record(
            {
                "project_full_name": payload.project_full_name.strip(),
                "decision": payload.decision,
                "reason": payload.reason.strip(),
                "query": payload.query.strip(),
                "source": "rest",
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ProjectAdoptionResponse(
        receipt=ProjectAdoptionReceipt(
            id=recorded["id"],
            project_full_name=recorded["project_full_name"],
            decision=recorded["decision"],
            created_at=str(recorded["created_at"]),
        ),
        stats=ProjectAdoptionStats(**recorded["stats"]),
    )


@router.get(
    "/projects/adoptions/stats",
    response_model=ProjectAdoptionStats,
    tags=["Projects"],
)
async def get_project_adoption_stats(
    days: int = Query(default=30, ge=1, le=365),
    service: ProjectAdoptionService = Depends(get_project_adoption_service),
) -> ProjectAdoptionStats:
    """采纳回执聚合：窗口内与累计的决策分布及复用率（adopted / 全部）。"""
    return ProjectAdoptionStats(**service.stats(since_days=days))
