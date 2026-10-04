"""RSS 2.0 feed API：canonical 简报 feed + legacy compatibility routes。

端点列表：
  GET  /api/feed.xml                     → 综合 feed（全部源按发布时间归并，每源限额）
  GET  /api/feeds/{source}.xml           → 单源 feed（arxiv/github/news/…）
  GET  /api/feeds/member.xml             → 注册用户全文 feed（?token= 用独立 RSS feed
                                           token，?source=a,b 自由组合；任意注册用户
                                           可用，未登录/无效 token 401）
  GET  /api/feeds/briefing.xml           → 每日综合简报全文 feed（公开，近 7 期）
  GET  /api/feeds/briefing-digest.xml    → 注册用户简报速览 feed（?token=，规则压缩版）

设计要点：
  - 公开 feed 面向中文读者：有中文译文的条目，description 用译文截断（X 源
    标题也用译文截断），无译文回退原摘要；只出摘要 + 回链（arxiv 指站内
    阅读页，其余源指原文链接）；每条摘要尾部带一行全文 RSS 订阅钩子（指向
    /subscriptions 引导注册登录），token feed 不带。Cache-Control 交双边缘缓存。
  - 全文/速览 feed 用独立的 user_feed_tokens 鉴权（hash_feed_token → token→user），
    与 MCP token 完全分离；token 永不过期、重新生成即吊销旧 token。响应
    noindex + private/no-store——带 token 的 URL 绝不进边缘缓存。
  - github 源由站内项目库「今日暴涨 top50」热榜供稿（scope=today + hot 排序，
    与 /projects 页同口径），不镜像 trending 抓取的 documents 池；
    热榜查询失败或为空时回退 documents 池兜底，保证 feed 不断更。
  - 简报 feed 只出综合报（briefings.date 裸日期键；'{date}_{module}' 模块报是
    综合报原料，不单列）。全文公开与 /report 口径一致（简报全文本就无鉴权），
    注册用户增量是速览版：M0 规则压缩（摘要节 + 条目标题一览），LLM 精简管线
    后续替换 condense_briefing_markdown 输出即可。渲染走规则 Markdown→HTML
    片段（rss_render 纯函数），description 按 RSS 惯例整体 XML 转义。
  - XML 渲染为纯函数，路由层只做读库与鉴权，便于契约测试。
  - 各 feed 都认 ?locale=，认法与 /api/report/latest 相同（en 开头即英文，其余
    一律中文）。英文版简报取英文正文，不回退到中文：阅读器按 guid 记住已推送
    的条目，先推了另一种语言，补上正文后也不会换回来。资讯条目在英文版里用
    原文标题和摘要，频道与钩子文案也换成英文。
  - 频道 <link> 指网站页面（资讯 feed 指首页，简报 feed 指 /report），feed
    自身的地址写在 atom:link rel="self"。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from typing import Any
from urllib.parse import quote
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from backend.app.api.dependencies import (
    get_briefing_repository,
    get_document_repository,
    get_feed_token_repository,
    get_project_catalog_query_service,
)
from backend.app.core.auth import hash_feed_token
from backend.app.repositories.briefing_repository import BriefingContentRepository
from backend.app.repositories.document_repository import DocumentRecentReader
from backend.app.repositories.feed_token_repository import FeedTokenRepository
from backend.app.services.briefing.daily_briefing import _truncate_summary, normalize_briefing_locale
from backend.app.services.briefing.rss_render import (
    condense_briefing_markdown,
    render_briefing_markdown_html,
    sanitize_public_resource_url,
    sanitize_public_text,
)
from backend.app.services.papers.presentation import public_base_url
from backend.app.services.project_catalog.query_service import ProjectCatalogQueryService

logger = logging.getLogger(__name__)

router = APIRouter()

# 与日报模块同一份源词汇表（去掉聚合维度 "all"，它由多源归并实现）。
FEED_SOURCES: frozenset[str] = frozenset({"arxiv", "github", "news", "producthunt", "hackernews", "x", "dailyhot"})

# 公开 feed 定位「最新」而非归档：近 48 小时、至多 100 条。
_PUBLIC_FEED_WINDOW = timedelta(hours=48)
_PUBLIC_FEED_LIMIT = 100
# 综合 feed 按源限额（100 条 / 7 源 → 每源至多 15 条）：github 热榜整榜共用
# 最新快照时间、恒排最前，X 一天几十条；不限额时两者占满 100 条，只有日期
# 的 HN/Product Hunt 永远挤不进来。单源 feed 与全文归档 feed 不限额。
_PUBLIC_FEED_PER_SOURCE_LIMIT = -(-_PUBLIC_FEED_LIMIT // len(FEED_SOURCES))
# token feed（注册用户）给更长回溯窗口与更高条数上限。
_MEMBER_FEED_WINDOW = timedelta(days=7)
_MEMBER_FEED_LIMIT = 500

_PUBLIC_CACHE_CONTROL = "public, max-age=900"
_MEMBER_CACHE_CONTROL = "private, no-store"
# Starlette 只对 text/* 自动补 charset；application/rss+xml 必须显式声明，
# 否则 GBK 区域环境（中文 Windows 浏览器/控制台）会把 UTF-8 字节按 GBK 解码出花屏。
# XML 声明里的 encoding 对规范解析器够用，但裸览/下载场景以 HTTP 头为准。
_FEED_MEDIA_TYPE = "application/rss+xml; charset=utf-8"
# 自托管部署未配置 PUBLIC_BASE_URL 时，与 sitemap/MCP 回链同策略回落品牌站点。
_BRAND_BASE_URL = "https://aigcnews.cn"

_CHANNEL_TITLE = "AIGC NEWS"
_CHANNEL_DESCRIPTION = "AI 资讯聚合：arXiv 论文、GitHub 项目、Product Hunt、Hacker News、X 与科技媒体日报（含 AI 生成摘要与译文，仅供参考）"

_INVALID_TOKEN_DETAIL = "feed 令牌无效或已吊销，请登录后在订阅页复制你的 RSS 链接"

# 公开 feed 转化钩子：每条摘要尾部一行，引导读者注册登录后免费订阅全文 RSS。
# RSS 条目在阅读器里被逐条消费、脱离 channel 上下文，钩子须随条目走。
# token feed 不带钩子——订阅用户已转化，不再插引导。
_PUBLIC_HOOK_PREFIX = "📮 全文 RSS（中文译文 · 完整归档），注册登录即可免费订阅："

# github 源供稿口径：站内项目库「今日暴涨」热榜（scope=today 强制 hot 排序）top50。
_GITHUB_HOT_FEED_LIMIT = 50

# 简报 feed：近 7 期综合报（一日一期，约一周归档）。
_BRIEFING_FEED_LIMIT = 7
_BRIEFING_CHANNEL_DESCRIPTION = "每日 AIGC 综合简报全文：跨源技术亮点、工程动态与行业资讯（内容由 AI 生成，仅供参考）"
_BRIEFING_DIGEST_CHANNEL_DESCRIPTION = "每日 AIGC 综合简报速览：内容摘要 + 条目标题一览（注册用户免费订阅；内容由 AI 生成）"


@dataclass(frozen=True)
class _FeedCopy:
    """一种语言的频道与条目文案；简报条目标题里的 {date} 换成期号。"""

    english: bool
    language: str
    description: str
    hook_prefix: str
    archive_title: str
    briefing_title: str
    briefing_digest_title: str
    briefing_description: str
    briefing_digest_description: str
    briefing_item_title: str
    briefing_digest_item_title: str


_FEED_COPY_ZH = _FeedCopy(
    english=False,
    language="zh-cn",
    description=_CHANNEL_DESCRIPTION,
    hook_prefix=_PUBLIC_HOOK_PREFIX,
    archive_title="全文归档",
    briefing_title="每日简报",
    briefing_digest_title="每日简报速览",
    briefing_description=_BRIEFING_CHANNEL_DESCRIPTION,
    briefing_digest_description=_BRIEFING_DIGEST_CHANNEL_DESCRIPTION,
    briefing_item_title="{date} 每日 AIGC 简报",
    briefing_digest_item_title="{date} 每日 AIGC 简报（速览）",
)
_FEED_COPY_EN = _FeedCopy(
    english=True,
    language="en",
    description=(
        "AI news roundup: arXiv papers, GitHub projects, Product Hunt, Hacker News, X and tech media"
        " (summaries are AI-generated, for reference only)"
    ),
    hook_prefix="📮 Full-text RSS with the complete archive, free for registered users: ",
    archive_title="Full archive",
    briefing_title="Daily briefing",
    briefing_digest_title="Daily briefing digest",
    briefing_description=(
        "The full daily AIGC briefing: cross-source technical highlights, engineering news and industry updates"
        " (AI-generated, for reference only)"
    ),
    briefing_digest_description=(
        "The daily AIGC briefing at a glance: the summary plus every item title"
        " (free for registered users; AI-generated)"
    ),
    briefing_item_title="{date} Daily AIGC Briefing",
    briefing_digest_item_title="{date} Daily AIGC Briefing (digest)",
)


def _feed_copy(locale: str | None) -> _FeedCopy:
    return _FEED_COPY_EN if normalize_briefing_locale(locale) == "en" else _FEED_COPY_ZH


def _project_to_feed_row(item: dict[str, Any], *, english: bool = False) -> dict[str, Any]:
    """项目库热榜条目 → feed 行（与 documents 行同形，供统一渲染/归并排序）。

    中文版优先中文简介，英文版优先原简介。
    """
    full_name = str(item.get("full_name") or "").strip()
    preferred, fallback = ("description", "description_zh") if english else ("description_zh", "description")
    description = str(item.get(preferred) or item.get(fallback) or "").strip()
    stars = item.get("stars")
    stats = f"⭐ {int(stars):,}" if isinstance(stars, (int, float)) else ""
    growth = item.get("daily_star_growth")
    if isinstance(growth, (int, float)) and growth > 0:
        today = f"+{int(growth):,} today" if english else f"今日 +{int(growth):,}"
        stats = f"{stats} · {today}" if stats else today
    summary = f"{description}\n\n{stats}" if description and stats else description or stats

    topics = item.get("topics")
    tags = [str(tag).strip() for tag in (topics if isinstance(topics, list) else []) if str(tag).strip()]
    language = str(item.get("language") or "").strip()
    if language:
        tags.insert(0, language)

    return {
        "id": full_name,
        "source": "github",
        "title": full_name,
        "url": str(item.get("url") or "").strip() or f"https://github.com/{full_name}",
        "summary": summary,
        "published_at": str(item.get("captured_at") or "").strip(),
        "published_date": str(item.get("daily_growth_date") or item.get("snapshot_date") or "").strip(),
        "created_at": "",
        "tags": json.dumps(tags, ensure_ascii=False),
    }


async def _github_feed_rows(
    documents: DocumentRecentReader,
    catalog: ProjectCatalogQueryService | None,
    *,
    since_iso: str,
    limit: int,
    english: bool = False,
) -> list[dict[str, Any]]:
    """github 源行：优先站内今日热榜，热榜不可用/为空时回退 documents 池。"""
    if catalog is not None:
        try:
            page = await catalog.list_public_projects(
                scope="today",
                category="",
                subcategory="",
                q="",
                language="",
                page=1,
                page_size=min(limit, _GITHUB_HOT_FEED_LIMIT),
                sort=None,
                user_id=None,
            )
            items = page.result.get("items") or []
            rows = [_project_to_feed_row(item, english=english) for item in items if isinstance(item, dict)]
            rows = [row for row in rows if row["id"]]
            if rows:
                # 整榜共用最新快照时间作 pubDate：各条目 captured_at 来自不同时次的
                # 快照刷新，若保留原值，全局按时间归并会把热榜打散成「重捕先后」序。
                # 统一后稳定排序保留 hot 名次，pubDate 语义 = 本期热榜快照时间。
                latest = max(row["published_at"] for row in rows)
                if latest:
                    for row in rows:
                        row["published_at"] = latest
                return rows
            logger.warning("[Feed] 项目库今日热榜为空，github feed 回退 documents 池")
        except Exception as exc:
            logger.warning("[Feed] 项目库今日热榜查询失败，github feed 回退 documents 池: %s", exc)
    return await asyncio.to_thread(
        documents.list_recent_by_source,
        "github",
        since_iso=since_iso,
        limit=limit,
    )


def _parse_published_at(value: Any) -> datetime | None:
    """解析 ISO 日期/时间字符串；脏串返回 None。"""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


# 只有日期的业务日期按 UTC 零点解析，但各源定日期的时区不一：HN/Techmeme RSS
# 为 UTC、Product Hunt 为太平洋时间，DailyHot 与 Techmeme 主页补充条目为北京时间。
# 北京时间 0–8 点入库的条目，其日期零点（UTC）晚于入库时刻，会被窗口当作未来
# 条目藏到 8 点；这类条目改用入库时间。容差 8 小时即北京时间领先 UTC 的幅度，
# 入库远早于业务日期的行（如 github 榜单重上榜仓）仍按业务日期零点。
_DATE_ONLY_VALUE = re.compile(r"\d{4}-\d{2}-\d{2}")
_BUSINESS_DATE_LEAD_TOLERANCE = timedelta(hours=8)


def _row_published(row: dict[str, Any]) -> datetime | None:
    """跨源统一时间口径：X 优先 published_at，其他源回退业务日期/入库时间。

    只有日期、且入库时间早于该日期 UTC 零点不超过 8 小时时取入库时间（见上）。
    """
    for field in ("published_at", "published_date", "created_at"):
        value = str(row.get(field) or "").strip()
        published = _parse_published_at(value)
        if published is None:
            continue
        if field != "created_at" and _DATE_ONLY_VALUE.fullmatch(value):
            created_value = str(row.get("created_at") or "").strip()
            ingested = None if _DATE_ONLY_VALUE.fullmatch(created_value) else _parse_published_at(created_value)
            if ingested is not None and published - _BUSINESS_DATE_LEAD_TOLERANCE <= ingested < published:
                return ingested
        return published
    return None


def _item_link(row: dict[str, Any], base_url: str) -> str | None:
    """条目链接：arxiv 指站内阅读页（导流），其余源本站无详情页、指原文链接。"""
    doc_id = str(row.get("id") or "").strip()
    source = str(row.get("source") or "").strip()
    if source == "arxiv" and doc_id:
        return f"{base_url}/papers/{quote(doc_id, safe='')}/read"
    url = sanitize_public_resource_url(str(row.get("url") or ""))
    return url


_PUBLIC_TITLE_TRANSLATION_LIMIT = 80
_PUBLIC_DESCRIPTION_TRANSLATION_LIMIT = 200
_BARE_URL = re.compile(r"https?://\S+")

# 非 X 源摘要入库即硬截断到 500 字符（persistence_adapter.project_document_write），
# 不补省略号：恰好满额的摘要在 feed 里补上。末尾是半截链接时整段去掉（半截 URL
# 会被阅读器自动链到错误地址）；截断点落在英文单词中间时退回上一个空白，末段含
# 中文或超长时不退，免得吞掉整句。
_STORED_SUMMARY_LIMIT = 500
_TRUNCATED_TAIL_URL = re.compile(r"https?://[!-~]*$")
_TRUNCATED_TAIL_WORD = re.compile(r"\s+[!-~]{0,39}[A-Za-z0-9]$")

# arXiv 标题/摘要沿用 LaTeX 源码写法，阅读器不渲染：排版命令只留内容（嵌套时
# 由内向外逐层剥），不含命令的短行内公式去掉定界符（$k$、\(TPP\)），转义字符
# 还原（\$1.5M → $1.5M），``引号'' 换成弯引号。仍含命令的公式与作者自定义宏
# （\method、\ours{}）原样保留；~ 在摘要里多作「约」用，也不动。
_LATEX_TEXT_COMMAND = re.compile(
    r"\\(?:textbf|textit|textsl|textsc|textrm|textsf|texttt|textsuperscript|textsubscript"
    r"|emph|underline|mbox|text|mathrm|mathbf|mathit|mathsf|mathtt)\{([^{}]*)\}"
)
_LATEX_INLINE_MATH = re.compile(r"(?<!\\)\$([^$]*?)(?<!\\)\$|\\\((.*?)\\\)")
_LATEX_SIMPLE_MATH_LIMIT = 20
_LATEX_ESCAPED_CHAR = re.compile(r"\\([$%&_#])")
_LATEX_QUOTED = re.compile(r"``([^`'\"]{1,120}?)(?:''|\")")


def _same_text(left: str, right: str) -> bool:
    return " ".join(left.split()) == " ".join(right.split())


def _unwrap_simple_math(match: re.Match[str]) -> str:
    body = match.group(1) if match.group(1) is not None else match.group(2)
    if body and len(body) <= _LATEX_SIMPLE_MATH_LIMIT and "\\" not in body and body == body.strip():
        return body
    return match.group(0)


def _plain_latex(text: str) -> str:
    for _ in range(3):
        stripped = _LATEX_TEXT_COMMAND.sub(r"\1", text)
        if stripped == text:
            break
        text = stripped
    text = _LATEX_INLINE_MATH.sub(_unwrap_simple_math, text)
    text = _LATEX_ESCAPED_CHAR.sub(r"\1", text)
    return _LATEX_QUOTED.sub(r"“\1”", text)


def _mark_truncated(text: str, *, mid_word: bool) -> str:
    without_url = _TRUNCATED_TAIL_URL.sub("", text)
    if without_url.strip() and without_url != text:
        text = without_url
    elif mid_word:
        text = _TRUNCATED_TAIL_WORD.sub("", text)
    return text.rstrip(" ,.;:，。；、：(（") + "…"


def _row_summary(row: dict[str, Any]) -> str:
    """条目原摘要：arXiv 去 LaTeX 排版；非 X 源入库截断满额的补省略号。"""
    raw = str(row.get("summary") or "")
    summary = raw.strip()
    source = str(row.get("source") or "").strip()
    if source == "arxiv":
        summary = _plain_latex(summary)
    if (
        summary
        and source != "x"
        and len(raw) == _STORED_SUMMARY_LIMIT
        and not summary.endswith(("…", "..."))
    ):
        summary = _mark_truncated(summary, mid_word=not raw[-1].isspace())
    return summary


def _row_title(row: dict[str, Any]) -> str:
    """条目原标题；X 纯链接推文（正文只有一条 URL）改用链接卡片标题。"""
    title = str(row.get("title") or "").strip()
    if str(row.get("source") or "").strip() == "arxiv":
        return _plain_latex(title)
    card = row.get("link_card")
    if _BARE_URL.fullmatch(title) and isinstance(card, dict):
        card_title = " ".join(str(card.get("title") or "").split())
        if card_title:
            return card_title
    return title


def _public_item_title(row: dict[str, Any], *, english: bool = False) -> str:
    """公开条目展示标题：X 源有中文译文时用译文截断，其余源保持原 title。

    库中无 title_zh 字段，X 的「标题」即推文原文（英文为主）；译文截断到
    80 字符当标题。榜单/媒体源本身已有面向中文读者的标题或仓库名，不动。
    英文版不换译文，推文原文同样截断到 80 字符。
    """
    title = _row_title(row)
    if str(row.get("source") or "").strip() != "x":
        return title
    text = title if english else str(row.get("translation_zh") or "").strip()
    if not text:
        return title
    return _truncate_summary(text, _PUBLIC_TITLE_TRANSLATION_LIMIT)


def _item_description(row: dict[str, Any], *, full: bool, title: str = "", english: bool = False) -> str:
    """摘要文本：公开 feed 优先中文译文截断（无译文回退原摘要）；token feed
    为原摘要 + 完整中文译文（不截断）。英文版只用原摘要。

    与展示标题同文的段落不再重复一遍：HN 的摘要就是标题，X 短推文的
    译文标题与译文摘要截断后同文。
    """
    summary = _row_summary(row)
    translation = "" if english else str(row.get("translation_zh") or "").strip()
    if full:
        parts = [summary] if summary and not _same_text(summary, title) else []
        # 未翻译内容回填的「译文」与库中原摘要同文，不重复
        if translation and translation != str(row.get("summary") or "").strip():
            parts.append(translation)
        return sanitize_public_text("\n\n".join(parts))
    text = (
        _truncate_summary(translation, _PUBLIC_DESCRIPTION_TRANSLATION_LIMIT)
        if translation
        else summary
    )
    return "" if _same_text(text, title) else sanitize_public_text(text)


def _parse_tags(value: Any) -> list[str]:
    """解析 tags 列（JSON 数组串，如 '["x", "daily"]'）；脏值按逗号分隔回落。

    documents.tags 与 authors 同约定——仓储层刻意保持 JSON 字符串透传，
     feed 渲染处自行解析。
    """
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        return [str(tag).strip() for tag in parsed if str(tag).strip()]
    return [tag.strip() for tag in value.split(",") if tag.strip()]


def build_feed_item(
    row: dict[str, Any], base_url: str, *, full: bool = False, locale: str | None = None
) -> str | None:
    """把文档行渲染为 <item> XML；缺 id/title/link 的行返回 None。"""
    doc_id = str(row.get("id") or "").strip()
    title = _row_title(row)
    link = _item_link(row, base_url)
    if not doc_id or not title or not link:
        return None
    copy = _feed_copy(locale)
    # 公开条目面向中文读者：X 源有译文时标题换成译文截断；token feed 条目保留原标题
    display_title = title if full else _public_item_title(row, english=copy.english)

    description = _item_description(row, full=full, title=display_title, english=copy.english)
    if not full:
        hook = f"{copy.hook_prefix}{base_url}/subscriptions"
        description = f"{description}\n\n{hook}" if description else hook
    categories = "".join(f"<category>{escape(tag)}</category>" for tag in _parse_tags(row.get("tags")))

    published = _row_published(row)
    pub_date = f"<pubDate>{format_datetime(published, usegmt=False)}</pubDate>" if published else ""
    return (
        "<item>"
        f"<title>{escape(display_title)}</title>"
        f"<link>{escape(link)}</link>"
        f'<guid isPermaLink="false">{escape(str(row.get("source") or ""))}:{escape(doc_id)}</guid>'
        f"{pub_date}"
        f"<description>{escape(description)}</description>"
        f"{categories}"
        "</item>"
    )


def build_rss_xml(
    *,
    channel_title: str,
    channel_link: str,
    self_link: str,
    channel_description: str,
    items: list[str],
    language: str = "zh-cn",
) -> str:
    """渲染 RSS 2.0 channel；items 为已渲染的 <item> 片段列表。

    channel_link 是频道对应的网站页面，self_link 是 feed 自身的地址。
    """
    body = "\n".join(items)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "<channel>\n"
        f"<title>{escape(channel_title)}</title>\n"
        f"<link>{escape(channel_link)}</link>\n"
        f"<description>{escape(channel_description)}</description>\n"
        f"<language>{escape(language)}</language>\n"
        f'<atom:link href="{escape(self_link)}" rel="self" type="application/rss+xml"/>\n'
        f"{body}\n"
        "</channel>\n"
        "</rss>\n"
    )


def _sort_rows_newest_first(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按跨源有效时间新到旧排序；脏时间串排尾（保持原相对序）。

    按解析后的时刻比较：各源时间串形态不一（裸日期、带/不带时区偏移），
    词法序只在同形态内可比。
    """
    floor = datetime.min.replace(tzinfo=timezone.utc)

    def key(row: dict[str, Any]) -> tuple[bool, datetime]:
        published = _row_published(row)
        return (published is not None, published or floor)

    return sorted(rows, key=key, reverse=True)


