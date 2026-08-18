"""MCP 线格式黄金语料录制器与校验引擎（PR 2.1）。

在任何行为变更（bench 打标、计数源 Redis 化、Go 重写）落地之前，把 Python
双 app（main.app / mcp_main.app）的 MCP 请求/响应逐字节冻结为
``corpus/*.jsonl`` 黄金语料。

运行形态（经 ``test_corpus_parity.py`` 入口，从而自动获得 conftest.py 的
MCP_TOOL_CALL_METRICS_PATH 重定向保护——录制绝不写生产计数文件）：

- 默认 verify：逐案重放并与语料比对，任一漂移即红；
- ``PARITY_RECORD=1``：重录全部语料 + ``corpus/fixtures.json`` +
  ``corpus/recording_context.json``。

确定性三支柱：

1. 全部外部依赖（文档/榜单/收藏/简报/项目搜索/分类/token 仓储）替换为
   固定 fixture 数据的 stub（stub 即 fixtures.json 的权威注入实现）；
2. 时间冻结在 2026-08-10 12:00:00+08:00（昨日 08-09 处于 embargo 窗口，
   08-08 已定稿，当日为草稿——三种榜单状态同批钉住）；
3. 易变值（mcp-session-id）按 corpus_manifest.json 正则归一后才落盘。

语料钉的是「录制时工作树行为」：任何改动 MCP 链路的提交若改变字节，verify
变红即为重录信号。``public_base_url`` 只读配置、绝不读请求头，因此 Host
差异不影响语料，Go 回放跨 host 安全。
"""

from __future__ import annotations

import base64
import contextlib
import copy
import difflib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.app import main as main_module, mcp_main
from backend.app.api import routes_mcp
from backend.app.api.dependencies import (
    get_application_repositories,
    get_briefing_repository,
    get_project_catalog_query_service,
    get_project_search_runtime,
)
from backend.app.core.app_version import resolve_app_version
from backend.app.core.auth import (
    get_mcp_access_token_authenticator,
    hash_mcp_token,
)
from backend.app.core.config import settings
from backend.app.services.dashboard import policy as dashboard_policy
from backend.app.services.mcp.inbound import (
    application as mcp_application,
    rate_limit as mcp_rate_limit,
    tools as mcp_tools_module,
)
from backend.tests.test_email_service_contracts import FakeRedis

PACKAGE_DIR = Path(__file__).resolve().parent
CORPUS_DIR = PACKAGE_DIR / "corpus"
MANIFEST_PATH = PACKAGE_DIR / "corpus_manifest.json"
FIXTURES_PATH = CORPUS_DIR / "fixtures.json"
RECORDING_CONTEXT_PATH = CORPUS_DIR / "recording_context.json"

RECORD_MODE = os.environ.get("PARITY_RECORD") == "1"

# ── 冻结时间 ────────────────────────────────────────────────────────────
# CST 2026-08-10 12:00：昨日（08-09）在 FINALIZE_HOUR=15 之前 → embargoed；
# 08-08 早于昨日 → finalized；当日 → 草稿。policy.datetime 是 dashboard
# 全部时间判定的唯一入口；application._date 仅服务 report/latest 日期解析。
_FROZEN_INSTANT = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone(timedelta(hours=8)))


class _FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):  # noqa: D102 - 与 datetime.now 签名一致
        if tz is None:
            return _FROZEN_INSTANT.replace(tzinfo=None)
        return _FROZEN_INSTANT.astimezone(tz)


class _FrozenDate(date):
    @classmethod
    def today(cls) -> date:
        return cls(2026, 8, 10)


@contextlib.contextmanager
def _frozen_time():
    with (
        patch.object(dashboard_policy, "datetime", _FrozenDateTime),
        patch.object(mcp_application, "_date", _FrozenDate),
    ):
        yield

# ── Fixture 实体（stub 输入，Go 回放经 fixtures.json 共享） ──────────────

# created_at 用真实 datetime 对象：safe_document 对非标量走 str()，
# 语料钉住 "2026-08-09 17:03:05" 这一 Python 字符串化形状。
_CREATED_AT = datetime(2026, 8, 9, 17, 3, 5)

# 与 postgres_document_repository.search_document_page / get_paper_detail
# 的 SELECT 列清单逐字对齐。
_ARXIV_DOC_A: dict[str, Any] = {
    "id": "2608.01234",
    "source": "arxiv",
    "source_channel": "huggingface_daily_html",
    "title": "多模态 Scaling Law 的再思考 🚀",
    "url": "https://arxiv.org/abs/2608.01234",
    # 敌意 unicode：U+2028/U+2029 行分隔符 + HTML 特殊字符 + CJK。
    "summary": "第一段。 第二段含 <tags> & \"quotes\" 与   —— 中文摘要。",
    "published_date": "2026-08-09",
    "tags": "multimodal,scaling-law",
    "score": 1.0,  # 整值浮点：Python json.dumps 输出 "1.0"
    "raw_score": 42.5,
    "rank_in_period": 1,
    "local_pdf_path": "/srv/aigcnews/storage/papers/2608.01234.pdf",
    "authors": '["Alice Zhang", "Bob Müller", "张三"]',
    "arxiv_id": "2608.01234",
    "created_at": _CREATED_AT,
}
_ARXIV_DOC_B: dict[str, Any] = {
    "id": "2608.05678",
    "source": "arxiv",
    "source_channel": "huggingface_daily_html",
    "title": "Agentic Tool Use at Internet Scale",
    "url": "https://arxiv.org/abs/2608.05678",
    "summary": "We study how agents call tools.",
    "published_date": "2026-08-08",
    "tags": "agents",
    "score": 0.95,
    "raw_score": 7,
    "rank_in_period": 2,
    "local_pdf_path": None,  # → /api/papers/{id}/pdf 代理 URL 分支
    "authors": "not-json",  # JSON 解析失败 → []
    "arxiv_id": "2608.05678",
    "created_at": _CREATED_AT,
}
_NEWS_DOC: dict[str, Any] = {
    "id": "news-20260809-openai",
    "source": "news",
    "source_channel": "techmeme_daily_rss",
    "title": "OpenAI 发布新一代模型",
    "url": "https://techmeme.com/260809/p1",
    "summary": "Techmeme 快讯。",
    "published_date": "2026-08-09",
    "tags": "openai",
    "score": 0.5,
    "raw_score": 88,
    "rank_in_period": 3,
    "local_pdf_path": None,  # 非 arxiv → pdf_media_url 为 None
    "authors": None,
    "arxiv_id": None,
    "created_at": _CREATED_AT,
}
# 截断边界钉住「字符数而非字节数」语义：98k ASCII + 2200 个三字节 CJK，
# 总长 100200 字符越过 100_000 阈值，切口落在 CJK 串中段。
_OVERSIZED_DOC: dict[str, Any] = {
    **_ARXIV_DOC_A,
    "id": "2608.oversized",
    "title": "Oversized Result Probe",
    "summary": "ab" * 49_000 + "越" * 2_200,
    "local_pdf_path": None,
}

