from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from langchain_core.documents import Document

from backend.app.core.config import settings
from backend.app.services.rag.database_tools import TOOL_DEFINITIONS, run_tool_calls
from backend.app.services.rag.development_orchestrator import (
    DevelopmentDecision,
    assess_candidate,
    classify_development_request,
)
from backend.app.services.rag.ports import RagRetriever
from backend.app.services.rag.raw_openai_streamer import (
    ChatCompletionResult,
    ToolCallResult,
    chat_completions,
    stream_chat_completions,
)
from backend.app.services.rag.reranker import (  # type: ignore[import]
    RELEVANCE_THRESHOLD,
    rerank,
)
from backend.app.services.rag.web_search_service import (
    WebSearchResult,
    format_search_results_as_context,
    web_search,
)

logger = logging.getLogger(__name__)

# SSE 错误帧的通用对外文案：原始异常只进服务端日志，不外泄给客户端。
_STREAM_ERROR_MESSAGE = "服务内部错误，请稍后重试"

# 默认保留最近几轮历史（每轮 = user + assistant 各一条）
MAX_HISTORY_TURNS = 5

SYSTEM_PROMPT = (
    "你是一个专业的 AIGC 技术助手。请始终使用中文进行思考和回答。\n"
    "你的思考过程（reasoning）也必须使用中文。\n"
    "你可以使用工具来查询数据库中的实时数据。当用户询问排行榜、统计数量、"
    "知识库内容等结构化数据问题时，请调用合适的工具获取真实数据后再回答。"
)

PROMPT_TEMPLATE = (
    "请基于以下上下文（Context）回答用户的问题。\n"
    "上下文来自以下数据源：\n"
    "  - [arxiv] = 学术论文（arXiv 预印本）\n"
    "  - [github] = GitHub 开源项目\n"
    "  - [news] = AI 行业新闻\n"
    "  - [producthunt] = Product Hunt 新产品\n"
    "  - [hackernews] = Hacker News 热帖\n"
    "  - [x] = X/Twitter 关注账号推文\n"
    "  - [neo4j] = 知识图谱实体\n"
    "  - [web-N] = 互联网实时搜索结果\n"
    "  - [db-query] = 数据库实时查询结果\n"
    "请仔细阅读上下文，优先根据上下文回答；如果上下文确实不包含足够信息，再说明。\n\n"
    "[上下文开始]\n"
    "{context_str}\n"
    "[上下文结束]\n\n"
    "{chat_history}"
    "用户问题: {query}"
)


# ── 通用辅助函数 ──────────────────────────────────────────────────

def _format_history(
    history: List[Dict[str, str]], max_turns: int = MAX_HISTORY_TURNS
) -> str:
    """将对话历史格式化为 Prompt 片段，只取最近 max_turns 轮（每轮 user+assistant 2条）。"""
    if not history:
        return ""
    recent = history[-(max_turns * 2) :]
    lines: List[str] = ["[对话历史开始]"]
    for msg in recent:
        role = msg.get("role", "")
        content = msg.get("content", "").strip()
        if role == "user":
            lines.append(f"用户: {content}")
        elif role == "assistant":
            lines.append(f"助手: {content}")
    lines.append("[对话历史结束]\n\n")
    return "\n".join(lines)


# 匹配 <think>...</think> 块（DeepSeek-R1 / QwQ 等本地推理模型）
_THINK_TAG_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL)


