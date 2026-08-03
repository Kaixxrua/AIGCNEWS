from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date as _date, timedelta as _td
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from backend.app.repositories.briefing_repository import BriefingReader
from backend.app.repositories.document_repository import DocumentStatisticsReader
from backend.app.repositories.rank_snapshot_repository import RankSnapshotReader
from backend.app.services.dashboard.policy import (
    compute_board_status as _compute_board_status,
    dedupe_docs as _dedupe_docs,
    resolve_snapshot_date as _resolve_snapshot_date,
    score_categories as _score_categories,
)
from backend.app.services.dashboard.query_service import DashboardQueryService
from backend.app.services.mcp.contracts import validate_iso_date
from backend.app.services.mcp.inbound.catalog import (
    _JSONRPC_INTERNAL_ERROR,
    _JSONRPC_INVALID_PARAMS,
    _JSONRPC_METHOD_NOT_FOUND,
    _PERIOD_CHOICES,
    _PRIVATE_MCP_TOOLS,
    _SOURCE_CHOICES,
    MCP_HOST_INSTRUCTIONS,
    MCP_PROMPTS,
    MCP_PROTOCOL_VERSION,
    MCP_RESOURCE_TEMPLATES,
    MCP_RESOURCES,
    MCP_SERVER_NAME,
    MCP_SERVER_VERSION,
    MCP_TOOLS,
)
from backend.app.services.mcp.inbound.context import (
    McpAuthorizationContext,
    McpInboundRequest,
    McpSessionTransport,
)
from backend.app.services.mcp.inbound.responses import _resource_content, _tool_error
from backend.app.services.mcp.inbound.tools import (
    McpToolContext,
    McpToolInputError,
    _call_tool,
    _clean_choice,
    _clean_string,
    _public_doc,
    _tool_get_paper_detail,
    _tool_get_project_categories,
    _tool_get_top_items,
    _tool_search_github_ai_projects,
    _validated_tool_args,
)

logger = logging.getLogger(__name__)


class McpResourceInputError(ValueError):
    """Raised when MCP resource parameters are invalid."""


class McpPromptInputError(ValueError):
    """Raised when MCP prompt parameters are invalid."""


@dataclass(frozen=True)
class McpProtocolDependencies:
    """Immutable application dependencies for one inbound MCP exchange."""

    authorization: McpAuthorizationContext
    tools: McpToolContext
    briefing_repository: BriefingReader
    session_transport: McpSessionTransport


@dataclass(frozen=True)
class McpProtocolResponse:
    """Framework-neutral HTTP projection produced by the MCP application."""

    status_code: int
    body: dict[str, Any] | None
    headers: dict[str, str]