_SOURCE_COUNTS = {
    "arxiv": 1234,
    "github": 567,
    "news": 89,
    "producthunt": 45,
    "hackernews": 23,
    "x": 12,
}
_TODAY_DOCUMENT_COUNT = 42

# 榜单 fixture：techmeme 条目的 url 与 DASH_ARXIV_1 相同 → 钉住 dedupe_docs
# 去重；hn-1 在「昨日已上榜」集合中 → 钉住 HN 日榜排重；HN 条目排到最后
# （other_docs + hackernews_docs 顺序）。
_DASH_ARXIV_1: dict[str, Any] = {
    "id": "2608.09999",
    "source": "arxiv",
    "source_channel": "huggingface_daily_html",
    "title": "A multimodal agent for scientific discovery",
    "url": "https://arxiv.org/abs/2608.09999",
    "summary": "An agentic multimodal system.",
    "published_date": "2026-08-08",
    "tags": "agent,multimodal",
    "score": 0.9,
    "raw_score": 88,
    "rank_in_period": 1,
    "local_pdf_path": None,  # dashboard 变体：无本地 PDF → None（无代理分支）
    "authors": '["Carol Danvers"]',
    "arxiv_id": "2608.09999",
    "created_at": _CREATED_AT,
}
_DASH_ARXIV_2: dict[str, Any] = {
    "id": "2608.07777",
    "source": "arxiv",
    "source_channel": "huggingface_daily_html",
    "title": "LLM routing with cheap experts",
    "url": "https://arxiv.org/abs/2608.07777",
    "summary": "Routing tokens across LLM experts.",
    "published_date": "2026-08-08",
    "tags": "llm",
    "score": 0.8,
    "raw_score": 55,
    "rank_in_period": 2,
    "local_pdf_path": "/srv/aigcnews/storage/papers/2608.07777.pdf",  # → /api/media/papers/
    "authors": "[]",
    "arxiv_id": "2608.07777",
    "created_at": _CREATED_AT,
}
_DASH_GITHUB: dict[str, Any] = {
    "id": "github-llm-ops",
    "source": "github",
    "source_channel": "github_trending_daily",
    "title": "owner/llm-ops",
    "url": "https://github.com/owner/llm-ops",
    "summary": "LLM 运维工具箱。",
    "published_date": "2026-08-08",
    "tags": "llm,ops",
    "score": 230.0,
    "raw_score": 230,
    "rank_in_period": 1,
    "local_pdf_path": None,
    "authors": None,
    "arxiv_id": None,
    "created_at": _CREATED_AT,
}
_DASH_NEWS_DUP: dict[str, Any] = {
    "id": "news-dup",
    "source": "news",
    "source_channel": "techmeme_daily_rss",
    "title": "转载：同一篇 arxiv 论文",
    "url": "https://arxiv.org/abs/2608.09999",  # 与 _DASH_ARXIV_1 同 URL → 被去重
    "summary": "重复条目。",
    "published_date": "2026-08-08",
    "tags": "",
    "score": 0.1,
    "raw_score": 3,
    "rank_in_period": 9,
    "local_pdf_path": None,
    "authors": None,
    "arxiv_id": None,
    "created_at": _CREATED_AT,
}
_DASH_HN_1: dict[str, Any] = {
    "id": "hn-1",
    "source": "hackernews",
    "source_channel": "hn_daily_html",
    "title": "Ask HN: yesterday repeat",
    "url": "https://news.ycombinator.com/item?id=1",
    "summary": "昨日已上榜。",
    "published_date": "2026-08-08",
    "tags": "",
    "score": 0.2,
    "raw_score": 5,
    "rank_in_period": 20,
    "local_pdf_path": None,
    "authors": None,
    "arxiv_id": None,
    "created_at": _CREATED_AT,
}
_DASH_HN_2: dict[str, Any] = {
    "id": "hn-2",
    "source": "hackernews",
    "source_channel": "hn_daily_html",
    "title": "Show HN: vector database benchmark",
    "url": "https://news.ycombinator.com/item?id=2",
    "summary": "A benchmark for vector databases.",
    "published_date": "2026-08-08",
    "tags": "benchmark",
    "score": 0.7,
    "raw_score": 99,
    "rank_in_period": 4,
    "local_pdf_path": None,
    "authors": None,
    "arxiv_id": None,
    "created_at": _CREATED_AT,
}
_DASH_X: dict[str, Any] = {
    "id": "x-1234567890",
    "source": "x",
    "source_channel": "x_daily_watchlist",
    "title": "推文：agents 正在重塑工具链",
    "url": "https://x.com/someone/status/1234567890",
    "summary": "Agents everywhere.",
    "published_date": "2026-08-08",
    "tags": "agents",
    "score": 0.6,
    "raw_score": 12,
    "rank_in_period": 5,
    "local_pdf_path": None,
    "authors": None,
    "arxiv_id": None,
    "created_at": _CREATED_AT,
}
_DASH_ARXIV_WEEKLY: dict[str, Any] = {
    **_DASH_ARXIV_1,
    "id": "2608.week",
    "source_channel": "huggingface_weekly_html",
    "title": "Weekly multimodal survey",
    "url": "https://arxiv.org/abs/2608.week",
    "local_pdf_path": None,
}

_DASHBOARD_CHANNEL_DOCS: dict[str, list[dict[str, Any]]] = {
    "huggingface_daily_html": [_DASH_ARXIV_1, _DASH_ARXIV_2],
    "github_trending_daily": [_DASH_GITHUB],
    "techmeme_daily_rss": [_DASH_NEWS_DUP],
    "producthunt_daily_html": [],
    "hn_daily_html": [_DASH_HN_1, _DASH_HN_2],
    "x_daily_watchlist": [_DASH_X],
    "huggingface_weekly_html": [_DASH_ARXIV_WEEKLY],
}
_YESTERDAY_HN_IDS = {"hn-1"}