def _filter_rows_to_window(
    rows: list[dict[str, Any]],
    *,
    window: timedelta,
    now: datetime,
) -> list[dict[str, Any]]:
    """只保留最终 RSS pubDate 位于声明窗口内的条目。

    DocumentRecentReader 为兼容历史数据，会把近期入库但业务日期较旧的行
    返回给调用者。RSS 不能沿用这个 fallback：阅读器会把旧 pubDate 当作新
    条目重新推送。因此这里按最终展示日期严格过滤，并丢弃无有效日期的行。
    """
    cutoff = now - window
    return [
        row
        for row in rows
        if (published := _row_published(row)) is not None
        and cutoff <= published <= now
    ]


def _cap_rows_per_source(rows: list[dict[str, Any]], per_source: int) -> list[dict[str, Any]]:
    """保持输入顺序，每个源至多保留 per_source 条。"""
    kept: dict[str, int] = {}
    capped: list[dict[str, Any]] = []
    for row in rows:
        source = str(row.get("source") or "")
        if kept.get(source, 0) < per_source:
            kept[source] = kept.get(source, 0) + 1
            capped.append(row)
    return capped


async def _collect_rows(
    documents: DocumentRecentReader,
    sources: set[str],
    *,
    window: timedelta,
    limit: int,
    catalog: ProjectCatalogQueryService | None = None,
    per_source_limit: int | None = None,
    english: bool = False,
) -> list[dict[str, Any]]:
    """并发拉取各源滚动窗口文档（github 改由站内今日热榜供稿），按发布时间归并后截断。

    per_source_limit 给定时，归并序上每个源只取最新的前 N 条再截断。
    """
    now = datetime.now(timezone.utc)
    since = (now - window).isoformat()
    # 共享 reader 为兼容历史数据可能返回近期入库的旧日期行；多取一批，避免
    # 这些行在数据库 LIMIT 内挤掉真正落在 RSS 窗口内的新条目，再由本层严格过滤。
    candidate_limit = min(max(limit * 2, limit), 500)
    doc_sources = sorted(sources - {"github"})
    tasks: list[Any] = [
        asyncio.to_thread(
            documents.list_recent_by_source,
            source,
            since_iso=since,
            limit=candidate_limit,
        )
        for source in doc_sources
    ]
    if "github" in sources:
        tasks.append(
            _github_feed_rows(
                documents, catalog, since_iso=since, limit=candidate_limit, english=english
            )
        )
    batches = await asyncio.gather(*tasks)
    merged = [row for batch in batches for row in batch]
    filtered = _filter_rows_to_window(merged, window=window, now=now)
    ordered = _sort_rows_newest_first(filtered)
    if per_source_limit is not None:
        ordered = _cap_rows_per_source(ordered, per_source_limit)
    return ordered[:limit]


