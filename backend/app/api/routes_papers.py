"""
Papers API：论文搜索、Top10 今日推荐、论文详情。

端点列表：
  GET  /api/papers/search?q=&limit=  → 文档搜索（title+summary+tags，所有来源）
  GET  /api/papers/top10-today        → 今日高分 Arxiv 论文前10，用于冷启动推荐
  GET  /api/papers/arxiv/{arxiv_id}   → 按 arXiv 编号取论文详情（简报条目只带编号）
  GET  /api/papers/{paper_id}         → 论文详情
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request

from backend.app.api.dependencies import (
    get_document_repository,
    get_papers_repository,
)
from backend.app.repositories.document_repository import (
    DocumentSearchReader,
    PapersReader,
)
from backend.app.services.papers.presentation import (
    project_pdf_media_url,
    safe_document,
)

router = APIRouter()


def _enrich_pdf_url(doc: Dict[str, Any], request: Request) -> Dict[str, Any]:
    """Compatibility wrapper for the extracted Papers presentation policy."""
    return project_pdf_media_url(doc, request)


def _safe_doc(row: Dict[str, Any]) -> Dict[str, Any]:
    """Compatibility wrapper for the extracted safe serialization policy."""
    return safe_document(row)


@router.get("/papers/search")
async def search_papers(
    request: Request,
    q: str = Query(..., min_length=1, max_length=200, description="搜索关键词"),
    limit: int = Query(default=20, ge=1, le=100),
    documents: DocumentSearchReader = Depends(get_document_repository),
):
    normalized_q = q.strip()
    if not normalized_q:
        raise HTTPException(status_code=422, detail="搜索关键词不能为空")

    rows = await asyncio.to_thread(documents.search_documents, normalized_q, limit, source="arxiv")
    docs = [safe_document(dict(row)) for row in rows]
    enriched = [project_pdf_media_url(document, request) for document in docs]
    return {"items": enriched, "total": len(enriched), "q": normalized_q}


@router.get("/papers/top10-today")
async def top10_today(
    request: Request,
    papers: PapersReader = Depends(get_papers_repository),
):
    rows = await asyncio.to_thread(papers.get_today_top_arxiv_documents)
    docs = [safe_document(dict(row)) for row in rows]
    enriched = [project_pdf_media_url(document, request) for document in docs]
    return {"items": enriched, "total": len(enriched)}


@router.get("/papers/arxiv/{arxiv_id}")
async def get_paper_by_arxiv_id(
    request: Request,
    arxiv_id: str = Path(..., pattern=r"^\d{4}\.\d{4,5}(?:v\d+)?$", description="新式 arXiv 编号，可带版本号"),
    papers: PapersReader = Depends(get_papers_repository),
):
    """简报里的论文条目只链到 Hugging Face / arXiv 页面、带着编号：按编号找到站内这篇，字段与 /papers/{paper_id} 相同。"""
    bare_id = arxiv_id.split("v", 1)[0]
    row = await asyncio.to_thread(papers.get_paper_by_arxiv_id, bare_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Paper 'arXiv:{bare_id}' not found")
    return project_pdf_media_url(safe_document(dict(row)), request)


@router.get("/papers/{paper_id}")
async def get_paper_detail(
    paper_id: str,
    request: Request,
    papers: PapersReader = Depends(get_papers_repository),
):
    row = await asyncio.to_thread(papers.get_paper_detail, paper_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id!r} not found")
    return project_pdf_media_url(safe_document(dict(row)), request)

