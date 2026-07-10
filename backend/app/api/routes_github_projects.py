from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.app.core.auth import OptionalUser, RequireUser
from backend.app.repositories.mysql_repo import MySQLRepository

router = APIRouter()

GitHubProjectSort = Literal["hot", "stars", "updated", "recent", "name"]
ProjectSource = Literal["all", "github", "website"]
ProjectScope = Literal["all", "today", "recommended"]


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
    category_slug: str | None = None
    category_name: str | None = None
    subcategory_slug: str | None = None
    subcategory_name: str | None = None
    tags: list[str] = Field(default_factory=list)
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
    snapshot_date: str | None = None
    captured_at: str | None = None
    rank_in_period: int | None = None
    raw_score: float = 0.0
    score: float = 0.0
    daily_star_growth: int = 0
    daily_growth_available: bool = False
    daily_growth_source: str = "unavailable"
    daily_growth_observed_at: str | None = None
    daily_growth_date: str | None = None
    previous_snapshot_date: str | None = None
    hot_score: float = 0.0
    scale_corrected_growth_score: float = 0.0
    growth_acceleration_score: float = 0.0
    absolute_growth_score: float = 0.0
    maintenance_activity_score: float = 0.0
    community_engagement_score: float = 0.0
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
    count: int


class GitHubProjectCategory(BaseModel):
    slug: str
    name: str
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
    item: dict[str, Any] | None = None


class ToolWebsiteUpdateRequest(BaseModel):
    title: str = Field(default="", max_length=512)
    description: str = Field(default="", max_length=2000)
    description_zh: str = Field(default="", max_length=512)
    category_slug: str = Field(default="other", max_length=64)
    subcategory_slug: str = Field(default="", max_length=64)
    tags: list[str] = Field(default_factory=list, max_length=8)
    image_url: str = Field(default="", max_length=1024)


class ToolWebsiteUpdateResponse(BaseModel):
    status: str
    message: str
    item: dict[str, Any] | None = None


class GitHubProjectTag(BaseModel):
    label: str
    count: int


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
    children: list[dict[str, str]] = Field(default_factory=list)


class ProjectTaxonomyResponse(BaseModel):
    items: list[ProjectTaxonomyItem]


def _user_id(user: dict[str, Any] | None) -> int | None:
    if not isinstance(user, dict):
        return None
    raw = user.get("user_id") or user.get("id") or user.get("sub")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _categories_response(result: dict[str, Any], *, min_stars: int, source: str) -> GitHubProjectCategoriesResponse:
    total = int(result.get("total") or 0)
    today_count = int(result.get("today_count") or 0)
    recommended_count = int(result.get("recommended_count") or 0)
    category_items = result.get("items") or []
    today_label = "今日添加" if source == "website" else "今日暴涨"
    scope_items = [
        {"slug": "all", "name": "全部", "count": total, "kind": "scope", "scope": "all", "children": []},
    ]
    if source != "website":
        scope_items.append({"slug": "recommended", "name": "站长推荐", "count": recommended_count, "kind": "scope", "scope": "recommended", "children": []})
    scope_items.append({"slug": "today", "name": today_label, "count": today_count, "kind": "scope", "scope": "today", "children": []})
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
    from backend.app.services.ingestion.project_taxonomy import WEBSITE_TAXONOMY

    return [
        {
            "slug": category["slug"],
            "name": category["name"],
            "children": [
                {"slug": child["slug"], "name": child["name"]}
                for child in category.get("children", [])
            ],
        }
        for category in WEBSITE_TAXONOMY
    ]


