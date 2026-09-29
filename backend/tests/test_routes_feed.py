"""RSS feed 路由与渲染契约测试。

覆盖：
  - 纯函数：item 渲染/跳过规则、回链策略（arxiv 站内、其余原文）、
    全文模式追加译文、公开条目优先中文译文截断（X 源标题亦用译文）、
    脏时间串容错、北京时间日期条目在 UTC 零点前入库取入库时间、
    跨形态时间串按时刻排序、入库截断满额的摘要补省略号、
    arXiv 标题/摘要去 LaTeX 排版、member source 参数解析、
    项目库热榜条目 → feed 行的字段映射；
  - 路由：公开综合/单源 feed 的缓存头与归并排序、非法源 404、
    github 源由站内今日热榜供稿（热榜不可用/为空时回退 documents 池）、
    token feed 的 401/200 门禁（独立 RSS feed token，非 MCP token；任意
    注册用户可用，不再校验会员档位）、noindex/no-store 响应头、
    /feeds/member.xml 不被 {source} 路径参数捕获（路由顺序锁定）；
  - 简报 feed：规则 Markdown→HTML 片段渲染（转义/行内规则/标题 code 去 #）、
    规则压缩速览（摘要节保留、条目正文丢弃、空章节回扫、标题剥 tag）、
    条目回链带期号（/report?date=，脏期号回落裸 /report）、
    /feeds/briefing.xml 公开全文（边缘缓存）、/feeds/briefing-digest.xml
    注册用户 token 门禁与 noindex/no-store、字面量路由均不被 {source} 捕获。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from xml.etree import ElementTree

import pytest
from fastapi.testclient import TestClient

from backend.app.api.dependencies import (
    get_briefing_repository,
    get_document_repository,
    get_feed_token_repository,
    get_project_catalog_query_service,
)
from backend.app.api.routes_feed import (
    _BRIEFING_FEED_LIMIT,
    _INVALID_TOKEN_DETAIL,
    _PUBLIC_DESCRIPTION_TRANSLATION_LIMIT,
    _PUBLIC_TITLE_TRANSLATION_LIMIT,
    _filter_rows_to_window,
    _parse_member_sources,
    _parse_published_at,
    _project_to_feed_row,
    _sort_rows_newest_first,
    build_briefing_feed_item,
    build_feed_item,
    build_rss_xml,
)
from backend.app.main import app
from backend.app.services.briefing.rss_render import (
    condense_briefing_markdown,
    render_briefing_markdown_html,
    sanitize_public_resource_url,
    sanitize_public_text,
)


def _doc(
    doc_id: str,
    *,
    source: str = "arxiv",
    title: str = "标题",
    url: str = "https://example.com/a",
    published_at: str = "2026-08-18T08:00:00+00:00",
    summary: str = "摘要",
    translation_zh: str | None = None,
    tags: str | None = None,
) -> dict:
    return {
        "id": doc_id,
        "source": source,
        "title": title,
        "url": url,
        "published_at": published_at,
        "published_date": "",
        "created_at": "",
        "summary": summary,
        "translation_zh": translation_zh,
        "tags": tags,
    }


def _iso_hours_ago(hours: float) -> str:
    """相对当前时间的 ISO 串：路由测试的时间必须在实时窗口内（窗口过滤按 now 过滤）。"""
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _rfc822(iso: str) -> str:
    """与 build_feed_item 一致的 pubDate 格式化，用于动态日期的断言。"""
    return format_datetime(datetime.fromisoformat(iso), usegmt=False)


# ---------------------------------------------------------------- 纯函数


def test_build_feed_item_arxiv_links_to_internal_read_page() -> None:
    item = build_feed_item(_doc("2508.12345"), "https://aigcnews.cn")
    assert item is not None
    assert "<link>https://aigcnews.cn/papers/2508.12345/read</link>" in item
    assert '<guid isPermaLink="false">arxiv:2508.12345</guid>' in item
    assert "<pubDate>Tue, 18 Aug 2026 08:00:00 +0000</pubDate>" in item
    # 公开条目：摘要 + 转化钩子（引导注册登录后免费订阅全文 RSS）
    assert "<description>摘要\n\n📮 全文 RSS（中文译文 · 完整归档），注册登录即可免费订阅：https://aigcnews.cn/subscriptions</description>" in item


def test_build_feed_item_full_mode_omits_conversion_hook() -> None:
    # token feed 条目不带钩子——订阅用户已转化，不再插引导
    item = build_feed_item(_doc("2508.12345", translation_zh="中文译文"), "https://aigcnews.cn", full=True)
    assert item is not None
    assert "📮" not in item
    assert "中文译文" in item


def test_build_feed_item_non_arxiv_links_to_original_url() -> None:
    item = build_feed_item(_doc("n1", source="news"), "https://aigcnews.cn")
    assert item is not None
    assert "<link>https://example.com/a</link>" in item


def test_build_feed_item_uses_non_x_published_date_when_published_at_missing() -> None:
    row = _doc(
        "n1",
        source="news",
        published_at="",
    )
    row["published_date"] = "2026-08-18"
    item = build_feed_item(row, "https://aigcnews.cn")
    assert item is not None
    assert "<pubDate>Tue, 18 Aug 2026 00:00:00 +0000</pubDate>" in item


def test_build_feed_item_falls_back_to_created_at_when_both_dates_missing() -> None:
    row = _doc("n1", source="news", published_at="")
    row["created_at"] = "2026-08-18T03:00:00+00:00"
    item = build_feed_item(row, "https://aigcnews.cn")
    assert item is not None
    assert "<pubDate>Tue, 18 Aug 2026 03:00:00 +0000</pubDate>" in item


def test_build_feed_item_uses_ingest_time_for_beijing_dated_rows_before_utc_midnight() -> None:
    # DailyHot 按北京时间定日期：北京 05:07 入库的 09-29 条目，日期零点（UTC，
    # 即北京 08:00）晚于入库时刻 → pubDate 取入库时间
    row = _doc("d1", source="dailyhot", published_at="")
    row["published_date"] = "2026-09-29"
    row["created_at"] = "2026-09-28T21:07:10.009719+00:00"
    item = build_feed_item(row, "https://aigcnews.cn")
    assert item is not None
    assert "<pubDate>Mon, 28 Sep 2026 21:07:10 +0000</pubDate>" in item

    # 日期零点之后入库：仍按业务日期零点，行为不变
    row["created_at"] = "2026-09-29T06:00:00+00:00"
    later = build_feed_item(row, "https://aigcnews.cn")
    assert later is not None
    assert "<pubDate>Tue, 29 Sep 2026 00:00:00 +0000</pubDate>" in later

    # 入库远早于业务日期（榜单重上榜仓）：不回退到首次入库时间
    row["created_at"] = "2026-09-22T19:02:10+00:00"
    reappeared = build_feed_item(row, "https://aigcnews.cn")
    assert reappeared is not None
    assert "<pubDate>Tue, 29 Sep 2026 00:00:00 +0000</pubDate>" in reappeared


def test_build_feed_item_escapes_xml_and_renders_categories() -> None:
    item = build_feed_item(_doc("x1", title="A & <B>", tags="LLM, Agent"), "https://aigcnews.cn")
    assert item is not None
    assert "A &amp; &lt;B&gt;" in item
    assert "<category>LLM</category><category>Agent</category>" in item


def test_build_feed_item_parses_json_array_tags() -> None:
    # documents.tags 的真实存储形态是 JSON 数组串（与 authors 同约定）；
    # 逗号分隔仅为脏值回落，JSON 形态不得渲染出引号/括号碎片。
    item = build_feed_item(_doc("x1", tags='["x", "daily", "MiniMax_AI"]'), "https://aigcnews.cn")
    assert item is not None
    assert "<category>x</category><category>daily</category><category>MiniMax_AI</category>" in item
    assert '["' not in item


def test_build_feed_item_skips_rows_missing_id_title_or_link() -> None:
    assert build_feed_item(_doc("", title="t"), "https://aigcnews.cn") is None
    assert build_feed_item(_doc("i", title=""), "https://aigcnews.cn") is None
    assert build_feed_item(_doc("i", source="news", url=""), "https://aigcnews.cn") is None


def test_build_feed_item_omits_pubdate_on_dirty_timestamp() -> None:
    item = build_feed_item(_doc("i", published_at="not-a-date"), "https://aigcnews.cn")
    assert item is not None
    assert "<pubDate>" not in item


def test_build_feed_item_full_mode_appends_translation_once() -> None:
    row = _doc("i", translation_zh="中文译文")
    full = build_feed_item(row, "https://aigcnews.cn", full=True)
    assert full is not None and "摘要\n\n中文译文" in full
    public = build_feed_item(row, "https://aigcnews.cn", full=False)
    # 防泄漏口径：译文正文不得以「摘要\n\n译文」的追加形态出现在公开条目；
    # 钩子营销文案里提到"中文译文"四字不算泄漏
    assert public is not None and "摘要\n\n中文译文" not in public
    assert "📮" in public
    # 译文与摘要相同（未翻译内容回填）时不重复
    same = build_feed_item(_doc("i", translation_zh="摘要"), "https://aigcnews.cn", full=True)
    assert same is not None and same.count("摘要") == 1


def _item_section(item: str, tag: str) -> str:
    return item.split(f"<{tag}>", 1)[1].split(f"</{tag}>", 1)[0]


def test_public_feed_item_description_prefers_truncated_translation() -> None:
    # 公开条目面向中文读者：有译文时 description 为译文截断（200 上限），
    # 原英文摘要不进公开 description；无译文回退原摘要
    row = _doc("a1", summary="English summary", translation_zh="模型" * 150)
    item = build_feed_item(row, "https://aigcnews.cn")
    assert item is not None
    body = _item_section(item, "description").split("\n\n📮", 1)[0]
    assert body.endswith("…")
    assert len(body) <= _PUBLIC_DESCRIPTION_TRANSLATION_LIMIT + 1
    assert "English summary" not in body

    no_translation = build_feed_item(_doc("a2", summary="English summary"), "https://aigcnews.cn")
    assert no_translation is not None
    assert _item_section(no_translation, "description").startswith("English summary\n\n📮")


def test_public_feed_item_title_uses_translation_only_for_x_source() -> None:
    # X 源「标题」即推文原文（英文为主）：有译文时标题换成译文截断；
    # 其余源保持原 title（榜单/媒体源标题本身面向中文读者或为仓库名）
    x_item = build_feed_item(
        _doc("x1", source="x", title="Original English tweet", translation_zh="推文的中文译文"),
        "https://aigcnews.cn",
    )
    assert x_item is not None
    assert _item_section(x_item, "title") == "推文的中文译文"

    arxiv_item = build_feed_item(
        _doc("a1", title="English paper title", translation_zh="论文中文译文"),
        "https://aigcnews.cn",
    )
    assert arxiv_item is not None
    assert _item_section(arxiv_item, "title") == "English paper title"

    # X 源无译文：回退原标题
    bare_x = build_feed_item(_doc("x2", source="x", title="Untranslated tweet"), "https://aigcnews.cn")
    assert bare_x is not None
    assert _item_section(bare_x, "title") == "Untranslated tweet"


def test_public_feed_item_x_title_truncates_long_translation() -> None:
    row = _doc("x1", source="x", title="tweet", translation_zh="推" * 120)
    item = build_feed_item(row, "https://aigcnews.cn")
    assert item is not None
    title = _item_section(item, "title")
    assert title.endswith("…")
    assert len(title) <= _PUBLIC_TITLE_TRANSLATION_LIMIT + 1


def test_member_feed_item_keeps_original_title_and_full_translation() -> None:
    # token feed 条目不截断、不换标题：原标题 + 完整译文全文
    long_translation = "译" * 300
    row = _doc(
        "x1", source="x", title="Original tweet",
        summary="English summary", translation_zh=long_translation,
    )
    item = build_feed_item(row, "https://aigcnews.cn", full=True)
    assert item is not None
    assert _item_section(item, "title") == "Original tweet"
    assert long_translation in item
    assert "…" not in item


def test_feed_item_description_does_not_repeat_the_title() -> None:
    # HN 的摘要就是标题：公开条目正文只剩钩子，token 条目正文为空
    hn = _doc("hn1", source="hackernews", title="Show HN: A tool", summary="Show HN:  A tool")
    public = build_feed_item(hn, "https://aigcnews.cn")
    assert public is not None
    assert _item_section(public, "description").startswith("📮")
    full = build_feed_item(hn, "https://aigcnews.cn", full=True)
    assert full is not None and _item_section(full, "description") == ""

    # X 短推文：译文标题与译文摘要截断后同文 → 正文不再重复
    tweet = _doc("x1", source="x", title="Short tweet", summary="Short tweet", translation_zh="简短推文")
    public_x = build_feed_item(tweet, "https://aigcnews.cn")
    assert public_x is not None
    assert _item_section(public_x, "title") == "简短推文"
    assert _item_section(public_x, "description").startswith("📮")
    # token 条目：原文标题不在正文里再出现一遍，只追加完整译文
    full_x = build_feed_item(tweet, "https://aigcnews.cn", full=True)
    assert full_x is not None and _item_section(full_x, "description") == "简短推文"

    # 与标题不同的摘要照常输出
    news = build_feed_item(_doc("n1", source="news", title="Headline", summary="Body"), "https://aigcnews.cn")
    assert news is not None and _item_section(news, "description").startswith("Body\n\n📮")


def test_bare_url_tweet_title_uses_link_card_title() -> None:
    row = _doc("x1", source="x", title="https://opencode.ai/data", summary="https://opencode.ai/data")
    row["link_card"] = {"url": "https://opencode.ai/data", "title": "AI Model Usage Rankings | OpenCode Data"}
    for full in (False, True):
        item = build_feed_item(row, "https://aigcnews.cn", full=full)
        assert item is not None
        assert _item_section(item, "title") == "AI Model Usage Rankings | OpenCode Data"

    # 无卡片标题：保持原 URL 标题（不凭空编标题）
    no_card = _doc("x2", source="x", title="https://x.com/i/article/2104641136346161153")
    item = build_feed_item(no_card, "https://aigcnews.cn")
    assert item is not None
    assert _item_section(item, "title") == "https://x.com/i/article/2104641136346161153"


def _description_body(item: str | None) -> str:
    assert item is not None
    return _item_section(item, "description").split("\n\n📮", 1)[0]


def test_feed_item_marks_summaries_cut_at_storage_limit() -> None:
    # 非 X 源摘要入库即硬截断到 500 字符、不补省略号：满额摘要补「…」，
    # 英文末尾半个单词退回上一个空白，句末标点让位给省略号
    english = "We study agents. " * 29 + "outperf"
    assert len(english) == 500
    row = _doc("2609.00001", title="Paper", summary=english)
    expected = ("We study agents. " * 29).rstrip(" .") + "…"
    assert _description_body(build_feed_item(row, "https://aigcnews.cn")) == expected
    assert _description_body(build_feed_item(row, "https://aigcnews.cn", full=True)) == expected

    chinese = "热点新闻，" * 100
    hot = _doc("d1", source="dailyhot", title="热榜", summary=chinese)
    assert _description_body(build_feed_item(hot, "https://aigcnews.cn")) == chinese[:-1] + "…"

    # 末段含中文：不按空白回退，免得吞掉整句
    mixed = "新 " + "中文" * 247 + "GPT4"
    assert len(mixed) == 500
    news = _doc("n1", source="news", title="Headline", summary=mixed)
    assert _description_body(build_feed_item(news, "https://aigcnews.cn")) == mixed + "…"

    # 截断点恰在空白处：末词完整，不回退
    boundary = "We study agents. " * 29 + "roles, "
    assert len(boundary) == 500
    row = _doc("2609.00004", title="Paper", summary=boundary)
    assert _description_body(build_feed_item(row, "https://aigcnews.cn")) == "We study agents. " * 29 + "roles…"

    # 末尾半截链接整段去掉，不留给阅读器自动链到错误地址
    url_tail = "原文：https://mp.weixin.qq.com/s/6avFCSo"
    linked = "新" * (500 - len(url_tail)) + url_tail
    hot = _doc("d2", source="dailyhot", title="热榜", summary=linked)
    assert _description_body(build_feed_item(hot, "https://aigcnews.cn")) == "新" * (500 - len(url_tail)) + "原文…"

    # 已自带省略号：不再叠加
    ellipsis = "热" * 499 + "…"
    hot = _doc("d3", source="dailyhot", title="热榜", summary=ellipsis)
    assert _description_body(build_feed_item(hot, "https://aigcnews.cn")) == ellipsis


def test_feed_item_keeps_summaries_below_limit_and_x_summaries_as_is() -> None:
    short = "We study agents. " * 29 + "outper"
    assert len(short) == 499
    item = build_feed_item(_doc("2609.00002", title="Paper", summary=short), "https://aigcnews.cn")
    assert _description_body(item) == short

    # X 摘要入库不截断，恰好 500 字符也不补省略号
    tweet = "tweet body " * 45 + "and more."
    tweet = tweet[:500]
    assert len(tweet) == 500
    x_item = build_feed_item(_doc("x1", source="x", title="Tweet", summary=tweet), "https://aigcnews.cn", full=True)
    assert x_item is not None
    assert _item_section(x_item, "description") == tweet.strip()


def test_arxiv_feed_item_strips_latex_markup_from_title_and_summary() -> None:
    row = _doc(
        "2609.00003",
        title=r"Scaling \textbf{S\textsuperscript{3}Gym} or a \$15 Frontier Run",
        summary=(
            r"We propose \emph{COBRA}, with pass@$k$ gains of $4$-$16\times$ for \$1.5M "
            r"under a tokens-per-parameter ratio (\(\mathrm{TPP}\)) and ``one-size-fits-all'' routing; "
            r"the $p(y \mid x)$ objective and \method{} stay as written, over ~45.6 million samples."
        ),
    )
    item = build_feed_item(row, "https://aigcnews.cn", full=True)
    assert item is not None
    assert _item_section(item, "title") == "Scaling S3Gym or a $15 Frontier Run"
    assert _item_section(item, "description") == (
        "We propose COBRA, with pass@k gains of 4-$16\\times$ for $1.5M "
        "under a tokens-per-parameter ratio (TPP) and “one-size-fits-all” routing; "
        "the $p(y \\mid x)$ objective and \\method{} stay as written, over ~45.6 million samples."
    )
    public = build_feed_item(row, "https://aigcnews.cn")
    assert public is not None
    assert _item_section(public, "title") == "Scaling S3Gym or a $15 Frontier Run"

    # 其他源的 $ 多是金额、反斜杠非 LaTeX：原样保留
    news = _doc("n1", source="news", title=r"Deal at \$5", summary=r"Costs $5 and $10, \emph{not} markup")
    news_item = build_feed_item(news, "https://aigcnews.cn", full=True)
    assert news_item is not None
    assert _item_section(news_item, "title") == r"Deal at \$5"
    assert _item_section(news_item, "description") == r"Costs $5 and $10, \emph{not} markup"


def test_parse_published_at_tolerates_dirty_and_naive_values() -> None:
    assert _parse_published_at("2026-08-18T08:00:00+00:00") is not None
    assert _parse_published_at("2026-08-18 08:00:00") is not None  # naive 按 UTC
    assert _parse_published_at("garbage") is None
    assert _parse_published_at(None) is None


def test_parse_member_sources_defaults_all_and_rejects_unknown() -> None:
    all_sources = _parse_member_sources(None)
    assert "arxiv" in all_sources and "x" in all_sources
    assert _parse_member_sources(" all ") == all_sources
    assert _parse_member_sources("arxiv, github") == {"arxiv", "github"}
    with pytest.raises(Exception) as exc_info:
        _parse_member_sources("arxiv,bogus")
    assert getattr(exc_info.value, "status_code") == 400


def _hot_item(full_name: str = "ifixai-ai/iFixAi", **overrides) -> dict:
    """项目库「今日暴涨」热榜条目的典型形态（与 /api/projects?scope=today 同构）。"""
    item = {
        "full_name": full_name,
        "url": f"https://github.com/{full_name}",
        "description": "English description",
        "description_zh": "中文简介",
        "stars": 12345,
        "daily_star_growth": 843,
        "captured_at": "2026-08-18T06:48:47.360083+00:00",
        "daily_growth_date": "2026-08-18",
        "snapshot_date": "2026-08-18",
        "language": "Python",
        "topics": ["llm", "agent"],
    }
    item.update(overrides)
    return item


def test_project_to_feed_row_maps_hot_board_item() -> None:
    row = _project_to_feed_row(_hot_item())
    assert row["id"] == "ifixai-ai/iFixAi"
    assert row["source"] == "github"
    assert row["title"] == "ifixai-ai/iFixAi"
    assert row["url"] == "https://github.com/ifixai-ai/iFixAi"
    assert row["published_at"] == "2026-08-18T06:48:47.360083+00:00"
    # 中文简介优先，附 star 总量与今日增量
    assert row["summary"] == "中文简介\n\n⭐ 12,345 · 今日 +843"
    assert json.loads(row["tags"]) == ["Python", "llm", "agent"]
    # 渲染为合法 feed item（pubDate 取 captured_at）
    item = build_feed_item(row, "https://aigcnews.cn")
    assert item is not None
    assert "<pubDate>Tue, 18 Aug 2026 06:48:47 +0000</pubDate>" in item


def test_project_to_feed_row_tolerates_missing_optional_fields() -> None:
    row = _project_to_feed_row(_hot_item(description_zh=None, daily_star_growth=None, language="", topics=None, url=""))
    # 无中文简介回退英文；无增量不渲染「今日 +」；url 缺失按 full_name 拼 GitHub 链接
    assert row["summary"] == "English description\n\n⭐ 12,345"
    assert row["url"] == "https://github.com/ifixai-ai/iFixAi"
    assert json.loads(row["tags"]) == []
    assert _project_to_feed_row(_hot_item(full_name=""))["id"] == ""


def test_build_rss_xml_channel_structure() -> None:
    xml = build_rss_xml(
        channel_title="AIGC NEWS",
        channel_link="https://aigcnews.cn/api/feed.xml",
        channel_description="描述 & 更多",
        items=["<item><title>t</title></item>"],
    )
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert '<rss version="2.0"' in xml
    assert "描述 &amp; 更多" in xml
    assert 'rel="self" type="application/rss+xml"' in xml
    assert xml.rstrip().endswith("</rss>")


# ---------------------------------------------------------------- 路由


def _catalog(items: list[dict] | None = None, *, error: Exception | None = None) -> MagicMock:
    """项目目录查询服务桩：默认空热榜（触发 documents 池兜底，等价旧语义）。"""
    catalog = MagicMock()
    if error is not None:
        catalog.list_public_projects = AsyncMock(side_effect=error)
    else:
        catalog.list_public_projects = AsyncMock(return_value=SimpleNamespace(result={"items": items or []}))
    return catalog


def _client(
    *,
    documents: MagicMock,
    tokens: MagicMock | None = None,
    catalog: MagicMock | None = None,
    briefings: MagicMock | None = None,
) -> TestClient:
    overrides = {
        get_document_repository: lambda: documents,
        # github 源默认走热榜供稿，任何命中 github 的路由都必须隔离真实项目库
        get_project_catalog_query_service: lambda: catalog if catalog is not None else _catalog(),
    }
    if tokens is not None:
        overrides[get_feed_token_repository] = lambda: tokens
    if briefings is not None:
        overrides[get_briefing_repository] = lambda: briefings
    app.dependency_overrides.update(overrides)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _cleanup_overrides():
    yield
    app.dependency_overrides.clear()


def test_rss_window_filters_old_published_date_even_when_recently_ingested() -> None:
    now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    old = _doc("old", source="news", published_at="")
    old["published_date"] = "2026-08-20"
    old["created_at"] = "2026-08-25T11:59:00+00:00"
    recent = _doc("recent", source="news", published_at="2026-08-25T11:00:00+00:00")
    # published_at 脏串时回退 created_at；最终 pubDate 落在窗口内 → 保留
    fallback = _doc("fallback", source="news", published_at="not-a-date")
    fallback["created_at"] = "2026-08-25T11:58:00+00:00"
    # 三个时间字段全无效 → 没有最终 pubDate 可言 → 丢弃
    dateless = _doc("dateless", source="news", published_at="not-a-date")

    filtered = _filter_rows_to_window(
        [old, recent, fallback, dateless], window=timedelta(hours=48), now=now
    )

    assert [row["id"] for row in filtered] == ["recent", "fallback"]


def test_rss_window_keeps_beijing_dated_rows_ingested_before_utc_midnight() -> None:
    # 北京时间 06:00：北京日期 09-29 的条目已入库。按日期 UTC 零点（北京 08:00）
    # 会被当作未来条目过滤掉，要到北京 08:00 才出现在 feed
    now = datetime(2026, 9, 28, 22, 0, tzinfo=timezone.utc)
    early = _doc("early", source="dailyhot", published_at="")
    early["published_date"] = "2026-09-29"
    early["created_at"] = "2026-09-28T21:07:10+00:00"

    filtered = _filter_rows_to_window([early], window=timedelta(hours=48), now=now)

    assert [row["id"] for row in filtered] == ["early"]


def test_sort_rows_orders_mixed_time_formats_by_instant() -> None:
    # 带 +08:00 偏移的串词法上大于同日 UTC 串，裸日期词法上小于同日任何时间串；
    # 排序须按解析后的时刻。同一时刻的行保持输入相对序（库内已按分数排好）。
    east = _doc("east", source="news", published_at="2026-09-29T07:00:00+08:00")
    utc = _doc("utc", source="x", published_at="2026-09-29T01:00:00+00:00")
    first_hn = _doc("hn-1", source="hackernews", published_at="")
    first_hn["published_date"] = "2026-09-29"
    second_hn = _doc("hn-2", source="hackernews", published_at="")
    second_hn["published_date"] = "2026-09-29"

    ordered = _sort_rows_newest_first([east, first_hn, second_hn, utc])

    assert [row["id"] for row in ordered] == ["utc", "hn-1", "hn-2", "east"]


def test_public_feed_merges_sources_newest_first_with_cache_headers() -> None:
    documents = MagicMock()

    def fake_list(source: str, *, since_iso: str, until_iso=None, limit: int = 500):
        if source == "arxiv":
            return [_doc("a-old", published_at=_iso_hours_ago(47))]
        if source == "news":
            return [_doc("n-new", source="news", published_at=_iso_hours_ago(1))]
        return []

    documents.list_recent_by_source.side_effect = fake_list
    client = _client(documents=documents)

    response = client.get("/api/feed.xml")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/rss+xml")
    # 必须显式带 charset=utf-8：GBK 区域环境（中文 Windows 浏览器）无 charset 会花屏
    assert "charset=utf-8" in response.headers["content-type"]
    assert response.headers["cache-control"] == "public, max-age=900"
    body = response.text
    # 全局按发布时间归并：news 的新条目必须排在 arxiv 旧条目之前
    assert body.index("n-new") < body.index("a-old")


def test_public_feed_by_source_and_unknown_source_404() -> None:
    documents = MagicMock()
    documents.list_recent_by_source.return_value = [_doc("a1")]
    client = _client(documents=documents)

    response = client.get("/api/feeds/arxiv.xml")
    assert response.status_code == 200
    assert "AIGC NEWS · arxiv" in response.text
    documents.list_recent_by_source.assert_called_once()
    assert documents.list_recent_by_source.call_args.args[0] == "arxiv"

    assert client.get("/api/feeds/bogus.xml").status_code == 404


# -------------------------------------------------- github 源：站内今日热榜供稿


def test_github_feed_serves_today_hot_board_instead_of_documents_pool() -> None:
    documents = MagicMock()
    captured = _iso_hours_ago(2)
    catalog = _catalog([_hot_item(captured_at=captured)])
    client = _client(documents=documents, catalog=catalog)

    response = client.get("/api/feeds/github.xml")

    assert response.status_code == 200
    body = response.text
    assert "ifixai-ai/iFixAi" in body
    assert "中文简介" in body and "今日 +843" in body
    assert f"<pubDate>{_rfc822(captured)}</pubDate>" in body
    # 不再镜像 trending 抓取的 documents 池
    documents.list_recent_by_source.assert_not_called()
    # 与站内 /projects?scope=today 同口径：scope=today + sort=None（服务端强制 hot）
    catalog.list_public_projects.assert_awaited_once()
    kwargs = catalog.list_public_projects.await_args.kwargs
    assert kwargs["scope"] == "today"
    assert kwargs["sort"] is None
    assert kwargs["page_size"] == 50


def test_github_feed_preserves_hot_rank_despite_mixed_capture_batches() -> None:
    # 热榜条目 captured_at 分属不同时次的快照刷新；feed 必须保持 hot 名次，
    # 不能按捕获时间重排（pubDate 统一归一到最新快照时间）。
    documents = MagicMock()
    latest = _iso_hours_ago(2)
    catalog = _catalog(
        [
            _hot_item("rank1/newly-recaptured", captured_at=latest),
            _hot_item("rank2/earlier-batch", captured_at=_iso_hours_ago(26)),
            _hot_item("rank3/mid-batch", captured_at=_iso_hours_ago(5)),
        ]
    )
    client = _client(documents=documents, catalog=catalog)

    response = client.get("/api/feeds/github.xml")

    assert response.status_code == 200
    body = response.text
    assert body.index("rank1/newly-recaptured") < body.index("rank2/earlier-batch")
    assert body.index("rank2/earlier-batch") < body.index("rank3/mid-batch")
    # 三条 pubDate 均归一到最新快照时间
    assert body.count(f"<pubDate>{_rfc822(latest)}</pubDate>") == 3


def test_github_feed_falls_back_to_documents_pool_when_hot_board_unavailable() -> None:
    for catalog in (_catalog(error=RuntimeError("db down")), _catalog([])):
        documents = MagicMock()
        documents.list_recent_by_source.return_value = [
            _doc(
                "gh-trending",
                source="github",
                url="https://github.com/a/b",
                published_at=_iso_hours_ago(3),
            )
        ]
        client = _client(documents=documents, catalog=catalog)

        response = client.get("/api/feeds/github.xml")

        # 热榜查询失败或为空都回退 documents 池，feed 不断更
        assert response.status_code == 200
        assert "gh-trending" in response.text
        documents.list_recent_by_source.assert_called_once()
        assert documents.list_recent_by_source.call_args.args[0] == "github"


def test_public_feed_merges_hot_board_items_with_other_sources() -> None:
    documents = MagicMock()

    def fake_list(source: str, *, since_iso: str, until_iso=None, limit: int = 500):
        if source == "news":
            return [_doc("n-old", source="news", published_at=_iso_hours_ago(24))]
        return []

    documents.list_recent_by_source.side_effect = fake_list
    catalog = _catalog([_hot_item(captured_at=_iso_hours_ago(1))])
    client = _client(documents=documents, catalog=catalog)

    response = client.get("/api/feed.xml")

    assert response.status_code == 200
    body = response.text
    # 热榜条目（captured_at 更近）参与全局归并排序，排在隔日 news 之前
    assert body.index("ifixai-ai/iFixAi") < body.index("n-old")
    # github 不走 documents 池，其余源不受影响
    queried = {call.args[0] for call in documents.list_recent_by_source.call_args_list}
    assert "github" not in queried and "news" in queried


def test_public_combined_feed_caps_each_source_so_hot_board_cannot_crowd_out() -> None:
    # 线上形态：热榜 50 条整榜共用最新快照时间（恒排最前），X 一天几十条，
    # HN 只有日期（归并时排在当天时间戳条目之后）。不限额时 github+X
    # 占满 100 条，HN 整源缺席。
    documents = MagicMock()
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()

    def fake_list(source: str, *, since_iso: str, until_iso=None, limit: int = 500):
        if source == "x":
            return [
                _doc(f"x{i}", source="x", url=f"https://x.com/a/status/{i}", published_at=_iso_hours_ago(0.5 + i * 0.1))
                for i in range(60)
            ]
        if source == "hackernews":
            hn = _doc("hn-story", source="hackernews", url="https://news.ycombinator.com/item?id=1", published_at="")
            hn["published_date"] = yesterday
            return [hn]
        return []

    documents.list_recent_by_source.side_effect = fake_list
    latest = _iso_hours_ago(0.1)
    catalog = _catalog([_hot_item(f"hot/repo{i}", captured_at=latest) for i in range(50)])
    client = _client(documents=documents, catalog=catalog)

    root = ElementTree.fromstring(client.get("/api/feed.xml").content)
    guids = [guid.text or "" for guid in root.iter("guid")]

    assert sum(guid.startswith("github:") for guid in guids) == 15
    assert sum(guid.startswith("x:") for guid in guids) == 15
    assert "hackernews:hn-story" in guids
    # 限额在归并序上取每源最新：热榜保留 hot 名次头部
    assert [guid for guid in guids if guid.startswith("github:")][:2] == ["github:hot/repo0", "github:hot/repo1"]

    # 单源 feed 不受综合限额影响：github 仍是整榜 50 条
    single = ElementTree.fromstring(client.get("/api/feeds/github.xml").content)
    assert len(single.findall("./channel/item")) == 50


def test_member_feed_uses_hot_board_for_github_source() -> None:
    documents = MagicMock()
    documents.list_recent_by_source.return_value = []
    tokens = MagicMock()
    tokens.get_user_by_feed_token_hash.return_value = {
        "user_id": 7,
        "membership_tier": "member",
    }
    catalog = _catalog([_hot_item(captured_at=_iso_hours_ago(2))])
    client = _client(documents=documents, tokens=tokens, catalog=catalog)

    response = client.get("/api/feeds/member.xml?token=ok&source=github,arxiv")

    assert response.status_code == 200
    assert "ifixai-ai/iFixAi" in response.text
    # github 由热榜供稿，documents 池只查 arxiv
    queried = {call.args[0] for call in documents.list_recent_by_source.call_args_list}
    assert queried == {"arxiv"}


def test_member_feed_requires_token_and_is_not_captured_by_source_route() -> None:
    documents = MagicMock()
    client = _client(documents=documents, tokens=MagicMock())
    response = client.get("/api/feeds/member.xml")
    # 路由顺序锁定：命中 token feed 路由的 401，而非 {source} 捕获后的 404
    assert response.status_code == 401
    assert response.json()["detail"] == _INVALID_TOKEN_DETAIL


def test_member_feed_rejects_invalid_token_but_allows_free_tier() -> None:
    documents = MagicMock()
    documents.list_recent_by_source.return_value = []
    tokens = MagicMock()
    tokens.get_user_by_feed_token_hash.return_value = None
    client = _client(documents=documents, tokens=tokens)
    assert client.get("/api/feeds/member.xml?token=bad").status_code == 401

    # 简报/全文 RSS 已降级为注册用户免费权益：免费档有效 token 直接放行
    tokens.get_user_by_feed_token_hash.return_value = {
        "user_id": 7,
        "membership_tier": "free",
    }
    response = client.get("/api/feeds/member.xml?token=ok")
    assert response.status_code == 200


def test_member_feed_returns_full_content_for_member() -> None:
    documents = MagicMock()
    documents.list_recent_by_source.return_value = [
        _doc("a1", translation_zh="中文译文", published_at=_iso_hours_ago(3))
    ]
    tokens = MagicMock()
    tokens.get_user_by_feed_token_hash.return_value = {
        "user_id": 7,
        "membership_tier": "member",
    }
    client = _client(documents=documents, tokens=tokens)

    response = client.get("/api/feeds/member.xml?token=ok")
    assert response.status_code == 200
    assert "中文译文" in response.text
    # token feed 不带获客钩子
    assert "📮" not in response.text
    assert "charset=utf-8" in response.headers["content-type"]
    assert response.headers["x-robots-tag"] == "noindex"
    assert response.headers["cache-control"] == "private, no-store"


def test_member_feed_source_combination_limits_queried_sources() -> None:
    documents = MagicMock()
    documents.list_recent_by_source.return_value = []
    tokens = MagicMock()
    tokens.get_user_by_feed_token_hash.return_value = {
        "user_id": 7,
        "membership_tier": "member",
    }
    client = _client(documents=documents, tokens=tokens)

    response = client.get("/api/feeds/member.xml?token=ok&source=arxiv,github")
    assert response.status_code == 200
    queried = {call.args[0] for call in documents.list_recent_by_source.call_args_list}
    assert queried == {"arxiv", "github"}

    assert client.get("/api/feeds/member.xml?token=ok&source=arxiv,bogus").status_code == 400


# ---------------------------------------------------------------- 简报 feed

_BRIEFING_MD = """# 今日 AIGC 技术资讯综合报｜2026年8月27日 `#news` `#LLM`

