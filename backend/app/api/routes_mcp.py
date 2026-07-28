from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid
from datetime import date as _date, datetime as _dt, timedelta as _td
from json import JSONDecodeError
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs, unquote, urlparse

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from backend.app.api.dependencies import (
    get_application_repositories,
    get_briefing_repository,
)
from backend.app.api.mcp_contracts import TOOL_INPUT_MODELS, input_schema, validate_iso_date
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
from backend.app.repositories.application_repository_factory import ApplicationRepositories
from backend.app.repositories.briefing_repository import BriefingReader
from backend.app.repositories.document_repository import (
    DocumentSearchReader,
    DocumentStatisticsReader,
    PapersReader,
)
from backend.app.repositories.project_write_repository import (
    UserProjectCollectionRepository,
)
from backend.app.repositories.rank_snapshot_repository import RankSnapshotReader
from backend.app.repositories.project_catalog_factory import get_project_catalog_repository
from backend.app.services.ingestion.source_github_mcp import search_github_projects_fallback
from backend.app.services.mcp.inbound.catalog import (
    MCP_HOST_INSTRUCTIONS,
    MCP_PRIVATE_TOOL_NAMES,
    MCP_PROMPTS,
    MCP_PROTOCOL_VERSION,
    MCP_PUBLIC_TOOL_NAMES,
    MCP_RESOURCES,
    MCP_RESOURCE_TEMPLATES,
    MCP_SERVER_NAME,
    MCP_SERVER_VERSION,
    MCP_TOOLS,
    MCP_TOOL_DEFINITIONS,
    MCP_TOOL_INPUT_MODELS,
    MAX_REQUEST_BYTES,
    MAX_RESOURCE_TEXT_CHARS,
    MAX_TOOL_RESULT_CHARS,
    _DATE_RE,
    _JSONRPC_INTERNAL_ERROR,
    _JSONRPC_INVALID_PARAMS,
    _JSONRPC_INVALID_REQUEST,
    _JSONRPC_METHOD_NOT_FOUND,
    _JSONRPC_PARSE_ERROR,
    _PERIOD_CHOICES,
    _PRIVATE_MCP_TOOLS,
    _PROJECT_FALLBACK_POLICY,
    _PROJECT_SCOPE_CHOICES,
    _PROJECT_SORT_CHOICES,
    _SOURCE_CHOICES,
)
from backend.app.services.mcp.inbound.responses import (
    _json_safe,
    _resource_content,
    _tool_error,
    _tool_response,
)
from backend.app.services.project_discovery import public_project_item, search_projects

logger = logging.getLogger(__name__)

router = APIRouter()

class McpToolInputError(ValueError):
    """Raised when MCP tool arguments are invalid."""


class McpResourceInputError(ValueError):
    """Raised when MCP resource parameters are invalid."""


class McpPromptInputError(ValueError):
    """Raised when MCP prompt parameters are invalid."""



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
    return public_project_item(item)


async def _search_indexed_documents(
    request: Request,
    args: dict[str, Any],
    *,
    source: str | None,
) -> dict[str, Any]:
    q = args["q"]
    page = args.get("page", 1)
    limit = args.get("limit", 10)
    documents: DocumentSearchReader = request.state.document_repository
    result = await asyncio.to_thread(
        documents.search_document_page,
        q,
        source=source,
        page=page,
        page_size=limit,
    )
    docs = [_safe_doc(dict(row)) for row in result.get("items") or []]
    items = [_public_doc(doc, request) for doc in docs]
    total = int(result.get("total") or 0)
    return {
        "q": q,
        "source": source or "all",
        "total": total,
        "returned_count": len(items),
        "page": page,
        "page_size": limit,
        "has_next": page * limit < total,
        "items": items,
    }


async def _tool_search_papers(request: Request, args: dict[str, Any]) -> dict[str, Any]:
    return await _search_indexed_documents(request, args, source="arxiv")


async def _tool_search_documents(request: Request, args: dict[str, Any]) -> dict[str, Any]:
    source = args["source"]
    return await _search_indexed_documents(
        request,
        args,
        source=None if source == "all" else source,
    )


async def _tool_get_paper_detail(
    request: Request,
    args: dict[str, Any],
    papers: PapersReader | None = None,
) -> dict[str, Any]:
    paper_id = _clean_string(args, "paper_id", required=True, max_len=128)
    reader = papers or request.state.papers_repository
    row = await asyncio.to_thread(reader.get_paper_detail, paper_id)
    if row is None:
        raise McpToolInputError(f"Document {paper_id!r} not found.")
    doc = _safe_doc(dict(row))
    return {"item": _public_doc(doc, request)}


