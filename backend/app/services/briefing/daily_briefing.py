from __future__ import annotations

import json
import logging
import re
from typing import Any, AsyncGenerator, AsyncIterator, Dict, List, Protocol

from backend.app.repositories.briefing_repository import BriefingContentRepository
from backend.app.repositories.document_repository import DocumentFeedReader
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

# ── 中转站 JSON 信封检测 ─────────────────────────────────────────────────────
# 上游代理协议漂移时，响应可能不是纯文本而是 {"answer": "..."}<CPA_DONE>
# 包装。该包装一旦入库，前端会把原始 JSON 当 Markdown 渲染（2026-08-09_x
# 缓存污染事故）；剥离失败时必须中止生成且不持久化。
_RELAY_ENVELOPE_PREFIX = '{"answer":'
_RELAY_DONE_MARKER = "<CPA_DONE>"

# 双语生成中另一语言失败时的对外文案（原文案保留，SSE wire 行为不变）。
_ALTERNATE_LANGUAGE_ERROR = "双语简报的另一语言生成失败，未保存不完整缓存。"


class _BlockResponseError(Exception):
    """LLM 输出被判定为上游拦截页/网关错误页，必须中止生成且不持久化。"""


def _strip_relay_envelope(text: str) -> str:
    """剥离中转站 JSON 信封，返回纯 Markdown 正文。

    非信封文本原样返回；形似信封但无法解析/不含 answer 字段时抛
    _BlockResponseError —— 宁可放弃本轮生成也不把包装层写进缓存。
    """
    stripped = text.strip()
    if (
        not stripped.startswith(_RELAY_ENVELOPE_PREFIX)
        and _RELAY_DONE_MARKER not in stripped
    ):
        return text
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise _BlockResponseError() from exc
    answer = payload.get("answer") if isinstance(payload, dict) else None
    if not isinstance(answer, str) or not answer.strip():
        raise _BlockResponseError()
    return answer.replace(_RELAY_DONE_MARKER, "").strip()


# ── 转义反引号还原 ───────────────────────────────────────────────────────────
# 提示词示例历史上的 `\`#标签\`` 写法（raw string 把反斜杠原样传给模型）曾让
# 模型把转义形式照搬进正文（2026-08-14_news/_producthunt/_x 等期事故）；
# Markdown 将 \` 渲染为字面反引号，标签便失去行内代码样式。提示词已修正，
# 此处兜底：入库前的整文净化把围栏代码块外的 \` 一律还原为 `。
_FENCED_CODE_BLOCK_RE = re.compile(r"(```[\s\S]*?(?:```|$))")
_ESCAPED_BACKTICK_RE = re.compile(r"\\`")


def _unescape_backticks(text: str) -> str:
    """还原正文中被转义的反引号（\\` → `），围栏代码块内容原样保留。

    未闭合的围栏按代码处理到文末（宁保守不误改代码样本）。
    """
    if "\\`" not in text:
        return text
    segments = _FENCED_CODE_BLOCK_RE.split(text)
    for i in range(0, len(segments), 2):
        segments[i] = _ESCAPED_BACKTICK_RE.sub("`", segments[i])
    return "".join(segments)


def _classified_briefing_error(exc: Exception) -> str:
    """SSE error payload：分类文案 + 异常类型名，不透出原始 str(exc)。

    原始异常文本可能携带上游 URL、网关回显或密钥片段；该路由仅管理员可见，
    保留异常类型名足够排查，完整堆栈由服务端日志承接。
    """
    err_text = str(exc).lower()
    if "timeout" in err_text or "timed out" in err_text:
        category = "模型服务响应超时"
    elif "429" in err_text or "rate_limit" in err_text or "rate limit" in err_text:
        category = "模型服务限流"
    elif "401" in err_text or "403" in err_text or "unauthorized" in err_text or "forbidden" in err_text:
        category = "模型服务鉴权失败"
    elif "connection" in err_text or "network" in err_text or "503" in err_text or "unavailable" in err_text:
        category = "模型服务不可用"
    else:
        category = "生成过程出现异常"
    return (
        f"简报生成失败：{category}（{type(exc).__name__}）。"
        "请稍后重试或查看服务端日志。"
    )