def _xml_response(xml: str, *, cache_control: str) -> Response:
    return Response(
        content=xml,
        media_type=_FEED_MEDIA_TYPE,
        headers={"Cache-Control": cache_control},
    )


def _resolve_base_url(request: Request) -> str:
    return public_base_url(request) or _BRAND_BASE_URL


def _self_link(base_url: str, path: str, copy: _FeedCopy) -> str:
    """feed 自身的地址；英文版带上 ?locale=en，与订阅时用的地址一致。"""
    return f"{base_url}{path}?locale=en" if copy.english else f"{base_url}{path}"


@router.get("/feed.xml", include_in_schema=False)
async def feed_all(
    request: Request,
    locale: str = Query(default="zh-CN"),
    documents: DocumentRecentReader = Depends(get_document_repository),
    catalog: ProjectCatalogQueryService = Depends(get_project_catalog_query_service),
):
    """综合公开 feed：全部源按发布时间归并（每源限额），摘要 + 回链。"""
    copy = _feed_copy(locale)
    rows = await _collect_rows(
        documents,
        FEED_SOURCES,
        window=_PUBLIC_FEED_WINDOW,
        limit=_PUBLIC_FEED_LIMIT,
        catalog=catalog,
        per_source_limit=_PUBLIC_FEED_PER_SOURCE_LIMIT,
        english=copy.english,
    )
    base_url = _resolve_base_url(request)
    items = [item for row in rows if (item := build_feed_item(row, base_url, locale=locale)) is not None]
    xml = build_rss_xml(
        channel_title=_CHANNEL_TITLE,
        channel_link=f"{base_url}/",
        self_link=_self_link(base_url, "/api/feed.xml", copy),
        channel_description=copy.description,
        items=items,
        language=copy.language,
    )
    return _xml_response(xml, cache_control=_PUBLIC_CACHE_CONTROL)


