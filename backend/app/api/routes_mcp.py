from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import uuid
from datetime import date as _date, datetime as _dt, timedelta as _td
from json import JSONDecodeError
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs, unquote, urlparse

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from backend.app.api.routes_dashboard import (
    _compute_board_status,
    _dedupe_docs,
    _enrich_doc_pdf_url,
    _get_docs_for_date,
    _resolve_snapshot_date,
    _score_categories,
)
from backend.app.api.routes_papers import _enrich_pdf_url, _safe_doc
from backend.app.core.auth import OptionalMcpUser
from backend.app.repositories.mysql_repo import MySQLRepository
from backend.app.services.ingestion.source_github_mcp import search_github_projects_fallback
from backend.app.services.project_discovery import search_projects

logger = logging.getLogger(__name__)

router = APIRouter()

MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_SERVER_NAME = "aigc-news"
MCP_SERVER_VERSION = "1.0.0"
MAX_REQUEST_BYTES = 64 * 1024
MAX_TOOL_RESULT_CHARS = 100_000
MAX_RESOURCE_TEXT_CHARS = 100_000

_JSONRPC_PARSE_ERROR = -32700
_JSONRPC_INVALID_REQUEST = -32600
_JSONRPC_METHOD_NOT_FOUND = -32601
_JSONRPC_INVALID_PARAMS = -32602
_JSONRPC_INTERNAL_ERROR = -32603

_SOURCE_CHOICES = {"all", "arxiv", "github", "news", "producthunt", "hackernews"}
_PERIOD_CHOICES = {"daily", "weekly", "monthly"}
_PROJECT_SCOPE_CHOICES = {"all", "today", "recommended"}
_PROJECT_SORT_CHOICES = {"hot", "stars", "updated", "recent", "name"}
_PROJECT_FALLBACK_POLICY = "local_first_github_only_when_local_zero"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class McpToolInputError(ValueError):
    """Raised when MCP tool arguments are invalid."""


class McpResourceInputError(ValueError):
    """Raised when MCP resource parameters are invalid."""


class McpPromptInputError(ValueError):
    """Raised when MCP prompt parameters are invalid."""


MCP_RESOURCES: list[dict[str, Any]] = [
    {
        "uri": "aigc-news://dashboard/summary",
        "name": "dashboard_summary",
        "title": "AIGC_NEWS Dashboard Summary",
        "description": "Latest public dashboard context: top items, trend radar, and aggregate source stats.",
        "mimeType": "application/json",
    },
    {
        "uri": "aigc-news://projects/categories",
        "name": "project_categories",
        "title": "AI Project Categories",
        "description": "Public GitHub AI project category and subcategory counts.",
        "mimeType": "application/json",
    },
    {
        "uri": "aigc-news://report/latest",
        "name": "latest_briefing",
        "title": "Latest AIGC_NEWS Briefing",
        "description": "Latest generated public briefing. Query parameters: source, period, date.",
        "mimeType": "text/markdown",
    },
]

MCP_RESOURCE_TEMPLATES: list[dict[str, Any]] = [
    {
        "uriTemplate": "aigc-news://dashboard/top{?source,period,date,limit}",
        "name": "dashboard_top_items",
        "title": "Dashboard Top Items",
        "description": "Read public ranked AIGC_NEWS items by source, period, optional date, and limit.",
        "mimeType": "application/json",
    },
    {
        "uriTemplate": "aigc-news://papers/{paper_id}",
        "name": "paper_detail",
        "title": "Paper or Indexed Item Detail",
        "description": "Read public metadata for one indexed AIGC_NEWS document by id.",
        "mimeType": "application/json",
    },
    {
        "uriTemplate": "aigc-news://projects/library{?q,category,subcategory,language,scope,sort,limit}",
        "name": "project_library",
        "title": "AI Project Library",
        "description": "Read public GitHub AI project library slices by query, taxonomy, language, scope, and sort.",
        "mimeType": "application/json",
    },
    {
        "uriTemplate": "aigc-news://report/latest{?source,period,date}",
        "name": "latest_briefing_by_filter",
        "title": "Filtered Latest Briefing",
        "description": "Read the latest generated briefing for a source, period, and optional date.",
        "mimeType": "text/markdown",
    },
]

MCP_PROMPTS: list[dict[str, Any]] = [
    {
        "name": "daily_research_brief",
        "title": "Daily AIGC research brief",
        "description": "Guide a client to summarize today's AIGC_NEWS context using public tools and resources.",
        "arguments": [
            {
                "name": "source",
                "description": "Optional source filter: all, arxiv, github, news, producthunt, hackernews.",
                "required": False,
            },
            {"name": "topic", "description": "Optional topic or keyword focus.", "required": False},
        ],
    },
    {
        "name": "project_discovery",
        "title": "GitHub AI project discovery",
        "description": "Guide a client to discover and compare public AI GitHub projects with AIGC_NEWS local-first search.",
        "arguments": [
            {"name": "topic", "description": "Optional search topic, e.g. RAG Web UI local deploy.", "required": False},
            {"name": "category", "description": "Optional project category slug.", "required": False},
            {"name": "language", "description": "Optional programming language filter.", "required": False},
        ],
    },
]

