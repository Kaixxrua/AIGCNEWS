"""RSS feed 路由与渲染契约测试。

覆盖：
  - 纯函数：item 渲染/跳过规则、回链策略（arxiv 站内、其余原文）、
    全文模式追加译文、公开条目优先中文译文截断（X 源标题亦用译文）、
    脏时间串容错、member source 参数解析、
    项目库热榜条目 → feed 行的字段映射；
  - 路由：公开综合/单源 feed 的缓存头与归并排序、非法源 404、
    github 源由站内今日热榜供稿（热榜不可用/为空时回退 documents 池）、
    会员 feed 的 401/403/200 档位门禁（独立 RSS feed token，非 MCP token）、
    noindex/no-store 响应头、
    /feeds/member.xml 不被 {source} 路径参数捕获（路由顺序锁定）。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.app.api.dependencies import (
    get_document_repository,
    get_feed_token_repository,
    get_project_catalog_query_service,
)
from backend.app.api.routes_feed import (
    _INVALID_TOKEN_DETAIL,
    _MEMBER_ONLY_DETAIL,
    _PUBLIC_DESCRIPTION_TRANSLATION_LIMIT,
    _PUBLIC_TITLE_TRANSLATION_LIMIT,
    _parse_member_sources,
    _parse_published_at,
    _project_to_feed_row,
    _filter_rows_to_window,
    build_feed_item,
    build_rss_xml,
)
from backend.app.main import app


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
    # 公开条目：摘要 + 转化钩子（指向游客可见的会员页）
    assert "<description>摘要\n\n📮 订阅会员全文 RSS（中文译文 · 完整归档）：https://aigcnews.cn/membership</description>" in item


def test_build_feed_item_full_mode_omits_conversion_hook() -> None:
    # 会员条目不带钩子——付费内容里不插广告
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
    # 会员条目不截断、不换标题：原标题 + 完整译文全文
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
) -> TestClient:
    overrides = {
        get_document_repository: lambda: documents,
        # github 源默认走热榜供稿，任何命中 github 的路由都必须隔离真实项目库
        get_project_catalog_query_service: lambda: catalog if catalog is not None else _catalog(),
    }
    if tokens is not None:
        overrides[get_feed_token_repository] = lambda: tokens
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
    # 路由顺序锁定：命中会员路由的 401，而非 {source} 捕获后的 404
    assert response.status_code == 401
    assert response.json()["detail"] == _INVALID_TOKEN_DETAIL


def test_member_feed_rejects_invalid_token_and_free_tier() -> None:
    documents = MagicMock()
    tokens = MagicMock()
    tokens.get_user_by_feed_token_hash.return_value = None
    client = _client(documents=documents, tokens=tokens)
    assert client.get("/api/feeds/member.xml?token=bad").status_code == 401

    tokens.get_user_by_feed_token_hash.return_value = {
        "user_id": 7,
        "membership_tier": "free",
    }
    response = client.get("/api/feeds/member.xml?token=ok")
    assert response.status_code == 403
    assert response.json()["detail"] == _MEMBER_ONLY_DETAIL


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
    # 会员 feed 不带获客钩子
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