async def _require_feed_identity(
    token: str,
    tokens: FeedTokenRepository,
) -> dict[str, Any]:
    """feed token → 注册用户身份：缺失/无效 401（fail-closed）。

    简报与全文 RSS 已降级为注册用户免费权益，此处只校验 token 有效，
    不再判定会员 tier。供所有 token feed 端点复用（member.xml、
    briefing-digest.xml）。"""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_INVALID_TOKEN_DETAIL,
        )
    identity = await asyncio.to_thread(
        tokens.get_user_by_feed_token_hash, hash_feed_token(token)
    )
    if identity is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_INVALID_TOKEN_DETAIL,
        )
    return identity


def build_briefing_feed_item(
    row: dict[str, Any], base_url: str, *, digest: bool = False, locale: str | None = None
) -> str | None:
    """把综合简报行渲染为 <item> XML；缺日期/正文的行返回 None。

    digest=False 全文（公开，与 /report 同内容）；digest=True 规则压缩速览
    （注册用户）。description 承载渲染后的 HTML 片段，按 RSS 惯例整体 XML 转义。
    guid 以期号（date）为身份：同一期重生成原地更新内容，阅读器不重复推送。
    link 带期号（/report?date=）：不带时，阅读器里点任何一期都打开当天简报。
    英文版只取英文正文，没有就跳过这一期（不回退中文，见模块说明）；guid 加
    -en，与中文版的同一期区分开。
    """
    copy = _feed_copy(locale)
    date_str = str(row.get("date") or "").strip()
    if copy.english:
        content = str(row.get("content_en") or "").strip()
    else:
        content = str(row.get("content_zh") or row.get("content") or "").strip()
    if not date_str or not content:
        return None
    markdown = condense_briefing_markdown(content) if digest else content
    description = render_briefing_markdown_html(markdown)
    title = (copy.briefing_digest_item_title if digest else copy.briefing_item_title).format(date=date_str)
    guid = f"{'briefing-digest' if digest else 'briefing'}{'-en' if copy.english else ''}:{date_str}"
    link = f"{base_url}/report"
    if _DATE_ONLY_VALUE.fullmatch(date_str):
        link = f"{link}?date={date_str}"
    published = _parse_published_at(str(row.get("created_at") or ""))
    pub_date = f"<pubDate>{format_datetime(published, usegmt=False)}</pubDate>" if published else ""
    return (
        "<item>"
        f"<title>{escape(title)}</title>"
        f"<link>{escape(link)}</link>"
        f'<guid isPermaLink="false">{escape(guid)}</guid>'
        f"{pub_date}"
        f"<description>{escape(description)}</description>"
        "</item>"
    )