# ── 写作纪律（拼接在每组 prompt 末尾）────────────────────────────────────────
# 针对真实生成数据暴露的三类专业度问题：
# 1) 元叙述口吻（"本报基于题目提供的……" / "The supplied feed …"）；
# 2) 条目编号沿用输入列表全局编号导致章节内跳号；
# 3) 条目缺来源链接，各期引用不一致。
_WRITING_DISCIPLINE = r"""
**写作纪律（所有章节必须遵守）：**
- 以编辑部第一人称口吻直接撰写（如"本报梳理""本报判断"）；全文禁止出现"题目""提供的材料""输入材料""给定资料""supplied""provided materials"等元叙述措辞
- 每个条目结尾必须用 Markdown 链接附上来源（使用输入中给出的 URL）
- 每个章节内的条目编号从 1 开始连续编号，不得沿用输入列表的全局编号
"""

_PROMPT_ALL = r"""你是一位专业的 AIGC 技术资讯编辑。请根据以下今日内容（综合学术论文、开源项目、行业新闻），撰写一份**内容详尽、深度全面**的综合今日报。

**要求：**
1. 使用 Markdown 格式输出
2. 包含"今日内容摘要"、"技术亮点"、"工程动态"、"行业资讯"、"值得关注"五个章节
3. **每篇内容都必须详细分析**，包括：核心要点、技术细节、影响分析、相关背景（每篇至少 3-5 句话）
4. 对每个章节进行深入的趋势总结和洞察点评
5. 语言专业且详尽，面向技术从业者
6. 最后附上日期和数据来源
7. **务必覆盖所有提供的内容，不要遗漏任何一条**
8. **每个一级或二级标题后面，必须添加具体的领域标签**，格式示例：## 标题 `#来源` `#领域`（反引号行内代码形式，切勿加反斜杠转义）。来源标签（必选1个）：`#arxiv` `#github` `#news` `#producthunt` `#hackernews` `#x`。领域标签（必选1-2个，选择最贴切的）：`#LLM` `#Agent` `#多模态` `#RAG` `#代码生成` `#图像生成` `#视频生成` `#语音合成` `#强化学习` `#数据集` `#评测基准` `#推理优化` `#模型压缩` `#开源模型` `#商业化` `#安全对齐` `#具身智能` `#知识图谱` `#MLOps` `#AI基础设施`。禁止使用过于宽泛的标签如 #ai #tool #trending

**今日内容（共 {count} 条）：**
{articles}

**生成日期：** {date}
""" + _WRITING_DISCIPLINE

_PROMPT_ARXIV = r"""你是一位专业的 AI 学术研究分析师。请根据以下今日 Arxiv 学术论文，撰写一份**内容详尽、深度全面**的学术今日报。

**要求：**
1. 使用 Markdown 格式输出
2. 包含"今日研究热点"、"核心技术突破"、"值得精读的论文"三个章节
3. **每篇论文都必须详细分析**，包括：研究动机、方法论创新、关键实验结论、与现有工作的对比（每篇至少 4-6 句话）
4. 对研究趋势进行深入总结，分析技术方向的演进
5. 语言专业严谨，面向研究人员
6. **务必覆盖所有提供的论文，不要遗漏任何一篇**
7. **每个一级或二级标题后面，必须添加具体的领域标签**，格式示例：## 标题 `#来源` `#领域`（反引号行内代码形式，切勿加反斜杠转义）。来源标签（必选1个）：`#arxiv`。领域标签（必选1-2个，选择最贴切的）：`#LLM` `#Agent` `#多模态` `#RAG` `#代码生成` `#图像生成` `#视频生成` `#语音合成` `#强化学习` `#数据集` `#评测基准` `#推理优化` `#模型压缩` `#开源模型` `#安全对齐` `#具身智能` `#知识图谱`。禁止使用过于宽泛的标签如 #ai #tool #trending

**今日 Arxiv 论文（共 {count} 篇）：**
{articles}

**生成日期：** {date}
""" + _WRITING_DISCIPLINE

_PROMPT_GITHUB = r"""你是一位专业的 AI 工程技术分析师。请根据以下今日 GitHub 开源项目，撰写一份**内容详尽、深度全面**的工程今日报。

**要求：**
1. 使用 Markdown 格式输出
2. 包含"今日明星项目"、"技术栈分析"、"实践价值"三个章节
3. **每个项目都必须详细分析**，包括：项目定位、核心功能、技术架构、使用场景、与同类项目对比（每个至少 4-6 句话）
4. 对开源生态的技术趋势进行深入洞察
5. 语言务实，面向工程师和架构师
6. **务必覆盖所有提供的项目，不要遗漏任何一个**
7. **每个一级或二级标题后面，必须添加具体的领域标签**，格式示例：## 标题 `#来源` `#领域`（反引号行内代码形式，切勿加反斜杠转义）。来源标签（必选1个）：`#github`。领域标签（必选1-2个，选择最贴切的）：`#LLM` `#Agent` `#RAG` `#代码生成` `#推理优化` `#模型压缩` `#开源模型` `#MLOps` `#AI基础设施` `#数据工程` `#Web框架` `#CLI工具` `#DevOps` `#前端` `#Rust` `#Python`。禁止使用过于宽泛的标签如 #ai #tool #trending

**今日 GitHub 项目（共 {count} 个）：**
{articles}

**生成日期：** {date}
""" + _WRITING_DISCIPLINE

