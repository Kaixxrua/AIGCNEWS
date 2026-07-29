from __future__ import annotations

import logging
import traceback
from typing import Any, AsyncGenerator, Dict, List

from backend.app.core.model_factory import get_chat_model
from backend.app.repositories.application_repository_context import (
    get_configured_application_repositories,
)
from backend.app.repositories.briefing_repository import BriefingContentRepository
from backend.app.repositories.document_repository import DocumentFeedReader
from backend.app.repositories.milvus_repo import MilvusRepository
from backend.app.repositories.rank_snapshot_repository import RankSnapshotReader
from backend.app.services.briefing.preparation import (
    PreparedBriefing,
    normalize_briefing_context,
    prepare_briefing,
)
from backend.app.services.ingestion.base_crawler import today_cst

logger = logging.getLogger(__name__)

# ── 续写相关常量 ─────────────────────────────────────────────────────────────
# 最大续写轮数，防止无限循环
_MAX_CONTINUATION_ROUNDS = 5

# 用于判断输出是否被截断的信号：如果内容没有以完整结尾标志结束，则认为被截断
_COMPLETION_MARKERS = ("---", "**", "。", "！", "\n")

_CONTINUATION_PROMPT = """你之前的回答在生成过程中被截断了。请从截断处**无缝续写**，不要重复已有内容，也不要重新开头。直接从上次停止的地方继续输出，直到报告完整结束。

以下是你之前已经生成的内容（请勿重复）：

---已生成内容开始---
{previous_content}
---已生成内容结束---

请从上面截断的位置**直接续写**，保持格式和风格一致，直到报告完整输出完毕。"""

# ── 外部拦截页 / 网关错误检测 ─────────────────────────────────────────────────
_BLOCK_RESPONSE_PATTERNS = (
    "您的 IP 涉嫌网络攻击",
    "您的IP涉嫌网络攻击",
    "请与站长联系",
    "涉嫌网络攻击",
    "Access Denied",
    "Cloudflare Ray ID",
    "cf-error-code",
    "Attention Required! | Cloudflare",
)

_BLOCK_RESPONSE_ERROR = (
    "生成简报时上游服务返回了访问拦截页或网关错误，已停止生成且未保存缓存。"
    "请检查 LLM 代理/API 网关或采集源的访问状态。"
)


_PROMPT_ALL = """你是一位专业的 AIGC 技术资讯编辑。请根据以下{period_label}热点内容（综合学术论文、开源项目、行业新闻），撰写一份**内容详尽、深度全面**的综合{period_label}报。

**要求：**
1. 使用 Markdown 格式输出
2. 包含"{period_label}热点摘要"、"技术亮点"、"工程动态"、"行业资讯"、"值得关注"五个章节
3. **每篇内容都必须详细分析**，包括：核心要点、技术细节、影响分析、相关背景（每篇至少 3-5 句话）
4. 对每个章节进行深入的趋势总结和洞察点评
5. 语言专业且详尽，面向技术从业者
6. 最后附上日期和数据来源
7. **务必覆盖所有提供的内容，不要遗漏任何一条**
8. **每个一级或二级标题后面，必须添加具体的领域标签**，格式为：`## 标题 \`#来源\` \`#领域\``。来源标签（必选1个）：`#arxiv` `#github` `#news` `#producthunt` `#hackernews`。领域标签（必选1-2个，选择最贴切的）：`#LLM` `#Agent` `#多模态` `#RAG` `#代码生成` `#图像生成` `#视频生成` `#语音合成` `#强化学习` `#数据集` `#评测基准` `#推理优化` `#模型压缩` `#开源模型` `#商业化` `#安全对齐` `#具身智能` `#知识图谱` `#MLOps` `#AI基础设施`。禁止使用过于宽泛的标签如 #ai #tool #trending

**{period_label}热点内容（共 {count} 条）：**
{articles}

**生成日期：** {date}
"""