def _parse_member_sources(raw: str | None) -> set[str]:
    """解析 ?source=a,b 组合；空 = 全部源，含非法源名抛 400。"""
    if raw is None or not raw.strip() or raw.strip().lower() == "all":
        return set(FEED_SOURCES)
    sources = {part.strip().lower() for part in raw.split(",") if part.strip()}
    unknown = sources - FEED_SOURCES
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"未知 feed 源：{', '.join(sorted(unknown))}",
        )
    return sources or set(FEED_SOURCES)


# 路由顺序锁定：/feeds/member.xml、/feeds/briefing.xml、/feeds/briefing-digest.xml
# 必须先于 /feeds/{source}.xml 注册，否则字面量会被路径参数捕获、
# 落到单源 feed 的 404 分支。
@router.get("/feeds/briefing.xml", include_in_schema=False)
async def feed_briefing(
    request: Request,
    locale: str = Query(default="zh-CN"),
    briefings: BriefingContentRepository = Depends(get_briefing_repository),
):
    """每日综合简报全文公开 feed：免鉴权（与 /report 同口径），近 7 期，边缘可缓存。"""
    copy = _feed_copy(locale)
    rows = await asyncio.to_thread(briefings.list_recent_daily_briefings, _BRIEFING_FEED_LIMIT)
    base_url = _resolve_base_url(request)
    items = [
        item for row in rows if (item := build_briefing_feed_item(row, base_url, locale=locale)) is not None
    ]
    xml = build_rss_xml(
        channel_title=f"{_CHANNEL_TITLE} · {copy.briefing_title}",
        channel_link=f"{base_url}/report",
        self_link=_self_link(base_url, "/api/feeds/briefing.xml", copy),
        channel_description=copy.briefing_description,
        items=items,
        language=copy.language,
    )
    return _xml_response(xml, cache_control=_PUBLIC_CACHE_CONTROL)


