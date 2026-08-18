"""RSS 2.0 feed API：公开摘要 feed（获客）+ 会员全文 feed（增值）。

端点列表：
  GET  /api/feed.xml                → 综合 feed（全部源按发布时间归并）
  GET  /api/feeds/{source}.xml      → 单源 feed（arxiv/github/news/…）
  GET  /api/feeds/member.xml        → 会员全文 feed（?token= 复用 MCP access token，
                                      ?source=a,b 自由组合；非会员 fail-closed 403）

设计要点：
  - 公开 feed 只出摘要 + 回链（arxiv 指站内阅读页，其余源指原文链接），
    全文是会员权益；Cache-Control 交双边缘缓存，回源压力近零。
  - 会员 feed 复用 user_mcp_tokens 鉴权（hash_mcp_token → token→user→tier），
    响应 noindex + private/no-store——带 token 的 URL 绝不进边缘缓存。
  - github 源由站内项目库「今日暴涨 top50」热榜供稿（scope=today + hot 排序，
    与 /projects 页同口径），不镜像 trending 抓取的 documents 池；
    热榜查询失败或为空时回退 documents 池兜底，保证 feed 不断更。
  - XML 渲染为纯函数，路由层只做读库与鉴权，便于契约测试。
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from typing import Any
from urllib.parse import quote
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from backend.app.api.dependencies import (
    get_document_repository,
    get_mcp_access_token_repository,
    get_project_catalog_query_service,
)
from backend.app.core.auth import hash_mcp_token
from backend.app.repositories.document_repository import DocumentRecentReader
from backend.app.services.membership.tiers import (
    MEMBERSHIP_TIER_MEMBER,
    normalize_membership_tier,
)
from backend.app.services.papers.presentation import public_base_url
from backend.app.services.project_catalog.query_service import ProjectCatalogQueryService

logger = logging.getLogger(__name__)

router = APIRouter()

# 与日报模块同一份源词汇表（去掉聚合维度 "all"，它由多源归并实现）。
FEED_SOURCES: frozenset[str] = frozenset({"arxiv", "github", "news", "producthunt", "hackernews", "x", "dailyhot"})

# 公开 feed 定位「最新」而非归档：近 48 小时、至多 100 条。
_PUBLIC_FEED_WINDOW = timedelta(hours=48)
_PUBLIC_FEED_LIMIT = 100
# 会员 feed 给更长回溯窗口与更高条数上限。
_MEMBER_FEED_WINDOW = timedelta(days=7)
_MEMBER_FEED_LIMIT = 500

_PUBLIC_CACHE_CONTROL = "public, max-age=900"
_MEMBER_CACHE_CONTROL = "private, no-store"
# 自托管部署未配置 PUBLIC_BASE_URL 时，与 sitemap/MCP 回链同策略回落品牌站点。
_BRAND_BASE_URL = "https://aigcnews.cn"

_CHANNEL_TITLE = "AIGC NEWS"
_CHANNEL_DESCRIPTION = "AI 资讯聚合：arXiv 论文、GitHub 项目、Product Hunt、Hacker News、X 与科技媒体日报"

_MEMBER_ONLY_DETAIL = "全文 RSS 是会员权益，开通会员后使用你的访问令牌订阅"
_INVALID_TOKEN_DETAIL = "feed 令牌无效或已吊销"

# github 源供稿口径：站内项目库「今日暴涨」热榜（scope=today 强制 hot 排序）top50。
_GITHUB_HOT_FEED_LIMIT = 50


def _project_to_feed_row(item: dict[str, Any]) -> dict[str, Any]:
    """项目库热榜条目 → feed 行（与 documents 行同形，供统一渲染/归并排序）。"""
    full_name = str(item.get("full_name") or "").strip()
    description = str(item.get("description_zh") or item.get("description") or "").strip()
    stars = item.get("stars")
    stats = f"⭐ {int(stars):,}" if isinstance(stars, (int, float)) else ""
    growth = item.get("daily_star_growth")
    if isinstance(growth, (int, float)) and growth > 0:
        stats = f"{stats} · 今日 +{int(growth):,}" if stats else f"今日 +{int(growth):,}"
    summary = f"{description}\n\n{stats}" if description and stats else description or stats

    topics = item.get("topics")
    tags = [str(tag).strip() for tag in (topics if isinstance(topics, list) else []) if str(tag).strip()]
    language = str(item.get("language") or "").strip()
    if language:
        tags.insert(0, language)

    return {
        "id": full_name,
        "source": "github",
        "title": full_name,
        "url": str(item.get("url") or "").strip() or f"https://github.com/{full_name}",
        "summary": summary,
        "published_at": str(item.get("captured_at") or "").strip(),
        "published_date": str(item.get("daily_growth_date") or item.get("snapshot_date") or "").strip(),
        "created_at": "",
        "tags": json.dumps(tags, ensure_ascii=False),
    }


async def _github_feed_rows(
    documents: DocumentRecentReader,
    catalog: ProjectCatalogQueryService | None,
    *,
    since_iso: str,
    limit: int,
) -> list[dict[str, Any]]:
    """github 源行：优先站内今日热榜，热榜不可用/为空时回退 documents 池。"""
    if catalog is not None:
        try:
            page = await catalog.list_public_projects(
                scope="today",
                category="",
                subcategory="",
                q="",
                language="",
                page=1,
                page_size=min(limit, _GITHUB_HOT_FEED_LIMIT),
                sort=None,
                user_id=None,
            )
            items = page.result.get("items") or []
            rows = [_project_to_feed_row(item) for item in items if isinstance(item, dict)]
            rows = [row for row in rows if row["id"]]
            if rows:
                return rows
            logger.warning("[Feed] 项目库今日热榜为空，github feed 回退 documents 池")
        except Exception as exc:
            logger.warning("[Feed] 项目库今日热榜查询失败，github feed 回退 documents 池: %s", exc)
    return await asyncio.to_thread(
        documents.list_recent_by_source,
        "github",
        since_iso=since_iso,
        limit=limit,
    )


def _parse_published_at(value: Any) -> datetime | None:
    """解析 ISO 日期/时间字符串；脏串返回 None。"""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _row_published_value(row: dict[str, Any]) -> str:
    """跨源统一时间口径：X 优先 published_at，其他源回退业务日期/入库时间。"""
    for field in ("published_at", "published_date", "created_at"):
        value = str(row.get(field) or "").strip()
        if value and _parse_published_at(value) is not None:
            return value
    return ""


def _item_link(row: dict[str, Any], base_url: str) -> str | None:
    """条目链接：arxiv 指站内阅读页（导流），其余源本站无详情页、指原文链接。"""
    doc_id = str(row.get("id") or "").strip()
    source = str(row.get("source") or "").strip()
    if source == "arxiv" and doc_id:
        return f"{base_url}/papers/{quote(doc_id, safe='')}/read"
    url = str(row.get("url") or "").strip()
    return url or None


def _item_description(row: dict[str, Any], *, full: bool) -> str:
    """摘要文本：公开 feed 仅 summary；会员 feed 追加中文译文（若有）。"""
    parts: list[str] = []
    summary = str(row.get("summary") or "").strip()
    if summary:
        parts.append(summary)
    if full:
        translation = str(row.get("translation_zh") or "").strip()
        if translation and translation != summary:
            parts.append(translation)
    return "\n\n".join(parts)


def _parse_tags(value: Any) -> list[str]:
    """解析 tags 列（JSON 数组串，如 '["x", "daily"]'）；脏值按逗号分隔回落。

    documents.tags 与 authors 同约定——仓储层刻意保持 JSON 字符串透传，
     feed 渲染处自行解析。
    """
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        return [str(tag).strip() for tag in parsed if str(tag).strip()]
    return [tag.strip() for tag in value.split(",") if tag.strip()]


def build_feed_item(row: dict[str, Any], base_url: str, *, full: bool = False) -> str | None:
    """把文档行渲染为 <item> XML；缺 id/title/link 的行返回 None。"""
    doc_id = str(row.get("id") or "").strip()
    title = str(row.get("title") or "").strip()
    link = _item_link(row, base_url)
    if not doc_id or not title or not link:
        return None

    description = _item_description(row, full=full)
    categories = "".join(f"<category>{escape(tag)}</category>" for tag in _parse_tags(row.get("tags")))

    published = _parse_published_at(_row_published_value(row))
    pub_date = f"<pubDate>{format_datetime(published, usegmt=False)}</pubDate>" if published else ""
    return (
        "<item>"
        f"<title>{escape(title)}</title>"
        f"<link>{escape(link)}</link>"
        f'<guid isPermaLink="false">{escape(str(row.get("source") or ""))}:{escape(doc_id)}</guid>'
        f"{pub_date}"
        f"<description>{escape(description)}</description>"
        f"{categories}"
        "</item>"
    )


def build_rss_xml(
    *,
    channel_title: str,
    channel_link: str,
    channel_description: str,
    items: list[str],
) -> str:
    """渲染 RSS 2.0 channel；items 为已渲染的 <item> 片段列表。"""
    body = "\n".join(items)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "<channel>\n"
        f"<title>{escape(channel_title)}</title>\n"
        f"<link>{escape(channel_link)}</link>\n"
        f"<description>{escape(channel_description)}</description>\n"
        "<language>zh-cn</language>\n"
        f'<atom:link href="{escape(channel_link)}" rel="self" type="application/rss+xml"/>\n'
        f"{body}\n"
        "</channel>\n"
        "</rss>\n"
    )


def _sort_rows_newest_first(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按跨源有效时间新到旧排序；脏时间串排尾（保持原相对序）。"""

    def key(row: dict[str, Any]) -> tuple[int, str]:
        published_value = _row_published_value(row)
        if not published_value:
            return (0, "")
        # 词法可比的 ISO 串可直接倒序比较，无需回传 datetime。
        return (1, published_value)

    return sorted(rows, key=key, reverse=True)