## 今日内容摘要 `#news`

本报梳理今日两条信息。

产业端继续升温。

## 技术亮点 `#arxiv`

**趋势总结与洞察：** 章节导言不应进入速览。

### 1. `ModelX`：新架构 `#arxiv`

**话题概述：** 条目正文不应进入速览。

**核心观点：** 同上。

## 工程动态 `#github`

### 1. `a/b`：工具更新 `#github`

**话题概述：** 条目正文。

## 日期与数据来源 `#news`

- 来源一：[https://example.com/a](https://example.com/a)
"""

_CONDENSED_BRIEFING_MD = """# 今日 AIGC 技术资讯综合报｜2026年8月27日
## 今日内容摘要
本报梳理今日两条信息。
产业端继续升温。
## 技术亮点
### 1. `ModelX`：新架构
## 工程动态
### 1. `a/b`：工具更新"""


def _briefing_row(
    date: str = "2026-08-27",
    content: str = _BRIEFING_MD,
    created_at: str = "2026-08-27T00:05:00+00:00",
) -> dict:
    return {
        "id": 1,
        "date": date,
        "created_at": created_at,
        "content_zh": content,
        "content_en": "",
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://example.com/a?x=1#part", "https://example.com/a?x=1#part"),
        ("/api/media/briefing.png?x=1#hero", "/api/media/briefing.png?x=1#hero"),
        ("file:///home/kaixxrua/secret.png", None),
        ("javascript:alert(1)", None),
        ("data:text/plain,secret", None),
        ("ftp://example.com/a", None),
        ("//example.com/a", None),
        ("/home/kaixxrua/secret.png", None),
        ("storage/secret.png", None),
        ("C:\\\\Users\\\\secret.png", None),
        ("\\\\server\\share\\secret.png", None),
        ("/api/media/../secret.png", None),
        ("https://user:pass@example.com/a", None),
    ],
)
def test_sanitize_public_resource_url_allowlists_public_resources(
    value: str, expected: str | None
) -> None:
    assert sanitize_public_resource_url(value) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("图片 ![x](/home/kaixxrua/secret.png) 链接 [secret](file:///tmp/a)", "图片  链接 secret"),
        ("安全 ![x](https://example.com/a.png) [a](/api/media/a.png)", "安全 ![x](https://example.com/a.png) [a](/api/media/a.png)"),
        ("裸路径 /home/kaixxrua/a.png storage/b.png file://tmp/a javascript:alert(1)", "裸路径    "),
    ],
)
def test_sanitize_public_text_removes_unsafe_markdown_resources(
    source: str, expected: str
) -> None:
    assert sanitize_public_text(source) == expected