MCP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_papers",
        "description": (
            "Search public AIGC_NEWS papers and indexed documents for explicitly scholarly or publication-centered requests: "
            "papers, literature, surveys or systematic reviews, citations, authors or venues, benchmarks or evaluations, "
            "methods or theory, experiments, and research results. Agent/MCP is only a topic, not an academic-intent signal. "
            "For generic Agent/MCP learning, tutorials, examples, implementations, SDKs, servers/clients, workflows, tool "
            "calling, demos, templates, or unspecified 资料, call search_github_ai_projects first. For an academic search, "
            "rewrite natural-language intent into a concise query of 1-3 established technical terms rather than the full user "
            "sentence; use at most three focused paper searches for distinct scholarly concepts. For mixed requests, choose one "
            "initial tool based on the dominant deliverable: implementations/tutorials use GitHub AI first, while papers/citations/"
            "experimental results use this tool first. Do not batch both primary searches or native WebSearch/WebFetch in the "
            "initial tool message. Inspect MCP results first; use a host web tool only if an MCP call fails, returns no relevant "
            "items, or lacks a specific fact, then search only for that missing detail."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {
                    "type": "string",
                    "description": "Concise semantic query using 1-3 established technical terms, not the full user sentence; e.g. AI Agent, LLM Agent, or Model Context Protocol.",
                },
                "limit": {"type": "integer", "description": "Maximum results, 1-20.", "default": 10},
            },
            "required": ["q"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_paper_detail",
        "description": (
            "Fetch public metadata for one indexed AIGC_NEWS document by id. "
            "Call this after search_papers or get_top_items when the user needs details for a specific item."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "paper_id": {"type": "string", "description": "Document id returned by search/top tools."},
            },
            "required": ["paper_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_top_items",
        "description": (
            "Return public top-ranked AIGC_NEWS items for a source, period, and optional snapshot date. "
            "Call this for daily, weekly, or monthly rankings and trend questions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "enum": sorted(_SOURCE_CHOICES),
                    "description": "Source filter. Use all unless the user names a source.",
                    "default": "all",
                },
                "period": {
                    "type": "string",
                    "enum": sorted(_PERIOD_CHOICES),
                    "description": "Ranking period.",
                    "default": "daily",
                },
                "date": {"type": "string", "description": "Optional snapshot date in YYYY-MM-DD format."},
                "limit": {"type": "integer", "description": "Maximum results, 1-20.", "default": 10},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_github_projects",
        "description": (
            "Search public GitHub repositories and open-source software only; this never searches the authenticated user's favorites. "
            "It covers any domain, including non-AI Windows, macOS, "
            "Linux, desktop, screenshot, screen-capture, productivity, and developer tools. Use it when the user explicitly asks "
            "to find/recommend open-source software, or when planning a complete product, independent subsystem, mature infrastructure "
            "capability, or architecture-level comparison. Do not call it for typo fixes, styling, renames, clear bugs, or isolated "
            "function/component changes. When search is warranted, use it before generic web search, shell/curl GitHub calls, or "
            "fetching repository pages. Do not batch it with native WebSearch/WebFetch/Bash: inspect the MCP result first. Use "
            "a host tool only if this call fails, returns no usable items, or lacks a specific fact required by the question, and "
            "then query only that missing detail. This includes requests for a Windows screenshot app like macOS iShot that can "
            "export configurable rounded-corner images. Translate non-English intent into a concise GitHub query while preserving "
            "product names and requested features. Inspect specific returned repositories only when their metadata is insufficient "
            "to verify a requested feature."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {
                    "type": "string",
                    "description": "Required concise GitHub search terms, max 120 chars. Translate non-English intent and preserve product/feature names.",
                },
                "language": {"type": "string", "description": "Optional programming language, max 64 chars."},
                "sort": {"type": "string", "enum": sorted(_PROJECT_SORT_CHOICES), "default": "stars"},
                "limit": {"type": "integer", "description": "Maximum projects, 1-20.", "default": 10},
            },
            "required": ["q"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_github_ai_projects",
        "description": (
            "Recommended local-first search for public GitHub AI projects in the curated/enriched AIGC_NEWS library; it explicitly excludes the authenticated user's favorites. "
            "Use this as the default first search for Agent/MCP topics, including generic learning resources or 资料, tutorials, "
            "examples, implementations, SDKs, servers/clients, workflows, tool calling, demos, templates, and general exploration, "
            "even when the user does not explicitly say GitHub or open source. Also use it when the user requests open-source AI "
            "candidates or plans a complete RAG/LLM/Agent/MCP product, independent subsystem, local AI deployment, workflow automation, "
            "or architecture-level comparison. Use search_papers first only when the dominant requested output is explicitly scholarly: "
            "papers, literature, surveys, citations, benchmarks/evaluations, methods/theory, experiments, or research results. For mixed "
            "requests choose one initial tool by the dominant deliverable; do not batch GitHub AI and paper search together. Do not batch "
            "it with native WebSearch/WebFetch/Bash: inspect the MCP result first. Use a host tool only if this call fails, returns "
            "no usable items, or lacks a specific fact required by the question, and then query only that "
            "missing detail. Do not call it for narrow edits, styling, renames, clear bugs, or isolated function/component changes "
            "merely because AI terms appear. It supports language filters, categories, station recommendations, and star rankings. "
            "For non-AI GitHub or open-source software, call search_github_projects instead. Use returned AIGC_NEWS fields such as "
            "description_zh, tags, categories, language, stars, daily_star_growth, hot_score, and URL before inspecting repositories. "
            "If local results are zero, this tool may perform a bounded read-only AI-focused GitHub Search fallback labeled github_api_fallback."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Optional short project search keyword, max 120 chars. Prefer concise terms like RAG, Web UI, local deploy, agent, MCP."},
                "category": {"type": "string", "description": "Optional AIGC_NEWS project category slug, max 64 chars."},
                "subcategory": {"type": "string", "description": "Optional AIGC_NEWS project subcategory slug, max 64 chars."},
                "language": {"type": "string", "description": "Optional programming language, max 64 chars, e.g. Python."},
                "scope": {"type": "string", "enum": sorted(_PROJECT_SCOPE_CHOICES), "default": "all"},
                "sort": {"type": "string", "enum": sorted(_PROJECT_SORT_CHOICES), "default": "stars"},
                "limit": {"type": "integer", "description": "Maximum projects, 1-20.", "default": 10},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_project_library",
        "description": (
            "Legacy compatibility entry for the curated/enriched AIGC_NEWS GitHub AI project library with local-first behavior. "
            "Existing clients may keep using it. New requests should use search_github_ai_projects for AI projects or "
            "search_github_projects for non-AI GitHub/open-source software. sort=hot uses exact consecutive daily snapshots "
            "when available; direct AI-focused GitHub fallback is attempted only after local results are zero."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Optional project search keyword, max 120 chars."},
                "category": {"type": "string", "description": "Optional category slug, max 64 chars."},
                "subcategory": {"type": "string", "description": "Optional subcategory slug, max 64 chars."},
                "language": {"type": "string", "description": "Optional programming language, max 64 chars."},
                "scope": {"type": "string", "enum": sorted(_PROJECT_SCOPE_CHOICES), "default": "all"},
                "sort": {"type": "string", "enum": sorted(_PROJECT_SORT_CHOICES), "default": "stars"},
                "limit": {"type": "integer", "description": "Maximum projects, 1-20.", "default": 10},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_project_categories",
        "description": (
            "List public AIGC_NEWS GitHub AI project categories and subcategory counts. "
            "Call this first only when category/subcategory taxonomy is unclear, then call search_github_ai_projects or get_project_library. "
            "Do not use direct GitHub or web search just to discover available AIGC_NEWS project categories."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
]

_PRIVATE_MCP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_my_project_favorites",
        "description": "Search the authenticated user's private GitHub project favorites. Call this only for the user's own saved or favorited projects.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Optional search keyword, max 120 chars."},
                "category": {"type": "string", "description": "Optional category slug, max 64 chars."},
                "subcategory": {"type": "string", "description": "Optional subcategory slug, max 64 chars."},
                "language": {"type": "string", "description": "Optional programming language, max 64 chars."},
                "tag": {"type": "string", "description": "Optional favorite project tag, max 64 chars."},
                "sort": {"type": "string", "enum": sorted(_PROJECT_SORT_CHOICES), "default": "recent"},
                "limit": {"type": "integer", "description": "Maximum favorites per page, 1-20.", "default": 10},
                "marker": {"type": "string", "description": "Opaque zero-based pagination marker returned by the previous call."},
            },
            "required": [],
            "additionalProperties": False,
        },
    }
]