# 项目库搜索 fixture。_search_project_library 对 items 只做
# localize_project_item + enrich_project_detail_url，其余键原样透传。
_PROJECT_RAW_1: dict[str, Any] = {
    "id": "repo-1",
    "full_name": "acme/rag-toolkit",
    "url": "https://github.com/acme/rag-toolkit",
    "description": "检索增强生成工具箱",
    "description_zh": "检索增强生成工具箱",
    "description_en": "RAG toolkit for production agents",
    "category_slug": "rag",
    "category_name": "检索增强",
    "category_name_zh": "检索增强",
    "category_name_en": "Retrieval-Augmented Generation",
    "subcategory_slug": "rag-eval",
    "subcategory_name": "RAG 评测",
    "subcategory_name_zh": "RAG 评测",
    "subcategory_name_en": "RAG Evaluation",
    "tags": ["检索", "评测"],
    "tags_zh": ["检索", "评测"],
    "tags_en": ["retrieval", "evaluation"],
    "topics": ["rag", "llm"],
    "language": "Python",
    "stars": 12345,
    "forks": 678,
    "pushed_at": "2026-08-09T10:00:00+00:00",
    "score": 0.875,
}
_PROJECT_RAW_2: dict[str, Any] = {
    "id": "repo-2",
    "full_name": "acme/prompt-lab",
    "url": "https://github.com/acme/prompt-lab",
    "description": "Prompt 工作台",
    "description_zh": "Prompt 工作台",
    "description_en": "A workbench for prompts",
    "category_slug": "prompt-engineering",
    "category_name": "提示工程",
    "category_name_zh": "提示工程",
    "category_name_en": "Prompt Engineering",
    "subcategory_slug": None,
    "subcategory_name": None,
    "subcategory_name_zh": None,
    "subcategory_name_en": None,
    "tags": [],
    "tags_zh": [],
    "tags_en": [],
    "topics": ["prompts"],
    "language": "TypeScript",
    "stars": 500,
    "forks": 12,
    "pushed_at": "2026-08-01T00:00:00+00:00",
    "score": 0.5,
}
_AI_SEARCH_RESULT: dict[str, Any] = {
    "items": [_PROJECT_RAW_1, _PROJECT_RAW_2],
    "total": 2,
    "local_total": 2,
    "page": 1,
    "limit": 10,
    "scope": "all",
    "sort": "relevance",
    "fallback_used": False,
    "result_origin": "aigc_news_local",
    "fallback_policy": "local_first_github_only_when_semantics_preserved",
}
_GENERIC_SEARCH_RESULT: dict[str, Any] = {
    "items": [
        {
            **_PROJECT_RAW_2,
            "id": "repo-9",
            "full_name": "acme/static-site-gen",
            "url": "https://github.com/acme/static-site-gen",
            "result_origin": "github_api_fallback",
        }
    ],
    "total": 1,
    "local_total": 0,
    "page": 1,
    "limit": 10,
    "scope": "all",
    "sort": "stars",
    "fallback_used": True,
    "result_origin": "github_api_fallback",
    "fallback_policy": "local_first_github_only_when_local_zero",
}

# 收藏 fixture：raw 仓储行（public_project_item 的输入超集）。
_FAV_ROW_1: dict[str, Any] = {
    "id": "fav-1",
    "full_name": "acme/rag-toolkit",
    "url": "https://github.com/acme/rag-toolkit",
    "description": "检索增强生成工具箱",
    "description_zh": "检索增强生成工具箱",
    "description_en": "RAG toolkit for production agents",
    "category_slug": "rag",
    "category_name": "检索增强",
    "category_name_zh": "检索增强",
    "category_name_en": "Retrieval-Augmented Generation",
    "subcategory_slug": "rag-eval",
    "subcategory_name": "RAG 评测",
    "subcategory_name_zh": "RAG 评测",
    "subcategory_name_en": "RAG Evaluation",
    "tags": ["检索"],
    "tags_zh": ["检索"],
    "tags_en": ["retrieval"],
    "tags_origin": "user",
    "topics": ["rag"],
    "language": "Python",
    "stars": 12345,
    "forks": 678,
    "pushed_at": "2026-08-09T10:00:00+00:00",
    "daily_star_growth": 321,
    "daily_growth_available": True,
    "hot_score": 87.5,
    "growth_suspicion_score": 0.125,
    "is_recommended": True,
    "result_origin": "aigc_news_local",
}
_FAV_ROW_2: dict[str, Any] = {
    **_FAV_ROW_1,
    "id": "fav-2",
    "full_name": "acme/agent-runtime",
    "url": "https://github.com/acme/agent-runtime",
    "tags_origin": "system",
    "is_recommended": False,
    "daily_growth_available": False,
    "daily_star_growth": 0,
    "hot_score": 0,
    "growth_suspicion_score": 0,
}
_FAV_ROW_3: dict[str, Any] = {
    **_FAV_ROW_1,
    "id": "fav-3",
    "full_name": "acme/eval-suite",
    "url": "https://github.com/acme/eval-suite",
}

_CATEGORIES_RESULT: dict[str, Any] = {
    "items": [
        {
            "slug": "agents",
            "name": "智能体",
            "name_zh": "智能体",
            "name_en": "Agents",
            "project_count": 128,
            "subcategories": [
                {
                    "slug": "agent-frameworks",
                    "name": "智能体框架",
                    "name_zh": "智能体框架",
                    "name_en": "Agent Frameworks",
                    "project_count": 64,
                }
            ],
        },
        {
            "slug": "rag",
            "name": "检索增强",
            "name_zh": "检索增强",
            "name_en": "Retrieval-Augmented Generation",
            "project_count": 96,
            "subcategories": [],
        },
    ],
    "total": 2,
    "today_count": 3,
    "recommended_count": 1,
}

_BRIEFING_ZH = "# 今日 AI 简报\n\n- 多模态智能体持续升温。\n"
_BRIEFING_EN = "# Daily AI Briefing\n\n- Multimodal agents keep trending.\n"
_BRIEFING_ROWS: dict[str, dict[str, Any]] = {
    "2026-08-10": {
        "content_zh": _BRIEFING_ZH,
        "content_en": _BRIEFING_EN,
        "content": None,
    },
    # markdown 截断：99k ASCII + 1500 CJK = 100500 字符，切口落在 CJK 中段，
    # footer 拼接后被整体截断（尾部不可见），钉住字符语义与 "\n\n[truncated]"。
    "2026-08-11": {
        "content_zh": "y" * 99_000 + "汉" * 1_500,
        "content_en": None,
        "content": None,
    },
}

_TOKENS: dict[str, dict[str, Any]] = {
    "parity-token": {"user_id": 42, "scopes": ["projects:favorites:read"]},
    "limited-token": {"user_id": 43, "scopes": []},
    "weird-scopes-token": {"user_id": 44, "scopes": "oops"},
}