async def _tool_get_top_items(request: Request, args: dict[str, Any]) -> dict[str, Any]:
    source = args.get("source", "all")
    period = args.get("period", "daily")
    date_value = args.get("date") or ""
    limit = args.get("limit", 10)

    rank_snapshots: RankSnapshotReader = request.state.rank_snapshot_repository
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
    docs = await asyncio.to_thread(
        _get_docs_for_date,
        rank_snapshots,
        snapshot_date,
        period,
        source_type,
        500,
    )
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
    q = args.get("q", "")
    category = "" if generic else args.get("category", "")
    subcategory = "" if generic else args.get("subcategory", "")
    language = args.get("language", "")
    scope = "all" if generic else args.get("scope", "all")
    sort = args.get("sort")
    page = args.get("page", 1)
    limit = args.get("limit", 10)
    return await search_projects(
        query=q,
        mode="generic" if generic else "ai",
        language=language,
        client_intent=None if generic else args.get("intent"),
        category=category,
        subcategory=subcategory,
        scope=scope,
        sort=sort,
        page=page,
        limit=limit,
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
    project_collections: UserProjectCollectionRepository = (
        request.state.project_collection_repository
    )
    result = await asyncio.to_thread(
        project_collections.list_user_project_collection,
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
    db = get_project_catalog_repository()
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
    "search_documents": _tool_search_documents,
    "get_paper_detail": _tool_get_paper_detail,
    "get_top_items": _tool_get_top_items,
    "search_github_projects": _tool_search_github_projects,
    "search_github_ai_projects": _tool_search_github_ai_projects,
    "get_project_library": _tool_get_project_library,
    "get_project_categories": _tool_get_project_categories,
    "search_my_project_favorites": _tool_search_my_project_favorites,
}
MCP_TOOL_REGISTRY = {
    name: {
        "definition": MCP_TOOL_DEFINITIONS[name],
        "input_model": MCP_TOOL_INPUT_MODELS[name],
        "handler": handler,
    }
    for name, handler in _TOOL_HANDLERS.items()
}



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
            validate_iso_date(date_str)
            anchor = _date.fromisoformat(date_str)
        except ValueError as exc:
            raise McpResourceInputError(str(exc)) from exc
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
    if date_value:
        try:
            validate_iso_date(date_value)
        except ValueError as exc:
            raise McpResourceInputError(str(exc)) from exc

    document_statistics: DocumentStatisticsReader = request.state.document_repository
    rank_snapshots: RankSnapshotReader = request.state.rank_snapshot_repository
    snapshot_date = _resolve_snapshot_date(date_value or None)
    board = _compute_board_status(snapshot_date)
    source_counts = await asyncio.to_thread(document_statistics.get_source_counts)
    total_documents = sum(int(value or 0) for value in source_counts.values())
    today_new_documents = await asyncio.to_thread(
        document_statistics.get_today_document_count
    )

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

    docs = await asyncio.to_thread(
        _get_docs_for_date,
        rank_snapshots,
        snapshot_date,
        period,
        None,
        500,
    )
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


async def _resource_report_latest(
    uri: str,
    query: dict[str, str],
    repository: BriefingReader,
) -> dict[str, Any]:
    source = _clean_choice(query, "source", _SOURCE_CHOICES, default="all")
    period = _clean_choice(query, "period", _PERIOD_CHOICES, default="daily")
    date_value = _clean_string(query, "date", max_len=10, default="")
    target = _resolve_report_date(period, date_value)
    suffix = "" if source == "all" else f"_{source}"
    cache_key = f"{target}{suffix}_{period}"
    item = await asyncio.to_thread(repository.get_briefing_by_date, cache_key)
    if item is None:
        raise McpResourceInputError(f"Briefing {cache_key!r} not found.")
    return _resource_content(uri, item.get("content", ""), mime_type="text/markdown")


def _resource_tool_args(query: dict[str, str], *, integer_fields: set[str]) -> dict[str, Any]:
    args: dict[str, Any] = dict(query)
    for field in integer_fields:
        if field not in args:
            continue
        raw = args[field]
        try:
            args[field] = int(raw)
        except (TypeError, ValueError):
            raise McpResourceInputError(f"{field} must be an integer.") from None
    return args


async def _read_resource(
    request: Request,
    uri: Any,
    briefing_repository: BriefingReader,
) -> dict[str, Any]:
    path, query = _parse_resource_uri(uri)

    try:
        if path == "dashboard/summary":
            return await _resource_dashboard_summary(request, uri, query)
        if path == "dashboard/top":
            return _resource_content(
                uri,
                await _tool_get_top_items(
                    request,
                    _validated_tool_args(
                        "get_top_items",
                        _resource_tool_args(query, integer_fields={"limit"}),
                    ),
                ),
            )
        if path == "projects/categories":
            return _resource_content(uri, await _tool_get_project_categories(request, {}))
        if path == "projects/library":
            return _resource_content(
                uri,
                await _tool_get_project_library(
                    request,
                    _validated_tool_args(
                        "get_project_library",
                        _resource_tool_args(query, integer_fields={"page", "limit"}),
                    ),
                ),
            )
        if path == "report/latest":
            return await _resource_report_latest(uri, query, briefing_repository)
        if path.startswith("papers/"):
            paper_id = path.removeprefix("papers/").strip()
            return _resource_content(
                uri,
                await _tool_get_paper_detail(
                    request,
                    _validated_tool_args("get_paper_detail", {"paper_id": paper_id}),
                ),
            )
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

Routing policy:
- Any explicit request to find, search, recommend, compare, or reuse a project, repository, open-source implementation, SDK, framework, component, template, example, or tutorial starts with one matching AIGC_NEWS MCP search, even if GitHub or open source was not named.
- Before implementing a major module, complete capability, or independent subsystem, perform one proactive project reuse check even without explicit discovery intent.
- Use `search_github_ai_projects` for AI/Agent/MCP/RAG/LLM engineering artifacts and `search_github_projects` for non-AI software artifacts. Requests to improve AI development efficiency, accelerate AI application delivery, or reduce repeated AI engineering work use `search_github_ai_projects` first.
- Use `search_papers` first only when the dominant requested output is explicitly scholarly: papers, literature, surveys, citations, authors/venues, academic benchmarks/evaluations, methods/theory, experiments, or research results. It returns arXiv papers only.
- Do not proactively search for copy or styling, renames, clear localized bugs, tests/logging/types, validation or field adjustments, simple CRUD, or an isolated function, component, or endpoint change.

Suggested flow:
1. Read `aigc-news://dashboard/summary` for the latest overall context.
2. Choose exactly one initial search route by the dominant deliverable and run at most one initial search per unchanged requirement. For mixed requests, do not batch primary searches.
3. Rewrite academic requests into 1-3 concise technical terms. Use `search_documents` only for explicit AIGC_NEWS indexed news/feed or cross-source searches.
4. Do not batch the selected MCP search with host WebSearch/WebFetch/Bash. Await and inspect the selected AIGC_NEWS result first.
5. If the MCP call fails, returns no usable or relevant items, or lacks a specific external fact, use another MCP tool or a host web tool only for that missing detail. All public project candidates require at least 500 GitHub stars; verify the current count for native WebSearch candidates and omit unverifiable or below-threshold projects.
6. Treat 500 stars as an eligibility floor, not proof of maintenance, security, license fit, documentation quality, or integration suitability. If reuse changes architecture, deployment, data ownership, licensing, or long-term maintenance, present reuse, design-reference, and build-from-scratch options and await the user's choice.
7. If a specific indexed item matters, call `get_paper_detail` for its id.
8. Summarize key trends, notable papers/projects/news, and why they matter, distinguishing AIGC_NEWS evidence from any later web fallback.

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

MCP-first discovery and reuse policy:
- Whenever the user explicitly asks to find, search, recommend, compare, or reuse a project, repository, open-source implementation, SDK, framework, component, template, example, or tutorial, call one matching AIGC_NEWS MCP search first. The user does not need to say GitHub or open source.
- Before implementing a major module, complete capability, or independent subsystem, perform one proactive reuse check even without explicit discovery intent. This means a cohesive capability with its own architecture, integration, or maintenance boundary—not merely a large diff. Examples include auth/permissions, payments, workflow engines, queues, search/indexing, collaboration, protocol implementations, sandboxes, local AI deployment, and end-to-end RAG or Agent subsystems.
- For AI, Agent, MCP, RAG, or LLM engineering artifacts, call `search_github_ai_projects` first. Requests to improve AI development efficiency, accelerate AI application delivery, or reduce repeated AI engineering work also use it first. For non-AI software artifacts, call `search_github_projects` first.
- Use `search_papers` first only when the dominant deliverable is explicitly scholarly: papers, literature, surveys, citations, authors/venues, academic benchmarks/evaluations, methods/theory, experiments, or research results.
- For mixed requests choose exactly one initial route by the dominant deliverable; do not batch primary searches.
- Do not proactively search for copy or styling, renames, clear localized bugs, tests/logging/types, validation or field adjustments, simple CRUD, or an isolated function, component, or endpoint change.
- Do not put the selected MCP search and native WebSearch/WebFetch/Bash in the same initial tool batch. Await and inspect the MCP result first.
- Use a host tool only if the MCP call fails, returns no usable or relevant items, or lacks a specific external fact required by the request; query only that missing detail rather than repeating the broad discovery search.
- All public local and direct-GitHub project results enforce a minimum of 500 GitHub stars. Before a native WebSearch candidate enters the comparison set, verify its current count is at least 500 and omit candidates whose count is unverifiable or below 500.
- `get_project_library` remains a legacy AI alias.
- For broad discovery/comparison questions, use the returned AIGC_NEWS local fields (`description`, `description_zh`, `tags`, `topics`, category/subcategory, language, stars, forks, pushed_at, url) as the project summary and evidence.
- Do not inspect each returned GitHub repository just to summarize candidates. Only visit GitHub/README/docs when the user explicitly asks about one or several named projects, or when local MCP metadata is insufficient to answer a concrete follow-up question.
- Direct GitHub fallback is only appropriate when the MCP result reports `local_total: 0` / no local AIGC_NEWS matches.

Suggested flow:
1. If category/subcategory is unclear, read `aigc-news://projects/categories` or call `get_project_categories`.
2. Call `search_github_projects` for non-AI software, or `search_github_ai_projects` for AI engineering artifacts, with concise `q`, relevant filters, and limit 5-10. AI queries default to `relevance`; use `stars` or `hot` only when the user explicitly wants popularity or trend order.
3. If `fallback_used` is false or `local_total` is positive, answer from the curated AIGC_NEWS local project library without re-checking every GitHub repo.
4. If local metadata is insufficient, explain what is missing; only then inspect the specific returned repo(s) needed for that missing detail.
5. If `fallback_used` is true and `result_origin` is `github_api_fallback`, clearly label those results as direct GitHub fallback rather than curated local catalog entries.
6. Filter candidates by requirement match, maintenance, integration fit, documentation, license fit, community, and security/stability. The 500-star minimum is mandatory eligibility, but stars alone do not establish suitability.
7. Show only the best 2-3 candidates. If none clearly saves implementation effort or reduces risk, recommend building within the current project without forcing a meaningless choice.
8. If adopting a candidate changes architecture, deployment, data ownership, licensing, or long-term maintenance, stop and ask the user to choose: reuse a numbered candidate, use it only as a design reference and build internally, build from scratch, or refine and search again. Do not start implementation in the same turn.
9. Run at most one initial search per unchanged requirement. Search again only when the user asks, filters change, the first result is empty, or candidates are incompatible.

These instructions guide MCP-aware agents; the MCP server cannot override a client's own system prompt or native tool priorities. Do not use personal favorites or admin-only MCP server configuration.
"""
        return {
            "description": "Discover, compare, and evaluate reusable public projects with local-first AIGC_NEWS MCP search.",
            "messages": [_prompt_message(text)],
        }

    raise McpPromptInputError(f"Unknown prompt: {name}")


def _validated_tool_args(name: str, arguments: Any) -> dict[str, Any]:
    input_model = TOOL_INPUT_MODELS.get(name)
    if input_model is None:
        raise McpToolInputError(f"Unknown tool: {name}")
    if not isinstance(arguments, dict):
        raise McpToolInputError("arguments 必须是 JSON 对象。")
    try:
        return input_model.model_validate(arguments).model_dump()
    except ValidationError as exc:
        detail = "; ".join(
            ".".join(str(part) for part in error["loc"]) + ": " + error["msg"]
            for error in exc.errors(include_url=False)
        )
        raise McpToolInputError(detail) from exc


async def _call_tool(request: Request, name: str, arguments: Any) -> dict[str, Any]:
    handler = _TOOL_HANDLERS.get(name)
    if handler is None:
        return _tool_error(f"Unknown tool: {name}")
    try:
        data = await handler(request, _validated_tool_args(name, arguments))
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
    briefing_repository: BriefingReader = Depends(get_briefing_repository),
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> Response:
    request.state.mcp_user = mcp_user
    request.state.papers_repository = repositories.documents
    request.state.document_repository = repositories.documents
    request.state.rank_snapshot_repository = repositories.rank_snapshots
    request.state.project_collection_repository = repositories.project_collections
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

    if "params" not in payload:
        params: dict[str, Any] = {}
    else:
        raw_params = payload["params"]
        if not isinstance(raw_params, dict):
            return _jsonrpc_error(request_id, _JSONRPC_INVALID_PARAMS, "params must be an object")
        params = raw_params

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
                "instructions": MCP_HOST_INSTRUCTIONS,
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
            result = await _read_resource(
                request,
                params.get("uri"),
                briefing_repository,
            )
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