_PROMPT_NEWS = r"""你是一位专业的 AI 行业分析师。请根据以下今日 AI 行业新闻，撰写一份**内容详尽、深度全面**的商业今日报。

**要求：**
1. 使用 Markdown 格式输出
2. 包含"今日行业动态"、"商业化进展"、"政策与监管"、"值得关注的趋势"四个章节
3. **每条新闻都必须详细分析**，包括：事件概述、商业影响、行业意义、潜在的连锁反应（每条至少 3-5 句话）
4. 对行业趋势进行深入总结和前瞻性判断
5. 语言通俗易懂，面向决策者和产品经理
6. **务必覆盖所有提供的新闻，不要遗漏任何一条**
7. **每个一级或二级标题后面，必须添加具体的领域标签**，格式示例：## 标题 `#来源` `#领域`（反引号行内代码形式，切勿加反斜杠转义）。来源标签（必选1个）：`#news`。领域标签（必选1-2个，选择最贴切的）：`#LLM` `#Agent` `#商业化` `#融资收购` `#监管政策` `#芯片算力` `#云服务` `#自动驾驶` `#医疗AI` `#教育AI` `#企业AI` `#开源生态`。禁止使用过于宽泛的标签如 #ai #tool #trending

**今日 AI 行业新闻（共 {count} 条）：**
{articles}

**生成日期：** {date}
""" + _WRITING_DISCIPLINE


_PROMPT_PRODUCTHUNT = r"""你是一位专业的 AI 产品分析师。请根据以下今日 Product Hunt AI 产品，撰写一份**内容详尽、深度全面**的产品今日报。

**要求：**
1. 使用 Markdown 格式输出
2. 包含"今日明星产品"、"功能亮点"、"市场价值"、"值得关注的产品"四个章节
3. **每个产品都必须详细分析**，包括：产品定位、核心功能、目标用户、差异化优势、与同类产品的差异（每个至少 4-6 句话）
4. 对 AI 产品赛道的趋势进行深入洞察
5. 语言通俗易懂，面向产品经理和技术创业者
6. **务必覆盖所有提供的产品，不要遗漏任何一个**
7. **每个一级或二级标题后面，必须添加具体的领域标签**，格式示例：## 标题 `#来源` `#领域`（反引号行内代码形式，切勿加反斜杠转义）。来源标签（必选1个）：`#producthunt`。领域标签（必选1-2个，选择最贴切的）：`#AI写作` `#AI设计` `#AI编程` `#AI营销` `#效率工具` `#开发者工具` `#SaaS` `#个人助理` `#协作工具` `#数据分析` `#自动化` `#API服务`。禁止使用过于宽泛的标签如 #ai #tool #trending

**今日 Product Hunt 产品（共 {count} 个）：**
{articles}

**生成日期：** {date}
""" + _WRITING_DISCIPLINE

_PROMPT_HACKERNEWS = r"""你是一位专业的技术社区观察员。请根据以下今日 Hacker News AI 相关讨论，撰写一份**内容详尽、深度全面**的社区洞察今日报。

**要求：**
1. 使用 Markdown 格式输出
2. 包含"社区热点话题"、"技术争鸣"、"工具与资源"、"值得深读"四个章节
3. **每条讨论都必须详细分析**，包括：话题概述、核心观点、社区争议、技术深度、实践价值（每条至少 4-6 句话）
4. 对社区讨论反映出的技术趋势进行深入洞察
5. 语言深度兼备，面向开发者和技术研究者
6. **务必覆盖所有提供的讨论，不要遗漏任何一条**
7. **每个一级或二级标题后面，必须添加具体的领域标签**，格式示例：## 标题 `#来源` `#领域`（反引号行内代码形式，切勿加反斜杠转义）。来源标签（必选1个）：`#hackernews`。领域标签（必选1-2个，选择最贴切的）：`#LLM` `#Agent` `#开源争议` `#隐私安全` `#编程语言` `#系统架构` `#创业` `#职业发展` `#硬件` `#Web技术` `#分布式系统` `#技术文化`。禁止使用过于宽泛的标签如 #ai #tool #trending

**今日 Hacker News AI 讨论（共 {count} 条）：**
{articles}

**生成日期：** {date}
""" + _WRITING_DISCIPLINE