def _marker(offset: int, limit: int) -> str:
    """与 tools.search_my_project_favorites 相同的 marker 编码（紧凑 JSON + b64url 去 =）。"""
    payload = json.dumps(
        {"offset": offset, "limit": limit}, separators=(",", ":")
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


# ── Stub 仓储 ────────────────────────────────────────────────────────────


class _StubDocuments:
    """DocumentSearchReader + PapersReader + DocumentStatisticsReader 三合一身。"""

    def search_document_page(
        self, query: str, *, source=None, page: int = 1, page_size: int = 20
    ) -> dict[str, Any]:
        if query == "oversized":
            return {"items": [dict(_OVERSIZED_DOC)], "total": 1}
        if query == "empty-query":
            return {"items": [], "total": 0}
        if (source or "").lower() == "news":
            return {"items": [dict(_NEWS_DOC)], "total": 1}
        return {"items": [dict(_ARXIV_DOC_A), dict(_ARXIV_DOC_B)], "total": 17}

    def get_paper_detail(self, paper_id: str) -> dict[str, Any] | None:
        if paper_id == "2608.01234":
            return dict(_ARXIV_DOC_A)
        return None

    def get_source_counts(self) -> dict[str, int]:
        return dict(_SOURCE_COUNTS)

    def get_today_document_count(self) -> int:
        return _TODAY_DOCUMENT_COUNT


class _StubRankSnapshots:
    def get_snapshot_documents(
        self, *, snapshot_date: str, source_channel: str, source_type: str, limit: int
    ) -> list[dict[str, Any]]:
        return [dict(doc) for doc in _DASHBOARD_CHANNEL_DOCS.get(source_channel, [])]

    def get_snapshot_doc_ids(self, *, snapshot_date: str, source_channel: str):
        if source_channel == "hn_daily_html":
            return set(_YESTERDAY_HN_IDS)
        return set()


class _StubProjectCollections:
    def list_user_project_collection(self, **kwargs) -> dict[str, Any]:
        if int(kwargs.get("page") or 1) <= 1:
            return {"items": [dict(_FAV_ROW_1), dict(_FAV_ROW_2)], "total": 3}
        return {"items": [dict(_FAV_ROW_3)], "total": 3}


class _StubBriefing:
    def get_briefing_by_date(self, key: str) -> dict[str, Any] | None:
        row = _BRIEFING_ROWS.get(key)
        return dict(row) if row is not None else None


class _StubCatalogQueries:
    min_stars = 500

    async def get_public_categories(self) -> dict[str, Any]:
        return copy.deepcopy(_CATEGORIES_RESULT)


class _StubTokenRepository:
    """按 hash_mcp_token 反查固定用户；未注册 token 返回 None（→ 401）。"""

    def get_user_by_mcp_token_hash(self, digest: str) -> dict[str, Any] | None:
        for token, user in _TOKENS.items():
            if hash_mcp_token(token) == digest:
                return dict(user)
        return None


def _search_projects_stub(**kwargs) -> dict[str, Any]:
    # handler 会原地改写 result（items/lang/attribution），每次调用深拷贝隔离。
    template = (
        _AI_SEARCH_RESULT
        if kwargs.get("mode") == "ai"
        else _GENERIC_SEARCH_RESULT
    )
    return copy.deepcopy(template)


# ── 用例定义 ─────────────────────────────────────────────────────────────


def _rpc(
    request_id: Any,
    method: str,
    params: Any = ...,
) -> str:
    """构造紧凑 JSON-RPC 请求体；params=... 表示省略 params 键。"""
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not ...:
        payload["params"] = params
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _raw(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


_JSON = {"content-type": "application/json"}


@dataclass(frozen=True)
class ParityCase:
    name: str
    file: str  # corpus/<file>.jsonl
    method: str
    path: str
    body: str | bytes = ""
    headers: Mapping[str, str] = field(default_factory=dict)
    app: str = "both"  # both | main | mcp
    auth: str | None = None  # _TOKENS 键名 → Authorization: Bearer <token>
    warmup: int = 0  # 录制前先原样发送的同请求次数（限流预热）
    rate_limit_overrides: tuple[tuple[str, int], ...] = ()
    profile: str = "default"  # default | tool_handler_crash | dispatch_crash
    replay: str = "static"  # static | stubbed


def _tool_call(name: str, arguments: dict[str, Any] | None = None, *, request_id: Any = 1) -> str:
    return _rpc(
        request_id,
        "tools/call",
        {"name": name, "arguments": {} if arguments is None else arguments},
    )


CASES: tuple[ParityCase, ...] = (
    # ── protocol.jsonl：信封/分派/错误面（全部 static） ──
    ParityCase(
        "initialize", "protocol", "POST", "/api/mcp",
        body=_rpc(1, "initialize", {}),
    ),
    ParityCase(
        "initialize-without-params", "protocol", "POST", "/api/mcp",
        body=_rpc("init", "initialize"),
    ),
    ParityCase(
        "notification-initialized", "protocol", "POST", "/api/mcp",
        body=_raw({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}),
    ),
    ParityCase(
        "notification-cancelled", "protocol", "POST", "/api/mcp",
        body=_raw({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}}),
    ),
    ParityCase(
        "idless-unknown-method", "protocol", "POST", "/api/mcp",
        body=_raw({"jsonrpc": "2.0", "method": "unknown/method"}),
    ),
    ParityCase(
        # 缺 id 的「请求」同样是 notification → 204 空体
        "idless-tools-list", "protocol", "POST", "/api/mcp",
        body=_raw({"jsonrpc": "2.0", "method": "tools/list"}),
    ),
    ParityCase(
        "tools-list", "protocol", "POST", "/api/mcp",
        body=_rpc(2, "tools/list", {}),
    ),
    ParityCase(
        "tools-list-authenticated", "protocol", "POST", "/api/mcp",
        body=_rpc(2, "tools/list", {}),
        auth="parity-token",
    ),
    ParityCase(
        "tools-list-id-null", "protocol", "POST", "/api/mcp",
        body=_rpc(None, "tools/list", {}),
    ),
    ParityCase(
        "tools-list-id-float", "protocol", "POST", "/api/mcp",
        body=_rpc(1.25, "tools/list", {}),
    ),
    ParityCase(
        "tools-list-id-bool", "protocol", "POST", "/api/mcp",
        body=_rpc(True, "tools/list", {}),
    ),
    ParityCase(
        "tools-list-id-zero", "protocol", "POST", "/api/mcp",
        body=_rpc(0, "tools/list", {}),
    ),
    ParityCase(
        "tools-list-without-params", "protocol", "POST", "/api/mcp",
        body=_rpc(22, "tools/list"),
    ),
    ParityCase(
        # 未知会话头被忽略：200 且响应不再回发 mcp-session-id
        "tools-list-unknown-session-header", "protocol", "POST", "/api/mcp",
        body=_rpc(3, "tools/list", {}),
        headers={**_JSON, "mcp-session-id": "not-the-initialize-session"},
    ),
    ParityCase(
        "unknown-method", "protocol", "POST", "/api/mcp",
        body=_rpc("unknown", "unknown/method", {}),
    ),
    ParityCase(
        # 无 ping 处理器：与未知方法同路
        "ping-is-method-not-found", "protocol", "POST", "/api/mcp",
        body=_rpc(9, "ping"),
    ),
    ParityCase(
        "parse-error-truncated-json", "protocol", "POST", "/api/mcp",
        body="{",
    ),
    ParityCase(
        "parse-error-invalid-utf8", "protocol", "POST", "/api/mcp",
        body=b"\xff",
    ),
    ParityCase(
        "parse-error-empty-body", "protocol", "POST", "/api/mcp",
        body="",
    ),
    ParityCase(
        "batch-rejected", "protocol", "POST", "/api/mcp",
        body=_raw([{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}]),
    ),
    ParityCase(
        "scalar-rejected", "protocol", "POST", "/api/mcp",
        body="1.5",
    ),
    ParityCase(
        "missing-jsonrpc", "protocol", "POST", "/api/mcp",
        body=_raw({"id": 7, "method": "tools/list"}),
    ),
    ParityCase(
        "wrong-jsonrpc", "protocol", "POST", "/api/mcp",
        body=_raw({"jsonrpc": "1.0", "id": 7, "method": "tools/list"}),
    ),
    ParityCase(
        "missing-method", "protocol", "POST", "/api/mcp",
        body=_raw({"jsonrpc": "2.0", "id": 7}),
    ),
    ParityCase(
        "method-not-string", "protocol", "POST", "/api/mcp",
        body=_raw({"jsonrpc": "2.0", "id": 7, "method": False}),
    ),
    ParityCase(
        # id 为对象 → 拒绝且回显 id=null
        "id-object-rejected", "protocol", "POST", "/api/mcp",
        body=_raw({"jsonrpc": "2.0", "id": {}, "method": "tools/list"}),
    ),
    ParityCase(
        "params-not-object", "protocol", "POST", "/api/mcp",
        body=_rpc(8, "tools/list", []),
    ),
    ParityCase(
        # MAX_REQUEST_BYTES=64KiB 边界 +1
        "oversized-body", "protocol", "POST", "/api/mcp",
        body=" " * (64 * 1024 + 1),
    ),
    ParityCase(
        "unknown-tool-call", "protocol", "POST", "/api/mcp",
        body=_tool_call("not-a-tool"),
        replay="stubbed",
    ),
    ParityCase(
        # 压测打标：UA 命中 mcp-latency-bench/ 前缀。响应须与 unknown-tool-call
        # 逐字节一致（免计数不泄漏到线格式）；「不进调用指标」由
        # test_mcp_tool_call_metrics 的分派/路由级用例钉住。
        "bench-tagged-tool-call", "protocol", "POST", "/api/mcp",
        body=_tool_call("not-a-tool"),
        headers={"user-agent": "mcp-latency-bench/0.1"},
        replay="stubbed",
    ),
    ParityCase(
        "tool-call-missing-name", "protocol", "POST", "/api/mcp",
        body=_rpc(6, "tools/call", {"arguments": {}}),
    ),
    ParityCase(
        "tool-call-handler-crash", "protocol", "POST", "/api/mcp",
        body=_tool_call("search_papers", {"q": "agent"}),
        profile="tool_handler_crash",
        replay="stubbed",
    ),
    ParityCase(
        "unauthorized-basic-scheme", "protocol", "POST", "/api/mcp",
        body=_rpc(1, "tools/list", {}),
        headers={**_JSON, "authorization": "Basic invalid"},
    ),
    ParityCase(
        "unauthorized-unknown-token", "protocol", "POST", "/api/mcp",
        body=_rpc(1, "tools/list", {}),
        auth="unknown-token",
    ),
    ParityCase(
        "unauthorized-malformed-scopes", "protocol", "POST", "/api/mcp",
        body=_rpc(1, "tools/list", {}),
        auth="weird-scopes-token",
    ),
    ParityCase(
        # 匿名 tools/call 限额压到 1：第一次（warmup）放行，第二次 429
        "rate-limited-429", "protocol", "POST", "/api/mcp",
        body=_tool_call("no_such_tool", request_id=2),
        warmup=1,
        rate_limit_overrides=(("MCP_ANONYMOUS_TOOL_CALL_LIMIT", 1),),
    ),
    ParityCase(
        "internal-error-500", "protocol", "POST", "/api/mcp",
        body=_rpc(1, "tools/list", {}),
        profile="dispatch_crash",
    ),
    ParityCase(
        "resources-list", "protocol", "POST", "/api/mcp",
        body=_rpc(4, "resources/list", {}),
    ),
    ParityCase(
        "resources-templates-list", "protocol", "POST", "/api/mcp",
        body=_rpc(5, "resources/templates/list", {}),
    ),
    ParityCase(
        "prompts-list", "protocol", "POST", "/api/mcp",
        body=_rpc(6, "prompts/list", {}),
    ),
    # ── tools.jsonl：8 工具 happy/error/截断（全部 stubbed） ──
    ParityCase(
        "search-papers", "tools", "POST", "/api/mcp",
        body=_tool_call("search_papers", {"q": "agent"}),
        replay="stubbed",
    ),
    ParityCase(
        "search-papers-pagination", "tools", "POST", "/api/mcp",
        body=_tool_call("search_papers", {"q": "agent", "page": 3}),
        replay="stubbed",
    ),
    ParityCase(
        "search-papers-empty", "tools", "POST", "/api/mcp",
        body=_tool_call("search_papers", {"q": "empty-query"}),
        replay="stubbed",
    ),
    ParityCase(
        "search-papers-oversized", "tools", "POST", "/api/mcp",
        body=_tool_call("search_papers", {"q": "oversized"}),
        replay="stubbed",
    ),
    ParityCase(
        "search-papers-missing-q", "tools", "POST", "/api/mcp",
        body=_tool_call("search_papers", {}),
    ),
    ParityCase(
        "search-papers-extra-arg", "tools", "POST", "/api/mcp",
        body=_tool_call("search_papers", {"q": "agent", "bogus": 1}),
    ),
    ParityCase(
        "search-documents-all", "tools", "POST", "/api/mcp",
        body=_tool_call("search_documents", {"q": "agent", "source": "all"}),
        replay="stubbed",
    ),
    ParityCase(
        "search-documents-news", "tools", "POST", "/api/mcp",
        body=_tool_call("search_documents", {"q": "agent", "source": "news"}),
        replay="stubbed",
    ),
    ParityCase(
        "search-documents-invalid-source", "tools", "POST", "/api/mcp",
        body=_tool_call("search_documents", {"q": "agent", "source": "bogus"}),
    ),
    ParityCase(
        "get-paper-detail", "tools", "POST", "/api/mcp",
        body=_tool_call("get_paper_detail", {"paper_id": "2608.01234"}),
        replay="stubbed",
    ),
    ParityCase(
        "get-paper-detail-not-found", "tools", "POST", "/api/mcp",
        body=_tool_call("get_paper_detail", {"paper_id": "2608.99999"}),
        replay="stubbed",
    ),
    ParityCase(
        "get-top-items", "tools", "POST", "/api/mcp",
        body=_tool_call("get_top_items", {"date": "2026-08-08"}),
        replay="stubbed",
    ),
    ParityCase(
        "get-top-items-embargoed", "tools", "POST", "/api/mcp",
        body=_tool_call("get_top_items", {"date": "2026-08-09"}),
        replay="stubbed",
    ),
    ParityCase(
        "get-top-items-default-date", "tools", "POST", "/api/mcp",
        body=_tool_call("get_top_items", {}),
        replay="stubbed",
    ),
    ParityCase(
        # 非法日期不报错：snapshot_date 原样回显、榜单状态按当日计算
        "get-top-items-invalid-date", "tools", "POST", "/api/mcp",
        body=_tool_call("get_top_items", {"date": "bogus"}),
        replay="stubbed",
    ),
    ParityCase(
        "get-top-items-weekly", "tools", "POST", "/api/mcp",
        body=_tool_call("get_top_items", {"date": "2026-08-08", "period": "weekly", "source": "arxiv"}),
        replay="stubbed",
    ),
    ParityCase(
        "search-github-projects", "tools", "POST", "/api/mcp",
        body=_tool_call("search_github_projects", {"q": "static site"}),
        replay="stubbed",
    ),
    ParityCase(
        "search-github-ai-projects", "tools", "POST", "/api/mcp",
        body=_tool_call("search_github_ai_projects", {"q": "rag"}),
        replay="stubbed",
    ),
    ParityCase(
        # lang=en：description_en 晋升、*_zh 剔除
        "search-github-ai-projects-en", "tools", "POST", "/api/mcp",
        body=_tool_call("search_github_ai_projects", {"q": "rag", "lang": "en"}),
        replay="stubbed",
    ),
    ParityCase(
        "get-project-categories", "tools", "POST", "/api/mcp",
        body=_tool_call("get_project_categories", {}),
        replay="stubbed",
    ),
    ParityCase(
        "get-project-categories-with-args", "tools", "POST", "/api/mcp",
        body=_tool_call("get_project_categories", {"x": 1}),
    ),
    ParityCase(
        # limit=2, total=3 → 发 next_marker（紧凑 JSON b64url）
        "favorites-first-page", "tools", "POST", "/api/mcp",
        body=_tool_call("search_my_project_favorites", {"limit": 2}),
        auth="parity-token",
        replay="stubbed",
    ),
    ParityCase(
        "favorites-next-page", "tools", "POST", "/api/mcp",
        body=_tool_call("search_my_project_favorites", {"limit": 2, "marker": _marker(2, 2)}),
        auth="parity-token",
        replay="stubbed",
    ),
    ParityCase(
        "favorites-anonymous", "tools", "POST", "/api/mcp",
        body=_tool_call("search_my_project_favorites", {}),
        replay="stubbed",
    ),
    ParityCase(
        "favorites-no-scope", "tools", "POST", "/api/mcp",
        body=_tool_call("search_my_project_favorites", {}),
        auth="limited-token",
        replay="stubbed",
    ),
    ParityCase(
        "favorites-bad-marker", "tools", "POST", "/api/mcp",
        body=_tool_call("search_my_project_favorites", {"marker": "bogus"}),
        auth="parity-token",
    ),
    ParityCase(
        "favorites-marker-limit-mismatch", "tools", "POST", "/api/mcp",
        body=_tool_call("search_my_project_favorites", {"limit": 3, "marker": _marker(2, 2)}),
        auth="parity-token",
    ),
    # ── resources.jsonl ──
    ParityCase(
        "resource-dashboard-summary", "resources", "POST", "/api/mcp",
        body=_rpc(1, "resources/read", {"uri": "aigc-news://dashboard/summary"}),
        replay="stubbed",
    ),
    ParityCase(
        "resource-dashboard-summary-weekly", "resources", "POST", "/api/mcp",
        body=_rpc(1, "resources/read", {"uri": "aigc-news://dashboard/summary?period=weekly&date=2026-08-08"}),
        replay="stubbed",
    ),
    ParityCase(
        "resource-dashboard-summary-embargoed", "resources", "POST", "/api/mcp",
        body=_rpc(1, "resources/read", {"uri": "aigc-news://dashboard/summary?date=2026-08-09"}),
        replay="stubbed",
    ),
    ParityCase(
        "resource-dashboard-top", "resources", "POST", "/api/mcp",
        body=_rpc(1, "resources/read", {"uri": "aigc-news://dashboard/top?source=all&date=2026-08-08&limit=3"}),
        replay="stubbed",
    ),
    ParityCase(
        "resource-projects-categories", "resources", "POST", "/api/mcp",
        body=_rpc(1, "resources/read", {"uri": "aigc-news://projects/categories"}),
        replay="stubbed",
    ),
    ParityCase(
        "resource-projects-library", "resources", "POST", "/api/mcp",
        body=_rpc(1, "resources/read", {"uri": "aigc-news://projects/library?q=rag&limit=5"}),
        replay="stubbed",
    ),
    ParityCase(
        "resource-report-latest-zh", "resources", "POST", "/api/mcp",
        body=_rpc(1, "resources/read", {"uri": "aigc-news://report/latest?date=2026-08-10"}),
        replay="stubbed",
    ),
    ParityCase(
        "resource-report-latest-en", "resources", "POST", "/api/mcp",
        body=_rpc(1, "resources/read", {"uri": "aigc-news://report/latest?date=2026-08-10&locale=en"}),
        replay="stubbed",
    ),
    ParityCase(
        "resource-report-not-found", "resources", "POST", "/api/mcp",
        body=_rpc(1, "resources/read", {"uri": "aigc-news://report/latest?date=2020-01-01"}),
        replay="stubbed",
    ),
    ParityCase(
        "resource-report-oversized", "resources", "POST", "/api/mcp",
        body=_rpc(1, "resources/read", {"uri": "aigc-news://report/latest?date=2026-08-11"}),
        replay="stubbed",
    ),
    ParityCase(
        "resource-paper-detail", "resources", "POST", "/api/mcp",
        body=_rpc(1, "resources/read", {"uri": "aigc-news://papers/2608.01234"}),
        replay="stubbed",
    ),
    ParityCase(
        "resource-unknown-uri", "resources", "POST", "/api/mcp",
        body=_rpc(1, "resources/read", {"uri": "aigc-news://bogus"}),
    ),
    ParityCase(
        "resource-bad-scheme", "resources", "POST", "/api/mcp",
        body=_rpc(1, "resources/read", {"uri": "https://example.com/x"}),
    ),
    ParityCase(
        "resource-missing-uri", "resources", "POST", "/api/mcp",
        body=_rpc(1, "resources/read", {}),
    ),
    # ── prompts.jsonl（static：纯静态文案 + 参数插值） ──
    ParityCase(
        "prompts-get-daily-brief", "prompts", "POST", "/api/mcp",
        body=_rpc(1, "prompts/get", {"name": "daily_research_brief"}),
    ),
    ParityCase(
        "prompts-get-daily-brief-args", "prompts", "POST", "/api/mcp",
        body=_rpc(1, "prompts/get", {"name": "daily_research_brief", "arguments": {"source": "arxiv", "topic": "多模态"}}),
    ),
    ParityCase(
        "prompts-get-project-discovery", "prompts", "POST", "/api/mcp",
        body=_rpc(1, "prompts/get", {"name": "project_discovery", "arguments": {"topic": "RAG", "category": "rag", "language": "Python"}}),
    ),
    ParityCase(
        "prompts-get-unknown", "prompts", "POST", "/api/mcp",
        body=_rpc(1, "prompts/get", {"name": "bogus"}),
    ),
    # ── surface.jsonl：mcp 瘦进程挂载面/CORS/探活 ──
    ParityCase(
        "mcp-live", "surface", "GET", "/api/live",
        app="mcp",
    ),
    ParityCase(
        "mcp-version", "surface", "GET", "/api/version",
        app="mcp",
    ),
    ParityCase(
        # TestClient 不跑 lifespan：monitoring runtime 缺失 → 503 聚合形状
        "mcp-ready-no-lifespan", "surface", "GET", "/api/ready",
        app="mcp",
    ),
    ParityCase(
        "mcp-unknown-path-404", "surface", "GET", "/api/not-mounted",
        app="mcp",
    ),
    ParityCase(
        "mcp-docs-not-exposed", "surface", "GET", "/docs",
        app="mcp",
    ),
    ParityCase(
        "mcp-get-mcp-endpoint-405", "surface", "GET", "/api/mcp",
        app="mcp",
    ),
    ParityCase(
        "mcp-cors-preflight-allowed", "surface", "OPTIONS", "/api/mcp",
        headers={
            "origin": "https://aigcnews.cn",
            "access-control-request-method": "POST",
        },
        app="mcp",
    ),
    ParityCase(
        "mcp-cors-preflight-disallowed", "surface", "OPTIONS", "/api/mcp",
        headers={
            "origin": "https://evil.example",
            "access-control-request-method": "POST",
        },
        app="mcp",
    ),
    ParityCase(
        # 实际响应上的 CORS 头（allow-origin + expose-headers）
        "mcp-post-with-origin", "surface", "POST", "/api/mcp",
        body=_rpc(2, "tools/list", {}),
        headers={**_JSON, "origin": "https://aigcnews.cn"},
        app="mcp",
    ),
)

_NAMES = [case.name for case in CASES]
assert len(set(_NAMES)) == len(_NAMES), f"用例名重复: {_NAMES}"


# ── 录制/回放引擎 ────────────────────────────────────────────────────────


def _load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _normalize_headers(
    headers: Mapping[str, str], manifest: Mapping[str, Any]
) -> dict[str, str]:
    normalized = {str(name).lower(): str(value) for name, value in headers.items()}
    for rule in manifest.get("normalizations", []):
        target = rule.get("target", "")
        prefix = "response.header."
        if not target.startswith(prefix):
            continue
        name = target[len(prefix):]
        if name in normalized and re.fullmatch(rule["pattern"], normalized[name]):
            normalized[name] = rule["replacement"]
    return dict(sorted(normalized.items()))


def _override_map() -> dict[Any, Any]:
    repositories = SimpleNamespace(
        documents=_StubDocuments(),
        rank_snapshots=_StubRankSnapshots(),
        project_collections=_StubProjectCollections(),
    )
    return {
        get_application_repositories: lambda: repositories,
        get_briefing_repository: lambda: _StubBriefing(),
        get_project_search_runtime: lambda: SimpleNamespace(
            search_projects=AsyncMock(side_effect=_search_projects_stub)
        ),
        get_project_catalog_query_service: lambda: _StubCatalogQueries(),
        get_mcp_access_token_authenticator: lambda: _StubTokenRepository(),
    }


@contextlib.contextmanager
def _case_patches(case: ParityCase):
    with contextlib.ExitStack() as stack:
        stack.enter_context(_frozen_time())
        for target, value in case.rate_limit_overrides:
            stack.enter_context(patch.object(mcp_rate_limit, target, value))
        if case.profile == "tool_handler_crash":
            stack.enter_context(
                patch.dict(
                    mcp_tools_module._TOOL_HANDLERS,
                    {"search_papers": AsyncMock(side_effect=RuntimeError("parity probe"))},
                )
            )
        elif case.profile == "dispatch_crash":

            class _CrashingApplication:
                def __init__(self, dependencies) -> None:
                    pass

                async def dispatch(self, inbound):
                    raise RuntimeError("parity probe")

            stack.enter_context(
                patch.object(routes_mcp, "McpProtocolApplication", _CrashingApplication)
            )
        elif case.profile != "default":
            raise ValueError(f"未知 profile: {case.profile}")
        yield


def _request_kwargs(case: ParityCase) -> dict[str, Any]:
    headers = dict(case.headers)
    if case.auth is not None:
        headers["authorization"] = f"Bearer {case.auth}"
    if case.method == "POST" and "content-type" not in {k.lower() for k in headers}:
        headers["content-type"] = "application/json"
    body = case.body.encode("utf-8") if isinstance(case.body, str) else case.body
    return {"headers": headers, "content": body}


def _run_on_app(case: ParityCase, app) -> dict[str, Any]:
    override_keys = set(_override_map())
    app.dependency_overrides.update(_override_map())
    sentinel = object()
    previous_redis = getattr(app.state, "redis", sentinel)
    app.state.redis = FakeRedis()
    try:
        client = TestClient(app, raise_server_exceptions=False)
        with _case_patches(case):
            for _ in range(case.warmup):
                client.request(case.method, case.path, **_request_kwargs(case))
            response = client.request(case.method, case.path, **_request_kwargs(case))
        return {
            "status": response.status_code,
            "headers": dict(response.headers),
            "body": response.content.decode("utf-8"),
        }
    finally:
        for key in override_keys:
            app.dependency_overrides.pop(key, None)
        if previous_redis is sentinel:
            with contextlib.suppress(AttributeError):
                delattr(app.state, "redis")
        else:
            app.state.redis = previous_redis


def run_case(case: ParityCase) -> dict[str, Any]:
    """执行单个用例，返回归一化后的 exchange；app=both 时双 app 逐字节互验。"""
    manifest = _load_manifest()

    def normalized(app) -> dict[str, Any]:
        exchange = _run_on_app(case, app)
        exchange["headers"] = _normalize_headers(exchange["headers"], manifest)
        return exchange

    if case.app == "both":
        main_exchange = normalized(main_module.app)
        mcp_exchange = normalized(mcp_main.app)
        if main_exchange != mcp_exchange:
            raise AssertionError(
                f"用例 {case.name} 在 main/mcp 双 app 间漂移:\n"
                + _diff_exchanges(main_exchange, mcp_exchange)
            )
        return main_exchange
    app = main_module.app if case.app == "main" else mcp_main.app
    return normalized(app)


def _diff_exchanges(left: Mapping[str, Any], right: Mapping[str, Any]) -> str:
    chunks: list[str] = []
    if left["status"] != right["status"]:
        chunks.append(f"status: {left['status']} != {right['status']}")
    if left["headers"] != right["headers"]:
        chunks.append(f"headers: {left['headers']!r} != {right['headers']!r}")
    if left["body"] != right["body"]:
        left_lines = _pretty_body(left["body"]).splitlines(keepends=True)
        right_lines = _pretty_body(right["body"]).splitlines(keepends=True)
        chunks.append(
            "body diff:\n"
            + "".join(
                difflib.unified_diff(left_lines, right_lines, "recorded", "live", n=2)
            )[:8000]
        )
    return "\n".join(chunks)


def _pretty_body(body: str) -> str:
    try:
        parsed = json.loads(body)
    except ValueError:
        return body
    return json.dumps(parsed, ensure_ascii=False, indent=2, sort_keys=True)


# ── 语料读写 ─────────────────────────────────────────────────────────────


def _request_record(case: ParityCase) -> dict[str, Any]:
    kwargs = _request_kwargs(case)
    record: dict[str, Any] = {
        "method": case.method,
        "path": case.path,
        "headers": dict(sorted(kwargs["headers"].items())),
    }
    body: bytes = kwargs["content"]
    try:
        record["body"] = body.decode("utf-8")
    except UnicodeDecodeError:
        record["body_b64"] = base64.b64encode(body).decode("ascii")
    return record


def run_all() -> dict[str, dict[str, Any]]:
    return {case.name: run_case(case) for case in CASES}


def record_all() -> None:
    exchanges = run_all()
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    by_file: dict[str, list[ParityCase]] = {}
    for case in CASES:
        by_file.setdefault(case.file, []).append(case)
    for file_stem, cases in by_file.items():
        path = CORPUS_DIR / f"{file_stem}.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for case in cases:
                exchange = exchanges[case.name]
                line = {
                    "name": case.name,
                    "app": case.app,
                    "replay": case.replay,
                    "request": _request_record(case),
                    "response": exchange,
                }
                handle.write(json.dumps(line, ensure_ascii=False) + "\n")
    FIXTURES_PATH.write_text(
        json.dumps(_fixtures_document(), ensure_ascii=False, indent=2, default=_exportable)
        + "\n",
        encoding="utf-8",
    )
    RECORDING_CONTEXT_PATH.write_text(
        json.dumps(_recording_context(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _exportable(value: Any) -> Any:
    if isinstance(value, datetime):
        return {"__type__": "datetime", "value": value.isoformat()}
    raise TypeError(f"fixtures.json 不支持序列化: {type(value)!r}")


def _fixtures_document() -> dict[str, Any]:
    return {
        "frozen_instant": "2026-08-10T12:00:00+08:00",
        "tokens": copy.deepcopy(_TOKENS),
        "documents": {
            "arxiv_a": _ARXIV_DOC_A,
            "arxiv_b": _ARXIV_DOC_B,
            "news": _NEWS_DOC,
            "oversized": _OVERSIZED_DOC,
        },
        "source_counts": _SOURCE_COUNTS,
        "today_document_count": _TODAY_DOCUMENT_COUNT,
        "dashboard_channels": _DASHBOARD_CHANNEL_DOCS,
        "yesterday_hn_ids": sorted(_YESTERDAY_HN_IDS),
        "project_search_results": {
            "ai": _AI_SEARCH_RESULT,
            "generic": _GENERIC_SEARCH_RESULT,
        },
        "favorites_rows": [_FAV_ROW_1, _FAV_ROW_2, _FAV_ROW_3],
        "categories": _CATEGORIES_RESULT,
        "briefings": {key: value for key, value in _BRIEFING_ROWS.items()},
        "marker_example_limit2_page2": _marker(2, 2),
    }


def _recording_context() -> dict[str, Any]:
    return {
        "public_base_url": settings.public_base_url,
        "cors_allowed_origins": settings.cors_allowed_origins,
        "app_version": resolve_app_version(),
        "frozen_instant": "2026-08-10T12:00:00+08:00",
    }


_RECORDED: dict[str, dict[str, Any]] | None = None


def _recorded_index() -> dict[str, dict[str, Any]]:
    global _RECORDED
    if _RECORDED is None:
        index: dict[str, dict[str, Any]] = {}
        for path in sorted(CORPUS_DIR.glob("*.jsonl")):
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if line:
                        record = json.loads(line)
                        index[record["name"]] = record
        _RECORDED = index
    return _RECORDED


def verify_case(case: ParityCase) -> None:
    recorded = _recorded_index().get(case.name)
    if recorded is None:
        raise AssertionError(
            f"语料缺少用例 {case.name}；以 PARITY_RECORD=1 重录: "
            "PARITY_RECORD=1 python -m pytest tests/parity/ -q"
        )
    if recorded.get("app") != case.app or recorded.get("replay") != case.replay:
        raise AssertionError(f"用例 {case.name} 元数据漂移，须重录语料")
    expected_request = recorded["request"]
    if expected_request != _request_record(case):
        raise AssertionError(f"用例 {case.name} 请求定义漂移，须重录语料")
    live = run_case(case)
    expected_response = recorded["response"]
    if live != expected_response:
        raise AssertionError(
            f"用例 {case.name} 响应漂移:\n" + _diff_exchanges(expected_response, live)
        )


def verify_generated_files_fresh() -> None:
    """fixtures.json / recording_context.json 与当前代码、配置同源。"""
    for path, current in (
        (FIXTURES_PATH, _fixtures_document()),
        (RECORDING_CONTEXT_PATH, _recording_context()),
    ):
        if not path.exists():
            raise AssertionError(f"缺少生成物 {path.name}；以 PARITY_RECORD=1 重录")
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        expected = json.loads(json.dumps(current, default=_exportable))
        if on_disk != expected:
            raise AssertionError(
                f"{path.name} 已陈旧（fixture/配置漂移）；以 PARITY_RECORD=1 重录"
            )


if __name__ == "__main__":
    raise SystemExit(
        "录制器只经 pytest 入口运行（需要 conftest.py 的指标路径重定向保护）:\n"
        "  校验: python -m pytest tests/parity/ -q\n"
        "  重录: PARITY_RECORD=1 python -m pytest tests/parity/ -q"
    )
