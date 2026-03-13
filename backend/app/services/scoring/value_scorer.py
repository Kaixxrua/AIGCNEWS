from __future__ import annotations

"""Arxiv 论文价值评分器（M9.5）

调用 LLM 对论文摘要进行"创新性 + 实用性"双维打分，
用于在 pipeline 入库前过滤低质量论文。
"""

import json
import logging
import re
import time
from typing import Any, Dict

from backend.app.core.model_factory import get_chat_model

logger = logging.getLogger(__name__)

# 默认过滤阈值：innovation + utility < 12 则丢弃
DEFAULT_MIN_SCORE = 12
# 429 重试配置
_MAX_RETRIES = 4
_RETRY_BASE_DELAY = 15.0  # 首次等待秒数（指数退避）
# 每次成功请求后的固定间隔，避免 RPM 超限
_REQUEST_INTERVAL = 3.0  # 秒

_SYSTEM_PROMPT = (
    "你是一个严格的计算机科学审稿人。"
    "请阅读以下论文摘要，并从'创新性(1-10)'、'实用性(1-10)'两个维度打分。"
    "返回纯 JSON，格式如下（不要有任何多余文字）："
    '{"innovation": <int>, "utility": <int>, "summary": "<一句话中文评价>"}'
)


class Scorer:
    """LLM 价值评分器（带 429 退避重试）。

    Usage::

        scorer = Scorer()
        result = scorer.assess_quality(abstract_text)
        # result = {"innovation": 8, "utility": 7, "summary": "提出...", "total": 15}
    """

    def __init__(self) -> None:
        # temperature=0 确保评分稳定、可重复
        self._llm = get_chat_model(temperature=0)

    def assess_quality(self, text: str) -> Dict[str, Any]:
        """对论文摘要进行打分，遇到 429 限速时自动指数退避重试。

        Returns:
            dict with keys: innovation (int), utility (int),
                            summary (str), total (int).
            出错时返回 {"innovation": 0, "utility": 0, "summary": "评分失败", "total": 0}
        """
        if not text or not text.strip():
            return {"innovation": 0, "utility": 0, "summary": "摘要为空", "total": 0}

        # 截断过长文本，避免超出上下文
        truncated = text.strip()[:2000]

        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=truncated),
        ]

        for attempt in range(_MAX_RETRIES):
            try:
                response = self._llm.invoke(messages)
                raw: str = (
                    response.content if hasattr(response, "content") else str(response)
                )
                result = _parse_score_json(raw)
                result["total"] = result.get("innovation", 0) + result.get("utility", 0)
                logger.debug(
                    "[Scorer] 打分完成: innovation=%d utility=%d summary=%s",
                    result["innovation"],
                    result["utility"],
                    result["summary"],
                )
                # 成功后等待固定间隔，避免后续请求触发 RPM
                time.sleep(_REQUEST_INTERVAL)
                return result

            except Exception as exc:
                exc_str = str(exc)
                is_rate_limit = "429" in exc_str or "rate_limit" in exc_str.lower()
                if is_rate_limit and attempt < _MAX_RETRIES - 1:
                    wait = _RETRY_BASE_DELAY * (2**attempt)
                    logger.warning(
                        "[Scorer] RPM 限速，第 %d/%d 次重试，等待 %.0fs...",
                        attempt + 1,
                        _MAX_RETRIES,
                        wait,
                    )
                    time.sleep(wait)
                else:
                    logger.warning("[Scorer] 打分失败: %s", exc)
                    return {
                        "innovation": 0,
                        "utility": 0,
                        "summary": "评分失败",
                        "total": 0,
                    }

        return {"innovation": 0, "utility": 0, "summary": "重试耗尽", "total": 0}


# ── 内部工具 ──────────────────────────────────────────────────────────────────


def _parse_score_json(raw: str) -> Dict[str, Any]:
    """从 LLM 输出中提取 JSON 对象，兼容 markdown code block 包裹。"""
    # 去掉 ```json ... ``` 包裹
    cleaned = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()

    # 尝试直接 parse
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # 容错：找第一个 { ... } 块
        m = re.search(r"\{.*?\}", cleaned, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group())
            except json.JSONDecodeError:
                data = {}
        else:
            data = {}

    innovation = _clamp(data.get("innovation", 0))
    utility = _clamp(data.get("utility", 0))
    summary = str(data.get("summary", "")).strip() or "无评价"
    return {"innovation": innovation, "utility": utility, "summary": summary}


def _clamp(val: Any, lo: int = 1, hi: int = 10) -> int:
    """将值限制在 [lo, hi] 范围内的整数。"""
    try:
        v = int(val)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(hi, v))
