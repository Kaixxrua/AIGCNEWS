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
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from backend.app.api.dependencies import get_document_repository
from backend.app.repositories.document_repository import DocumentSearchReader
from backend.app.repositories.mysql_repo import MySQLRepository
from backend.app.services.papers.arxiv_identity import extract_arxiv_id
from backend.app.services.papers.presentation import project_pdf_media_url, safe_document

router = APIRouter()


def _enrich_pdf_url(doc: Dict[str, Any], request: Request) -> Dict[str, Any]:
    """Compatibility wrapper for the extracted Papers presentation policy."""
    return project_pdf_media_url(doc, request)


def _safe_doc(row: Dict[str, Any]) -> Dict[str, Any]:
    """Compatibility wrapper for the extracted safe serialization policy."""
    return safe_document(row)


# ---------------------------------------------------------------------------
# GET /api/papers/search
# ---------------------------------------------------------------------------


@router.get("/papers/search")
async def search_papers(
    request: Request,
    q: str = Query(..., min_length=1, max_length=200, description="搜索关键词"),
    limit: int = Query(default=20, ge=1, le=100),
    documents: DocumentSearchReader = Depends(get_document_repository),
):
    """
    搜索所有来源的文档（title + summary + tags，支持自然语言查询放宽）。

    返回结果包含 source 字段：
    - source=='arxiv' 且存在 id 时，前端可跳转 /papers/:id/read
    - 其他来源继续跳原始 url
    """
    normalized_q = q.strip()
    if not normalized_q:
        raise HTTPException(status_code=422, detail="搜索关键词不能为空")

    rows = await asyncio.to_thread(documents.search_documents, normalized_q, limit)
    docs = [_safe_doc(dict(row)) for row in rows]
    enriched = [_enrich_pdf_url(d, request) for d in docs]
    return {"items": enriched, "total": len(enriched), "q": normalized_q}


# ---------------------------------------------------------------------------
# GET /api/papers/top10-today
# ---------------------------------------------------------------------------


@router.get("/papers/top10-today")
async def top10_today(request: Request):
    """
    冷启动推荐：返回今日高分 Arxiv 论文前10，按 raw_score 倒序。

    当无当日数据时回退到全库近期 Top10 arxiv 论文。
    """
    import asyncio
    from datetime import datetime, timezone, timedelta
    from backend.app.repositories.mysql_repo import MySQLRepository

    db = MySQLRepository()

    def _do_query() -> List[Dict[str, Any]]:
        tz_cst = timezone(timedelta(hours=8))
        today = datetime.now(tz_cst).date().isoformat()

        # 优先查今日入库的 arxiv 论文（created_at 前10位匹配今日日期）
        sql_today = """
            SELECT id, source, source_channel, title, url, summary,
                   published_date, tags, score, raw_score, rank_in_period,
                   local_pdf_path, created_at
            FROM documents
            WHERE source = 'arxiv'
              AND LEFT(created_at, 10) = %s
            ORDER BY COALESCE(raw_score, score, 0) DESC
            LIMIT 10
        """
        conn = db._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql_today, (today,))
                rows = cur.fetchall()
            conn.commit()

            if rows:
                return [_safe_doc(dict(r)) for r in rows]

            # 回退：全库近期 Top10 arxiv
            sql_fallback = """
                SELECT id, source, source_channel, title, url, summary,
                       published_date, tags, score, raw_score, rank_in_period,
                       local_pdf_path, created_at
                FROM documents
                WHERE source = 'arxiv'
                ORDER BY created_at DESC, COALESCE(raw_score, score, 0) DESC
                LIMIT 10
            """
            with conn.cursor() as cur:
                cur.execute(sql_fallback)
                rows = cur.fetchall()
            conn.commit()
            return [_safe_doc(dict(r)) for r in rows]
        finally:
            conn.close()

    docs = await asyncio.to_thread(_do_query)
    enriched = [_enrich_pdf_url(d, request) for d in docs]
    return {"items": enriched, "total": len(enriched)}