_PROMPT_DAILYHOT = r"""你是一位专业的中文科技资讯编辑。请根据以下今日中文互联网各大站点内容（36氪、IT之家、少数派、掘金、知乎、虎嗅、极客公园、爱范儿等），撰写一份**内容详尽、深度全面**的全网资讯今日报。

**要求：**
1. 使用 Markdown 格式输出
2. 包含"AI 与大模型动态"、"产品与商业化"、"开发者与技术社区"、"其他值得关注"四个章节
3. **每条内容都必须详细分析**，包括：来源、事件概述、背景与影响（每条至少 3-5 句话）
4. AI 相关条目优先详写；对跨榜单共同反映出的行业趋势进行深入洞察
5. 语言通俗易懂，面向 AI 从业者与技术爱好者
6. **务必覆盖所有提供的条目，不要遗漏任何一条**
7. **每个一级或二级标题后面，必须添加具体的领域标签**，格式示例：## 标题 `#来源` `#领域`（反引号行内代码形式，切勿加反斜杠转义）。来源标签（必选1个）：`#dailyhot`。领域标签（必选1-2个，选择最贴切的）：`#LLM` `#Agent` `#多模态` `#产品发布` `#商业化` `#开源模型` `#AI基础设施` `#开发者工具` `#监管政策` `#行业动态` `#硬件` `#其他`。禁止使用过于宽泛的标签如 #ai #tool #trending

**今日全网内容（共 {count} 条）：**
{articles}

**生成日期：** {date}
""" + _WRITING_DISCIPLINE

_PROMPT_X = r"""你是一位专业的 AI 行业观察员。请根据以下今日 X（Twitter）上 AI 公司与知名开发者官方账号的推文（已按账号分组），撰写一份**内容详尽、深度全面**的 X 动态今日报。

**要求：**
1. 使用 Markdown 格式输出
2. 包含"官方发布与公告"、"研究与技术分享"、"行业观点与洞察"、"值得关注"四个章节
3. **以账号为单位组织分析**：每个账号的当日动态写成一段完整评述，包括发布者的官方身份与职位背景、核心内容、背景与影响、对产品路线或研究方向释放的信号（每个账号至少 4-6 句话）；同一账号有多条推文时须逐条点明要点，但合并在同一账号条目下，不得拆成互不相干的孤立条目
4. 对官方账号动态反映出的行业趋势进行深入洞察；这些账号均为 AI 公司与知名开发者的官方账号，分析应基于发布者身份与内容本身
5. 语言通俗易懂，面向 AI 从业者与技术爱好者
6. **务必覆盖所有提供的账号，不要遗漏任何一个账号；账号下的每条推文都要提及**
7. **每个一级或二级标题后面，必须添加具体的领域标签**，格式示例：## 标题 `#来源` `#领域`（反引号行内代码形式，切勿加反斜杠转义）。来源标签（必选1个）：`#x`。领域标签（必选1-2个，选择最贴切的）：`#LLM` `#Agent` `#多模态` `#开源模型` `#产品发布` `#研究论文` `#商业化` `#安全对齐` `#AI基础设施` `#开发者工具` `#观点争议` `#监管政策`。禁止使用过于宽泛的标签如 #ai #tool #trending
8. 只能根据输入中的推文内容和发布者身份进行分析，全文禁止编造输入中没有提供的事实
9. 每个账号条目结尾必须用 Markdown 链接附上该账号当日推文的来源（使用输入中给出的 URL）

**今日 X 账号动态（共 {count} 个账号）：**
{articles}

**生成日期：** {date}
""" + _WRITING_DISCIPLINE

_BRIEFING_LANGUAGES = ("zh-CN", "en")
_LANGUAGE_INSTRUCTIONS = {
    "zh-CN": "\n\n请只使用简体中文撰写完整简报。标题、分析、日期与说明均使用中文；URL、产品名和代码标识保留原文。",
    "en": "\n\nWrite the complete briefing in natural English only. Use English for headings, analysis, dates, and explanations; preserve URLs, product names, and code identifiers verbatim.",
}


def normalize_briefing_locale(locale: str | None) -> str:
    return "en" if str(locale or "").lower().startswith("en") else "zh-CN"