def test_build_feed_item_skips_unsafe_required_external_link() -> None:
    row = _doc("unsafe", source="news", url="file:///home/kaixxrua/private.png")
    assert build_feed_item(row, "https://aigcnews.cn") is None


def test_build_feed_item_sanitizes_unsafe_description_content() -> None:
    row = _doc(
        "unsafe-summary",
        source="news",
        summary="摘要 /home/kaixxrua/private.png [私密](file:///tmp/private.png)",
    )
    item = build_feed_item(row, "https://aigcnews.cn")
    assert item is not None
    assert "/home/" not in item
    assert "file://" not in item
    assert "私密" in item


def test_render_briefing_markdown_html_drops_unsafe_images_and_links() -> None:
    html = render_briefing_markdown_html(
        "![泄漏](/home/kaixxrua/secret.png) [私密](javascript:alert(1)) "
        "![安全](https://example.com/a.png) [媒体](/api/media/a.png)"
    )
    assert "secret.png" not in html
    assert "javascript:" not in html
    assert "泄漏" not in html
    assert "私密" in html
    assert '<img src="https://example.com/a.png" alt="安全" />' in html
    assert '<a href="/api/media/a.png">媒体</a>' in html


def test_build_briefing_feed_item_sanitizes_historical_dirty_content() -> None:
    row = _briefing_row(
        content=(
            "# 简报\\n"
            "泄漏 /home/kaixxrua/16e94576-3c54-4a46-8f1c-cdf75f3a419d.png\\n"
            "[私密](file:///tmp/private.png)"
        )
    )
    item = build_briefing_feed_item(row, "https://aigcnews.cn")
    assert item is not None
    assert "/home/" not in item
    assert "file://" not in item
    assert "16e94576" not in item