def _extract_thinking_and_content(chunk: Any) -> Tuple[str, str]:
    """
    从流式 chunk 中同时提取思维链（thinking）和正文（content）。

    兼容以下四种格式：

    1. Anthropic 原生 SDK（ChatAnthropic + Extended Thinking）
       chunk.content 是列表，每个元素是字典：
         {"type": "thinking", "thinking": "..."} → 思维链
         {"type": "text",    "text":    "..."} → 正文
         {"type": "thinking_delta", "thinking": "..."} → 流式思维链增量
         {"type": "text_delta",     "text":     "..."} → 流式正文增量
         {"index": ..., "type": "input_json_delta", ...} 等工具调用块 → 忽略

    2. additional_kwargs["reasoning_content"]
       Claude / DeepSeek 通过 OpenAI-compatible 代理透传的扩展字段

    3. additional_kwargs["thinking"]
       部分 OpenAI-compatible 代理字段

    4. content 字符串内含 <think>...</think> 标签
       DeepSeek-R1 / QwQ 本地格式
    """
    additional: Dict[str, Any] = getattr(chunk, "additional_kwargs", {}) or {}
    raw_content_field = getattr(chunk, "content", None)

    thinking_parts: List[str] = []
    text_parts: List[str] = []

    # ── 格式 1：Anthropic 原生 content 列表 ─────────────────────────
    if isinstance(raw_content_field, list):
        for block in raw_content_field:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type", "")
            if block_type in ("thinking", "thinking_delta"):
                val = block.get("thinking") or block.get("thinking_delta") or ""
                if val:
                    thinking_parts.append(str(val))
            elif block_type in ("text", "text_delta"):
                val = block.get("text") or block.get("text_delta") or ""
                if val:
                    text_parts.append(str(val))
            # input_json_delta / tool_use / 其他类型直接忽略

        thinking = "".join(thinking_parts)
        raw_content = "".join(text_parts)

    else:
        # ── 格式 2 / 3：additional_kwargs 扩展字段 ───────────────────
        raw_content = str(raw_content_field or "")
        thinking = str(additional.get("reasoning_content") or "") or str(
            additional.get("thinking") or ""
        )

        # ── 格式 4：<think> 标签内嵌在 content 中 ──────────────────
        if not thinking and raw_content:
            match = _THINK_TAG_RE.search(raw_content)
            if match:
                thinking = match.group(1)
                raw_content = _THINK_TAG_RE.sub("", raw_content).strip()

    return thinking, raw_content