async def _collect_rows(
    documents: DocumentRecentReader,
    sources: set[str],
    *,
    window: timedelta,
    limit: int,
    catalog: ProjectCatalogQueryService | None = None,
) -> list[dict[str, Any]]:
    """并发拉取各源滚动窗口文档（github 改由站内今日热榜供稿），按发布时间归并后截断。"""
    since = (datetime.now(timezone.utc) - window).isoformat()
    doc_sources = sorted(sources - {"github"})
    tasks: list[Any] = [
        asyncio.to_thread(
            documents.list_recent_by_source,
            source,
            since_iso=since,
            limit=limit,
        )
        for source in doc_sources
    ]
    if "github" in sources:
        tasks.append(_github_feed_rows(documents, catalog, since_iso=since, limit=limit))
    batches = await asyncio.gather(*tasks)
    merged = [row for batch in batches for row in batch]
    return _sort_rows_newest_first(merged)[:limit]


def _xml_response(xml: str, *, cache_control: str) -> Response:
    return Response(
        content=xml,
        media_type="application/rss+xml",
        headers={"Cache-Control": cache_control},
    )


def _resolve_base_url(request: Request) -> str:
    return public_base_url(request) or _BRAND_BASE_URL


@router.get("/feed.xml", include_in_schema=False)
async def feed_all(
    request: Request,
    documents: DocumentRecentReader = Depends(get_document_repository),
    catalog: ProjectCatalogQueryService = Depends(get_project_catalog_query_service),
):
    """综合公开 feed：全部源按发布时间归并，摘要 + 回链。"""
    rows = await _collect_rows(
        documents,
        FEED_SOURCES,
        window=_PUBLIC_FEED_WINDOW,
        limit=_PUBLIC_FEED_LIMIT,
        catalog=catalog,
    )
    base_url = _resolve_base_url(request)
    items = [item for row in rows if (item := build_feed_item(row, base_url)) is not None]
    xml = build_rss_xml(
        channel_title=_CHANNEL_TITLE,
        channel_link=f"{base_url}/api/feed.xml",
        channel_description=_CHANNEL_DESCRIPTION,
        items=items,
    )
    return _xml_response(xml, cache_control=_PUBLIC_CACHE_CONTROL)