def test_briefing_xml_is_well_formed_and_contains_no_unsafe_resource_tokens() -> None:
    rows = [
        _briefing_row(
            content="# 简报\\n![泄漏](/home/kaixxrua/secret.png)\\n安全 [媒体](https://example.com/a)"
        )
    ]
    item = build_briefing_feed_item(rows[0], "https://aigcnews.cn")
    assert item is not None
    xml = build_rss_xml(
        channel_title="AIGC NEWS · 每日简报",
        channel_link="https://aigcnews.cn/report",
        channel_description="每日简报",
        items=[item],
    )
    ElementTree.fromstring(xml)
    for token in ("/home/", "file://", "javascript:", "data:", "ftp://", "storage/"):
        assert token not in xml


def test_render_briefing_markdown_html_covers_headings_paragraphs_and_lists() -> None:
    html = render_briefing_markdown_html(_BRIEFING_MD)
    assert "<h1>今日 AIGC 技术资讯综合报｜2026年8月27日" in html
    assert "<h2>今日内容摘要" in html
    assert "<h3>1. <code>ModelX</code>：新架构" in html
    assert "<p>本报梳理今日两条信息。</p>" in html
    assert "<strong>话题概述：</strong>" in html
    assert '<li>来源一：<a href="https://example.com/a">https://example.com/a</a></li>' in html