_PROMPT_ARXIV = """你是一位专业的 AI 学术研究分析师。请根据以下{period_label} Arxiv 学术论文，撰写一份**内容详尽、深度全面**的学术{period_label}报。

**要求：**
1. 使用 Markdown 格式输出
2. 包含"{period_label}研究热点"、"核心技术突破"、"值得精读的论文"三个章节
3. **每篇论文都必须详细分析**，包括：研究动机、方法论创新、关键实验结论、与现有工作的对比（每篇至少 4-6 句话）
4. 对研究趋势进行深入总结，分析技术方向的演进
5. 语言专业严谨，面向研究人员
6. **务必覆盖所有提供的论文，不要遗漏任何一篇**
7. **每个一级或二级标题后面，必须添加具体的领域标签**，格式为：`## 标题 \`#来源\` \`#领域\``。来源标签（必选1个）：`#arxiv`。领域标签（必选1-2个，选择最贴切的）：`#LLM` `#Agent` `#多模态` `#RAG` `#代码生成` `#图像生成` `#视频生成` `#语音合成` `#强化学习` `#数据集` `#评测基准` `#推理优化` `#模型压缩` `#开源模型` `#安全对齐` `#具身智能` `#知识图谱`。禁止使用过于宽泛的标签如 #ai #tool #trending

**{period_label} Arxiv 论文（共 {count} 篇）：**
{articles}

**生成日期：** {date}
"""

_PROMPT_GITHUB = """你是一位专业的 AI 工程技术分析师。请根据以下{period_label} GitHub 热门开源项目，撰写一份**内容详尽、深度全面**的工程{period_label}报。

**要求：**
1. 使用 Markdown 格式输出
2. 包含"{period_label}明星项目"、"技术栈分析"、"实践价值"三个章节
3. **每个项目都必须详细分析**，包括：项目定位、核心功能、技术架构、使用场景、Stars 增长趋势、与同类项目对比（每个至少 4-6 句话）
4. 对开源生态的技术趋势进行深入洞察
5. 语言务实，面向工程师和架构师
6. **务必覆盖所有提供的项目，不要遗漏任何一个**
7. **每个一级或二级标题后面，必须添加具体的领域标签**，格式为：`## 标题 \`#来源\` \`#领域\``。来源标签（必选1个）：`#github`。领域标签（必选1-2个，选择最贴切的）：`#LLM` `#Agent` `#RAG` `#代码生成` `#推理优化` `#模型压缩` `#开源模型` `#MLOps` `#AI基础设施` `#数据工程` `#Web框架` `#CLI工具` `#DevOps` `#前端` `#Rust` `#Python`。禁止使用过于宽泛的标签如 #ai #tool #trending

**{period_label} GitHub 热门项目（共 {count} 个）：**
{articles}

**生成日期：** {date}
"""

_PROMPT_NEWS = """你是一位专业的 AI 行业分析师。请根据以下{period_label} AI 行业新闻，撰写一份**内容详尽、深度全面**的商业{period_label}报。

**要求：**
1. 使用 Markdown 格式输出
2. 包含"{period_label}行业动态"、"商业化进展"、"政策与监管"、"值得关注的趋势"四个章节
3. **每条新闻都必须详细分析**，包括：事件概述、商业影响、行业意义、潜在的连锁反应（每条至少 3-5 句话）
4. 对行业趋势进行深入总结和前瞻性判断
5. 语言通俗易懂，面向决策者和产品经理
6. **务必覆盖所有提供的新闻，不要遗漏任何一条**
7. **每个一级或二级标题后面，必须添加具体的领域标签**，格式为：`## 标题 \`#来源\` \`#领域\``。来源标签（必选1个）：`#news`。领域标签（必选1-2个，选择最贴切的）：`#LLM` `#Agent` `#商业化` `#融资收购` `#监管政策` `#芯片算力` `#云服务` `#自动驾驶` `#医疗AI` `#教育AI` `#企业AI` `#开源生态`。禁止使用过于宽泛的标签如 #ai #tool #trending

**{period_label} AI 行业新闻（共 {count} 条）：**
{articles}

**生成日期：** {date}
"""


_PROMPT_PRODUCTHUNT = """你是一位专业的 AI 产品分析师。请根据以下{period_label} Product Hunt 热门 AI 产品，撰写一份**内容详尽、深度全面**的产品{period_label}报。

**要求：**
1. 使用 Markdown 格式输出
2. 包含"{period_label}明星产品"、"功能亮点"、"市场价值"、"值得关注的产品"四个章节
3. **每个产品都必须详细分析**，包括：产品定位、核心功能、目标用户、差异化优势、社区热度分析（每个至少 4-6 句话）
4. 对 AI 产品赛道的趋势进行深入洞察
5. 语言通俗易懂，面向产品经理和技术创业者
6. **务必覆盖所有提供的产品，不要遗漏任何一个**
7. **每个一级或二级标题后面，必须添加具体的领域标签**，格式为：`## 标题 \`#来源\` \`#领域\``。来源标签（必选1个）：`#producthunt`。领域标签（必选1-2个，选择最贴切的）：`#AI写作` `#AI设计` `#AI编程` `#AI营销` `#效率工具` `#开发者工具` `#SaaS` `#个人助理` `#协作工具` `#数据分析` `#自动化` `#API服务`。禁止使用过于宽泛的标签如 #ai #tool #trending

**{period_label} Product Hunt 热门产品（共 {count} 个）：**
{articles}

**生成日期：** {date}
"""