def _tool_website_override_payload(
    *,
    user_id: int,
    website_id: int,
    title: str,
    description_zh: str,
    category_slug: str,
    subcategory_slug: str,
    tags: list[str],
    description: str = "",
    image_url: str = "",
) -> dict[str, Any]:
    from backend.app.services.ingestion.project_taxonomy import (
        WEBSITE_CATEGORY_BY_SLUG,
        WEBSITE_DEFAULT_SUBCATEGORY_BY_CATEGORY,
        WEBSITE_SUBCATEGORY_BY_CATEGORY_SLUG,
        clean_text,
        normalize_subcategory,
    )

    clean_title = clean_text(title, max_len=512)
    clean_description_zh = clean_text(description_zh, max_len=160)
    if not clean_title:
        raise ValueError("工具名称不能为空")
    if not clean_description_zh:
        raise ValueError("中文说明不能为空")

    clean_category = clean_text(category_slug, max_len=64)
    if clean_category not in WEBSITE_CATEGORY_BY_SLUG:
        clean_category = "other"
    clean_subcategory, subcategory_name = normalize_subcategory(
        clean_category,
        subcategory_slug,
        subcategory_by_category_slug=WEBSITE_SUBCATEGORY_BY_CATEGORY_SLUG,
        default_subcategory_by_category=WEBSITE_DEFAULT_SUBCATEGORY_BY_CATEGORY,
    )
    clean_tags: list[str] = []
    for tag in tags or []:
        clean_tag = clean_text(tag, max_len=24)
        if clean_tag and clean_tag not in clean_tags:
            clean_tags.append(clean_tag)
        if len(clean_tags) >= 4:
            break
    return {
        "user_id": user_id,
        "website_id": website_id,
        "title": clean_title,
        "description": clean_text(description, max_len=2000),
        "image_url": clean_text(image_url, max_len=1024),
        "description_zh": clean_description_zh,
        "category_slug": clean_category,
        "category_name": WEBSITE_CATEGORY_BY_SLUG[clean_category],
        "subcategory_slug": clean_subcategory,
        "subcategory_name": subcategory_name,
        "tags": clean_tags,
    }


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
    sort: GitHubProjectSort | None = Query(default=None),
    user: dict[str, Any] | None = Depends(OptionalUser),
) -> GitHubProjectsResponse:
    """公共 AI 项目库：只展示 GitHub 项目；网页收藏只存在于个人收藏夹。"""
    user_id = _user_id(user)
    if source == "website":
        raise HTTPException(status_code=404, detail="网页收藏仅在个人收藏夹中可见")
    effective_source: ProjectSource = "github"
    min_stars = 500
    db = MySQLRepository()
    clean_category = category.strip()
    clean_subcategory = subcategory.strip()
    clean_q = q.strip()
    effective_sort = "hot" if scope == "today" else (sort or "stars")
    result = await asyncio.to_thread(
        db.list_projects,
        source=effective_source,
        scope=scope,
        category=clean_category,
        subcategory=clean_subcategory,
        q=clean_q,
        language=language.strip(),
        page=page,
        page_size=page_size,
        sort=effective_sort,
        min_stars=min_stars,
        enriched_only=True,
        user_id=user_id,
    )
    return _projects_response(
        result,
        min_stars=min_stars,
        source=source,
        scope=scope,
        category=clean_category,
        subcategory=clean_subcategory,
        q=clean_q,
        sort=effective_sort,
    )