def test_render_briefing_markdown_html_escapes_raw_html_and_link_quotes() -> None:
    html = render_briefing_markdown_html("正文 <script>alert(1)</script> 与 [a](https://x.com?a=1&b=2)")
    assert "&lt;script&gt;" in html
    assert "<script>" not in html
    # 链接 URL 里的 & 以 HTML 实体进入 href，阅读器解码后仍是合法 URL
    assert '<a href="https://x.com?a=1&amp;b=2">a</a>' in html


def test_render_briefing_markdown_html_strips_tag_hash_only_in_headings() -> None:
    html = render_briefing_markdown_html("## 标题 `#news`\n正文代码 `#define` 保留井号")
    h2_line = next(line for line in html.split("\n") if line.startswith("<h2"))
    p_line = next(line for line in html.split("\n") if line.startswith("<p"))
    # 标题标签不显示前导 #（与前端/邮件渲染约定一致）；正文代码不受影响
    assert "<code>news</code>" in h2_line
    assert "<code>#define</code>" in p_line


def test_condense_briefing_markdown_keeps_abstract_and_item_titles_only() -> None:
    digest = condense_briefing_markdown(_BRIEFING_MD)
    assert digest == _CONDENSED_BRIEFING_MD


def test_condense_briefing_markdown_drops_section_intros_and_metadata_section() -> None:
    digest = condense_briefing_markdown(_BRIEFING_MD)
    assert "趋势总结与洞察" not in digest
    assert "话题概述" not in digest
    # 尾部「日期与数据来源」正文被丢后成为空章节，回扫时整节移除
    assert "日期与数据来源" not in digest
    assert "https://example.com/a" not in digest
    # 标题里的 `#tag` 行内代码全部剥掉
    assert "`#" not in digest


