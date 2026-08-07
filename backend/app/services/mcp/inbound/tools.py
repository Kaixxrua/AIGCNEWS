from __future__ import annotations

import asyncio
import base64
import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from pydantic import ValidationError
from starlette.requests import Request

from backend.app.repositories.document_repository import (
    DocumentSearchReader,
    PapersReader,
)
from backend.app.repositories.project_catalog_factory import (
    get_project_catalog_repository,
)
from backend.app.repositories.project_write_repository import (
    UserProjectCollectionRepository,
)
from backend.app.repositories.rank_snapshot_repository import RankSnapshotReader
from backend.app.services.dashboard.policy import (
    compute_board_status,
    dedupe_docs,
    enrich_doc_pdf_url,
    resolve_snapshot_date,
)
from backend.app.services.dashboard.query_service import DashboardQueryService
from backend.app.services.ingestion.source_github_mcp import (
    search_github_projects_fallback,
)
from backend.app.services.mcp.contracts import TOOL_INPUT_MODELS
from backend.app.services.mcp.inbound.catalog import (
    _PROJECT_SORT_CHOICES,
    MCP_TOOL_DEFINITIONS,
    MCP_TOOL_INPUT_MODELS,
)
from backend.app.services.mcp.inbound.context import McpAuthorizationContext
from backend.app.services.mcp.inbound.responses import _tool_error, _tool_response
from backend.app.services.papers.presentation import (
    project_pdf_media_url,
    safe_document,
)
from backend.app.services.project_discovery import public_project_item, search_projects

logger = logging.getLogger(__name__)


class McpToolInputError(ValueError):
    """Raised when MCP tool arguments are invalid."""


@dataclass(frozen=True)
class McpToolContext:
    """Immutable dependencies available to inbound public and private MCP tools."""

    user: dict[str, Any] | None
    documents: DocumentSearchReader
    papers: PapersReader
    rank_snapshots: RankSnapshotReader
    project_collection: UserProjectCollectionRepository
    request: Request
    project_searcher: Callable[..., Awaitable[dict[str, Any]]] = search_projects

    @property
    def authorization(self) -> McpAuthorizationContext:
        return McpAuthorizationContext(self.user)


ToolHandler = Callable[[McpToolContext, dict[str, Any]], Awaitable[dict[str, Any]]]


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


def _clean_choice(
    args: dict[str, Any], key: str, choices: set[str], *, default: str
) -> str:
    value = _clean_string(args, key, max_len=64, default=default).lower() or default
    if value not in choices:
        raise McpToolInputError(f"{key} 必须是以下之一：{', '.join(sorted(choices))}。")
    return value


def _public_doc(
    doc: dict[str, Any], request: Request, *, dashboard: bool = False
) -> dict[str, Any]:
    enriched = (
        enrich_doc_pdf_url(dict(doc), request)
        if dashboard
        else project_pdf_media_url(dict(doc), request)
    )
    enriched.pop("local_pdf_path", None)
    return enriched


async def _search_indexed_documents(
    context: McpToolContext,
    args: dict[str, Any],
    *,
    source: str | None,
) -> dict[str, Any]:
    tool_context = context
    q = args["q"]
    page = args.get("page", 1)
    limit = args.get("limit", 10)
    result = await asyncio.to_thread(
        tool_context.documents.search_document_page,
        q,
        source=source,
        page=page,
        page_size=limit,
    )
    docs = [safe_document(dict(row)) for row in result.get("items") or []]
    items = [_public_doc(doc, tool_context.request) for doc in docs]
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


async def _tool_search_papers(
    context: McpToolContext, args: dict[str, Any]
) -> dict[str, Any]:
    return await _search_indexed_documents(context, args, source="arxiv")


async def _tool_search_documents(
    context: McpToolContext, args: dict[str, Any]
) -> dict[str, Any]:
    source = args["source"]
    return await _search_indexed_documents(
        context,
        args,
        source=None if source == "all" else source,
    )


async def _tool_get_paper_detail(
    context: McpToolContext,
    args: dict[str, Any],
    papers: PapersReader | None = None,
) -> dict[str, Any]:
    request = context.request
    paper_id = _clean_string(args, "paper_id", required=True, max_len=128)
    reader = papers or context.papers
    row = await asyncio.to_thread(reader.get_paper_detail, paper_id)
    if row is None:
        raise McpToolInputError(f"Document {paper_id!r} not found.")
    doc = safe_document(dict(row))
    return {"item": _public_doc(doc, request)}