def select_briefing_content(item: Dict[str, Any], locale: str | None) -> str:
    selected = normalize_briefing_locale(locale)
    if selected == "en":
        candidates = (item.get("content_en"), item.get("content"), item.get("content_zh"))
    else:
        candidates = (item.get("content_zh"), item.get("content"), item.get("content_en"))
    return next((str(value) for value in candidates if str(value or "").strip()), "")

# source → (prompt_template, cache_key_suffix)
_SOURCE_CONFIG: Dict[str, tuple[str, str]] = {
    "all": (_PROMPT_ALL, ""),
    "arxiv": (_PROMPT_ARXIV, "_arxiv"),
    "github": (_PROMPT_GITHUB, "_github"),
    "news": (_PROMPT_NEWS, "_news"),
    "producthunt": (_PROMPT_PRODUCTHUNT, "_producthunt"),
    "hackernews": (_PROMPT_HACKERNEWS, "_hackernews"),
    "x": (_PROMPT_X, "_0800_x"),
    "dailyhot": (_PROMPT_DAILYHOT, "_dailyhot"),
}


# source → 日榜快照 channel（简报仅按日生成，weekly/monthly 已移除）
_SOURCE_CHANNELS: Dict[str, str] = {
    "arxiv": "huggingface_daily_html",
    "github": "github_trending_daily",
    "news": "techmeme_daily_rss",
    "producthunt": "producthunt_daily_html",
    "hackernews": "hn_daily_html",
    "x": "x_daily_watchlist",
    "dailyhot": "dailyhot_daily",
}


def get_briefing_cache_key(target_date: str, source: str) -> str:
    """Return the persisted briefing cache key for a source.

    This must stay in sync with the suffix used inside ``stream_generate``
    (derived from ``_SOURCE_CONFIG``).
    """
    _, suffix = _SOURCE_CONFIG.get(source, _SOURCE_CONFIG["all"])
    return f"{target_date}{suffix}"


def _filter_docs_by_channel(
    docs: List[Dict[str, Any]],
    source: str,
) -> List[Dict[str, Any]]:
    """按 source_channel 精确过滤文档，确保只保留对应日榜 channel 的数据。

    注意：过滤后为空时返回空列表（不回退到未过滤数据），
    以避免日报混入其他周期榜单数据。由调用方决定兜底策略。
    """
    if source == "all":
        result = []
        for doc in docs:
            src = (doc.get("source") or "").lower()
            expected_channel = _SOURCE_CHANNELS.get(src)
            channel = doc.get("source_channel") or doc.get("channel") or ""
            # 没有 channel 映射的来源不过滤（保留该文档）
            if not expected_channel or channel == expected_channel:
                result.append(doc)
        return result

    expected_channel = _SOURCE_CHANNELS.get(source)
    if not expected_channel:
        return []
    filtered = [
        d
        for d in docs
        if (d.get("source_channel") or d.get("channel") or "") == expected_channel
    ]
    return filtered


_SUMMARY_LIMIT = 200

# 推文 URL 形如 https://x.com/{handle}/status/{id}；兼容 twitter.com 历史链接。
# 与前端 xBoardViewModel 的 X_HANDLE_URL_RE 同一口径。
_X_HANDLE_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:x|twitter)\.com/([^/?\s]+)/status/",
    re.IGNORECASE,
)