# ---------------------------------------------------------------------------
# GET /api/papers/{paper_id}
# ---------------------------------------------------------------------------


@router.get("/papers/{paper_id}")
async def get_paper_detail(paper_id: str, request: Request):
    """
    论文详情：按 id (md5 hex) 查询，返回完整元数据 + pdf_media_url。
    """
    import asyncio
    from backend.app.repositories.mysql_repo import MySQLRepository

    db = MySQLRepository()

    def _do_get() -> Optional[Dict[str, Any]]:
        sql = """
            SELECT id, source, source_channel, title, url, summary,
                   published_date, tags, score, raw_score, rank_in_period,
                   local_pdf_path, created_at
            FROM documents
            WHERE id = %s
            LIMIT 1
        """
        conn = db._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (paper_id,))
                row = cur.fetchone()
            conn.commit()
            return _safe_doc(dict(row)) if row else None
        finally:
            conn.close()

    from fastapi import HTTPException

    doc = await asyncio.to_thread(_do_get)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id!r} not found")
    return _enrich_pdf_url(doc, request)


# ---------------------------------------------------------------------------
# GET /api/papers/{paper_id}/pdf  — arxiv PDF 代理（解决前端 CORS）
# ---------------------------------------------------------------------------

def _extract_arxiv_id(url_or_id: str) -> Optional[str]:
    """Compatibility wrapper for the extracted Arxiv identity policy."""
    return extract_arxiv_id(url_or_id)


@router.get("/papers/{paper_id}/pdf")
async def proxy_arxiv_pdf(paper_id: str, request: Request):
    """
    代理 arxiv PDF 文件到前端，解决浏览器 CORS 限制。
    优先使用本地缓存文件；若无，从 export.arxiv.org 流式拉取并透传。
    """
    import asyncio
    from backend.app.repositories.mysql_repo import MySQLRepository

    db = MySQLRepository()

    # 1. 查询数据库获取 local_pdf_path 和 url
    def _get_doc() -> Optional[Dict[str, Any]]:
        sql = "SELECT local_pdf_path, url, source FROM documents WHERE id = %s LIMIT 1"
        conn = db._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (paper_id,))
                row = cur.fetchone()
            conn.commit()
            return dict(row) if row else None
        finally:
            conn.close()

    doc = await asyncio.to_thread(_get_doc)
    if doc is None:
        raise HTTPException(status_code=404, detail="Paper not found")

    # 2. 若有本地文件，直接重定向到 /api/media/papers/
    local_path = doc.get("local_pdf_path") or ""
    if local_path and os.path.isfile(local_path):
        filename = os.path.basename(local_path)
        base_url = str(request.base_url).rstrip("/")
        # 感知真实协议（HTTPS），避免 Mixed Content
        forwarded_proto = request.headers.get("x-forwarded-proto", "")
        if forwarded_proto:
            base_url = base_url.replace("http://", f"{forwarded_proto}://", 1)
        from fastapi.responses import RedirectResponse

        return RedirectResponse(url=f"{base_url}/api/media/papers/{filename}")

    # 3. 从 arxiv URL 提取 arxiv_id
    paper_url = doc.get("url") or ""
    arxiv_id = _extract_arxiv_id(paper_url) or _extract_arxiv_id(paper_id)
    if not arxiv_id:
        raise HTTPException(
            status_code=422, detail="Cannot determine arxiv ID from paper URL"
        )

    # 4. 流式代理 arxiv PDF
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; AIGC-News-Bot/1.0; "
            "+https://github.com/aigc-news)"
        ),
        "Accept": "application/pdf,*/*",
    }

    async def _stream_pdf():
        async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
            async with client.stream("GET", pdf_url, headers=headers) as resp:
                if resp.status_code != 200:
                    raise HTTPException(
                        status_code=resp.status_code,
                        detail=f"arxiv returned {resp.status_code} for {pdf_url}",
                    )
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    yield chunk

    return StreamingResponse(
        _stream_pdf(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{arxiv_id}.pdf"',
            "Cache-Control": "public, max-age=86400",
            "Access-Control-Allow-Origin": "*",
        },
    )