@router.get("/feeds/briefing-digest.xml", include_in_schema=False)
async def feed_briefing_digest(
    request: Request,
    token: str = Query(default=""),
    locale: str = Query(default="zh-CN"),
    briefings: BriefingContentRepository = Depends(get_briefing_repository),
    tokens: FeedTokenRepository = Depends(get_feed_token_repository),
):
    """注册用户简报速览 feed：规则压缩版（内容摘要 + 条目标题一览），feed token 鉴权。"""
    await _require_feed_identity(token, tokens)

    copy = _feed_copy(locale)
    rows = await asyncio.to_thread(briefings.list_recent_daily_briefings, _BRIEFING_FEED_LIMIT)
    base_url = _resolve_base_url(request)
    items = [
        item
        for row in rows
        if (item := build_briefing_feed_item(row, base_url, digest=True, locale=locale)) is not None
    ]
    xml = build_rss_xml(
        channel_title=f"{_CHANNEL_TITLE} · {copy.briefing_digest_title}",
        channel_link=f"{base_url}/report",
        self_link=_self_link(base_url, "/api/feeds/briefing-digest.xml", copy),
        channel_description=copy.briefing_digest_description,
        items=items,
        language=copy.language,
    )
    return Response(
        content=xml,
        media_type=_FEED_MEDIA_TYPE,
        headers={
            "Cache-Control": _MEMBER_CACHE_CONTROL,
            "X-Robots-Tag": "noindex",
        },
    )


