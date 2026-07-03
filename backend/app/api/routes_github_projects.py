from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from backend.app.repositories.mysql_repo import MySQLRepository

router = APIRouter()

GitHubProjectSort = Literal["stars", "updated", "recent", "name"]


class GitHubProjectItem(BaseModel):
    repo_id: str | int
    full_name: str
    title: str | None = None
    url: str | None = None
    description: str | None = None
    description_zh: str | None = None
    category_slug: str | None = None
    category_name: str | None = None
    tags: list[str] = []
    language: str | None = None
    topics: list[str] = []
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
    confidence: float = 0.0


class GitHubProjectsResponse(BaseModel):
    items: list[GitHubProjectItem]
    total: int
    page: int
    page_size: int
    has_next: bool
    min_stars: int
    category: str = ""
    q: str = ""
    sort: str = "stars"


class GitHubProjectCategory(BaseModel):
    slug: str
    name: str
    count: int


class GitHubProjectCategoriesResponse(BaseModel):
    items: list[GitHubProjectCategory]
    total: int
    min_stars: int


@router.get("/github/projects", response_model=GitHubProjectsResponse, tags=["GitHub Projects"])
async def list_github_projects(
    category: str = Query(default="", max_length=64),
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
        category=category.strip(),
        q=q.strip(),
        sort=sort,
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
    categories = await asyncio.to_thread(
        db.get_github_project_categories,
        min_stars=min_stars,
        enriched_only=True,
    )
    total = sum(int(item.get("count") or 0) for item in categories)
    return GitHubProjectCategoriesResponse(
        items=[{"slug": "all", "name": "全部", "count": total}, *categories],
        total=total,
        min_stars=min_stars,
    )