_PROMPT_HACKERNEWS = """你是一位专业的技术社区观察员。请根据以下{period_label} Hacker News AI 相关热门讨论，撰写一份**内容详尽、深度全面**的社区洞察{period_label}报。

**要求：**
1. 使用 Markdown 格式输出
2. 包含"社区热点话题"、"技术争鸣"、"工具与资源"、"值得深读"四个章节
3. **每条讨论都必须详细分析**，包括：话题概述、核心观点、社区争议、技术深度、实践价值（每条至少 4-6 句话）
4. 对社区讨论反映出的技术趋势进行深入洞察
5. 语言深度兼备，面向开发者和技术研究者
6. **务必覆盖所有提供的讨论，不要遗漏任何一条**
7. **每个一级或二级标题后面，必须添加具体的领域标签**，格式为：`## 标题 \`#来源\` \`#领域\``。来源标签（必选1个）：`#hackernews`。领域标签（必选1-2个，选择最贴切的）：`#LLM` `#Agent` `#开源争议` `#隐私安全` `#编程语言` `#系统架构` `#创业` `#职业发展` `#硬件` `#Web技术` `#分布式系统` `#技术文化`。禁止使用过于宽泛的标签如 #ai #tool #trending

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
            stars = int(doc.get("stars") or 0)
            growth = int(doc.get("raw_score") or score or 0)
            channel = doc.get("source_channel") or doc.get("channel") or ""
            if stars > 0:
                score_label = f"⭐ Stars: {stars}"
                if channel.startswith("github_trending_") and growth:
                    score_label += f"（+{growth} 本周期）"
            else:
                score_label = f"📈 本周期新增 Stars: {growth}"
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


def _looks_like_block_response(text: str) -> bool:
    """识别上游 WAF/代理拦截页，避免把错误页当成简报保存。"""
    if not text:
        return False
    lowered = text.lower()
    return any(pattern.lower() in lowered for pattern in _BLOCK_RESPONSE_PATTERNS)


def _filter_blocked_docs(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """过滤采集中误入库的拦截页内容。"""
    clean_docs: List[Dict[str, Any]] = []
    for doc in docs:
        haystack = "\n".join(
            str(doc.get(key) or "") for key in ("title", "summary", "url")
        )
        if _looks_like_block_response(haystack):
            logger.warning(
                "跳过疑似拦截页文档: id=%s source=%s title=%s",
                doc.get("id"),
                doc.get("source"),
                doc.get("title"),
            )
            continue
        clean_docs.append(doc)
    return clean_docs


def _milvus_doc_to_briefing_doc(doc: Any, fallback_source: str = "github") -> Dict[str, Any]:
    """将 Milvus/LangChain Document 转为简报生成使用的 dict 结构。"""
    meta = dict(getattr(doc, "metadata", None) or {})
    page_content = str(getattr(doc, "page_content", "") or "")
    source = str(meta.get("source") or fallback_source).lower()
    stars = meta.get("stars") or meta.get("raw_score") or meta.get("score") or 0
    raw_score = meta.get("raw_score") or stars

    return {
        "id": str(meta.get("id") or meta.get("pk") or ""),
        "source": source,
        "source_channel": meta.get("source_channel") or meta.get("channel") or "",
        "channel": meta.get("source_channel") or meta.get("channel") or "",
        "title": meta.get("title") or "无标题",
        "summary": page_content,
        "url": meta.get("url") or "",
        "published_date": meta.get("published_date") or "",
        "score": meta.get("score") or raw_score or 0.0,
        "raw_score": raw_score or 0.0,
        "stars": stars or 0,
        "language": meta.get("language") or "",
    }


def _dedupe_docs(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按 id/title/url 去重，避免 Milvus chunk 级结果重复进入 Prompt。"""
    seen: set[str] = set()
    result: List[Dict[str, Any]] = []
    for doc in docs:
        key = str(doc.get("id") or doc.get("url") or doc.get("title") or "").strip()
        if not key:
            key = str(len(result))
        if key in seen:
            continue
        seen.add(key)
        result.append(doc)
    return result