@router.get("/feeds/member.xml", include_in_schema=False)
async def feed_member(
    request: Request,
    token: str = Query(default=""),
    source: str | None = Query(default=None),
    locale: str = Query(default="zh-CN"),
    documents: DocumentRecentReader = Depends(get_document_repository),
    tokens: FeedTokenRepository = Depends(get_feed_token_repository),
    catalog: ProjectCatalogQueryService = Depends(get_project_catalog_query_service),
):
    """注册用户全文 feed：独立 RSS feed token 鉴权，任意注册用户可用。"""
    await _require_feed_identity(token, tokens)

    copy = _feed_copy(locale)
    sources = _parse_member_sources(source)
    rows = await _collect_rows(
        documents,
        sources,
        window=_MEMBER_FEED_WINDOW,
        limit=_MEMBER_FEED_LIMIT,
        catalog=catalog,
        english=copy.english,
    )
    base_url = _resolve_base_url(request)
    items = [
        item for row in rows if (item := build_feed_item(row, base_url, full=True, locale=locale)) is not None
    ]
    xml = build_rss_xml(
        channel_title=f"{_CHANNEL_TITLE} · {copy.archive_title}",
        channel_link=f"{base_url}/",
        self_link=_self_link(base_url, "/api/feeds/member.xml", copy),
        channel_description=copy.description,
        items=items,
        language=copy.language,
    )
    return Response(
        content=xml,
        media_type=_FEED_MEDIA_TYPE,
        headers={
            "Cache-Control": _MEMBER_CACHE_CONTROL,
            "X-Robots-Tag": "noindex",
        },
    )


