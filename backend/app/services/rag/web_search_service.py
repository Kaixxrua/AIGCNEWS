from __future__ import annotations

"""
联网搜索服务 — web_search_service.py

使用 Kimi 内置的 $web_search builtin_function 实现联网搜索。
需要在 .env 中配置：
  KIMI_API_KEY=sk-xxx          # Moonshot AI API Key
  KIMI_BASE_URL=https://api.moonshot.cn/v1   # 默认值，通常无需修改
  KIMI_MODEL=kimi-k2-turbo-preview           # 支持 $web_search 的模型

工作流程（两轮 tool_calls 循环）：
  1. 发送用户 query + $web_search 工具声明 → Kimi 返回 finish_reason=tool_calls
  2. 将 tool_call.function.arguments 原封不动作为 role=tool 消息提交
  3. Kimi 执行联网搜索，返回 finish_reason=stop 的最终结果文本
  4. 将最终文本包装为 WebSearchResult 列表返回

返回格式（统一）：
  List[WebSearchResult]，每条包含 title / url / snippet / source="web"
"""

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List

import httpx

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

# $web_search builtin_function 声明（Kimi 格式）
_WEB_SEARCH_TOOL: List[Dict[str, Any]] = [
    {
        "type": "builtin_function",
        "function": {
            "name": "$web_search",
        },
    }
]


@dataclass
class WebSearchResult:
    title: str = ""
    url: str = ""
    snippet: str = ""
    source: str = "web"
    # 额外元信息（搜索返回的完整内容）
    content: str = ""


# ──────────────────────────────────────────────────────────────────────────────
# Kimi $web_search builtin_function 后端
# ──────────────────────────────────────────────────────────────────────────────


async def _search_kimi_builtin(
    query: str, max_results: int = 6
) -> List[WebSearchResult]:
    """
    调用 Kimi 内置 $web_search builtin_function 执行联网搜索。

    两轮 tool_calls 循环：
      Round 1: 发送带 $web_search 工具声明的请求 → 收到 finish_reason=tool_calls
      Round 2: 将 arguments 原封不动提交（role=tool）→ Kimi 返回搜索结果文本
    """
    # 使用专属的 Kimi API 配置
    api_key = settings.kimi_api_key
    base_url = (settings.kimi_base_url or "https://api.moonshot.cn/v1").rstrip("/")
    model = settings.kimi_model or "kimi-k2-turbo-preview"
    api_url = f"{base_url}/chat/completions"

    if not api_key:
        logger.warning(
            "[WebSearch] KIMI_API_KEY 未配置，联网搜索已禁用。"
            "请在 .env 中添加 KIMI_API_KEY=sk-xxx（Moonshot AI 官方 Key）"
        )
        return []

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    messages: List[Dict[str, Any]] = [
        {
            "role": "system",
            "content": "你是 Kimi，请使用联网搜索工具查询用户的问题并返回详细结果。",
        },
        {"role": "user", "content": query},
    ]

    # ── Round 1：让 Kimi 生成 $web_search 调用 ──────────────────────
    payload_r1: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "temperature": 0.3,
        "max_tokens": 4096,
        "tools": _WEB_SEARCH_TOOL,
    }

    logger.info(f"[WebSearch] Round 1 → {api_url}, model={model}")

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
        resp1 = await client.post(api_url, json=payload_r1, headers=headers)
        if resp1.status_code != 200:
            logger.error(
                f"[WebSearch] Round 1 HTTP {resp1.status_code}: {resp1.text[:300]}"
            )
        resp1.raise_for_status()
        data1 = resp1.json()

    choices1 = data1.get("choices") or []
    if not choices1:
        logger.warning("[WebSearch] Round 1 返回空 choices")
        return []

    choice1 = choices1[0]
    finish_reason1 = choice1.get("finish_reason") or ""
    message1 = choice1.get("message") or {}

    logger.info(f"[WebSearch] Round 1 finish_reason={finish_reason1!r}")

    if finish_reason1 != "tool_calls":
        # Kimi 直接回答了（未触发搜索）
        content_text = message1.get("content") or ""
        logger.info("[WebSearch] Kimi 未触发 $web_search，将直接内容包装为搜索结果")
        if content_text:
            return [
                WebSearchResult(
                    title=query[:60],
                    url="",
                    snippet=content_text[:800],
                    content=content_text,
                )
            ]
        return []

    # ── Round 2：将 tool_calls arguments 原封不动提交给 Kimi ─────────
    tool_calls = message1.get("tool_calls") or []
    if not tool_calls:
        logger.warning("[WebSearch] finish_reason=tool_calls 但 tool_calls 列表为空")
        return []

    # 将 Round 1 的 assistant 消息加入上下文（必须保留）
    messages.append(message1)

    # 逐个处理 tool_calls（$web_search 通常只有一个）
    for tc in tool_calls:
        tc_id = tc.get("id") or ""
        func = tc.get("function") or {}
        tc_name = func.get("name") or ""
        # 关键：arguments 原封不动返回，不做任何处理
        tc_arguments = func.get("arguments") or "{}"

        logger.info(
            f"[WebSearch] 提交 tool_call: id={tc_id!r} name={tc_name!r} "
            f"arguments={tc_arguments!r}"
        )

        messages.append(
            {
                "role": "tool",
                "tool_call_id": tc_id,
                "name": tc_name,
                "content": tc_arguments,  # 原封不动，Kimi 文档明确要求
            }
        )

    payload_r2: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "temperature": 0.3,
        "max_tokens": 8192,
        "tools": _WEB_SEARCH_TOOL,  # 每次请求都带上 tools 声明
    }

    logger.info("[WebSearch] Round 2 → 等待 Kimi 执行联网搜索...")

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
        resp2 = await client.post(api_url, json=payload_r2, headers=headers)
        if resp2.status_code != 200:
            logger.error(
                f"[WebSearch] Round 2 HTTP {resp2.status_code}: {resp2.text[:300]}"
            )
        resp2.raise_for_status()
        data2 = resp2.json()

    choices2 = data2.get("choices") or []
    if not choices2:
        logger.warning("[WebSearch] Round 2 返回空 choices")
        return []

    choice2 = choices2[0]
    message2 = choice2.get("message") or {}
    final_content = message2.get("content") or ""

    logger.info(
        f"[WebSearch] Round 2 finish_reason={choice2.get('finish_reason')!r}，"
        f"内容长度={len(final_content)}"
    )

    if not final_content:
        return []

    return _parse_kimi_response(final_content, query, max_results)


