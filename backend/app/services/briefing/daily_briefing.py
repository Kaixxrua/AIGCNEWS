from __future__ import annotations

import logging
import traceback
from datetime import date
from typing import Any, AsyncGenerator, Dict, List, Optional

from backend.app.core.model_factory import get_chat_model
from backend.app.repositories.mysql_repo import MySQLRepository

logger = logging.getLogger(__name__)

# ── Prompt 模板（按来源类型区分）──────────────────────────────────────────────
# 模板中使用 {period_label} 来适配日/周/月报措辞

_PROMPT_ALL = """你是一位专业的 AIGC 技术资讯编辑。请根据以下{period_label}热点内容（综合学术论文、开源项目、行业新闻），撰写一份结构清晰的综合{period_label}报。

**要求：**
1. 使用 Markdown 格式输出
2. 包含"{period_label}热点摘要"、"技术亮点"、"工程动态"、"行业资讯"、"值得关注"五个章节
3. 每篇内容用一两句话精炼概括
4. 语言简洁专业，面向技术从业者
5. 最后附上日期和数据来源

**{period_label}热点内容（共 {count} 条）：**
{articles}

**生成日期：** {date}
"""

_PROMPT_ARXIV = """你是一位专业的 AI 学术研究分析师。请根据以下{period_label} Arxiv 学术论文，撰写一份学术{period_label}报。

**要求：**
1. 使用 Markdown 格式输出
2. 包含"{period_label}研究热点"、"核心技术突破"、"值得精读的论文"三个章节
3. 重点突出研究创新点和实验结论
4. 语言专业严谨，面向研究人员

**{period_label} Arxiv 论文（共 {count} 篇）：**
{articles}

**生成日期：** {date}
"""

_PROMPT_GITHUB = """你是一位专业的 AI 工程技术分析师。请根据以下{period_label} GitHub 热门开源项目，撰写一份工程{period_label}报。

**要求：**
1. 使用 Markdown 格式输出
2. 包含"{period_label}明星项目"、"技术栈分析"、"实践价值"三个章节
3. 重点突出项目的工程价值、使用场景、Stars 趋势
4. 语言务实，面向工程师和架构师

**{period_label} GitHub 热门项目（共 {count} 个）：**
{articles}

**生成日期：** {date}
"""

_PROMPT_NEWS = """你是一位专业的 AI 行业分析师。请根据以下{period_label} AI 行业新闻，撰写一份商业{period_label}报。

**要求：**
1. 使用 Markdown 格式输出
2. 包含"{period_label}行业动态"、"商业化进展"、"政策与监管"、"值得关注的趋势"四个章节
3. 重点突出商业影响力和行业趋势
4. 语言通俗易懂，面向决策者和产品经理

**{period_label} AI 行业新闻（共 {count} 条）：**
{articles}

**生成日期：** {date}
"""


_PROMPT_PRODUCTHUNT = """你是一位专业的 AI 产品分析师。请根据以下{period_label} Product Hunt 热门 AI 产品，撰写一份产品{period_label}报。

**要求：**
1. 使用 Markdown 格式输出
2. 包含"{period_label}明星产品"、"功能亮点"、"市场价值"、"值得关注的产品"四个章节
3. 重点突出产品的核心功能、适用场景和社区热度（得票数）
4. 语言通俗易懂，面向产品经理和技术创业者

**{period_label} Product Hunt 热门产品（共 {count} 个）：**
{articles}

**生成日期：** {date}
"""

_PROMPT_HACKERNEWS = """你是一位专业的技术社区观察员。请根据以下{period_label} Hacker News AI 相关热门讨论，撰写一份社区洞察{period_label}报。

**要求：**
1. 使用 Markdown 格式输出
2. 包含"社区热点话题"、"技术争鸣"、"工具与资源"、"值得深读"四个章节
3. 重点突出社区观点、技术讨论的深度和实践价值
4. 语言深度兼备，面向开发者和技术研究者

**{period_label} Hacker News AI 讨论（共 {count} 条）：**
{articles}

**生成日期：** {date}
"""

_PERIOD_LABEL: dict[str, str] = {
    "daily": "今日",
    "weekly": "本周",
    "monthly": "本月",
}

# source → (prompt_template, cache_key_suffix)
_SOURCE_CONFIG: Dict[str, tuple[str, str]] = {
    "all": (_PROMPT_ALL, ""),
    "arxiv": (_PROMPT_ARXIV, "_arxiv"),
    "github": (_PROMPT_GITHUB, "_github"),
    "news": (_PROMPT_NEWS, "_news"),
    "producthunt": (_PROMPT_PRODUCTHUNT, "_producthunt"),
    "hackernews": (_PROMPT_HACKERNEWS, "_hackernews"),
}