def test_condense_briefing_markdown_single_section_passthrough() -> None:
    # 只有一个章节的纯散文简报退化为原文——速览不删信息
    content = "# 标题 `#news`\n## 唯一章节\n正文一\n正文二"
    assert condense_briefing_markdown(content) == "# 标题\n## 唯一章节\n正文一\n正文二"


def test_build_briefing_feed_item_full_mode() -> None:
    item = build_briefing_feed_item(_briefing_row(), "https://aigcnews.cn")
    assert item is not None
    assert "<title>2026-08-27 每日 AIGC 简报</title>" in item
    # 回链带期号：旧一期不再落到当天简报（/report 按 ?date= 选期）
    assert "<link>https://aigcnews.cn/report?date=2026-08-27</link>" in item
    assert '<guid isPermaLink="false">briefing:2026-08-27</guid>' in item
    assert "<pubDate>Thu, 27 Aug 2026 00:05:00 +0000</pubDate>" in item
    # 全文模式：条目正文保留；description 为整体 XML 转义的 HTML 片段
    assert "话题概述" in item
    assert "&lt;h2&gt;" in item
    assert "📮" not in item


def test_build_briefing_feed_item_digest_mode_condenses() -> None:
    item = build_briefing_feed_item(_briefing_row(), "https://aigcnews.cn", digest=True)
    assert item is not None
    assert "<title>2026-08-27 每日 AIGC 简报（速览）</title>" in item
    assert "<link>https://aigcnews.cn/report?date=2026-08-27</link>" in item
    assert '<guid isPermaLink="false">briefing-digest:2026-08-27</guid>' in item
    assert "本报梳理" in item
    assert "话题概述" not in item
    assert "日期与数据来源" not in item


