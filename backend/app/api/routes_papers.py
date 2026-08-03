"""
Papers API：论文搜索、Top10 今日推荐、论文详情、PDF 代理。

端点列表：
  GET  /api/papers/search?q=&limit=  → 文档搜索（title+summary+tags，所有来源）
  GET  /api/papers/top10-today        → 今日高分 Arxiv 论文前10，用于冷启动推荐
  GET  /api/papers/{paper_id}         → 论文详情（含 pdf_media_url）
  GET  /api/papers/{paper_id}/pdf     → 代理 arxiv PDF（解决前端 CORS）
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, StreamingResponse

from backend.app.api.dependencies import (
    get_document_repository,
    get_papers_repository,
    get_pdf_relay,
)
from backend.app.repositories.document_repository import (
    DocumentSearchReader,
    PapersReader,
)
from backend.app.services.papers.arxiv_identity import (
    ARXIV_REQUEST_HEADERS,
    arxiv_pdf_url,
    extract_arxiv_id,
    pdf_response_headers,
)
from backend.app.services.papers.pdf_relay import PdfRelay
from backend.app.services.papers.presentation import (
    local_pdf_redirect_url,
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

    rows = await asyncio.to_thread(documents.search_documents, normalized_q, limit)
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


@router.get("/papers/{paper_id}/pdf")
async def proxy_arxiv_pdf(
    paper_id: str,
    request: Request,
    papers: PapersReader = Depends(get_papers_repository),
    relay: PdfRelay = Depends(get_pdf_relay),
):
    doc = await asyncio.to_thread(papers.get_paper_pdf_source, paper_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Paper not found")

    local_path = doc.get("local_pdf_path") or ""
    if local_path and os.path.isfile(local_path):
        return RedirectResponse(url=local_pdf_redirect_url(local_path, request))

    paper_url = doc.get("url") or ""
    arxiv_id = extract_arxiv_id(paper_url) or extract_arxiv_id(paper_id)
    if not arxiv_id:
        raise HTTPException(
            status_code=422, detail="Cannot determine arxiv ID from paper URL"
        )

    return StreamingResponse(
        relay.stream(arxiv_pdf_url(arxiv_id), ARXIV_REQUEST_HEADERS),
        media_type="application/pdf",
        headers=pdf_response_headers(arxiv_id),
    )