def _mcp_headers(session_id: str | None = None) -> dict[str, str]:
    headers = {"MCP-Protocol-Version": MCP_PROTOCOL_VERSION}
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    return headers


def _jsonrpc_result(request_id: Any, result: dict[str, Any], *, session_id: str | None = None) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "result": result},
        headers=_mcp_headers(session_id),
    )


def _jsonrpc_error(request_id: Any, code: int, message: str) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}},
        headers=_mcp_headers(),
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _tool_response(data: dict[str, Any], *, is_error: bool = False) -> dict[str, Any]:
    safe_data = _json_safe(data)
    text = json.dumps(safe_data, ensure_ascii=False)
    if len(text) > MAX_TOOL_RESULT_CHARS:
        safe_data = {
            "truncated": True,
            "reason": f"Tool result exceeded {MAX_TOOL_RESULT_CHARS} characters.",
            "preview": text[:MAX_TOOL_RESULT_CHARS],
        }
        text = json.dumps(safe_data, ensure_ascii=False)
    result: dict[str, Any] = {"content": [{"type": "text", "text": text}], "isError": is_error}
    if not is_error:
        result["structuredContent"] = safe_data
    return result


def _tool_error(message: str) -> dict[str, Any]:
    return _tool_response({"error": message}, is_error=True)