def test_build_briefing_feed_item_skips_rows_without_date_or_content() -> None:
    assert build_briefing_feed_item(_briefing_row(date=""), "https://aigcnews.cn") is None
    assert build_briefing_feed_item(_briefing_row(content=""), "https://aigcnews.cn") is None


def test_build_briefing_feed_item_links_bare_report_for_non_date_key() -> None:
    # 期号不是 YYYY-MM-DD（脏键）时不拼进查询串，回落简报页默认的当天
    item = build_briefing_feed_item(_briefing_row(date="2026-08-27_x"), "https://aigcnews.cn")
    assert item is not None
    assert "<link>https://aigcnews.cn/report</link>" in item


def test_build_briefing_feed_item_falls_back_to_content_column() -> None:
    row = _briefing_row()
    row["content_zh"] = ""
    row["content"] = _BRIEFING_MD
    item = build_briefing_feed_item(row, "https://aigcnews.cn")
    assert item is not None
    assert "本报梳理" in item


def test_briefing_feed_is_public_full_text_with_edge_cache_headers() -> None:
    briefings = MagicMock()
    briefings.list_recent_daily_briefings.return_value = [_briefing_row()]
    client = _client(documents=MagicMock(), briefings=briefings)

    response = client.get("/api/feeds/briefing.xml")
    assert response.status_code == 200
    # 命中简报路由而非 {source} 捕获（捕获会以 404 拒绝 "briefing"）
    assert response.headers["cache-control"] == "public, max-age=900"
    assert "charset=utf-8" in response.headers["content-type"]
    assert "x-robots-tag" not in response.headers
    briefings.list_recent_daily_briefings.assert_called_once_with(_BRIEFING_FEED_LIMIT)
    assert "<title>AIGC NEWS · 每日简报</title>" in response.text
    assert "<title>2026-08-27 每日 AIGC 简报</title>" in response.text
    assert "话题概述" in response.text


