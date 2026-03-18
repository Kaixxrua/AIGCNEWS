from __future__ import annotations

"""
联网搜索服务 — web_search_service.py

支持多种搜索引擎后端：
1. DuckDuckGo（免费，无需 API Key，使用 duckduckgo-search 库）
2. Brave Search API（需要 BRAVE_SEARCH_API_KEY，每月 2000 次免费）
3. Tavily API（需要 TAVILY_API_KEY，RAG 友好的结构化结果）

优先级：Tavily > Brave > DuckDuckGo（按照 .env 中 API Key 的存在与否自动选择）

返回格式（统一）：
  List[WebSearchResult]，每条包含 title / url / snippet / source="web"
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import List

from backend.app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class WebSearchResult:
    title: str = ""
    url: str = ""
    snippet: str = ""
    source: str = "web"
    # 额外元信息（Tavily 带完整正文）
    content: str = ""


# ──────────────────────────────────────────────────────────────────────────────
# DuckDuckGo 后端（免费，无需 Key）
# ──────────────────────────────────────────────────────────────────────────────


async def _search_duckduckgo(query: str, max_results: int = 6) -> List[WebSearchResult]:
    """使用 duckduckgo-search 进行联网搜索（同步库，wrap 进线程池）。"""

    def _sync_search() -> List[WebSearchResult]:
        try:
            from duckduckgo_search import DDGS  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "联网搜索需要安装 duckduckgo-search：pip install duckduckgo-search"
            ) from exc

        results: List[WebSearchResult] = []
        with DDGS() as ddgs:
            for item in ddgs.text(query, max_results=max_results):
                results.append(
                    WebSearchResult(
                        title=item.get("title") or "",
                        url=item.get("href") or "",
                        snippet=item.get("body") or "",
                    )
                )
        return results

    return await asyncio.to_thread(_sync_search)


# ──────────────────────────────────────────────────────────────────────────────
# Brave Search API 后端
# ──────────────────────────────────────────────────────────────────────────────


async def _search_brave(query: str, max_results: int = 6) -> List[WebSearchResult]:
    """调用 Brave Search API（需要 BRAVE_SEARCH_API_KEY）。"""
    import httpx

    api_key = settings.brave_search_api_key
    if not api_key:
        raise ValueError("BRAVE_SEARCH_API_KEY 未配置")

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": max_results, "text_decorations": "0"},
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": api_key,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    results: List[WebSearchResult] = []
    for item in data.get("web", {}).get("results", []):
        results.append(
            WebSearchResult(
                title=item.get("title") or "",
                url=item.get("url") or "",
                snippet=item.get("description") or "",
            )
        )
    return results


# ──────────────────────────────────────────────────────────────────────────────
# Tavily Search API 后端（RAG 友好）
# ──────────────────────────────────────────────────────────────────────────────


async def _search_tavily(query: str, max_results: int = 6) -> List[WebSearchResult]:
    """调用 Tavily Search API（需要 TAVILY_API_KEY），返回带完整正文的结果。"""
    import httpx

    api_key = settings.tavily_api_key
    if not api_key:
        raise ValueError("TAVILY_API_KEY 未配置")

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
                "include_raw_content": False,
                "include_answer": False,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    results: List[WebSearchResult] = []
    for item in data.get("results", []):
        results.append(
            WebSearchResult(
                title=item.get("title") or "",
                url=item.get("url") or "",
                snippet=item.get("content") or "",
                content=item.get("raw_content") or "",
            )
        )
    return results


# ──────────────────────────────────────────────────────────────────────────────
# 公开入口：自动选择最优后端
# ──────────────────────────────────────────────────────────────────────────────


async def web_search(query: str, max_results: int = 6) -> List[WebSearchResult]:
    """
    联网搜索统一入口。

    自动按优先级选择可用后端：
      1. Tavily（results 最佳，RAG 友好）
      2. Brave Search
      3. DuckDuckGo（免费兜底）

    如果所有后端都失败，返回空列表并记录日志，不向上抛异常。
    """
    # 按优先级选择后端
    backends = []
    if getattr(settings, "tavily_api_key", ""):
        backends.append(("tavily", _search_tavily))
    if getattr(settings, "brave_search_api_key", ""):
        backends.append(("brave", _search_brave))
    # DuckDuckGo 作为兜底（不需要 key）
    backends.append(("duckduckgo", _search_duckduckgo))

    for name, backend_fn in backends:
        try:
            logger.info(f"[WebSearch] 使用 {name} 后端搜索: {query!r}")
            results = await backend_fn(query, max_results)
            logger.info(f"[WebSearch] {name} 返回 {len(results)} 条结果")
            return results
        except Exception as exc:
            logger.warning(f"[WebSearch] {name} 后端失败: {exc}")
            if name != backends[-1][0]:
                logger.info(f"[WebSearch] 切换到下一个后端...")
            continue

    logger.error(f"[WebSearch] 所有后端均失败，query={query!r}")
    return []


def format_search_results_as_context(results: List[WebSearchResult]) -> str:
    """将联网搜索结果格式化为 LLM 上下文字符串。"""
    if not results:
        return ""

    lines: list[str] = ["[联网搜索结果开始]"]
    for i, item in enumerate(results, start=1):
        lines.append(f"\n[web-{i}] {item.title}")
        if item.url:
            lines.append(f"URL: {item.url}")
        body = item.content or item.snippet
        if body:
            # 截断过长内容（每条最多 800 字符）
            truncated = body[:800] + ("…" if len(body) > 800 else "")
            lines.append(truncated)
    lines.append("\n[联网搜索结果结束]")
    return "\n".join(lines)
