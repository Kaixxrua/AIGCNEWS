from __future__ import annotations

import re
import traceback
from typing import Any, AsyncGenerator, Dict, List, Tuple

from langchain_core.documents import Document

from backend.app.core.model_factory import get_chat_model
from backend.app.services.rag.retriever import HybridRetriever
from backend.app.services.rag.reranker import rerank, RELEVANCE_THRESHOLD  # type: ignore[import]


# 默认保留最近几轮历史（每轮 = user + assistant 各一条）
MAX_HISTORY_TURNS = 5

PROMPT_TEMPLATE = (
    "你是一个专业的 AIGC 技术助手。请基于以下上下文（Context）回答用户的问题。\n"
    "上下文来自三类数据源：\n"
    "  - [arxiv] = 学术论文（arXiv 预印本）\n"
    "  - [github] = GitHub 开源项目\n"
    "  - [news] = AI 行业新闻\n"
    "  - [neo4j] = 知识图谱实体\n"
    "请仔细阅读上下文，优先根据上下文回答；如果上下文确实不包含足够信息，再说明。\n\n"
    "[上下文开始]\n"
    "{context_str}\n"
    "[上下文结束]\n\n"
    "{chat_history}"
    "用户问题: {query}"
)


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


class ChatService:
    def __init__(self, retriever: HybridRetriever) -> None:
        self.retriever = retriever
        self._llm = get_chat_model()

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
            parts.append(f"{header}\n{content}")
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

    async def stream_chat(
        self,
        query: str,
        history: List[Dict[str, str]] | None = None,
        max_history_turns: int = MAX_HISTORY_TURNS,
        temperature: float | None = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        try:
            # 1. 立即告知前端正在检索，避免前端长时间白屏
            yield {"type": "status", "data": "searching"}

            # 2. 一次检索：获取候选文档
            raw_docs = await self.retriever.search(query)

            # 3. 告知前端正在精排
            yield {"type": "status", "data": "reranking"}

            # 4. LLM 二次精排：过滤不相关文档，按相关性排序
            ranked_docs = await rerank(query, raw_docs, threshold=RELEVANCE_THRESHOLD)

            # 5. 构建上下文（使用精排后的文档）
            context_str = self._build_context(ranked_docs)
            chat_history_str = _format_history(
                history or [], max_turns=max_history_turns
            )
            prompt = PROMPT_TEMPLATE.format(
                context_str=context_str,
                chat_history=chat_history_str,
                query=query,
            )

            # 6. 推送参考来源（精排后的文档）
            yield {"type": "sources", "data": self._build_sources(ranked_docs)}

            # 7. 流式生成回答（支持思维链）
            llm = get_chat_model(temperature) if temperature is not None else self._llm
            async for chunk in llm.astream(prompt):
                thinking, content = _extract_thinking_and_content(chunk)
                if thinking:
                    yield {"type": "thinking", "data": thinking}
                if content:
                    yield {"type": "content", "data": content}

        except Exception as exc:
            traceback.print_exc()
            yield {"type": "error", "data": str(exc)}
