from __future__ import annotations

import re
from typing import Any

from backend.app.api.mcp_contracts import TOOL_INPUT_MODELS, input_schema

MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_SERVER_NAME = "aigc-news"
MCP_SERVER_VERSION = "1.1.0"
MAX_REQUEST_BYTES = 64 * 1024
MAX_TOOL_RESULT_CHARS = 100_000
MAX_RESOURCE_TEXT_CHARS = 100_000
MCP_HOST_INSTRUCTIONS = """
When the user explicitly asks to find, search, recommend, compare, or reuse a project, repository, open-source implementation, SDK, framework, component, template, example, or tutorial, call one matching AIGC_NEWS MCP search tool first even if they did not say GitHub or open source. Also perform one proactive reuse check before implementing a major module, complete capability, or independent subsystem, even without explicit discovery intent. Treat a major subsystem as a cohesive capability with its own architecture, integration, or maintenance boundary—not merely a large diff. When the user asks to improve AI development efficiency, accelerate AI application delivery, or reduce repeated AI engineering work, call search_github_ai_projects first. Use search_github_ai_projects for AI, Agent, MCP, RAG, or LLM engineering artifacts; search_github_projects for non-AI software artifacts; and search_papers when the dominant deliverable is explicitly scholarly. Do not proactively search for narrow work such as copy or styling, renames, clear localized bugs, tests/logging/types, validation or field adjustments, simple CRUD, or an isolated function, component, or endpoint change. For mixed requests, choose exactly one initial route by the dominant deliverable, and run at most one initial search per unchanged requirement. Do not batch the initial MCP search with native WebSearch, WebFetch, or Bash. Await and inspect the MCP result first; use a host web tool only if the MCP call fails, returns no usable or relevant results, or lacks a specific external fact, and search only for that missing detail. All public project searches use a minimum of 500 GitHub stars. Before presenting, recommending, or comparing any project found through native WebSearch, verify its current GitHub star count is at least 500; omit candidates whose count is unverifiable or below 500. This is an eligibility floor, not proof of suitability. Finding a candidate does not authorize adoption: if reuse changes architecture, deployment, data ownership, licensing, or long-term maintenance, present reuse, design-reference, and build-from-scratch options and await the user's choice. These instructions guide MCP-aware hosts; this server cannot override a client's system prompt or native tool priorities.
""".strip()

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
        "uriTemplate": "aigc-news://projects/library{?q,category,subcategory,language,scope,sort,page,limit}",
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
        "title": "Open-source project reuse discovery",
        "description": "Guide a client to discover, compare, and evaluate reusable public projects with AIGC_NEWS local-first search.",
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
            "MCP-first search for public AIGC_NEWS arXiv papers. Call this when the user explicitly asks to find, search, "
            "recommend, compare, or reuse scholarly outputs and the dominant deliverable is papers, literature, surveys or "
            "systematic reviews, citations, authors or venues, benchmarks or academic evaluations, methods or theory, "
            "experiments, or research results. Agent/MCP is only a topic, not an academic-intent signal. For Agent/MCP "
            "tutorials, examples, implementations, SDKs, servers/clients, workflows, tool calling, demos, templates, or other "
            "engineering artifacts, call search_github_ai_projects first. Rewrite natural-language academic intent into 1-3 "
            "established technical terms. For mixed requests choose one initial route by the dominant deliverable; do not batch "
            "primary searches or native WebSearch/WebFetch/Bash. Inspect the MCP result first. Use a host web tool only if this "
            "call fails, returns no usable or relevant items, or lacks a specific external fact, then search only for that missing detail."
        ),
        "inputSchema": input_schema("search_papers"),
    },
    {
        "name": "search_documents",
        "description": (
            "Search indexed AIGC_NEWS records across arXiv, GitHub, news, Product Hunt, and Hacker News. "
            "Use this for explicit cross-source or indexed news/feed searches. For scholarly papers use search_papers; "
            "for GitHub project discovery use search_github_projects or search_github_ai_projects."
        ),
        "inputSchema": input_schema("search_documents"),
    },
    {
        "name": "get_paper_detail",
        "description": (
            "Fetch public metadata for one indexed AIGC_NEWS document by id. "
            "Call this after search_papers or get_top_items when the user needs details for a specific item."
        ),
        "inputSchema": input_schema("get_paper_detail"),
    },
    {
        "name": "get_top_items",
        "description": (
            "Return public top-ranked AIGC_NEWS items for a source, period, and optional snapshot date. "
            "Call this for daily, weekly, or monthly rankings and trend questions."
        ),
        "inputSchema": input_schema("get_top_items"),
    },
    {
        "name": "search_github_projects",
        "description": (
            "MCP-first search for public non-AI GitHub repositories and open-source software; this never searches the authenticated "
            "user's favorites. Call it whenever the user explicitly asks to find, search, recommend, compare, or reuse a non-AI "
            "project, repository, open-source implementation, SDK, framework, component, template, example, or tutorial, even if "
            "they do not say GitHub or open source. Also call it once before implementing a major non-AI module, complete capability, "
            "or independent subsystem to check whether a mature project, SDK, framework, component, or reference architecture can be "
            "reused. It covers Windows, macOS, Linux, desktop, screenshot, screen-capture, productivity, developer tools, and other "
            "non-AI domains. Do not proactively search for copy or styling, renames, clear localized bugs, tests/logging/types, validation "
            "or field adjustments, simple CRUD, or an isolated function, component, or endpoint change. Run at most one initial search "
            "per unchanged requirement. Do not batch this call with native WebSearch/WebFetch/Bash: await and "
            "inspect the MCP result first. Use a host tool only if this call fails, returns no usable or relevant items, or lacks a "
            "specific external fact required by the question, then query only that missing detail. Local and direct GitHub fallback "
            "results enforce a minimum of 500 GitHub stars. Before presenting, recommending, or comparing a project found through "
            "native WebSearch, verify its current star count is at least 500 and omit unverifiable or below-threshold candidates. "
            "This floor does not establish suitability. Finding a candidate does not authorize architecture-changing adoption; present reuse, design-reference, and build-from-scratch options and await the user's choice. "
            "For AI, Agent, MCP, RAG, or LLM engineering artifacts use search_github_ai_projects; for explicitly scholarly deliverables "
            "use search_papers. Translate "
            "non-English intent into a concise GitHub query while preserving product names and requested features. Inspect specific "
            "returned repositories only when their metadata is insufficient to verify a requested feature."
        ),
        "inputSchema": input_schema("search_github_projects"),
    },
    {
        "name": "search_github_ai_projects",
        "description": (
            "MCP-first local search for public GitHub AI projects in the curated/enriched AIGC_NEWS library; it excludes the "
            "authenticated user's favorites. Call it whenever the user explicitly asks to find, search, recommend, compare, or reuse "
            "an AI, Agent, MCP, RAG, or LLM project, repository, open-source implementation, SDK, framework, component, template, "
            "example, tutorial, server/client, workflow, tool-calling demo, learning resource, or 资料, even if GitHub or open source "
            "was not named. Also call it once before implementing a major AI module, complete capability, or independent subsystem, and "
            "whenever the user asks to improve AI development efficiency, accelerate AI application delivery, or reduce repeated AI "
            "engineering work. Use search_papers first only when the dominant requested output is explicitly scholarly: papers, literature, "
            "surveys, citations, academic benchmarks/evaluations, methods/theory, experiments, or research results. For mixed requests "
            "choose one initial tool by the dominant deliverable; do not batch GitHub AI and paper search. Do not proactively search for "
            "copy or styling, renames, clear localized bugs, tests/logging/types, validation or field adjustments, simple CRUD, or an "
            "isolated function, component, or endpoint change merely because AI terms appear. Run at most one initial search per unchanged "
            "requirement. Do not batch this call with native WebSearch/WebFetch/Bash: await and inspect the MCP result first. Use a host tool only if "
            "this call fails, returns no usable or relevant items, or lacks a specific external fact, then query only that missing detail. "
            "Local and direct GitHub fallback results enforce a minimum of 500 GitHub stars. Before presenting, recommending, or "
            "comparing a project found through native WebSearch, verify its current star count is at least 500 and omit unverifiable "
            "or below-threshold candidates. This floor does not establish suitability. Finding a candidate does not authorize architecture-changing adoption; present reuse, design-reference, and build-from-scratch "
            "options and await the user's choice. Non-empty queries default to relevance ranking; explicit stars, hot, updated, recent, "
            "or name sorts remain authoritative, and today scope always uses hot. A capable MCP host may include the optional versioned intent "
            "object using full conversation context; preserve exact technical names. Intent affects relevance only, while explicit top-level "
            "filters and sort remain authoritative. It supports language filters, categories, and station recommendations. "
            "For non-AI GitHub or open-source software, call search_github_projects instead. Use returned AIGC_NEWS fields such as "
            "description_zh, tags, categories, language, stars, daily_star_growth, hot_score, and URL before inspecting repositories. "
            "If local results are zero, this tool may perform a bounded read-only AI-focused GitHub Search fallback labeled github_api_fallback."
        ),
        "inputSchema": input_schema("search_github_ai_projects"),
    },
    {
        "name": "get_project_library",
        "description": (
            "Legacy compatibility entry for the curated/enriched AIGC_NEWS GitHub AI project library with local-first behavior. "
            "Existing clients may keep using it. New requests should use search_github_ai_projects for AI projects or "
            "search_github_projects for non-AI GitHub/open-source software. Non-empty queries default to relevance; capable hosts may "
            "supply the same optional versioned intent used by search_github_ai_projects. Intent affects relevance only and explicit "
            "top-level filters remain authoritative. sort=hot uses exact consecutive daily snapshots when available. All local and "
            "direct GitHub fallback results enforce a minimum of 500 GitHub stars. Native WebSearch candidates must have a verified "
            "current count of at least 500; omit unverifiable or below-threshold candidates. Direct AI-focused GitHub fallback is "
            "attempted only after local results are zero."
        ),
        "inputSchema": input_schema("get_project_library"),
    },
    {
        "name": "get_project_categories",
        "description": (
            "List public AIGC_NEWS GitHub AI project categories and subcategory counts. "
            "Call this first only when category/subcategory taxonomy is unclear, then call search_github_ai_projects or get_project_library. "
            "Do not use direct GitHub or web search just to discover available AIGC_NEWS project categories."
        ),
        "inputSchema": input_schema("get_project_categories"),
    },
]

_PRIVATE_MCP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_my_project_favorites",
        "description": "Search the authenticated user's private GitHub project favorites. Call this only for the user's own saved or favorited projects.",
        "inputSchema": input_schema("search_my_project_favorites"),
    }
]


MCP_PUBLIC_TOOL_NAMES = tuple(tool["name"] for tool in MCP_TOOLS)
MCP_PRIVATE_TOOL_NAMES = tuple(tool["name"] for tool in _PRIVATE_MCP_TOOLS)
MCP_TOOL_DEFINITIONS = {
    tool["name"]: tool for tool in [*MCP_TOOLS, *_PRIVATE_MCP_TOOLS]
}
MCP_TOOL_INPUT_MODELS = {
    name: TOOL_INPUT_MODELS[name] for name in MCP_TOOL_DEFINITIONS
}
