"""RSS feed 路由与渲染契约测试。

覆盖：
  - 纯函数：item 渲染/跳过规则、回链策略（arxiv 站内、其余原文）、
    全文模式追加译文、脏时间串容错、member source 参数解析；
  - 路由：公开综合/单源 feed 的缓存头与归并排序、非法源 404、
    会员 feed 的 401/403/200 档位门禁、noindex/no-store 响应头、
    /feeds/member.xml 不被 {source} 路径参数捕获（路由顺序锁定）。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.app.api.dependencies import (
    get_document_repository,
    get_mcp_access_token_repository,
)
from backend.app.api.routes_feed import (
    _INVALID_TOKEN_DETAIL,
    _MEMBER_ONLY_DETAIL,
    _parse_member_sources,
    _parse_published_at,
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


# ---------------------------------------------------------------- 纯函数


def test_build_feed_item_arxiv_links_to_internal_read_page() -> None:
    item = build_feed_item(_doc("2508.12345"), "https://aigcnews.cn")
    assert item is not None
    assert "<link>https://aigcnews.cn/papers/2508.12345/read</link>" in item
    assert '<guid isPermaLink="false">arxiv:2508.12345</guid>' in item
    assert "<pubDate>Tue, 18 Aug 2026 08:00:00 +0000</pubDate>" in item
    assert "<description>摘要</description>" in item


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
    assert public is not None and "中文译文" not in public
    # 译文与摘要相同（未翻译内容回填）时不重复
    same = build_feed_item(_doc("i", translation_zh="摘要"), "https://aigcnews.cn", full=True)
    assert same is not None and same.count("摘要") == 1


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


def _client(*, documents: MagicMock, tokens: MagicMock | None = None) -> TestClient:
    overrides = {get_document_repository: lambda: documents}
    if tokens is not None:
        overrides[get_mcp_access_token_repository] = lambda: tokens
    app.dependency_overrides.update(overrides)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _cleanup_overrides():
    yield
    app.dependency_overrides.clear()


def test_public_feed_merges_sources_newest_first_with_cache_headers() -> None:
    documents = MagicMock()

    def fake_list(source: str, *, since_iso: str, until_iso=None, limit: int = 500):
        if source == "arxiv":
            return [_doc("a-old", published_at="2026-08-17T01:00:00+00:00")]
        if source == "news":
            return [_doc("n-new", source="news", published_at="2026-08-18T09:00:00+00:00")]
        return []

    documents.list_recent_by_source.side_effect = fake_list
    client = _client(documents=documents)

    response = client.get("/api/feed.xml")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/rss+xml")
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
    tokens.get_user_by_mcp_token_hash.return_value = None
    client = _client(documents=documents, tokens=tokens)
    assert client.get("/api/feeds/member.xml?token=bad").status_code == 401

    tokens.get_user_by_mcp_token_hash.return_value = {
        "user_id": 7,
        "membership_tier": "free",
    }
    response = client.get("/api/feeds/member.xml?token=ok")
    assert response.status_code == 403
    assert response.json()["detail"] == _MEMBER_ONLY_DETAIL


def test_member_feed_returns_full_content_for_member() -> None:
    documents = MagicMock()
    documents.list_recent_by_source.return_value = [_doc("a1", translation_zh="中文译文")]
    tokens = MagicMock()
    tokens.get_user_by_mcp_token_hash.return_value = {
        "user_id": 7,
        "membership_tier": "member",
    }
    client = _client(documents=documents, tokens=tokens)

    response = client.get("/api/feeds/member.xml?token=ok")
    assert response.status_code == 200
    assert "中文译文" in response.text
    assert response.headers["x-robots-tag"] == "noindex"
    assert response.headers["cache-control"] == "private, no-store"


def test_member_feed_source_combination_limits_queried_sources() -> None:
    documents = MagicMock()
    documents.list_recent_by_source.return_value = []
    tokens = MagicMock()
    tokens.get_user_by_mcp_token_hash.return_value = {
        "user_id": 7,
        "membership_tier": "member",
    }
    client = _client(documents=documents, tokens=tokens)

    response = client.get("/api/feeds/member.xml?token=ok&source=arxiv,github")
    assert response.status_code == 200
    queried = {call.args[0] for call in documents.list_recent_by_source.call_args_list}
    assert queried == {"arxiv", "github"}

    assert client.get("/api/feeds/member.xml?token=ok&source=arxiv,bogus").status_code == 400
