"""
站内速查 API（⌘K）。

端点列表：
  GET  /api/search?q=&limit=&locale=  → 项目、论文、简报、推文四组结果，每组前 limit 条与命中总数
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.app.api.dependencies import (
    get_briefing_repository,
    get_document_repository,
    get_project_catalog_query_service,
)
from backend.app.core.auth import RequireUser
from backend.app.core.config import settings
from backend.app.domain.search_semantics import normalize_search_query
from backend.app.repositories.briefing_repository import BriefingSearchReader
from backend.app.repositories.document_repository import DocumentSearchReader
from backend.app.services.project_catalog.query_service import ProjectCatalogQueryService
from backend.app.services.search.quick_search import quick_search

router = APIRouter()


@router.get("/search", dependencies=[Depends(RequireUser)])
async def search_site(
    q: str = Query(..., min_length=1, max_length=120, description="搜索关键词"),
    limit: int = Query(default=5, ge=1, le=8),
    locale: str = Query(default="zh-CN", max_length=16, description="zh-CN/en，决定简报读哪种语言的正文"),
    catalog: ProjectCatalogQueryService = Depends(get_project_catalog_query_service),
    documents: DocumentSearchReader = Depends(get_document_repository),
    briefings: BriefingSearchReader = Depends(get_briefing_repository),
) -> dict[str, Any]:
    """一次查齐四组；X 源关闭时不返回推文组，也不查 X 简报。某组失败时其余照常返回，失败的组名列在 failed。"""
    clean_q = normalize_search_query(q)
    if not clean_q:
        raise HTTPException(status_code=422, detail="搜索关键词不能为空")
    return await quick_search(
        clean_q,
        limit=limit,
        locale=locale,
        catalog=catalog,
        documents=documents,
        briefings=briefings,
        include_tweets=bool(settings.x_source_enabled),
    )