class McpProtocolApplication:
    """Dispatch validated inbound requests and own MCP JSON-RPC projections."""

    def __init__(self, dependencies: McpProtocolDependencies) -> None:
        self._dependencies = dependencies

    def _result(
        self,
        request_id: Any,
        result: dict[str, Any],
        *,
        session_id: str | None = None,
    ) -> McpProtocolResponse:
        return McpProtocolResponse(
            status_code=200,
            body={"jsonrpc": "2.0", "id": request_id, "result": result},
            headers=self._dependencies.session_transport.headers(session_id),
        )

    def error(self, request_id: Any, code: int, message: str) -> McpProtocolResponse:
        return McpProtocolResponse(
            status_code=200,
            body={
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": code, "message": message},
            },
            headers=self._dependencies.session_transport.headers(),
        )

    async def dispatch(self, inbound: McpInboundRequest) -> McpProtocolResponse:
        request_id = inbound.request_id
        method = inbound.method
        params = inbound.params

        if inbound.is_initialized_notification:
            return McpProtocolResponse(
                status_code=204,
                body=None,
                headers=self._dependencies.session_transport.headers(),
            )

        if method == "initialize":
            session_id = self._dependencies.session_transport.new_session_id()
            return self._result(
                request_id,
                {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "resources": {"subscribe": False, "listChanged": False},
                        "prompts": {"listChanged": False},
                    },
                    "serverInfo": {
                        "name": MCP_SERVER_NAME,
                        "version": MCP_SERVER_VERSION,
                    },
                    "instructions": MCP_HOST_INSTRUCTIONS,
                },
                session_id=session_id,
            )

        if method == "tools/list":
            tools = MCP_TOOLS + (
                _PRIVATE_MCP_TOOLS
                if self._dependencies.authorization.is_authenticated
                else []
            )
            return self._result(request_id, {"tools": tools})

        if method == "tools/call":
            name = params.get("name")
            if not isinstance(name, str) or not name:
                return self.error(
                    request_id,
                    _JSONRPC_INVALID_PARAMS,
                    "tools/call params.name is required",
                )
            arguments = params.get("arguments", {})
            if (
                name == "search_my_project_favorites"
                and not self._dependencies.authorization.is_authenticated
            ):
                result = _tool_error("Authentication is required for this tool.")
            else:
                result = await _call_tool(self._dependencies.tools, name, arguments)
            return self._result(request_id, result)

        if method == "resources/list":
            return self._result(request_id, {"resources": MCP_RESOURCES})

        if method == "resources/templates/list":
            return self._result(
                request_id, {"resourceTemplates": MCP_RESOURCE_TEMPLATES}
            )

        if method == "resources/read":
            try:
                result = await _read_resource(
                    self._dependencies.tools,
                    params.get("uri"),
                    self._dependencies.briefing_repository,
                )
            except McpResourceInputError as exc:
                return self.error(request_id, _JSONRPC_INVALID_PARAMS, str(exc))
            except Exception:
                logger.exception("MCP resource read failed: %s", params.get("uri"))
                return self.error(
                    request_id, _JSONRPC_INTERNAL_ERROR, "Resource read failed"
                )
            return self._result(request_id, result)

        if method == "prompts/list":
            return self._result(request_id, {"prompts": MCP_PROMPTS})

        if method == "prompts/get":
            try:
                result = _get_prompt(params.get("name"), params.get("arguments", {}))
            except McpPromptInputError as exc:
                return self.error(request_id, _JSONRPC_INVALID_PARAMS, str(exc))
            return self._result(request_id, result)

        return self.error(request_id, _JSONRPC_METHOD_NOT_FOUND, "Method not found")


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
    anchor = _date.today()
    if date_str:
        try:
            validate_iso_date(date_str)
            anchor = _date.fromisoformat(date_str)
        except ValueError as exc:
            raise McpResourceInputError(str(exc)) from exc

    if period == "weekly":
        anchor = anchor - _td(days=anchor.weekday())
    elif period == "monthly":
        anchor = anchor.replace(day=1)
    return anchor.isoformat()


async def _resource_dashboard_summary(
    tool_context: McpToolContext,
    uri: str,
    query: dict[str, str],
) -> dict[str, Any]:
    period = _clean_choice(query, "period", _PERIOD_CHOICES, default="daily")
    date_value = _clean_string(query, "date", max_len=10, default="")
    if date_value:
        try:
            validate_iso_date(date_value)
        except ValueError as exc:
            raise McpResourceInputError(str(exc)) from exc

    document_statistics: DocumentStatisticsReader = tool_context.documents
    rank_snapshots: RankSnapshotReader = tool_context.rank_snapshots
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
        DashboardQueryService(rank_snapshots).get_docs_for_date,
        snapshot_date,
        period,
        None,
        500,
    )
    deduped = _dedupe_docs(docs)
    top10 = [
        _public_doc(dict(doc), tool_context.request, dashboard=True)
        for doc in deduped[:10]
    ]
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
    locale = _clean_string(query, "locale", max_len=16, default="zh-CN")
    from backend.app.services.briefing.daily_briefing import select_briefing_content

    return _resource_content(uri, select_briefing_content(item, locale), mime_type="text/markdown")


def _resource_tool_args(
    query: dict[str, str], *, integer_fields: set[str]
) -> dict[str, Any]:
    args: dict[str, Any] = dict(query)
    for field in integer_fields:
        if field not in args:
            continue
        try:
            args[field] = int(args[field])
        except (TypeError, ValueError):
            raise McpResourceInputError(f"{field} must be an integer.") from None
    return args


async def _read_resource(
    context: McpToolContext,
    uri: Any,
    briefing_repository: BriefingReader,
) -> dict[str, Any]:
    path, query = _parse_resource_uri(uri)
    tool_context = context

    try:
        if path == "dashboard/summary":
            return await _resource_dashboard_summary(tool_context, uri, query)
        if path == "dashboard/top":
            return _resource_content(
                uri,
                await _tool_get_top_items(
                    tool_context,
                    _validated_tool_args(
                        "get_top_items",
                        _resource_tool_args(query, integer_fields={"limit"}),
                    ),
                ),
            )
        if path == "projects/categories":
            return _resource_content(
                uri, await _tool_get_project_categories(tool_context, {})
            )
        if path == "projects/library":
            return _resource_content(
                uri,
                await _tool_search_github_ai_projects(
                    tool_context,
                    _validated_tool_args(
                        "get_project_library",
                        _resource_tool_args(
                            query, integer_fields={"page", "limit"}
                        ),
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
                    tool_context,
                    _validated_tool_args(
                        "get_paper_detail", {"paper_id": paper_id}
                    ),
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
