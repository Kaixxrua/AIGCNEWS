"""站内速查（⌘K）：一次请求同时查项目、论文、简报、推文，每组取前几条。

各组沿用现成的检索口径：项目走公共项目库（与 /api/projects?q=、MCP search_github_ai_projects
同库同排序）；论文与推文走文档检索（与 /api/papers/search、MCP search_documents 同一 SQL，
分别限定 arxiv 与 x 来源）；简报按期查正文关键词。UI 素材在前端本地目录里查，不经这里。
一组失败不拖累别的组：失败的组名列进 failed，其余照常返回。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from backend.app.domain.search_semantics import search_terms
from backend.app.repositories.briefing_repository import BriefingSearchReader
from backend.app.repositories.document_repository import DocumentSearchReader
from backend.app.services.briefing.daily_briefing import (
    get_briefing_cache_key,
    normalize_briefing_locale,
)
from backend.app.services.project_catalog.query_service import ProjectCatalogQueryService

logger = logging.getLogger(__name__)

BRIEFING_TYPES = ("all", "arxiv", "github", "news", "producthunt", "hackernews", "x", "dailyhot")
# 期键是 'YYYY-MM-DD' 加后缀，后缀与生成时同一张表；反查出是哪种简报。
_TYPE_BY_SUFFIX = {get_briefing_cache_key("", kind): kind for kind in BRIEFING_TYPES}
_X_SUFFIX = get_briefing_cache_key("", "x")

SUMMARY_CHARS = 160
SNIPPET_CHARS = 140
_SNIPPET_LEAD_IN = 30
_PAPER_AUTHORS = 3

_BLOCK_SPLIT = re.compile(r"\n\s*\n")
_LIST_MARK = re.compile(r"^\s*(?:\d+[.)]|[-*+])\s+")
_HEADING = re.compile(r"^\s*#{1,6}\s+")
_LEAD = re.compile(r"^\*\*(.+?)\*\*")
_TAG_CODE = re.compile(r"`#[^`]*`")
_SOURCE_LINK = re.compile(r"\[(?:来源|原文|链接|source|link)\]\([^)]*\)", re.IGNORECASE)
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_EMPHASIS = re.compile(r"\*\*|__|`")
_LEAD_NOTE = re.compile(r"^\s*[（(][^）)]*[）)]")
_LEAD_COLON = re.compile(r"^\s*[：:]\s*")
_SPACE = re.compile(r"\s+")
_X_HANDLE = re.compile(r"^https?://(?:www\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})/status/", re.IGNORECASE)


def _clip(text: str, limit: int) -> str:
    text = _SPACE.sub(" ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _web_url(value: Any) -> str:
    url = str(value or "").strip()
    return url if url.lower().startswith(("https://", "http://")) else ""


def _plain(markdown: str) -> str:
    """一段简报 Markdown 去掉标记只留字：标签、来源链接整个去掉，其余链接留字。"""
    text = _SOURCE_LINK.sub("", markdown)
    text = _TAG_CODE.sub("", text)
    text = _LINK.sub(r"\1", text)
    text = _EMPHASIS.sub("", text)
    return _SPACE.sub(" ", text).strip()


def briefing_excerpt(body: str, terms: list[str]) -> dict[str, str]:
    """从一期简报里挑命中关键词最多的一段（同样多取靠前的），给出标题、条目名与截在命中处的摘录。"""
    patterns = [re.compile(re.escape(term), re.IGNORECASE) for term in terms if term]
    title = ""
    best: tuple[int, str, str] | None = None
    for block in _BLOCK_SPLIT.split(body or ""):
        raw = _LIST_MARK.sub("", block.strip(), count=1)
        if not raw:
            continue
        if _HEADING.match(raw):
            raw = _HEADING.sub("", raw, count=1)
            if not title and block.lstrip().startswith("# "):
                title = _plain(raw.split("\n", 1)[0])
            # 单独一行的标题不拿来当摘录：一期的标题另外给，节标题没内容。
            if "\n" not in raw:
                continue
        hits = sum(1 for pattern in patterns if pattern.search(_plain(raw)))
        if not hits or (best is not None and hits <= best[0]):
            continue
        # 条目形如「**名称**（owner/repo）：正文」：名称单拿出来，摘录从正文起。
        lead_match = _LEAD.match(raw)
        lead = _plain(lead_match.group(1)) if lead_match else ""
        rest = raw[lead_match.end():] if lead_match else raw
        if lead:
            rest = _LEAD_COLON.sub("", _LEAD_NOTE.sub("", rest, count=1), count=1)
        best = (hits, lead, _plain(rest))
        if hits == len(patterns):
            break
    if best is None:
        return {"title": title, "lead": "", "snippet": ""}
    _, lead, text = best
    positions = [match.start() for pattern in patterns if (match := pattern.search(text))]
    start = max(0, min(positions) - _SNIPPET_LEAD_IN) if positions and len(text) > SNIPPET_CHARS else 0
    end = start + SNIPPET_CHARS
    snippet = ("…" if start else "") + text[start:end].strip() + ("…" if end < len(text) else "")
    return {"title": title, "lead": lead, "snippet": snippet}


def _project(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "full_name": str(row.get("full_name") or row.get("repo_id") or ""),
        "url": _web_url(row.get("url")),
        "description": str(row.get("description") or ""),
        "description_zh": str(row.get("description_zh") or ""),
        "description_en": str(row.get("description_en") or ""),
        "stars": int(row.get("stars") or 0),
        "language": str(row.get("language") or ""),
    }


def _author_names(value: Any) -> list[str]:
    names: Any = value
    if isinstance(value, str):
        try:
            names = json.loads(value)
        except ValueError:
            names = value.split(",")
    if not isinstance(names, list):
        return []
    return [str(name).strip() for name in names if str(name).strip()]


def _paper(row: dict[str, Any]) -> dict[str, Any]:
    names = _author_names(row.get("authors"))
    return {
        "id": str(row.get("id") or ""),
        "title": _clip(str(row.get("title") or ""), 300),
        "summary": _clip(str(row.get("summary") or ""), SUMMARY_CHARS),
        "date": str(row.get("published_date") or "")[:10],
        "authors": names[:_PAPER_AUTHORS],
        "author_count": len(names),
    }


def _tweet(row: dict[str, Any]) -> dict[str, Any]:
    url = _web_url(row.get("url"))
    handle = _X_HANDLE.match(url)
    return {
        "id": str(row.get("id") or ""),
        "text": _clip(str(row.get("summary") or row.get("title") or ""), 200),
        "url": url,
        "author": handle.group(1) if handle else "",
        "date": str(row.get("published_date") or "")[:10],
    }


async def _projects(catalog: ProjectCatalogQueryService, q: str, limit: int) -> dict[str, Any]:
    page = await catalog.list_public_projects(
        scope="all",
        category="",
        subcategory="",
        q=q,
        language="",
        page=1,
        page_size=limit,
        sort=None,
        user_id=None,
    )
    items = list(page.result.get("items") or [])
    return {"total": int(page.result.get("total") or 0), "items": [_project(dict(row)) for row in items[:limit]]}


async def _documents(documents: DocumentSearchReader, q: str, source: str, limit: int) -> dict[str, Any]:
    page = await asyncio.to_thread(documents.search_document_page, q, source=source, page=1, page_size=limit)
    shape = _paper if source == "arxiv" else _tweet
    items = [shape(dict(row)) for row in page.get("items") or []]
    return {"total": int(page.get("total") or 0), "items": items}


async def _briefings(
    briefings: BriefingSearchReader,
    q: str,
    limit: int,
    locale: str,
    include_x: bool,
) -> dict[str, Any]:
    terms = search_terms(q)
    if not terms:
        return {"total": 0, "items": []}
    page = await asyncio.to_thread(
        briefings.search_briefings,
        terms,
        locale=locale,
        limit=limit,
        exclude_suffixes=() if include_x else (_X_SUFFIX,),
    )
    items = []
    for row in page.get("items") or []:
        key = str(row.get("date") or "")
        kind = _TYPE_BY_SUFFIX.get(key[10:])
        if kind is None:
            continue
        items.append({"id": row.get("id"), "date": key[:10], "type": kind, **briefing_excerpt(str(row.get("body") or ""), terms)})
    return {"total": int(page.get("total") or 0), "items": items}


async def quick_search(
    q: str,
    *,
    limit: int,
    locale: str,
    catalog: ProjectCatalogQueryService,
    documents: DocumentSearchReader,
    briefings: BriefingSearchReader,
    include_tweets: bool,
) -> dict[str, Any]:
    """q 须已归一化且非空。返回 {q, groups: {组名: {total, items}}, failed: [失败的组名]}，组按固定顺序。"""
    jobs = {
        "projects": _projects(catalog, q, limit),
        "papers": _documents(documents, q, "arxiv", limit),
        "briefings": _briefings(briefings, q, limit, normalize_briefing_locale(locale), include_tweets),
    }
    if include_tweets:
        jobs["tweets"] = _documents(documents, q, "x", limit)
    results = await asyncio.gather(*jobs.values(), return_exceptions=True)
    groups: dict[str, Any] = {}
    failed: list[str] = []
    for name, result in zip(jobs, results):
        if isinstance(result, BaseException):
            if not isinstance(result, Exception):
                raise result
            logger.warning("quick search group %s failed", name, exc_info=result)
            failed.append(name)
            continue
        groups[name] = result
    return {"q": q, "groups": groups, "failed": failed}