@router.get(
    "/projects/categories",
    response_model=GitHubProjectCategoriesResponse,
    tags=["Projects"],
)
async def list_project_categories(
    source: ProjectSource = Query(default="all"),
    user: dict[str, Any] | None = Depends(OptionalUser),
) -> GitHubProjectCategoriesResponse:
    """返回公共 GitHub 项目库分类及数量；个人网页分类使用 /projects/me/categories。"""
    user_id = _user_id(user)
    if source == "website":
        raise HTTPException(status_code=404, detail="网页收藏分类仅在个人收藏夹中可见")
    effective_source: ProjectSource = "github"
    min_stars = 500
    db = MySQLRepository()
    result = await asyncio.to_thread(
        db.get_project_categories,
        source=effective_source,
        min_stars=min_stars,
        enriched_only=True,
    )
    return _categories_response(result, min_stars=min_stars, source=source)


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
) -> GitHubProjectsResponse:
    """当前登录用户的个人收藏夹；默认只返回 GitHub 项目收藏，source=website 返回个人网页。"""
    user_id = _user_id(user)
    if not user_id:
        raise HTTPException(status_code=401, detail="用户身份无效")
    min_stars = 500
    db = MySQLRepository()
    clean_category = category.strip()
    clean_subcategory = subcategory.strip()
    clean_q = q.strip()
    clean_tag = tag.strip()
    result = await asyncio.to_thread(
        db.list_user_project_collection,
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
) -> GitHubProjectCategoriesResponse:
    """当前登录用户个人收藏夹分类；默认只统计 GitHub 收藏，source=website 统计个人网页。"""
    user_id = _user_id(user)
    if not user_id:
        raise HTTPException(status_code=401, detail="用户身份无效")
    min_stars = 500
    db = MySQLRepository()
    result = await asyncio.to_thread(
        db.get_user_project_categories,
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
) -> GitHubProjectTagsResponse:
    """当前登录用户个人收藏夹真实标签；不返回预制分类或默认标签。"""
    user_id = _user_id(user)
    if not user_id:
        raise HTTPException(status_code=401, detail="用户身份无效")
    effective_source = "website" if source == "website" else "github"
    db = MySQLRepository()
    result = await asyncio.to_thread(
        db.get_user_project_tags,
        user_id=user_id,
        source=effective_source,
        min_stars=500,
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
) -> ProjectFavoriteResponse:
    """收藏 GitHub 项目或工具网站到当前用户收藏夹。"""
    user_id = _user_id(user)
    if not user_id:
        raise HTTPException(status_code=401, detail="用户身份无效")
    db = MySQLRepository()
    try:
        result = await asyncio.to_thread(
            db.add_project_favorite,
            user_id=user_id,
            source=request.source,
            repo_id=request.repo_id,
            website_id=request.website_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ProjectFavoriteResponse(status="succeeded", message="已加入我的收藏。", **result)


@router.delete("/projects/me/favorites", response_model=ProjectFavoriteResponse, tags=["Projects"])
async def unfavorite_project(
    request: ProjectFavoriteRequest | None = Body(default=None),
    source: Literal["github", "website"] | None = Query(default=None),
    repo_id: str | None = Query(default=None),
    website_id: str | None = Query(default=None),
    user: dict[str, Any] = Depends(RequireUser),
) -> ProjectFavoriteResponse:
    """从当前用户收藏夹取消收藏 GitHub 项目或工具网站。"""
    user_id = _user_id(user)
    if not user_id:
        raise HTTPException(status_code=401, detail="用户身份无效")
    db = MySQLRepository()
    try:
        favorite_request = _favorite_request_from_inputs(
            request,
            source=source,
            repo_id=repo_id,
            website_id=website_id,
        )
        deleted = await asyncio.to_thread(
            db.remove_project_favorite,
            user_id=user_id,
            source=favorite_request.source,
            repo_id=favorite_request.repo_id,
            website_id=favorite_request.website_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
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


@router.post("/projects/me/tool-websites", response_model=ToolWebsiteAddResponse, tags=["Projects"])
async def add_my_tool_website(
    request: ToolWebsiteAddRequest,
    user: dict[str, Any] = Depends(RequireUser),
) -> ToolWebsiteAddResponse:
    """普通用户自动添加工具网站到自己的收藏夹。"""
    user_id = _user_id(user)
    if not user_id:
        raise HTTPException(status_code=401, detail="用户身份无效")
    url = (request.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL 不能为空")

    from backend.app.services.ingestion.tool_website_fetcher import ToolWebsiteFetchError
    from backend.app.services.ingestion.tool_website_enricher import ToolWebsiteEnricher

    try:
        result = await asyncio.to_thread(
            lambda: ToolWebsiteEnricher().add_and_enrich(
                url,
                added_by_user_id=user_id,
                visibility="private",
            )
        )
        item = result.get("item") or {}
        website_id = item.get("website_id")
        if website_id:
            db = MySQLRepository()
            link_state = await asyncio.to_thread(
                db.link_user_tool_website,
                user_id=user_id,
                website_id=int(website_id),
                added_via="existing" if result.get("duplicate") else "auto",
            )
            item = await asyncio.to_thread(
                db.get_tool_website_item_for_user,
                user_id=user_id,
                website_id=int(website_id),
            )
            if item:
                item.update(link_state)
    except ToolWebsiteFetchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (ValueError, LookupError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"工具网站添加或富化失败：{exc}") from exc

    duplicate = bool(result.get("duplicate"))
    return ToolWebsiteAddResponse(
        status="succeeded",
        message="工具网站已存在，已加入我的收藏。" if duplicate else "工具网站已添加到我的收藏。",
        duplicate=duplicate,
        item=item,
    )


@router.post("/projects/me/tool-websites/manual", response_model=ToolWebsiteAddResponse, tags=["Projects"])
async def add_my_tool_website_manual(
    request: ToolWebsiteManualAddRequest,
    user: dict[str, Any] = Depends(RequireUser),
) -> ToolWebsiteAddResponse:
    """普通用户手动添加工具网站到自己的收藏夹。"""
    user_id = _user_id(user)
    if not user_id:
        raise HTTPException(status_code=401, detail="用户身份无效")
    url = (request.url or "").strip()
    title = (request.title or "").strip()
    description_zh = (request.description_zh or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL 不能为空")
    if not title:
        raise HTTPException(status_code=400, detail="工具名称不能为空")
    if not description_zh:
        raise HTTPException(status_code=400, detail="中文说明不能为空")

    from backend.app.services.ingestion.tool_website_fetcher import ToolWebsiteFetchError
    from backend.app.services.ingestion.tool_website_enricher import ToolWebsiteEnricher

    try:
        result = await asyncio.to_thread(
            lambda: ToolWebsiteEnricher().add_manual(
                url=url,
                title=title,
                description_zh=description_zh,
                category_slug=request.category_slug,
                subcategory_slug=request.subcategory_slug,
                tags=request.tags,
                added_by_user_id=user_id,
                visibility="private",
            )
        )
        item = result.get("item") or {}
        website_id = item.get("website_id")
        if website_id:
            db = MySQLRepository()
            link_state = await asyncio.to_thread(
                db.link_user_tool_website,
                user_id=user_id,
                website_id=int(website_id),
                added_via="manual",
            )
            override_payload = _tool_website_override_payload(
                user_id=user_id,
                website_id=int(website_id),
                title=title,
                description_zh=description_zh,
                category_slug=request.category_slug,
                subcategory_slug=request.subcategory_slug,
                tags=request.tags,
                description=description_zh,
            )
            item = await asyncio.to_thread(db.upsert_user_tool_website_override, override_payload)
            if item:
                item.update(link_state)
    except ToolWebsiteFetchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (ValueError, LookupError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"工具网站手动添加失败：{exc}") from exc

    duplicate = bool(result.get("duplicate"))
    return ToolWebsiteAddResponse(
        status="succeeded",
        message="工具网站已存在，已加入我的收藏。" if duplicate else "工具网站已手动添加到我的收藏。",
        duplicate=duplicate,
        item=item,
    )


@router.patch("/projects/me/tool-websites/{website_id}", response_model=ToolWebsiteUpdateResponse, tags=["Projects"])
async def update_my_tool_website(
    website_id: int,
    request: ToolWebsiteUpdateRequest,
    user: dict[str, Any] = Depends(RequireUser),
) -> ToolWebsiteUpdateResponse:
    """手动编辑当前用户自己的网页收藏卡片信息，不修改全局网站元数据。"""
    user_id = _user_id(user)
    if not user_id:
        raise HTTPException(status_code=401, detail="用户身份无效")
    db = MySQLRepository()
    try:
        payload = _tool_website_override_payload(
            user_id=user_id,
            website_id=website_id,
            title=request.title,
            description=request.description,
            description_zh=request.description_zh,
            category_slug=request.category_slug,
            subcategory_slug=request.subcategory_slug,
            tags=request.tags,
            image_url=request.image_url,
        )
        item = await asyncio.to_thread(db.upsert_user_tool_website_override, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ToolWebsiteUpdateResponse(status="succeeded", message="网页收藏信息已更新。", item=item)


@router.delete("/projects/me/tool-websites/{website_id}", response_model=ToolWebsiteDeleteResponse, tags=["Projects"])
async def remove_my_tool_website(
    website_id: int,
    user: dict[str, Any] = Depends(RequireUser),
) -> ToolWebsiteDeleteResponse:
    """只把工具网站移出当前用户收藏夹，不删除全局工具库。"""
    user_id = _user_id(user)
    if not user_id:
        raise HTTPException(status_code=401, detail="用户身份无效")
    db = MySQLRepository()
    deleted = await asyncio.to_thread(db.unlink_user_tool_website, user_id=user_id, website_id=website_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="该工具网站不在你的收藏夹中")
    return ToolWebsiteDeleteResponse(status="succeeded", message="已移出我的收藏。", deleted=True, website_id=website_id)


@router.get("/projects/taxonomy", response_model=ProjectTaxonomyResponse, tags=["Projects"])
async def get_project_taxonomy() -> ProjectTaxonomyResponse:
    """返回普通用户手动添加工具网站时可选的分类体系。"""
    return ProjectTaxonomyResponse(items=_taxonomy_items())


@router.get("/github/projects", response_model=GitHubProjectsResponse, tags=["GitHub Projects"])
async def list_github_projects(
    category: str = Query(default="", max_length=64),
    subcategory: str = Query(default="", max_length=64),
    q: str = Query(default="", max_length=120),
    language: str = Query(default="", max_length=64),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=60),
    sort: GitHubProjectSort = Query(default="stars"),
) -> GitHubProjectsResponse:
    """收藏夹式 GitHub 项目库：历史项目、stars > 500、AI 分类与中文描述。"""
    min_stars = 500
    db = MySQLRepository()
    result = await asyncio.to_thread(
        db.list_github_projects,
        category=category.strip(),
        subcategory=subcategory.strip(),
        q=q.strip(),
        language=language.strip(),
        page=page,
        page_size=page_size,
        sort=sort,
        min_stars=min_stars,
        enriched_only=True,
    )
    return GitHubProjectsResponse(
        items=result["items"],
        total=int(result["total"]),
        page=int(result["page"]),
        page_size=int(result["page_size"]),
        has_next=int(result["page"]) * int(result["page_size"]) < int(result["total"]),
        min_stars=min_stars,
        scope="all",
        category=category.strip(),
        subcategory=subcategory.strip(),
        q=q.strip(),
        sort=sort,
        source="github",
    )


@router.get(
    "/github/projects/categories",
    response_model=GitHubProjectCategoriesResponse,
    tags=["GitHub Projects"],
)
async def list_github_project_categories() -> GitHubProjectCategoriesResponse:
    """返回 GitHub 项目库 AI 分类及数量。"""
    min_stars = 500
    db = MySQLRepository()
    result = await asyncio.to_thread(
        db.get_project_categories,
        source="github",
        min_stars=min_stars,
        enriched_only=True,
    )
    return _categories_response(result, min_stars=min_stars, source="github")