@router.get("/feeds/{source}.xml", include_in_schema=False)
async def feed_by_source(
    source: str,
    request: Request,
    locale: str = Query(default="zh-CN"),
    documents: DocumentRecentReader = Depends(get_document_repository),
    catalog: ProjectCatalogQueryService = Depends(get_project_catalog_query_service),
):
    """单源公开 feed；非法源 404。"""
    normalized = source.strip().lower()
    if normalized not in FEED_SOURCES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"未知 feed 源：{normalized}",
        )
    copy = _feed_copy(locale)
    rows = await _collect_rows(
        documents,
        {normalized},
        window=_PUBLIC_FEED_WINDOW,
        limit=_PUBLIC_FEED_LIMIT,
        catalog=catalog,
        english=copy.english,
    )
    base_url = _resolve_base_url(request)
    items = [item for row in rows if (item := build_feed_item(row, base_url, locale=locale)) is not None]
    xml = build_rss_xml(
        channel_title=f"{_CHANNEL_TITLE} · {normalized}",
        channel_link=f"{base_url}/",
        self_link=_self_link(base_url, f"/api/feeds/{normalized}.xml", copy),
        channel_description=copy.description,
        items=items,
        language=copy.language,
    )
    return _xml_response(xml, cache_control=_PUBLIC_CACHE_CONTROL)