def _parse_member_sources(raw: str | None) -> set[str]:
    """解析 ?source=a,b 组合；空 = 全部源，含非法源名抛 400。"""
    if raw is None or not raw.strip() or raw.strip().lower() == "all":
        return set(FEED_SOURCES)
    sources = {part.strip().lower() for part in raw.split(",") if part.strip()}
    unknown = sources - FEED_SOURCES
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"未知 feed 源：{', '.join(sorted(unknown))}",
        )
    return sources or set(FEED_SOURCES)


# 路由顺序锁定：/feeds/member.xml 必须先于 /feeds/{source}.xml 注册，
# 否则 "member" 会被路径参数捕获、落到单源 feed 的 404 分支。
@router.get("/feeds/member.xml", include_in_schema=False)
async def feed_member(
    request: Request,
    token: str = Query(default=""),
    source: str | None = Query(default=None),
    documents: DocumentRecentReader = Depends(get_document_repository),
    tokens=Depends(get_mcp_access_token_repository),
    catalog: ProjectCatalogQueryService = Depends(get_project_catalog_query_service),
):
    """会员全文 feed：token 鉴权（复用 MCP access token），非会员 fail-closed 403。"""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_INVALID_TOKEN_DETAIL,
        )
    identity = await asyncio.to_thread(tokens.get_user_by_mcp_token_hash, hash_mcp_token(token))
    if identity is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_INVALID_TOKEN_DETAIL,
        )
    if normalize_membership_tier(identity.get("membership_tier")) != MEMBERSHIP_TIER_MEMBER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_MEMBER_ONLY_DETAIL,
        )

    sources = _parse_member_sources(source)
    rows = await _collect_rows(
        documents,
        sources,
        window=_MEMBER_FEED_WINDOW,
        limit=_MEMBER_FEED_LIMIT,
        catalog=catalog,
    )
    base_url = _resolve_base_url(request)
    items = [item for row in rows if (item := build_feed_item(row, base_url, full=True)) is not None]
    xml = build_rss_xml(
        channel_title=f"{_CHANNEL_TITLE} · 会员全文",
        channel_link=f"{base_url}/api/feeds/member.xml",
        channel_description=_CHANNEL_DESCRIPTION,
        items=items,
    )
    return Response(
        content=xml,
        media_type="application/rss+xml",
        headers={
            "Cache-Control": _MEMBER_CACHE_CONTROL,
            "X-Robots-Tag": "noindex",
        },
    )


@router.get("/feeds/{source}.xml", include_in_schema=False)
async def feed_by_source(
    source: str,
    request: Request,
    documents: DocumentRecentReader = Depends(get_document_repository),
    catalog: ProjectCatalogQueryService = Depends(get_project_catalog_query_service),
):
    """单源公开 feed；非法源 404。"""
    normalized = source.strip().lower()
    if normalized not in FEED_SOURCES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"未知 feed 源：{normalized}",
        )
    rows = await _collect_rows(
        documents,
        {normalized},
        window=_PUBLIC_FEED_WINDOW,
        limit=_PUBLIC_FEED_LIMIT,
        catalog=catalog,
    )
    base_url = _resolve_base_url(request)
    items = [item for row in rows if (item := build_feed_item(row, base_url)) is not None]
    xml = build_rss_xml(
        channel_title=f"{_CHANNEL_TITLE} · {normalized}",
        channel_link=f"{base_url}/api/feeds/{normalized}.xml",
        channel_description=_CHANNEL_DESCRIPTION,
        items=items,
    )
    return _xml_response(xml, cache_control=_PUBLIC_CACHE_CONTROL)