class GenerationOrchestrator:
    def __init__(
        self,
        retriever: RagRetriever,
        *,
        stream_completion: Any = stream_chat_completions,
        completion: Any = chat_completions,
        web_searcher: Any = web_search,
        web_context_formatter: Any = format_search_results_as_context,
        reranker: Any = rerank,
        database_tool_runner: Any = run_tool_calls,
        tool_definitions: Any = TOOL_DEFINITIONS,
        development_classifier: Any = classify_development_request,
        project_searcher: Any,
    ) -> None:
        self.retriever = retriever
        self._stream_completion = stream_completion
        self._completion = completion
        self._web_searcher = web_searcher
        self._web_context_formatter = web_context_formatter
        self._reranker = reranker
        self._database_tool_runner = database_tool_runner
        self._tool_definitions = tool_definitions
        self._development_classifier = development_classifier
        self._project_searcher = project_searcher

    @staticmethod
    def _build_web_sources(results: List[WebSearchResult]) -> List[Dict[str, Any]]:
        """将联网搜索结果转换为前端来源格式。"""
        sources = []
        for i, item in enumerate(results, start=1):
            sources.append(
                {
                    "id": f"web-{i}",
                    "score": 0.0,
                    "source": "web",
                    "title": item.title or item.url,
                    "url": item.url,
                    "published_date": "",
                }
            )
        return sources

    @staticmethod
    def _build_context(docs: List[Document]) -> str:
        parts: List[str] = []
        for doc in docs:
            meta = doc.metadata or {}
            source_type = str(meta.get("source") or "unknown")
            title = str(meta.get("title") or "")
            url = str(meta.get("url") or "")
            content = doc.page_content.strip()
            if not content:
                continue
            header = f"[{source_type}]"
            if title:
                header += f" {title}"
            if url:
                header += f" ({url})"
            entry = f"{header}\n{content}"
            # 对 GitHub 来源追加结构化数值字段，确保 LLM 能看到 stars/forks/language
            if source_type.lower() == "github":
                stars = meta.get("stars") or meta.get("raw_score") or 0
                forks = meta.get("forks") or 0
                language = meta.get("language") or ""
                extra_parts = [f"Stars: {int(stars)}"]
                if forks:
                    extra_parts.append(f"Forks: {int(forks)}")
                if language:
                    extra_parts.append(f"Language: {language}")
                extra_line = " | ".join(extra_parts)
                entry += f"\n[GitHub 数据] {extra_line} | URL: {url}"
            parts.append(entry)
        return "\n\n".join(parts)

    @staticmethod
    def _safe_meta(meta: Dict[str, Any]) -> Dict[str, Any]:
        safe: Dict[str, Any] = {}
        for k, v in meta.items():
            if isinstance(v, (str, int, float, bool, type(None))):
                safe[k] = v
            elif isinstance(v, dict):
                safe[k] = {
                    dk: (
                        str(dv)
                        if not isinstance(dv, (str, int, float, bool, type(None)))
                        else dv
                    )
                    for dk, dv in v.items()
                }
            else:
                safe[k] = str(v)
        return safe

    @staticmethod
    def _build_sources(docs: List[Document]) -> List[Dict[str, Any]]:
        """
        从精排后的文档列表构建参考来源。

        只展示 retriever='vector' 的向量检索文档（已通过 embedding 相似度阈值）。
        sqlite_fallback / source_fallback 文档只用于 LLM 上下文，不展示为来源。
        """
        candidates: List[Dict[str, Any]] = []
        seen_urls: set[str] = set()

        for index, doc in enumerate(docs, start=1):
            meta = dict(doc.metadata or {})
            retriever_type = str(meta.get("retriever") or "")

            # 只展示向量检索文档
            if retriever_type not in ("vector", "hybrid"):
                continue

            source_id = (
                meta.get("id")
                or meta.get("source_id")
                or meta.get("source")
                or f"doc-{index}"
            )
            url = str(meta.get("url") or "")
            title = str(meta.get("title") or "")

            # 跳过无标题且无 URL 的碎片文档
            if not title and not url:
                continue

            dedup_key = url if url else f"{title}::{source_id}"
            if dedup_key in seen_urls:
                continue
            seen_urls.add(dedup_key)

            # 使用 embedding 精排相似度分数（0-10）
            rerank_score = float(meta.get("rerank_score") or 0.0)

            candidates.append(
                {
                    "id": str(source_id),
                    "score": rerank_score,
                    "source": str(meta.get("source") or ""),
                    "title": title,
                    "url": url,
                    "published_date": str(meta.get("published_date") or ""),
                }
            )

        candidates.sort(key=lambda x: x.get("score") or 0.0, reverse=True)
        return candidates

    async def _run_tool_calls(
        self, tool_calls: List[ToolCallResult]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], str]:
        return await self._database_tool_runner(tool_calls)

    async def _stream_direct_development(
        self,
        query: str,
        history: List[Dict[str, str]],
        decision: DevelopmentDecision,
        model: str,
        temperature: float,
        max_history_turns: int,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        yield {"type": "sources", "data": []}
        history_text = _format_history(history, max_turns=max_history_turns)
        instruction = (
            "这是一个局部或已明确路线的开发需求。直接提供最小、可执行的实现建议，不搜索外部项目。"
            "优先复用现有代码和依赖。你没有直接编辑用户仓库的工具，不得声称已经修改文件。"
        )
        if "user_chose_reuse" in decision.reasons:
            instruction = "用户已经选择复用前一轮候选项目。基于对话中的候选和约束给出接入/二次开发方案，不重复搜索。"
        elif "user_chose_scratch" in decision.reasons:
            instruction = "用户已经明确选择从零自研。给出贴合现有需求的架构和实施步骤，不重复搜索开源项目。"
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT + "\n" + instruction},
            {"role": "user", "content": f"{history_text}用户问题: {query}"},
        ]
        async for delta in self._stream_completion(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=settings.llm_max_tokens,
        ):
            if delta.reasoning:
                yield {"type": "thinking", "data": delta.reasoning}
            if delta.content:
                yield {"type": "content", "data": delta.content}

    async def _stream_project_discovery(
        self,
        query: str,
        decision: DevelopmentDecision,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        yield {"type": "status", "data": "discovering_projects"}
        result = await self._project_searcher(
            query=decision.query_hint,
            mode=decision.search_mode,
            language=decision.language_hint,
            limit=5,
        )
        items = list(result.get("items") or [])
        sources = [
            {
                "id": item.get("id"),
                "title": item.get("full_name") or "GitHub project",
                "url": item.get("url") or "",
                "source": "mcp-project-search",
                "score": item.get("hot_score") or item.get("stars") or 0,
                "result_origin": item.get("result_origin") or result.get("result_origin"),
            }
            for item in items[:5]
        ]
        yield {"type": "sources", "data": sources}
        if not items:
            failure = str(result.get("fallback_error") or "").strip()
            detail = f"（{failure}）" if failure else ""
            yield {
                "type": "content",
                "data": (
                    f"没有找到足够匹配的开源项目{detail}。请选择下一步：\n"
                    "- **B：从零开发**，我将按需求给出架构和实施方案\n"
                    "- **C：调整条件后重新搜索**"
                ),
            }
            return

        assessed = [(item, assess_candidate(item, high_risk=decision.scores.risk >= 3)) for item in items[:5]]
        worthwhile = [(item, assessment) for item, assessment in assessed if assessment.worthwhile]
        selected = (worthwhile or assessed)[:3]
        lines = ["我先检查了可复用的开源项目："]
        for index, (item, assessment) in enumerate(selected, 1):
            description = item.get("description_zh") or item.get("description") or "暂无简介"
            origin = "AIGC_NEWS 本地项目库" if item.get("result_origin") != "github_api_fallback" else "GitHub 实时 fallback"
            lines.append(
                f"{index}. **{item.get('full_name') or '未命名项目'}**（{item.get('stars', 0)} stars，{item.get('language') or '语言未知'}）\n"
                f"   - {description}\n   - 来源：{origin}；候选质量：{assessment.score:.2f}；许可证与安全性仍需在采用前核实"
            )

        must_ask = decision.route == "search_and_ask" or any(a.requires_user_choice for _, a in selected)
        if decision.route == "light_search" and not worthwhile:
            lines.extend(["", "这些候选的复用价值没有明显高于当前自研成本，建议直接基于现有项目实现。我可以继续给出最小实现方案。"])
        elif must_ask:
            lines.extend([
                "", "请选择下一步：",
                "- **A：复用开源项目**（回复项目编号，我再给出接入/二次开发方案）",
                "- **B：从零开发**（按你的需求自行设计）",
                "- **C：调整条件后重新搜索**",
            ])
        else:
            lines.extend(["", "建议优先评估第 1 个候选；它属于低路线影响的可复用方案。如不采用，我也可以直接给出自研实现。"])
        yield {"type": "content", "data": "\n".join(lines)}

    async def stream_chat(
        self,
        query: str,
        history: List[Dict[str, str]] | None = None,
        max_history_turns: int = MAX_HISTORY_TURNS,
        temperature: float | None = None,
        web_search_enabled: bool = False,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        try:
            effective_model = settings.thinking_model_name or settings.chat_model_name
            effective_temp = temperature if temperature is not None else settings.llm_temperature
            decision = self._development_classifier(query, history or [])
            logger.info(
                "[ChatService] development route=%s score=%s reasons=%s mode=%s",
                decision.route,
                decision.score,
                list(decision.reasons),
                decision.search_mode,
            )

            if decision.route == "clarify":
                yield {"type": "status", "data": "clarifying_scope"}
                yield {"type": "sources", "data": []}
                yield {
                    "type": "content",
                    "data": (
                        "这个需求的范围还不够明确。它是：\n"
                        "1. **现有项目中的局部修改**——我直接按当前代码处理；还是\n"
                        "2. **完整功能或独立子系统**——我先搜索可复用的开源项目，再比较复用与自研？"
                    ),
                }
                return

            if decision.route == "direct":
                async for event in self._stream_direct_development(
                    query, history or [], decision, effective_model, effective_temp, max_history_turns
                ):
                    yield event
                return

            if decision.route in {"light_search", "search_and_ask"}:
                async for event in self._stream_project_discovery(query, decision):
                    yield event
                return

            # 非开发请求保留原有 RAG、联网搜索和结构化工具路径。
            yield {"type": "status", "data": "searching"}

            # 并发执行：RAG 检索 + 联网搜索 + LLM 工具判断（第一轮）

            # 构建第一轮 LLM 调用的消息（带 tools）
            first_round_messages: List[Dict[str, Any]] = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ]

            tasks: Dict[str, Any] = {
                "rag": self.retriever.search(query),
                "tool_decision": self._completion(
                    messages=first_round_messages,
                    model=effective_model,
                    temperature=effective_temp,
                    max_tokens=1024,
                    tools=self._tool_definitions,
                    tool_choice="auto",
                ),
            }
            if web_search_enabled:
                tasks["web"] = self._web_searcher(query, max_results=6)

            task_keys = list(tasks.keys())
            task_coros = list(tasks.values())
            results = await asyncio.gather(*task_coros, return_exceptions=True)
            task_results = dict(zip(task_keys, results))

            # 提取 RAG 结果
            raw_docs = task_results.get("rag", [])
            if isinstance(raw_docs, Exception):
                logger.warning("[ChatService] RAG search error: %s", raw_docs)
                raw_docs = []

            # 提取联网搜索结果
            web_results: List[WebSearchResult] = []
            if "web" in task_results:
                wr = task_results["web"]
                web_results = wr if not isinstance(wr, Exception) else []

            # 提取工具判断结果
            tool_decision: Optional[ChatCompletionResult] = None
            td = task_results.get("tool_decision")
            if isinstance(td, ChatCompletionResult):
                tool_decision = td
            elif isinstance(td, Exception):
                logger.warning("[ChatService] Tool decision error: %s", td)

            # 3. 执行工具调用（如果 LLM 返回了 tool_calls）
            tool_messages: List[Dict[str, Any]] = []
            tool_sources: List[Dict[str, Any]] = []
            tool_context = ""

            if tool_decision and tool_decision.tool_calls:
                logger.info(
                    "[ChatService] LLM requested %s tool call(s): %s",
                    len(tool_decision.tool_calls),
                    [tc.name for tc in tool_decision.tool_calls],
                )
                yield {"type": "status", "data": "querying database"}
                tool_messages, tool_sources, tool_context = await self._run_tool_calls(
                    tool_decision.tool_calls
                )

            # 4. 智能精排：检查向量检索文档的 Milvus 分数
            VECTOR_SCORE_SKIP_THRESHOLD = 0.6
            vector_docs = [
                d for d in raw_docs if (d.metadata or {}).get("retriever") == "vector"
            ]
            best_vector_score = (
                min((d.metadata.get("score", 1.0) for d in vector_docs), default=1.0)
                if vector_docs
                else 1.0
            )

            if best_vector_score > VECTOR_SCORE_SKIP_THRESHOLD or not vector_docs:
                logger.info(
                    "[ChatService] Skipping rerank: best_vector_score=%.4f > %s or no vector docs",
                    best_vector_score,
                    VECTOR_SCORE_SKIP_THRESHOLD,
                )
                ranked_docs = raw_docs
                for doc in ranked_docs:
                    doc.metadata = dict(doc.metadata or {})
                    doc.metadata.setdefault("rerank_score", 0.0)
            else:
                yield {"type": "status", "data": "reranking"}
                ranked_docs = await self._reranker(
                    query, raw_docs, threshold=RELEVANCE_THRESHOLD
                )

            # 5. 构建上下文
            rag_context = self._build_context(ranked_docs)
            web_context = (
                self._web_context_formatter(web_results) if web_results else ""
            )
            context_parts = [
                p for p in [tool_context, rag_context, web_context] if p
            ]
            context_str = (
                "\n\n".join(context_parts) if context_parts else "（暂无相关上下文）"
            )

            chat_history_str = _format_history(
                history or [], max_turns=max_history_turns
            )
            prompt = PROMPT_TEMPLATE.format(
                context_str=context_str,
                chat_history=chat_history_str,
                query=query,
            )

            # 6. 推送参考来源
            rag_sources = self._build_sources(ranked_docs)
            web_sources = self._build_web_sources(web_results) if web_results else []
            all_sources = tool_sources + rag_sources + web_sources
            yield {"type": "sources", "data": all_sources}

            # 7. 构建第二轮消息（流式生成最终回答）
            messages_for_api: List[Dict[str, Any]] = [
                {"role": "system", "content": SYSTEM_PROMPT},
            ]

            if tool_decision and tool_decision.tool_calls and tool_messages:
                # Tool Use 路径：把第一轮的 assistant + tool 消息都加上
                assistant_msg: Dict[str, Any] = {"role": "assistant", "content": None}
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in tool_decision.tool_calls
                ]
                messages_for_api.append({"role": "user", "content": query})
                messages_for_api.append(assistant_msg)
                messages_for_api.extend(tool_messages)
                # 最后追加一个 user 消息，提示 LLM 根据工具结果 + RAG 上下文回答
                messages_for_api.append(
                    {"role": "user", "content": prompt}
                )
            else:
                # 无工具调用，直接用 prompt
                messages_for_api.append({"role": "user", "content": prompt})

            # 8. 流式生成回答（支持思维链）
            async for delta in self._stream_completion(
                messages=messages_for_api,
                model=effective_model,
                temperature=effective_temp,
                max_tokens=settings.llm_max_tokens,
            ):
                if delta.reasoning:
                    yield {"type": "thinking", "data": delta.reasoning}
                if delta.content:
                    yield {"type": "content", "data": delta.content}

        except Exception:
            logger.exception("[ChatService] stream failed")
            yield {"type": "error", "data": _STREAM_ERROR_MESSAGE}