def _parse_kimi_response(
    text: str, query: str, max_results: int = 6
) -> List[WebSearchResult]:
    """
    将 Kimi $web_search 返回的 Markdown 文本解析为 WebSearchResult 列表。

    尝试提取 [标题](URL) 格式的链接；无结构化链接时将整段内容作为一条结果。
    """
    results: List[WebSearchResult] = []
    seen_urls: set = set()

    # 提取所有 Markdown 链接：[标题](URL)
    link_pattern = re.compile(r"\[([^\]]+)\]\((https?://[^\)\s]+)\)")
    found_links = link_pattern.findall(text)

    if found_links:
        for title, link_url in found_links:
            if link_url in seen_urls:
                continue
            seen_urls.add(link_url)

            # 提取链接后的文字作为摘要
            link_expr = f"[{title}]({link_url})"
            link_pos = text.find(link_expr)
            snippet_start = link_pos + len(link_expr)
            snippet_raw = text[snippet_start : snippet_start + 400].strip()
            # 清理 Markdown 标记
            snippet = link_pattern.sub(r"\1", snippet_raw)
            snippet = re.sub(r"[#*`>\-]+\s*", "", snippet).strip()[:300]

            results.append(
                WebSearchResult(
                    title=title.strip(),
                    url=link_url.strip(),
                    snippet=snippet,
                    content=text,
                )
            )
            if len(results) >= max_results:
                break

    if not results:
        # 无结构化链接，整段内容作为一条结果
        results.append(
            WebSearchResult(
                title=query[:60],
                url="",
                snippet=text[:800],
                content=text,
            )
        )

    return results


# ──────────────────────────────────────────────────────────────────────────────
# 公开入口
# ──────────────────────────────────────────────────────────────────────────────


async def web_search(query: str, max_results: int = 6) -> List[WebSearchResult]:
    """
    联网搜索统一入口。

    使用 Kimi 内置的 $web_search builtin_function 执行联网搜索。
    搜索失败时返回空列表并记录日志，不向上抛异常。
    """
    try:
        logger.info(f"[WebSearch] 使用 Kimi $web_search 搜索: {query!r}")
        results = await _search_kimi_builtin(query, max_results)
        logger.info(f"[WebSearch] Kimi $web_search 返回 {len(results)} 条结果")
        return results
    except Exception as exc:
        logger.error(f"[WebSearch] Kimi $web_search 失败: {exc}", exc_info=True)
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