class DailyBriefingService:
    """Generate and persist daily briefing reports with SSE streaming."""

    def __init__(
        self,
        top_k: int = 10,
        briefing_repository: BriefingContentRepository | None = None,
        document_feed: DocumentFeedReader | None = None,
        rank_snapshot_reader: RankSnapshotReader | None = None,
    ) -> None:
        repositories = None
        if (
            briefing_repository is None
            or document_feed is None
            or rank_snapshot_reader is None
        ):
            repositories = get_configured_application_repositories()
        self._briefings = briefing_repository or repositories.briefings
        self._document_feed = document_feed or repositories.documents
        self._rank_snapshots = rank_snapshot_reader or repositories.rank_snapshots
        self._top_k = top_k
        self._llm = get_chat_model()

    def _get_github_docs_from_milvus(self, period: str) -> List[Dict[str, Any]]:
        """GitHub 简报优先从 Milvus 取 README 丰富内容。"""
        expected_channel = _PERIOD_CHANNEL_MAP.get("github", {}).get(period, "")
        try:
            milvus_repo = MilvusRepository()
            vector_docs = milvus_repo.search_by_source("github", top_k=self._top_k * 5)
        except Exception as exc:
            logger.warning("Milvus 获取 GitHub 简报文档失败，回退 MySQL: %s", exc)
            return []

        docs = [_milvus_doc_to_briefing_doc(doc, "github") for doc in vector_docs]
        if expected_channel:
            period_docs = [
                doc
                for doc in docs
                if (doc.get("source_channel") or doc.get("channel") or "")
                == expected_channel
            ]
            if period_docs:
                docs = period_docs
            else:
                logger.info(
                    "Milvus 未找到 channel=%s 的 GitHub 文档，使用 Milvus GitHub 全量结果兜底",
                    expected_channel,
                )

        docs = [doc for doc in docs if doc.get("source") == "github"]
        docs = _dedupe_docs(docs)
        docs.sort(
            key=lambda d: (d.get("raw_score") or d.get("stars") or d.get("score") or 0),
            reverse=True,
        )
        docs = docs[: self._top_k]
        logger.info(
            "Milvus 返回 GitHub 简报文档 %d 条 (period=%s, channel=%s)",
            len(docs),
            period,
            expected_channel,
        )
        return docs

    def _prepare_briefing(
        self,
        *,
        target_date: str,
        source: str,
        period: str,
    ) -> PreparedBriefing:
        context = normalize_briefing_context(
            target_date=target_date,
            source=source,
            period=period,
            source_config=_SOURCE_CONFIG,
            period_labels=_PERIOD_LABEL,
            period_channels=_PERIOD_CHANNEL_MAP,
        )
        return prepare_briefing(
            context=context,
            top_k=self._top_k,
            snapshot_reader=self._rank_snapshots,
            document_feed=self._document_feed,
            source_config=_SOURCE_CONFIG,
            filter_by_period=_filter_docs_by_period,
            format_articles=_format_articles,
            is_blocked=_looks_like_block_response,
        )

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
        today = target_date or today_cst()
        context = normalize_briefing_context(
            target_date=today,
            source=source,
            period=period,
            source_config=_SOURCE_CONFIG,
            period_labels=_PERIOD_LABEL,
            period_channels=_PERIOD_CHANNEL_MAP,
        )
        source = context.source
        period = context.period
        period_label = context.period_label
        cache_date = context.cache_date

        try:
            # 1. 若非强制重新生成，检查缓存
            if not force_regenerate:
                existing = self._briefings.get_briefing_by_date(cache_date)
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

            logger.info(
                "开始获取文档，source=%s, period=%s, date=%s...", source, period, today
            )
            prepared = self._prepare_briefing(
                target_date=today,
                source=source,
                period=period,
            )
            docs = list(prepared.documents)

            yield {
                "type": "start",
                "data": {
                    "date": today,
                    "doc_count": len(docs),
                    "cached": False,
                    "fallback": prepared.fallback_used,
                    "milvus": prepared.milvus_used,
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
            prompt = prepared.prompt or ""

            # 4. Stream LLM generation（支持截断续写）
            full_content: List[str] = []

            # 首次生成：边接收 LLM token 边转发给前端，避免 SSE 长时间空闲断流
            async for token in self._stream_llm_round(prompt):
                full_content.append(token)
                yield {"type": "content", "data": token}

            accumulated = "".join(full_content)
            if _looks_like_block_response(accumulated):
                logger.error("LLM 上游返回疑似拦截页，停止简报生成: source=%s", source)
                yield {"type": "error", "data": _BLOCK_RESPONSE_ERROR}
                return

            # 5. 截断续写：检测输出是否被截断，若是则多轮续写
            for continuation_round in range(1, _MAX_CONTINUATION_ROUNDS + 1):
                if not self._is_truncated(accumulated):
                    logger.info("报告生成完整，无需续写 (round %d)", continuation_round)
                    break

                logger.warning(
                    "检测到输出可能被截断 (round %d/%d)，启动续写...",
                    continuation_round,
                    _MAX_CONTINUATION_ROUNDS,
                )
                yield {
                    "type": "content",
                    "data": "",  # 空 token 作为续写信号（前端无感）
                }

                # 构建续写 prompt，将已有内容作为上下文
                cont_prompt = _CONTINUATION_PROMPT.format(
                    previous_content=accumulated[-4000:]  # 只传最后 4000 字符避免超长
                )

                async for token in self._stream_llm_round(cont_prompt):
                    full_content.append(token)
                    yield {"type": "content", "data": token}

                accumulated = "".join(full_content)
                if _looks_like_block_response(accumulated):
                    logger.error(
                        "LLM 续写阶段返回疑似拦截页，停止简报生成: source=%s", source
                    )
                    yield {"type": "error", "data": _BLOCK_RESPONSE_ERROR}
                    return
            else:
                logger.warning(
                    "已达最大续写轮数 (%d)，停止续写", _MAX_CONTINUATION_ROUNDS
                )

            # 6. Persist only if LLM actually produced content
            complete_text = "".join(full_content)
            if _looks_like_block_response(complete_text):
                logger.error("生成结果为疑似拦截页，跳过持久化: source=%s", source)
                yield {"type": "error", "data": _BLOCK_RESPONSE_ERROR}
                return

            if complete_text.strip():
                briefing_id = self._briefings.save_briefing(cache_date, complete_text)
                logger.info("日报已持久化，id=%d, source=%s", briefing_id, source)
            else:
                briefing_id = -1
                logger.warning("LLM 未输出任何内容，跳过持久化")
            yield {"type": "done", "data": {"briefing_id": briefing_id}}

        except Exception as exc:
            err_text = str(exc)
            if _looks_like_block_response(err_text):
                logger.error(
                    "简报生成被上游服务拦截，停止生成且不返回原始拦截页: source=%s",
                    source,
                    exc_info=True,
                )
                yield {"type": "error", "data": _BLOCK_RESPONSE_ERROR}
                return
            traceback.print_exc()
            yield {"type": "error", "data": err_text}

    async def _stream_llm_round(self, prompt: str) -> AsyncGenerator[str, None]:
        """执行一轮 LLM 流式生成，逐 token 返回。"""
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
                yield str(content)

    @staticmethod
    def _is_truncated(text: str) -> bool:
        """判断 LLM 输出是否被截断（未完整结束）。

        检测逻辑：
        1. 内容过短（少于 200 字符）且非空 → 可能截断
        2. 最后一行在 Markdown 标题/列表/粗体中间断开 → 截断
        3. 最后一个字符是中文字符且没有标点结尾 → 可能截断
        4. 存在未闭合的 Markdown 代码块 → 截断
        """
        if not text or not text.strip():
            return False

        stripped = text.strip()

        # 内容过短且没有明显的报告结尾标志
        if len(stripped) < 200:
            return True

        # 检查未闭合的 Markdown 代码块（``` 出现奇数次）
        if stripped.count("```") % 2 != 0:
            return True

        last_line = stripped.split("\n")[-1].strip()

        # 最后一行是 Markdown 标题但没有内容（如 "## " 或 "### 技术"）
        if last_line.startswith("#") and len(last_line) < 6:
            return True

        # 最后一行以 "**" 开头但没有闭合（如 "**项目名称" 没有 "**" 结尾）
        if last_line.count("**") % 2 != 0:
            return True

        # 最后一行以数字列表开头但内容很短（如 "3. "）
        if len(last_line) < 5 and any(
            last_line.startswith(f"{i}.") for i in range(1, 30)
        ):
            return True

        return False

    def get_history(self, limit: int = 30) -> List[Dict[str, Any]]:
        return self._briefings.list_briefings(limit=limit)

    def get_briefing(self, briefing_id: int) -> Dict[str, Any] | None:
        return self._briefings.get_briefing(briefing_id)