async def _tool_get_top_items(
    context: McpToolContext, args: dict[str, Any]
) -> dict[str, Any]:
    tool_context = context
    source = args.get("source", "all")
    period = args.get("period", "daily")
    date_value = args.get("date") or ""
    limit = args.get("limit", 10)

    snapshot_date = resolve_snapshot_date(date_value or None)
    board = compute_board_status(snapshot_date)
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
        DashboardQueryService(tool_context.rank_snapshots).get_docs_for_date,
        snapshot_date,
        period,
        source_type,
        500,
    )
    items = [
        _public_doc(dict(doc), tool_context.request, dashboard=True)
        for doc in dedupe_docs(docs)[:limit]
    ]
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
    project_searcher: Callable[..., Awaitable[dict[str, Any]]] | None = None,
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
    search = project_searcher or search_projects
    return await search(
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


async def _tool_search_github_projects(
    context: McpToolContext, args: dict[str, Any]
) -> dict[str, Any]:
    return await _search_project_library(
        args,
        mode="generic",
        project_searcher=(
            context.project_searcher if context is not None else search_projects
        ),
    )


async def _tool_search_github_ai_projects(
    context: McpToolContext, args: dict[str, Any]
) -> dict[str, Any]:
    return await _search_project_library(
        args,
        mode="ai",
        project_searcher=(
            context.project_searcher if context is not None else search_projects
        ),
    )


async def _tool_search_my_project_favorites(
    context: McpToolContext, args: dict[str, Any]
) -> dict[str, Any]:
    tool_context = context
    authorization = tool_context.authorization
    user_id = authorization.user_id
    if user_id <= 0:
        raise McpToolInputError("Authentication is required for this tool.")
    if not authorization.has_scope("projects:favorites:read"):
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
            marker_data = json.loads(
                base64.urlsafe_b64decode(marker + padding).decode("utf-8")
            )
            offset = int(marker_data["offset"])
            marker_limit = int(marker_data["limit"])
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            raise McpToolInputError(
                "marker must be the opaque value returned by this tool."
            ) from exc
        if offset < 0 or marker_limit != limit or offset % limit:
            raise McpToolInputError(
                "marker is invalid or was issued for a different limit."
            )
    page = offset // limit + 1
    result = await asyncio.to_thread(
        tool_context.project_collection.list_user_project_collection,
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
    items = [public_project_item(item) for item in result.get("items") or []]
    total = int(result.get("total") or 0)
    next_offset = offset + len(items)
    next_marker = None
    if next_offset < total:
        marker_json = json.dumps(
            {"offset": next_offset, "limit": limit}, separators=(",", ":")
        )
        next_marker = base64.urlsafe_b64encode(marker_json.encode("utf-8")).decode(
            "ascii"
        ).rstrip("=")
    return {
        "items": items,
        "total": total,
        "q": q,
        "tag": tag,
        "sort": sort,
        "marker": next_marker,
    }


async def _tool_get_project_categories(
    _context_value: McpToolContext, args: dict[str, Any]
) -> dict[str, Any]:
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


_TOOL_HANDLERS: dict[str, ToolHandler] = {
    "search_papers": _tool_search_papers,
    "search_documents": _tool_search_documents,
    "get_paper_detail": _tool_get_paper_detail,
    "get_top_items": _tool_get_top_items,
    "search_github_projects": _tool_search_github_projects,
    "search_github_ai_projects": _tool_search_github_ai_projects,
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


async def _call_tool(
    context: McpToolContext, name: str, arguments: Any
) -> dict[str, Any]:
    handler = _TOOL_HANDLERS.get(name)
    if handler is None:
        return _tool_error(f"Unknown tool: {name}")
    try:
        data = await handler(context, _validated_tool_args(name, arguments))
        return _tool_response(data)
    except McpToolInputError as exc:
        return _tool_error(str(exc))
    except Exception:
        logger.exception("MCP tool call failed: %s", name)
        return _tool_error("Tool execution failed.")