_PERIOD_CHANNEL_MAP: dict[str, dict[str, str]] = {
    "arxiv": {
        "daily": "huggingface_daily_html",
        "weekly": "huggingface_weekly_html",
        "monthly": "huggingface_monthly_html",
    },
    "github": {
        "daily": "github_trending_daily",
        "weekly": "github_trending_weekly",
        "monthly": "github_trending_monthly",
    },
    "news": {
        "daily": "techmeme_daily_rss",
        # news 目前仅有日榜数据，周/月榜暂不支持
    },
    "producthunt": {
        "daily": "producthunt_daily_html",
        # producthunt 目前仅有日榜数据
    },
    "hackernews": {
        "daily": "hn_daily_html",
        # hackernews 目前仅有日榜数据
    },
}


def _filter_docs_by_period(
    docs: List[Dict[str, Any]],
    source: str,
    period: str,
) -> List[Dict[str, Any]]:
    """按 source_channel 精确过滤文档，确保返回指定 period 的数据。

    注意：过滤后为空时返回空列表（不回退到未过滤数据），
    以避免日报混入月报数据。由调用方决定兜底策略。
    """
    if source == "all":
        result = []
        for doc in docs:
            src = (doc.get("source") or "").lower()
            ch_map = _PERIOD_CHANNEL_MAP.get(src, {})
            expected_channel = ch_map.get(period)
            channel = doc.get("source_channel") or doc.get("channel") or ""
            # 如果该 source 在 _PERIOD_CHANNEL_MAP 中没有对应 period 的配置，
            # 则保留该文档（不过滤掉没有 channel 映射的来源）
            if not expected_channel or channel == expected_channel:
                result.append(doc)
        return result

    ch_map = _PERIOD_CHANNEL_MAP.get(source, {})
    expected_channel = ch_map.get(period)
    if not expected_channel:
        # 该 source 对此 period 无 channel 配置，返回空（如 news 的周报/月报）
        return []
    filtered = [
        d
        for d in docs
        if (d.get("source_channel") or d.get("channel") or "") == expected_channel
    ]
    return filtered


def _format_articles(docs: List[Dict[str, Any]], source: str = "all") -> str:
    lines: List[str] = []
    for i, doc in enumerate(docs, start=1):
        title = doc.get("title") or "无标题"
        summary = doc.get("summary") or ""
        url = doc.get("url") or ""
        score = doc.get("score") or 0.0
        src = doc.get("source") or source

        if src == "github":
            score_label = f"⭐ Stars: {int(score)}"
        elif src == "news":
            score_label = f"📰 {doc.get('feed_name') or '新闻'}"
        else:
            score_label = f"评分: {score:.1f}"

        lines.append(f"{i}. **{title}**（{score_label}）")
        if summary:
            lines.append(f"   {summary[:200]}")
        if url:
            lines.append(f"   🔗 {url}")
        lines.append("")
    return "\n".join(lines)


