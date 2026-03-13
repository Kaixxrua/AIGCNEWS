from __future__ import annotations

"""LLM 异步批量评分器（M11/M12）

对采集到的 Document 列表进行 AI 打分，
使用 Semaphore 控制并发，遇到 429 限速时自动退避重试。
"""

import asyncio
import json
import logging
import re
from typing import Any, Dict, List

from langchain_core.documents import Document

from backend.app.core.model_factory import get_chat_model

logger = logging.getLogger(__name__)

# 并发控制：同时最多 1 个 LLM 请求，避免 RPM 超限
_DEFAULT_CONCURRENCY = 1
# 默认兜底分数（解析失败时）
_FALLBACK_SCORE = 5
# 429 重试配置
_MAX_RETRIES = 4
_RETRY_BASE_DELAY = 15.0  # 首次重试等待秒数（指数退避）
# 每次成功请求后的固定等待（避免触发 RPM）
_REQUEST_INTERVAL = 3.0  # 秒

_SCORE_PROMPT_TEMPLATE = """\
你是一个严苛的技术主编。请对以下资讯打分（0-10分）：
标题：{title}
摘要：{summary}

评分维度：1.技术创新性 2.社区影响力/实用价值。
请仅返回JSON（不要有任何多余文字）：{{"score": <int>, "reason": "<简短评价>"}}"""


class LLMScorer:
    """异步批量 LLM 评分器。

    Usage::

        scorer = LLMScorer()
        scored_docs = await scorer.score_documents(docs)
        # 每个 doc.metadata 增加 ai_score (int) 和 ai_reason (str)
    """

    def __init__(self, concurrency: int = _DEFAULT_CONCURRENCY) -> None:
        self._llm = get_chat_model(temperature=0)
        self._semaphore = asyncio.Semaphore(concurrency)

    async def score_documents(self, docs: List[Document]) -> List[Document]:
        """顺序对所有文档打分，结果写入 doc.metadata。

        为避免 RPM 限速，文档逐条处理（concurrency=1 时等同顺序执行）。

        Args:
            docs: 待评分文档列表

        Returns:
            已在 metadata 中注入 ai_score / ai_reason 的文档列表
        """
        if not docs:
            return docs

        tasks = [self._score_one(doc) for doc in docs]
        return await asyncio.gather(*tasks)

    async def _score_one(self, doc: Document) -> Document:
        """对单个文档打分，带 Semaphore 并发控制 + 指数退避重试（应对 429）。"""
        async with self._semaphore:
            title = doc.metadata.get("title", "")
            summary = (doc.page_content or "")[:800]
            prompt = _SCORE_PROMPT_TEMPLATE.format(title=title, summary=summary)

            for attempt in range(_MAX_RETRIES):
                try:
                    from langchain_core.messages import HumanMessage

                    response = await self._llm.ainvoke([HumanMessage(content=prompt)])
                    raw: str = (
                        response.content
                        if hasattr(response, "content")
                        else str(response)
                    )
                    result = _parse_score_json(raw)
                    doc.metadata["ai_score"] = result["score"]
                    doc.metadata["ai_reason"] = result["reason"]
                    logger.debug(
                        "[LLMScorer] %s -> score=%d reason=%s",
                        title[:40],
                        result["score"],
                        result["reason"][:30],
                    )
                    # 成功后等待固定间隔，避免后续请求触发 RPM
                    await asyncio.sleep(_REQUEST_INTERVAL)
                    break  # 成功，退出重试循环

                except Exception as exc:
                    exc_str = str(exc)
                    # 判断是否为速率限制错误
                    is_rate_limit = "429" in exc_str or "rate_limit" in exc_str.lower()
                    if is_rate_limit and attempt < _MAX_RETRIES - 1:
                        wait = _RETRY_BASE_DELAY * (2**attempt)
                        logger.warning(
                            "[LLMScorer] RPM 限速，第 %d/%d 次重试，等待 %.0fs (%s)...",
                            attempt + 1,
                            _MAX_RETRIES,
                            wait,
                            title[:30],
                        )
                        await asyncio.sleep(wait)
                    else:
                        logger.warning("[LLMScorer] 打分失败 (%s): %s", title[:40], exc)
                        doc.metadata["ai_score"] = _FALLBACK_SCORE
                        doc.metadata["ai_reason"] = "评分失败"
                        break

        return doc


# ── 内部工具 ──────────────────────────────────────────────────────────────────


def _parse_score_json(raw: str) -> Dict[str, Any]:
    """从 LLM 输出中提取 JSON，兼容 markdown 代码块包裹。"""
    cleaned = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\{.*?\}", cleaned, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group())
            except json.JSONDecodeError:
                data = {}
        else:
            data = {}

    score = _clamp_score(data.get("score", _FALLBACK_SCORE))
    reason = str(data.get("reason", "")).strip() or "无评价"
    return {"score": score, "reason": reason}


def _clamp_score(val: Any, lo: int = 0, hi: int = 10) -> int:
    try:
        return max(lo, min(hi, int(val)))
    except (TypeError, ValueError):
        return _FALLBACK_SCORE