def test_briefing_feed_skips_contentless_rows() -> None:
    briefings = MagicMock()
    briefings.list_recent_daily_briefings.return_value = [
        _briefing_row(date="2026-08-27"),
        _briefing_row(date="2026-08-26", content=""),
    ]
    client = _client(documents=MagicMock(), briefings=briefings)

    response = client.get("/api/feeds/briefing.xml")
    assert response.status_code == 200
    assert "2026-08-27 每日 AIGC 简报" in response.text
    assert "2026-08-26" not in response.text


def test_briefing_digest_requires_token_and_is_not_captured_by_source_route() -> None:
    client = _client(documents=MagicMock(), briefings=MagicMock(), tokens=MagicMock())
    response = client.get("/api/feeds/briefing-digest.xml")
    # 路由顺序锁定：命中速览路由的 401，而非 {source} 捕获后的 404
    assert response.status_code == 401
    assert response.json()["detail"] == _INVALID_TOKEN_DETAIL


def test_briefing_digest_allows_free_tier() -> None:
    """简报速览已降级为注册用户免费权益：免费档有效 token 直接放行。"""
    briefings = MagicMock()
    briefings.list_recent_daily_briefings.return_value = [_briefing_row()]
    tokens = MagicMock()
    tokens.get_user_by_feed_token_hash.return_value = {
        "user_id": 7,
        "membership_tier": "free",
    }
    client = _client(documents=MagicMock(), briefings=briefings, tokens=tokens)
    response = client.get("/api/feeds/briefing-digest.xml?token=ok")
    assert response.status_code == 200
    assert "<title>2026-08-27 每日 AIGC 简报（速览）</title>" in response.text


def test_briefing_digest_returns_condensed_content_for_member() -> None:
    briefings = MagicMock()
    briefings.list_recent_daily_briefings.return_value = [_briefing_row()]
    tokens = MagicMock()
    tokens.get_user_by_feed_token_hash.return_value = {
        "user_id": 7,
        "membership_tier": "member",
    }
    client = _client(documents=MagicMock(), briefings=briefings, tokens=tokens)

    response = client.get("/api/feeds/briefing-digest.xml?token=ok")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-robots-tag"] == "noindex"
    assert "<title>AIGC NEWS · 每日简报速览</title>" in response.text
    assert "<title>2026-08-27 每日 AIGC 简报（速览）</title>" in response.text
    assert "本报梳理" in response.text
    assert "话题概述" not in response.text