class DailyBriefingService:
    """Generate and persist daily briefing reports with SSE streaming."""

    def __init__(
        self,
        mysql_repo: MySQLRepository | None = None,
        top_k: int = 10,
    ) -> None:
        self._db = mysql_repo or MySQLRepository()
        self._top_k = top_k
        self._llm = get_chat_model()

    async def stream_generate(
        self,
        target_date: str | None = None,
        source: str = "all",
        period: str = "daily",
        force_regenerate: bool = True,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Stream the briefing generation process as SSE payloads.

        Args:
            target_date: ISO date string，默认今天
            source: "all" | "arxiv" | "github" | "news" | "producthunt" | "hackernews"
            period: "daily" | "weekly" | "monthly"
            force_regenerate: 若为 True（默认），始终重新生成，不使用缓存

        Payload types:
          - {"type": "start",    "data": {"date": str, "doc_count": int, "source": str}}
          - {"type": "content",  "data": str}           # incremental token
          - {"type": "done",     "data": {"briefing_id": int}}
          - {"type": "error",    "data": str}
        """
        today = target_date or date.today().isoformat()
        source = source if source in _SOURCE_CONFIG else "all"
        period = period if period in ("daily", "weekly", "monthly") else "daily"
        _, cache_suffix = _SOURCE_CONFIG[source]
        period_label = _PERIOD_LABEL.get(period, "今日")

        # 缓存 key 加入 source 和 period 区分
        cache_date = f"{today}{cache_suffix}_{period}"

        try:
            # 1. 若非强制重新生成，检查缓存
            if not force_regenerate:
                existing = self._db.get_briefing_by_date(cache_date)
                if existing:
                    yield {
                        "type": "start",
                        "data": {
                            "date": today,
                            "doc_count": 0,
                            "cached": True,
                            "source": source,
                            "period": period,
                        },
                    }
                    yield {"type": "content", "data": existing["content"]}
                    yield {"type": "done", "data": {"briefing_id": existing["id"]}}
                    return

            # 2. Fetch documents (优先从快照表获取，按日期+channel 精确查询)
            logger.info(
                "开始获取文档，source=%s, period=%s, date=%s...", source, period, today
            )
            source_type: Optional[str] = None if source == "all" else source
            docs: List[Dict[str, Any]] = []
            fallback_used = False

            # 2a. 确定期望的 source_channel 列表
            expected_channels: List[str] = []
            if source == "all":
                for src_key, ch_map in _PERIOD_CHANNEL_MAP.items():
                    ch = ch_map.get(period)
                    if ch:
                        expected_channels.append(ch)
            else:
                ch_map = _PERIOD_CHANNEL_MAP.get(source, {})
                ch = ch_map.get(period)
                if ch:
                    expected_channels.append(ch)

            # 2b. 优先从快照表按日期+channel 精确获取
            if expected_channels:
                for channel in expected_channels:
                    snap_docs = self._db.get_snapshot_documents(
                        snapshot_date=today,
                        source_channel=channel,
                        source_type=source_type,
                        limit=self._top_k,
                    )
                    docs.extend(snap_docs)
                # 按 raw_score 降序排序，取 top_k
                docs.sort(
                    key=lambda d: (d.get("raw_score") or d.get("score") or 0),
                    reverse=True,
                )
                docs = docs[: self._top_k]
                logger.info(
                    "快照表返回 %d 条 (channels=%s)", len(docs), expected_channels
                )

            # 2c. 快照表无数据时，回退到 documents 表 + channel 过滤
            if not docs:
                logger.info("快照表无数据，回退到 documents 表...")
                all_docs = self._db.get_top_documents(
                    limit=self._top_k * 3, source_type=source_type
                )
                # 所有周期（包括 daily）都按 source_channel 过滤
                docs = _filter_docs_by_period(all_docs, source, period)
                docs = docs[: self._top_k]
                logger.info(
                    "documents 表过滤后返回 %d 条 (period=%s)", len(docs), period
                )

            # 2d. 依然无数据时，使用最新文档兜底
            if not docs:
                logger.info("尝试兜底逻辑 (get_latest_documents)...")
                docs = self._db.get_latest_documents(limit=self._top_k)
                fallback_used = True
                logger.info("兜底逻辑返回 %d 条", len(docs))

            yield {
                "type": "start",
                "data": {
                    "date": today,
                    "doc_count": len(docs),
                    "cached": False,
                    "fallback": fallback_used,
                    "source": source,
                    "period": period,
                },
            }

            if not docs:
                logger.warning("依然没有文档，发送'暂无数据'提示")
                msg = (
                    f"# {today} {period_label}简报\n\n"
                    "> 数据库中暂无对应周期的文档，请先运行数据采集任务。\n"
                )
                yield {"type": "content", "data": msg}
                yield {"type": "done", "data": {"briefing_id": -1}}
                return

            logger.info(
                "找到 %d 条文档，source=%s，开始构建 Prompt...", len(docs), source
            )

            # 3. Build prompt (按 source 选择模板，传入 period_label 适配措辞)
            prompt_template, _ = _SOURCE_CONFIG[source]
            prompt = prompt_template.format(
                count=len(docs),
                articles=_format_articles(docs, source),
                date=today,
                period_label=period_label,
            )

            # 4. Stream LLM generation
            full_content: List[str] = []
            async for chunk in self._llm.astream(prompt):
                raw_content = getattr(chunk, "content", None)
                # Anthropic Extended Thinking 返回的 content 可能是
                # list[dict]（含 thinking_block / text_block），需要提取纯文本
                if isinstance(raw_content, list):
                    text_parts = []
                    for block in raw_content:
                        if isinstance(block, dict):
                            if block.get("type") == "text":
                                text_parts.append(block.get("text", ""))
                            # 跳过 thinking_block 等非文本块
                        elif isinstance(block, str):
                            text_parts.append(block)
                    content = "".join(text_parts)
                else:
                    content = raw_content or ""
                if content:
                    full_content.append(str(content))
                    yield {"type": "content", "data": str(content)}

            # 5. Persist only if LLM actually produced content
            complete_text = "".join(full_content)
            if complete_text.strip():
                briefing_id = self._db.save_briefing(cache_date, complete_text)
                logger.info("日报已持久化，id=%d, source=%s", briefing_id, source)
            else:
                briefing_id = -1
                logger.warning("LLM 未输出任何内容，跳过持久化")
            yield {"type": "done", "data": {"briefing_id": briefing_id}}

        except Exception as exc:
            traceback.print_exc()
            yield {"type": "error", "data": str(exc)}

    def get_history(self, limit: int = 30) -> List[Dict[str, Any]]:
        return self._db.list_briefings(limit=limit)

    def get_briefing(self, briefing_id: int) -> Dict[str, Any] | None:
        with self._db._connect() as conn:
            row = conn.execute(
                "SELECT * FROM briefings WHERE id=?", (briefing_id,)
            ).fetchone()
        return dict(row) if row else None
