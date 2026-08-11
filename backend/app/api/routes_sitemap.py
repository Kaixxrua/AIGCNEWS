"""
Sitemap API：动态 sitemap.xml，向搜索引擎开放近期论文阅读页索引。

端点列表：
  GET  /api/sitemap.xml  → 近期 arXiv 论文阅读页 URL 集（7 条静态路由仍由
                           前端 public/sitemap.xml 提供，两者在 robots.txt
                           中并列声明）
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, Request, Response

from backend.app.api.dependencies import get_document_repository
from backend.app.repositories.document_repository import DocumentRecentReader
from backend.app.services.papers.presentation import public_base_url

router = APIRouter()

# 滚动窗口与单文件条数上限：近 90 天 arXiv 论文、至多 5000 条
# （远低于 sitemap 规范的 50k 单文件上限，索引期内容保持新鲜）。
_SITEMAP_WINDOW_DAYS = 90
_SITEMAP_LIMIT = 5000
# 爬虫抓取低频，一小时缓存足够；由响应头交给边缘/客户端缓存。
_CACHE_CONTROL = "public, max-age=3600"
# 自托管部署未配置 PUBLIC_BASE_URL 时，与 MCP 回链同策略回落到品牌站点。
_BRAND_BASE_URL = "https://aigcnews.cn"
_DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def _iso_date(value: Any) -> str | None:
    """从 published_at / published_date 提取 YYYY-MM-DD；脏时间串返回 None。"""
    if value is None:
        return None
    match = _DATE_PREFIX.match(str(value))
    return match.group(1) if match else None


def build_sitemap_xml(rows: list[dict[str, Any]], base_url: str) -> str:
    """把文档行渲染为 urlset XML；无 id 的行跳过，脏时间串仅省略 lastmod。"""
    entries = []
    for row in rows:
        doc_id = str(row.get("id") or "").strip()
        if not doc_id:
            continue
        loc = f"{base_url}/papers/{quote(doc_id, safe='')}/read"
        entry = f"  <url><loc>{escape(loc)}</loc>"
        lastmod = _iso_date(row.get("published_at") or row.get("published_date"))
        if lastmod:
            entry += f"<lastmod>{lastmod}</lastmod>"
        entries.append(entry + "</url>")
    body = "\n".join(entries)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}\n</urlset>\n"
    )


@router.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml(
    request: Request,
    documents: DocumentRecentReader = Depends(get_document_repository),
):
    since = (datetime.now(timezone.utc) - timedelta(days=_SITEMAP_WINDOW_DAYS)).isoformat()
    rows = await asyncio.to_thread(
        documents.list_recent_by_source,
        "arxiv",
        since_iso=since,
        limit=_SITEMAP_LIMIT,
    )
    base_url = public_base_url(request) or _BRAND_BASE_URL
    return Response(
        content=build_sitemap_xml(rows, base_url),
        media_type="application/xml",
        headers={"Cache-Control": _CACHE_CONTROL},
    )