def _truncate_summary(summary: str, limit: int = _SUMMARY_LIMIT) -> str:
    """按词/句边界截断摘要并补省略号。

    旧实现 summary[:200] 会在词中间硬切断，模型会把"简介在 'a' 处截断"
    写进简报正文；截断点优先落在后半段的空白或标点边界上。
    """
    text = " ".join(str(summary).split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    boundary = max(
        cut.rfind(mark) for mark in (" ", ",", ".", ";", "，", "。", "；", "、", "：")
    )
    if boundary >= limit // 2:
        cut = cut[:boundary]
    return cut.rstrip(" ,.;，。；、：") + "…"


def _group_x_docs_by_account(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """X 简报输入以账号为单位：按推文 URL 的 handle 分组（无 handle 回退昵称）。

    分组顺序 = 账号首次出现顺序（保留输入顺序）；组内保持输入相对顺序。handle 与昵称都缺失的文档并入同一个
    "官方账号动态"兜底分组，不静默丢弃。
    """
    groups: List[Dict[str, Any]] = []
    by_key: Dict[str, Dict[str, Any]] = {}
    for doc in docs:
        url = str(doc.get("url") or "")
        match = _X_HANDLE_URL_RE.search(url)
        handle = match.group(1).lower() if match else ""
        nickname = str(doc.get("author_name") or "").strip()
        key = handle or nickname.lstrip("@").lower()
        group = by_key.get(key)
        if group is None:
            group = {"handle": handle, "nickname": nickname, "docs": []}
            by_key[key] = group
            groups.append(group)
        elif not group["nickname"] and nickname:
            group["nickname"] = nickname
        group["docs"].append(doc)
    return groups


def _x_account_label(group: Dict[str, Any]) -> str:
    """账号条目标题：昵称与 handle 同时存在且不同名时并列展示。"""
    nickname = group["nickname"]
    handle = group["handle"]
    nick_plain = nickname.lstrip("@")
    if nickname and handle and nick_plain.lower() != handle:
        return f"📣 {nickname} (@{handle})"
    if nick_plain:
        return f"📣 @{nick_plain}"
    if handle:
        return f"📣 @{handle}"
    return "📣 官方账号动态"


def _format_x_articles_by_account(docs: List[Dict[str, Any]]) -> str:
    groups = _group_x_docs_by_account(docs)
    lines: List[str] = []
    for i, group in enumerate(groups, start=1):
        tweets = group["docs"]
        lines.append(f"{i}. {_x_account_label(group)}（{len(tweets)} 条推文）")
        for j, doc in enumerate(tweets, start=1):
            title = doc.get("title") or "无标题"
            summary = doc.get("summary") or ""
            url = doc.get("url") or ""
            lines.append(f"   {j}) **{title}**")
            if summary:
                lines.append(f"      {_truncate_summary(summary)}")
            if url:
                lines.append(f"      🔗 {url}")
        lines.append("")
    return "\n".join(lines)


def _count_briefing_items(docs: List[Dict[str, Any]], source: str = "all") -> int:
    """简报覆盖口径计数：X 以账号为单位，其余来源以条目为单位。"""
    if source == "x":
        return len(_group_x_docs_by_account(docs))
    return len(docs)


def _format_articles(docs: List[Dict[str, Any]], source: str = "all") -> str:
    # X 简报以账号为单位：同一账号当日推文聚合为一个编号条目。
    # 综合简报（source="all"）是跨源混排，X 条目仍按单条推文渲染。
    if source == "x":
        return _format_x_articles_by_account(docs)
    lines: List[str] = []
    for i, doc in enumerate(docs, start=1):
        title = doc.get("title") or "无标题"
        summary = doc.get("summary") or ""
        url = doc.get("url") or ""
        src = str(doc.get("source") or source).lower()

        # 简报只接收内容和来源归属，不把 score/raw_score 或其他互动指标
        # 暴露给模型。它们仍由 preparation.py 用于候选排序。
        if src == "news":
            attribution = f"📰 {doc.get('feed_name') or '新闻'}"
        elif src == "x":
            author = str(doc.get("author_name") or "").strip().lstrip("@")
            attribution = f"📣 @{author}" if author else "📣 官方账号动态"
        else:
            attribution = ""

        heading = f"{i}. **{title}**"
        if attribution:
            heading += f"（{attribution}）"
        lines.append(heading)
        if summary:
            lines.append(f"   {_truncate_summary(summary)}")
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


class BriefingModel(Protocol):
    """Streaming model boundary used by briefing generation."""

    def astream(self, prompt: str) -> AsyncIterator[Any]: ...


class BriefingSavedNotifier(Protocol):
    """简报真实保存成功后的投递通知边界。

    仅 save_briefing() 成功返回有效 id 后触发；缓存命中、无文档、空正文、
    双语失败或任何 error 路径均不触发。默认不挂载（None），由组合层负责
    把订阅补发编排接入；实现必须快速返回（如同步提交后台任务），通知异常
    由服务方隔离，不影响已保存简报与 SSE 事件流。
    """

    def __call__(
        self,
        *,
        report_date: str,
        source: str,
        cache_key: str,
        briefing_id: int,
        content_zh: str,
    ) -> None: ...


class DailyBriefingService:
    """Generate and persist daily briefing reports with SSE streaming."""

    def __init__(
        self,
        *,
        briefing_repository: BriefingContentRepository,
        document_feed: DocumentFeedReader,
        rank_snapshot_reader: RankSnapshotReader,
        model: BriefingModel,
        top_k: int = 10,
        briefing_saved: BriefingSavedNotifier | None = None,
    ) -> None:
        self._briefings = briefing_repository
        self._document_feed = document_feed
        self._rank_snapshots = rank_snapshot_reader
        self._top_k = top_k
        self._llm = model
        self._briefing_saved = briefing_saved

    def _notify_briefing_saved(
        self,
        *,
        report_date: str,
        source: str,
        cache_key: str,
        briefing_id: int,
        content_zh: str,
    ) -> None:
        """触发保存后通知；通知失败仅记录，绝不影响生成结果。"""
        if self._briefing_saved is None:
            return
        try:
            self._briefing_saved(
                report_date=report_date,
                source=source,
                cache_key=cache_key,
                briefing_id=briefing_id,
                content_zh=content_zh,
            )
        except Exception:
            logger.error(
                "[Briefing] 简报保存后的订阅通知失败: source=%s briefing_id=%s",
                source,
                briefing_id,
                exc_info=True,
            )

    def _prepare_briefing(
        self,
        *,
        target_date: str,
        source: str,
    ) -> PreparedBriefing:
        context = normalize_briefing_context(
            target_date=target_date,
            source=source,
            source_config=_SOURCE_CONFIG,
            source_channels=_SOURCE_CHANNELS,
        )
        return prepare_briefing(
            context=context,
            top_k=self._top_k,
            snapshot_reader=self._rank_snapshots,
            document_feed=self._document_feed,
            source_config=_SOURCE_CONFIG,
            filter_by_channel=_filter_docs_by_channel,
            format_articles=_format_articles,
            is_blocked=_looks_like_block_response,
            count_items=_count_briefing_items,
        )

    async def stream_generate(
        self,
        target_date: str | None = None,
        source: str = "all",
        force_regenerate: bool = True,
        locale: str = "zh-CN",
        generate_bilingual: bool = False,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Stream the briefing generation process as SSE payloads.

        Args:
            target_date: ISO date string，默认今天
            source: "all" | "arxiv" | "github" | "news" | "producthunt" | "hackernews" | "x" | "dailyhot"
            force_regenerate: 若为 True（默认），始终重新生成，不使用缓存

        Payload types:
          - {"type": "start",    "data": {"date": str, "doc_count": int, "source": str}}
          - {"type": "content",  "data": str}           # incremental token
          - {"type": "done",     "data": {"briefing_id": int}}
          - {"type": "error",    "data": str}
        """
        today = target_date or today_cst()
        requested_locale = normalize_briefing_locale(locale)
        context = normalize_briefing_context(
            target_date=today,
            source=source,
            source_config=_SOURCE_CONFIG,
            source_channels=_SOURCE_CHANNELS,
        )
        source = context.source
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
                        },
                    }
                    yield {"type": "content", "data": select_briefing_content(existing, requested_locale)}
                    yield {"type": "done", "data": {"briefing_id": existing["id"]}}
                    return

            logger.info(
                "开始获取文档，source=%s, date=%s...", source, today
            )
            prepared = self._prepare_briefing(
                target_date=today,
                source=source,
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
                },
            }

            if not docs:
                logger.warning("依然没有文档，发送'暂无数据'提示")
                msg = (
                    f"# {today} 今日简报\n\n"
                    "> 数据库中暂无对应周期的文档，请先运行数据采集任务。\n"
                )
                yield {"type": "content", "data": msg}
                yield {"type": "done", "data": {"briefing_id": -1}}
                return

            logger.info(
                "找到 %d 条文档，source=%s，开始构建 Prompt...", len(docs), source
            )
            prompt = prepared.prompt or ""
            if generate_bilingual:
                prompt += _LANGUAGE_INSTRUCTIONS[requested_locale]

            # 4. Stream the requested language first（含截断续写，边生成边转发）
            primary_parts: List[str] = []
            try:
                async for token in self._stream_with_continuation(
                    prompt, source=source, parts=primary_parts
                ):
                    yield {"type": "content", "data": token}
            except _BlockResponseError:
                logger.error(
                    "LLM 上游返回疑似拦截页，停止简报生成: source=%s", source
                )
                yield {"type": "error", "data": _BLOCK_RESPONSE_ERROR}
                return

            # 5. Persist only if LLM actually produced content
            complete_text = "".join(primary_parts)
            if complete_text.strip():
                if generate_bilingual:
                    alternate_locale = next(item for item in _BRIEFING_LANGUAGES if item != requested_locale)
                    alternate_prompt = (prepared.prompt or "") + _LANGUAGE_INSTRUCTIONS[alternate_locale]
                    # 另一语言与主语言走同一条含续写的生成路径（续写对等），
                    # 仅不向客户端推流。
                    alternate_parts: List[str] = []
                    try:
                        async for _token in self._stream_with_continuation(
                            alternate_prompt, source=source, parts=alternate_parts
                        ):
                            pass
                    except _BlockResponseError:
                        logger.error(
                            "双语简报另一语言返回疑似拦截页: source=%s", source
                        )
                        yield {"type": "error", "data": _ALTERNATE_LANGUAGE_ERROR}
                        return
                    alternate_text = "".join(alternate_parts)
                    if not alternate_text.strip():
                        yield {"type": "error", "data": _ALTERNATE_LANGUAGE_ERROR}
                        return
                    contents = {requested_locale: complete_text, alternate_locale: alternate_text}
                    briefing_id = self._briefings.save_briefing(
                        cache_date,
                        contents["zh-CN"],
                        content_zh=contents["zh-CN"],
                        content_en=contents["en"],
                    )
                    logger.info("双语简报已持久化，id=%d, source=%s", briefing_id, source)
                    self._notify_briefing_saved(
                        report_date=today,
                        source=source,
                        cache_key=cache_date,
                        briefing_id=briefing_id,
                        content_zh=contents["zh-CN"],
                    )
                else:
                    briefing_id = self._briefings.save_briefing(cache_date, complete_text)
                    self._notify_briefing_saved(
                        report_date=today,
                        source=source,
                        cache_key=cache_date,
                        briefing_id=briefing_id,
                        content_zh=complete_text,
                    )
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
            logger.error(
                "简报生成流异常: source=%s",
                source,
                exc_info=True,
            )
            yield {"type": "error", "data": _classified_briefing_error(exc)}

    async def _stream_with_continuation(
        self,
        prompt: str,
        *,
        source: str,
        parts: List[str],
    ) -> AsyncGenerator[str, None]:
        """流式生成简报正文，截断时自动多轮续写。

        每个产出 token 同时 append 到 parts 并向调用方 yield；迭代结束后
        调用方用 "".join(parts) 取得完整文本。主语言与双语场景的另一语言
        共用本路径，保证续写行为对等。疑似拦截页时抛 _BlockResponseError。
        """
        async for token in self._stream_llm_round(prompt):
            parts.append(token)
            yield token

        accumulated = self._sanitize_parts(parts)

        # 截断续写：检测输出是否被截断，若是则多轮续写
        for continuation_round in range(1, _MAX_CONTINUATION_ROUNDS + 1):
            if not self._is_truncated(accumulated):
                logger.info("报告生成完整，无需续写 (round %d)", continuation_round)
                break

            logger.warning(
                "检测到输出可能被截断 (round %d/%d)，启动续写...",
                continuation_round,
                _MAX_CONTINUATION_ROUNDS,
            )
            yield ""  # 空 token 作为续写信号（前端无感）

            # 构建续写 prompt，将已有内容作为上下文
            cont_prompt = _CONTINUATION_PROMPT.format(
                previous_content=accumulated[-4000:]  # 只传最后 4000 字符避免超长
            )

            async for token in self._stream_llm_round(cont_prompt):
                parts.append(token)
                yield token

            accumulated = self._sanitize_parts(parts)
        else:
            logger.warning(
                "已达最大续写轮数 (%d)，停止续写", _MAX_CONTINUATION_ROUNDS
            )

    @staticmethod
    def _sanitize_parts(parts: List[str]) -> str:
        """每轮生成后的整文净化：拦截页拒绝、中转站信封剥离。

        剥离信封时同步重写 parts（调用方最终 "".join(parts) 入库），
        保证缓存里永远是纯 Markdown 而非包装层原文。
        """
        accumulated = "".join(parts)
        if _looks_like_block_response(accumulated):
            raise _BlockResponseError()
        stripped = _strip_relay_envelope(accumulated)
        if stripped != accumulated:
            logger.warning("检测到中转站 JSON 信封，已剥离包装层")
            parts[:] = [stripped]
            accumulated = stripped
        unescaped = _unescape_backticks(accumulated)
        if unescaped != accumulated:
            logger.warning("检测到转义反引号，已还原为行内代码形式")
            parts[:] = [unescaped]
            accumulated = unescaped
        return accumulated

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

        只保留结构性信号；不再按篇幅长短判断——短但完整的简报
        被误判截断会触发无意义续写，甚至让模型重复已生成内容。
        1. 存在未闭合的 Markdown 代码块（``` 出现奇数次）→ 截断
        2. 最后一行是悬空的 Markdown 标题（如 "## "、"### 技术"）→ 截断
        3. 最后一行粗体标记未闭合（奇数个 "**"）→ 截断
        4. 最后一行是悬空的数字列表项（如 "3. "）→ 截断
        """
        if not text or not text.strip():
            return False

        stripped = text.strip()

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