def _as_args(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise McpToolInputError("arguments 必须是 JSON 对象。")
    return value


def _clean_string(
    args: dict[str, Any],
    key: str,
    *,
    required: bool = False,
    max_len: int = 200,
    default: str = "",
) -> str:
    raw = args.get(key, default)
    if raw is None:
        raw = ""
    if not isinstance(raw, str):
        raise McpToolInputError(f"{key} 必须是字符串。")
    value = raw.strip()
    if required and not value:
        raise McpToolInputError(f"{key} 不能为空。")
    if len(value) > max_len:
        raise McpToolInputError(f"{key} 不能超过 {max_len} 个字符。")
    return value


def _clean_limit(args: dict[str, Any], *, default: int = 10, max_value: int = 20) -> int:
    raw = args.get("limit", default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise McpToolInputError("limit 必须是整数。") from None
    return max(1, min(value, max_value))


def _clean_choice(args: dict[str, Any], key: str, choices: set[str], *, default: str) -> str:
    value = _clean_string(args, key, max_len=64, default=default).lower() or default
    if value not in choices:
        raise McpToolInputError(f"{key} 必须是以下之一：{', '.join(sorted(choices))}。")
    return value


def _public_doc(doc: dict[str, Any], request: Request, *, dashboard: bool = False) -> dict[str, Any]:
    enriched = _enrich_doc_pdf_url(dict(doc), request) if dashboard else _enrich_pdf_url(dict(doc), request)
    enriched.pop("local_pdf_path", None)
    return enriched


def _clip_text(value: Any, max_chars: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= max_chars else text[: max_chars - 1].rstrip() + "…"


def _bounded_strings(value: Any, max_items: int = 4) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    items: list[str] = []
    for item in value:
        text = _clip_text(item, 40)
        if text and text not in items:
            items.append(text)
        if len(items) >= max_items:
            break
    return items


def _public_project_item(item: dict[str, Any]) -> dict[str, Any]:
    data = dict(item)
    return {
        "id": data.get("id"),
        "full_name": _clip_text(data.get("full_name") or data.get("title"), 160),
        "url": _clip_text(data.get("url"), 500),
        "description": _clip_text(data.get("description"), 180),
        "description_zh": _clip_text(data.get("description_zh"), 80),
        "category_slug": _clip_text(data.get("category_slug"), 64),
        "category_name": _clip_text(data.get("category_name"), 80),
        "subcategory_slug": _clip_text(data.get("subcategory_slug"), 64),
        "subcategory_name": _clip_text(data.get("subcategory_name"), 80),
        "tags": _bounded_strings(data.get("tags")),
        "topics": _bounded_strings(data.get("topics")),
        "language": _clip_text(data.get("language"), 64),
        "stars": int(data.get("stars") or 0),
        "forks": int(data.get("forks") or 0),
        "pushed_at": data.get("pushed_at"),
        "daily_star_growth": int(data.get("daily_star_growth") or 0),
        "daily_growth_available": bool(data.get("daily_growth_available")),
        "hot_score": float(data.get("hot_score") or 0),
        "is_recommended": bool(data.get("is_recommended")),
        "result_origin": _clip_text(data.get("result_origin") or "aigc_news_local", 40),
    }


async def _tool_search_papers(request: Request, args: dict[str, Any]) -> dict[str, Any]:
    q = _clean_string(args, "q", required=True, max_len=200)
    limit = _clean_limit(args)
    db = MySQLRepository()
    rows = await asyncio.to_thread(db.search_documents, q, limit)
    docs = [_safe_doc(dict(row)) for row in rows]
    items = [_public_doc(doc, request) for doc in docs]
    return {"q": q, "total": len(items), "items": items}


async def _tool_get_paper_detail(request: Request, args: dict[str, Any]) -> dict[str, Any]:
    paper_id = _clean_string(args, "paper_id", required=True, max_len=128)
    db = MySQLRepository()

    def _do_get() -> dict[str, Any] | None:
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

    doc = await asyncio.to_thread(_do_get)
    if not doc:
        raise McpToolInputError(f"Document {paper_id!r} not found.")
    return {"item": _public_doc(doc, request)}


async def _tool_get_top_items(request: Request, args: dict[str, Any]) -> dict[str, Any]:
    source = _clean_choice(args, "source", _SOURCE_CHOICES, default="all")
    period = _clean_choice(args, "period", _PERIOD_CHOICES, default="daily")
    date_value = _clean_string(args, "date", max_len=10, default="")
    if date_value and not _DATE_RE.fullmatch(date_value):
        raise McpToolInputError("date 必须是 YYYY-MM-DD 格式。")
    limit = _clean_limit(args)

    db = MySQLRepository()
    snapshot_date = _resolve_snapshot_date(date_value or None)
    board = _compute_board_status(snapshot_date)
    if board["is_embargoed"]:
        return {
            "items": [],
            "total": 0,
            "period": period,
            "source": source,
            "snapshot_date": snapshot_date,
            "is_finalized": board["is_finalized"],
            "is_embargoed": True,
        }

    source_type = None if source == "all" else source
    docs = await asyncio.to_thread(_get_docs_for_date, db, snapshot_date, period, source_type, 500)
    items = [_public_doc(dict(doc), request, dashboard=True) for doc in _dedupe_docs(docs)[:limit]]
    return {
        "items": items,
        "total": len(items),
        "period": period,
        "source": source,
        "snapshot_date": snapshot_date,
        "is_finalized": board["is_finalized"],
        "is_embargoed": False,
    }


async def _search_project_library(
    args: dict[str, Any],
    *,
    mode: str,
) -> dict[str, Any]:
    generic = mode == "generic"
    q = _clean_string(args, "q", required=generic, max_len=120)
    category = "" if generic else _clean_string(args, "category", max_len=64)
    subcategory = "" if generic else _clean_string(args, "subcategory", max_len=64)
    language = _clean_string(args, "language", max_len=64)
    scope = "all" if generic else _clean_choice(args, "scope", _PROJECT_SCOPE_CHOICES, default="all")
    requested_sort = _clean_choice(
        args,
        "sort",
        _PROJECT_SORT_CHOICES,
        default="hot" if scope == "today" else ("recent" if scope == "recommended" else "stars"),
    )
    sort = "hot" if scope == "today" else requested_sort
    limit = _clean_limit(args)
    return await search_projects(
        query=q,
        mode="generic" if generic else "ai",
        language=language,
        category=category,
        subcategory=subcategory,
        scope=scope,
        sort=sort,
        limit=limit,
        repository_factory=MySQLRepository,
        fallback_search=search_github_projects_fallback,
    )


async def _tool_search_github_projects(_request: Request, args: dict[str, Any]) -> dict[str, Any]:
    return await _search_project_library(args, mode="generic")


async def _tool_search_github_ai_projects(_request: Request, args: dict[str, Any]) -> dict[str, Any]:
    return await _search_project_library(args, mode="ai")


async def _tool_get_project_library(_request: Request, args: dict[str, Any]) -> dict[str, Any]:
    return await _search_project_library(args, mode="ai")


async def _tool_search_my_project_favorites(request: Request, args: dict[str, Any]) -> dict[str, Any]:
    user = getattr(request.state, "mcp_user", None)
    try:
        user_id = int((user or {}).get("user_id") or 0)
    except (TypeError, ValueError):
        user_id = 0
    if user_id <= 0:
        raise McpToolInputError("Authentication is required for this tool.")
    if "projects:favorites:read" not in (user or {}).get("scopes", frozenset()):
        raise McpToolInputError("This token requires the projects:favorites:read scope.")
    q = _clean_string(args, "q", max_len=120)
    category = _clean_string(args, "category", max_len=64)
    subcategory = _clean_string(args, "subcategory", max_len=64)
    language = _clean_string(args, "language", max_len=64)
    tag = _clean_string(args, "tag", max_len=64)
    sort = _clean_choice(args, "sort", _PROJECT_SORT_CHOICES, default="recent")
    limit = _clean_limit(args)
    marker = _clean_string(args, "marker", max_len=128)
    offset = 0
    if marker:
        try:
            padding = "=" * (-len(marker) % 4)
            marker_data = json.loads(base64.urlsafe_b64decode(marker + padding).decode("utf-8"))
            offset = int(marker_data["offset"])
            marker_limit = int(marker_data["limit"])
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            raise McpToolInputError("marker must be the opaque value returned by this tool.") from exc
        if offset < 0 or marker_limit != limit or offset % limit:
            raise McpToolInputError("marker is invalid or was issued for a different limit.")
    page = offset // limit + 1
    result = await asyncio.to_thread(
        MySQLRepository().list_user_project_collection,
        user_id=user_id,
        source="github",
        scope="all",
        category=category,
        subcategory=subcategory,
        q=q,
        language=language,
        tag=tag,
        page=page,
        page_size=limit,
        sort=sort,
        min_stars=500,
        enriched_only=True,
    )
    items = [_public_project_item(item) for item in result.get("items") or []]
    total = int(result.get("total") or 0)
    next_offset = offset + len(items)
    next_marker = None
    if next_offset < total:
        marker_json = json.dumps({"offset": next_offset, "limit": limit}, separators=(",", ":"))
        next_marker = base64.urlsafe_b64encode(marker_json.encode("utf-8")).decode("ascii").rstrip("=")
    return {
        "items": items,
        "total": total,
        "q": q,
        "tag": tag,
        "sort": sort,
        "marker": next_marker,
    }


async def _tool_get_project_categories(_request: Request, args: dict[str, Any]) -> dict[str, Any]:
    if args:
        raise McpToolInputError("get_project_categories 不接受参数。")
    db = MySQLRepository()
    result = await asyncio.to_thread(
        db.get_project_categories,
        source="github",
        min_stars=500,
        enriched_only=True,
    )
    return {
        "items": result.get("items") or [],
        "total": int(result.get("total") or 0),
        "today_count": int(result.get("today_count") or 0),
        "recommended_count": int(result.get("recommended_count") or 0),
        "min_stars": 500,
        "source": "github",
    }


_TOOL_HANDLERS: dict[str, Callable[[Request, dict[str, Any]], Awaitable[dict[str, Any]]]] = {
    "search_papers": _tool_search_papers,
    "get_paper_detail": _tool_get_paper_detail,
    "get_top_items": _tool_get_top_items,
    "search_github_projects": _tool_search_github_projects,
    "search_github_ai_projects": _tool_search_github_ai_projects,
    "get_project_library": _tool_get_project_library,
    "get_project_categories": _tool_get_project_categories,
    "search_my_project_favorites": _tool_search_my_project_favorites,
}


def _resource_content(uri: str, data: Any, *, mime_type: str = "application/json") -> dict[str, Any]:
    if mime_type == "application/json":
        text = json.dumps(_json_safe(data), ensure_ascii=False)
        if len(text) > MAX_RESOURCE_TEXT_CHARS:
            text = json.dumps(
                {
                    "truncated": True,
                    "reason": f"Resource exceeded {MAX_RESOURCE_TEXT_CHARS} characters.",
                    "preview": text[:MAX_RESOURCE_TEXT_CHARS],
                },
                ensure_ascii=False,
            )
    else:
        text = str(data or "")
        if len(text) > MAX_RESOURCE_TEXT_CHARS:
            text = text[:MAX_RESOURCE_TEXT_CHARS] + "\n\n[truncated]"

    return {"contents": [{"uri": uri, "mimeType": mime_type, "text": text}]}


def _parse_resource_uri(uri: Any) -> tuple[str, dict[str, str]]:
    if not isinstance(uri, str) or not uri.strip():
        raise McpResourceInputError("resources/read params.uri is required.")
    parsed = urlparse(uri.strip())
    if parsed.scheme != "aigc-news":
        raise McpResourceInputError("Only aigc-news:// resource URIs are supported.")
    path = f"{unquote(parsed.netloc)}{unquote(parsed.path)}".strip("/")
    if not path:
        raise McpResourceInputError("Resource URI path is required.")
    query = {
        key: values[-1]
        for key, values in parse_qs(parsed.query, keep_blank_values=True).items()
        if values
    }
    return path, query


def _resolve_report_date(period: str, date_str: str = "") -> str:
    today = _date.today()
    if date_str:
        try:
            anchor = _dt.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            raise McpResourceInputError("date must use YYYY-MM-DD format.") from None
    else:
        anchor = today

    if period == "weekly":
        anchor = anchor - _td(days=anchor.weekday())
    elif period == "monthly":
        anchor = anchor.replace(day=1)
    return anchor.isoformat()


async def _resource_dashboard_summary(request: Request, uri: str, query: dict[str, str]) -> dict[str, Any]:
    period = _clean_choice(query, "period", _PERIOD_CHOICES, default="daily")
    date_value = _clean_string(query, "date", max_len=10, default="")
    if date_value and not _DATE_RE.fullmatch(date_value):
        raise McpResourceInputError("date must use YYYY-MM-DD format.")

    db = MySQLRepository()
    snapshot_date = _resolve_snapshot_date(date_value or None)
    board = _compute_board_status(snapshot_date)
    source_counts = await asyncio.to_thread(db.get_source_counts)
    total_documents = sum(int(value or 0) for value in source_counts.values())
    today_new_documents = await asyncio.to_thread(db.get_today_document_count)

    if board["is_embargoed"]:
        return _resource_content(
            uri,
            {
                "top_list": [],
                "radar": [],
                "stats": {
                    "total_documents": total_documents,
                    "today_new_documents": today_new_documents,
                    "source_counts": source_counts,
                },
                "period": period,
                "snapshot_date": snapshot_date,
                "is_finalized": board["is_finalized"],
                "is_embargoed": True,
            },
        )

    docs = await asyncio.to_thread(_get_docs_for_date, db, snapshot_date, period, None, 500)
    deduped = _dedupe_docs(docs)
    top10 = [_public_doc(dict(doc), request, dashboard=True) for doc in deduped[:10]]
    return _resource_content(
        uri,
        {
            "top_list": top10,
            "radar": _score_categories(deduped[:50]),
            "stats": {
                "total_documents": total_documents,
                "today_new_documents": today_new_documents,
                "source_counts": source_counts,
            },
            "period": period,
            "snapshot_date": snapshot_date,
            "is_finalized": board["is_finalized"],
            "is_embargoed": False,
        },
    )


async def _resource_report_latest(uri: str, query: dict[str, str]) -> dict[str, Any]:
    source = _clean_choice(query, "source", _SOURCE_CHOICES, default="all")
    period = _clean_choice(query, "period", _PERIOD_CHOICES, default="daily")
    date_value = _clean_string(query, "date", max_len=10, default="")
    target = _resolve_report_date(period, date_value)
    suffix = "" if source == "all" else f"_{source}"
    cache_key = f"{target}{suffix}_{period}"
    db = MySQLRepository()
    item = await asyncio.to_thread(db.get_briefing_by_date, cache_key)
    if item is None:
        raise McpResourceInputError(f"Briefing {cache_key!r} not found.")
    return _resource_content(uri, item.get("content", ""), mime_type="text/markdown")


async def _read_resource(request: Request, uri: Any) -> dict[str, Any]:
    path, query = _parse_resource_uri(uri)

    try:
        if path == "dashboard/summary":
            return await _resource_dashboard_summary(request, uri, query)
        if path == "dashboard/top":
            return _resource_content(uri, await _tool_get_top_items(request, query))
        if path == "projects/categories":
            return _resource_content(uri, await _tool_get_project_categories(request, {}))
        if path == "projects/library":
            return _resource_content(uri, await _tool_get_project_library(request, query))
        if path == "report/latest":
            return await _resource_report_latest(uri, query)
        if path.startswith("papers/"):
            paper_id = path.removeprefix("papers/").strip()
            return _resource_content(uri, await _tool_get_paper_detail(request, {"paper_id": paper_id}))
    except McpToolInputError as exc:
        raise McpResourceInputError(str(exc)) from exc

    raise McpResourceInputError(f"Unknown resource URI: {uri}")


def _prompt_arg(arguments: dict[str, Any], key: str, *, max_len: int = 120) -> str:
    value = arguments.get(key, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise McpPromptInputError(f"{key} must be a string.")
    return value.strip()[:max_len]


def _prompt_message(text: str) -> dict[str, Any]:
    return {"role": "user", "content": {"type": "text", "text": text.strip()}}


def _get_prompt(name: Any, arguments: Any) -> dict[str, Any]:
    if not isinstance(name, str) or not name:
        raise McpPromptInputError("prompts/get params.name is required.")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise McpPromptInputError("prompts/get params.arguments must be an object.")

    if name == "daily_research_brief":
        source = _prompt_arg(arguments, "source", max_len=32) or "all"
        if source not in _SOURCE_CHOICES:
            source = "all"
        topic = _prompt_arg(arguments, "topic", max_len=120)
        topic_line = f" Focus on this topic: {topic}." if topic else ""
        text = f"""
Use the AIGC_NEWS MCP public context to produce a concise research brief.{topic_line}

Suggested flow:
1. Read `aigc-news://dashboard/summary` for the latest overall context.
2. For generic Agent/MCP learning, tutorials, examples, implementations, SDK/server/client resources, workflows, tool calling, or unspecified 资料, call `search_github_ai_projects` first even if GitHub/open source was not named.
3. Use `search_papers` first only when the dominant requested output is explicitly scholarly: papers, literature, surveys, citations, authors/venues, benchmarks/evaluations, methods/theory, experiments, or research results. Rewrite academic requests into 1-3 concise technical terms.
4. For mixed requests choose one initial route by the dominant deliverable: implementations/tutorials use GitHub AI; papers/citations/experimental results use papers. Do not batch both primary searches or MCP and host web tools in the same initial tool message.
5. Inspect the selected AIGC_NEWS result before adding another source. If the MCP call fails, returns no relevant items, or lacks a specific fact, use another MCP tool or a host web tool only for that missing detail.
6. If a specific indexed item matters, call `get_paper_detail` for its id.
7. Summarize key trends, notable papers/projects/news, and why they matter, distinguishing AIGC_NEWS evidence from any later web fallback.

These instructions guide MCP-aware agents; the MCP server cannot override a client's own system prompt or native tool priorities. Do not use private user data or admin-only operations.
"""
        return {
            "description": "Summarize the latest public AIGC_NEWS context.",
            "messages": [_prompt_message(text)],
        }

    if name == "project_discovery":
        topic = _prompt_arg(arguments, "topic", max_len=120)
        category = _prompt_arg(arguments, "category", max_len=64)
        language = _prompt_arg(arguments, "language", max_len=64)
        filters = []
        if topic:
            filters.append(f"topic `{topic}`")
        if category:
            filters.append(f"category `{category}`")
        if language:
            filters.append(f"language `{language}`")
        filter_text = " Focus on " + " and ".join(filters) + "." if filters else ""
        text = f"""
Use the AIGC_NEWS MCP public GitHub project context to discover useful projects.{filter_text}

Decision policy before searching:
- First reuse capabilities already present in the current codebase and dependencies.
- Do not call project search for typo fixes, styling/copy, renames, clear bugs, validation/field changes, tests/logging/types, simple CRUD, or isolated function/component/endpoint changes.
- Always search when the user explicitly asks for open-source alternatives, describes a complete product or independent subsystem, references an existing product, or requests mature/high-risk infrastructure such as auth, payments, permissions, workflow engines, search engines, queues, collaboration, protocol implementations, or sandboxes.
- For remaining development requests, score 0-3 on scope, standardization, external integration, risk, expected effort, and reuse potential. Total 0-4 means implement directly; 5-8 means one light search only when it can change the decision; 9-18 means search and ask the user to choose a route.

Local-first search policy:
- For qualifying non-AI software requests, call `search_github_projects` before generic web/GitHub search.
- For Agent/MCP topics, `search_github_ai_projects` is the default first route for generic learning or 资料, tutorials, examples, implementations, SDKs, servers/clients, workflows, tool calling, demos, templates, and exploration, even without an explicit GitHub/open-source request.
- Use `search_papers` first only when the dominant deliverable is explicitly scholarly (papers/literature/surveys/citations/benchmarks/evaluations/methods/theory/experiments/research results). For mixed requests choose one initial route by the dominant deliverable; do not batch both searches.
- For other qualifying AI requests (RAG, local deployment, Web UI, workflow automation, Python AI repos), call `search_github_ai_projects` first.
- Do not put the selected MCP search and native WebSearch/WebFetch/Bash in the same initial tool batch. Await and inspect the MCP result first.
- Use a host tool only if the MCP call fails, returns no usable items, or lacks a specific fact required by the request; query only that missing detail rather than repeating the broad discovery search.
- `get_project_library` remains a legacy AI alias.
- For broad discovery/comparison questions, use the returned AIGC_NEWS local fields (`description`, `description_zh`, `tags`, `topics`, category/subcategory, language, stars, forks, pushed_at, url) as the project summary and evidence.
- Do not inspect each returned GitHub repository just to summarize candidates. Only visit GitHub/README/docs when the user explicitly asks about one or several named projects, or when local MCP metadata is insufficient to answer a concrete follow-up question.
- Direct GitHub fallback is only appropriate when the MCP result reports `local_total: 0` / no local AIGC_NEWS matches.

Suggested flow:
1. If category/subcategory is unclear, read `aigc-news://projects/categories` or call `get_project_categories`.
2. Call `search_github_projects` for generic software, or `search_github_ai_projects` for AI projects, with concise `q`, relevant filters, sort `stars` or `hot`, and limit 5-10.
3. If `fallback_used` is false or `local_total` is positive, answer from the curated AIGC_NEWS local project library without re-checking every GitHub repo.
4. If local metadata is insufficient, explain what is missing; only then inspect the specific returned repo(s) needed for that missing detail.
5. If `fallback_used` is true and `result_origin` is `github_api_fallback`, clearly label those results as direct GitHub fallback rather than curated local catalog entries.
6. Filter candidates by requirement match, maintenance, integration fit, documentation, license fit, community, and security/stability; stars alone are not suitability.
7. Show only the best 2-3 candidates. If none clearly saves implementation effort or reduces risk, recommend building within the current project without forcing a meaningless choice.
8. If adopting a candidate changes architecture, deployment, data ownership, licensing, or long-term maintenance, stop and ask the user to choose: reuse a numbered candidate, build from scratch, or refine and search again. Do not start implementation in the same turn.
9. Run at most one initial search per unchanged requirement. Search again only when the user asks, filters change, the first result is empty, or candidates are incompatible.

These instructions guide MCP-aware agents; the MCP server cannot override a client's own system prompt or native tool priorities. Do not use personal favorites or admin-only MCP server configuration.
"""
        return {
            "description": "Discover and compare public AI GitHub projects with local-first AIGC_NEWS MCP search.",
            "messages": [_prompt_message(text)],
        }

    raise McpPromptInputError(f"Unknown prompt: {name}")


async def _call_tool(request: Request, name: str, arguments: Any) -> dict[str, Any]:
    handler = _TOOL_HANDLERS.get(name)
    if handler is None:
        return _tool_error(f"Unknown tool: {name}")
    try:
        data = await handler(request, _as_args(arguments))
        return _tool_response(data)
    except McpToolInputError as exc:
        return _tool_error(str(exc))
    except Exception:
        logger.exception("MCP tool call failed: %s", name)
        return _tool_error("Tool execution failed.")


@router.post("/mcp", tags=["MCP"])
async def mcp_endpoint(
    request: Request,
    mcp_user: dict[str, Any] | None = Depends(OptionalMcpUser),
) -> Response:
    request.state.mcp_user = mcp_user
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_REQUEST_BYTES:
                return _jsonrpc_error(None, _JSONRPC_INVALID_REQUEST, "Request body too large")
        except ValueError:
            return _jsonrpc_error(None, _JSONRPC_INVALID_REQUEST, "Invalid Content-Length")

    raw = await request.body()
    if len(raw) > MAX_REQUEST_BYTES:
        return _jsonrpc_error(None, _JSONRPC_INVALID_REQUEST, "Request body too large")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, JSONDecodeError):
        return _jsonrpc_error(None, _JSONRPC_PARSE_ERROR, "Parse error")

    if isinstance(payload, list):
        return _jsonrpc_error(None, _JSONRPC_INVALID_REQUEST, "Batch JSON-RPC requests are not supported")
    if not isinstance(payload, dict):
        return _jsonrpc_error(None, _JSONRPC_INVALID_REQUEST, "Invalid Request")

    request_id = payload.get("id")
    if request_id is not None and not isinstance(request_id, (str, int, float)):
        return _jsonrpc_error(None, _JSONRPC_INVALID_REQUEST, "Invalid request id")
    if payload.get("jsonrpc") != "2.0":
        return _jsonrpc_error(request_id, _JSONRPC_INVALID_REQUEST, "Invalid JSON-RPC version")

    method = payload.get("method")
    if not isinstance(method, str) or not method:
        return _jsonrpc_error(request_id, _JSONRPC_INVALID_REQUEST, "Missing method")

    params = payload.get("params") or {}
    if params is not None and not isinstance(params, dict):
        return _jsonrpc_error(request_id, _JSONRPC_INVALID_PARAMS, "params must be an object")

    if method == "notifications/initialized" and "id" not in payload:
        return Response(status_code=204, headers=_mcp_headers())

    if "id" not in payload:
        return _jsonrpc_error(None, _JSONRPC_INVALID_REQUEST, "Request id is required")

    if method == "initialize":
        session_id = f"aigc-news-{uuid.uuid4().hex}"
        return _jsonrpc_result(
            request_id,
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"subscribe": False, "listChanged": False},
                    "prompts": {"listChanged": False},
                },
                "serverInfo": {"name": MCP_SERVER_NAME, "version": MCP_SERVER_VERSION},
            },
            session_id=session_id,
        )

    if method == "tools/list":
        tools = MCP_TOOLS + (_PRIVATE_MCP_TOOLS if mcp_user else [])
        return _jsonrpc_result(request_id, {"tools": tools})

    if method == "tools/call":
        name = params.get("name") if isinstance(params, dict) else None
        if not isinstance(name, str) or not name:
            return _jsonrpc_error(request_id, _JSONRPC_INVALID_PARAMS, "tools/call params.name is required")
        arguments = params.get("arguments", {}) if isinstance(params, dict) else {}
        if name == "search_my_project_favorites" and not mcp_user:
            result = _tool_error("Authentication is required for this tool.")
        else:
            result = await _call_tool(request, name, arguments)
        return _jsonrpc_result(request_id, result)

    if method == "resources/list":
        return _jsonrpc_result(request_id, {"resources": MCP_RESOURCES})

    if method == "resources/templates/list":
        return _jsonrpc_result(request_id, {"resourceTemplates": MCP_RESOURCE_TEMPLATES})

    if method == "resources/read":
        try:
            result = await _read_resource(request, params.get("uri"))
        except McpResourceInputError as exc:
            return _jsonrpc_error(request_id, _JSONRPC_INVALID_PARAMS, str(exc))
        except Exception:
            logger.exception("MCP resource read failed: %s", params.get("uri"))
            return _jsonrpc_error(request_id, _JSONRPC_INTERNAL_ERROR, "Resource read failed")
        return _jsonrpc_result(request_id, result)

    if method == "prompts/list":
        return _jsonrpc_result(request_id, {"prompts": MCP_PROMPTS})

    if method == "prompts/get":
        try:
            result = _get_prompt(params.get("name"), params.get("arguments", {}))
        except McpPromptInputError as exc:
            return _jsonrpc_error(request_id, _JSONRPC_INVALID_PARAMS, str(exc))
        return _jsonrpc_result(request_id, result)

    return _jsonrpc_error(request_id, _JSONRPC_METHOD_NOT_FOUND, "Method not found")
