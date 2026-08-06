from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.services.wechat_sogou.parser import (
    extract_article_identity,
    extract_signed_url_from_redirect,
    is_antispider_content,
    normalize_account_name,
    parse_article_search_page,
)

FIXTURES = Path(__file__).parent / "fixtures" / "wechat_sogou"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_article_search_page_extracts_items() -> None:
    items = parse_article_search_page(_fixture("search_page.html"))

    assert len(items) == 7
    first = items[0]
    assert first["title"] == "如何快速入门AI安全领域?"
    assert first["account_name"] == "Ai迷思录"
    assert first["link_path"].startswith("/link?url=")
    assert first["published_ts"] == 1772370986
    assert "AI 安全" in first["summary"]


def test_parse_article_search_page_filters_by_account() -> None:
    items = parse_article_search_page(_fixture("search_page.html"))
    target = normalize_account_name("AI迷思录")
    matched = [i for i in items if normalize_account_name(i["account_name"]) == target]

    assert len(matched) == 3
    assert {i["title"] for i in matched} == {
        "如何快速入门AI安全领域?",
        "OSCP推出AI 红队课程?先别交钱,免费平替来了",
        "AI安全一线信源清单推荐",
    }


def test_parse_article_search_page_empty_on_no_results() -> None:
    assert parse_article_search_page("<html><body>暂无相关结果</body></html>") == []


def test_is_antispider_content_detects_captcha_page() -> None:
    assert is_antispider_content("<html>antispider 验证码</html>") is True
    assert is_antispider_content(_fixture("search_page.html")) is False


def test_extract_signed_url_from_redirect_joins_js_parts() -> None:
    url = extract_signed_url_from_redirect(_fixture("redirect_page.html"))

    assert url.startswith("https://mp.weixin.qq.com/s?src=11")
    assert "signature=" in url
    assert "'" not in url


def test_extract_signed_url_from_redirect_raises_on_garbage() -> None:
    with pytest.raises(ValueError):
        extract_signed_url_from_redirect("<html>nope</html>")


def test_extract_article_identity_reads_canonical_vars() -> None:
    identity = extract_article_identity(_fixture("article_page.html"))

    assert identity["biz"] == "Mzk1NzE0NDcyNg=="
    assert identity["mid"] == "2247483765"
    assert identity["idx"] == "1"
    assert identity["user_name"] == "gh_2780e022a16c"
    assert identity["nickname"] == "Ai迷思录"
    assert identity["msg_title"] == "如何快速入门AI安全领域?"
    assert identity["published_at"] == "2026-03-01T13:16:20+00:00"


def test_extract_article_identity_tolerates_empty_string_fallback_chain() -> None:
    # Real mp pages emit: var mid = "2247483765" || "" || "";
    body = (
        '<script>var biz = "Mzk1NzE0NDcyNg==" || "" || "";\n'
        'var mid = "2247483765" || "" || "";\n'
        'var idx = "1" || "" || "";</script>'
    )
    identity = extract_article_identity(body)

    assert identity["biz"] == "Mzk1NzE0NDcyNg=="
    assert identity["mid"] == "2247483765"
    assert identity["idx"] == "1"


def test_parse_article_search_page_unescapes_cover_url() -> None:
    # Real Sogou result covers carry HTML entities: thumb?appid=201147&amp;url=...
    body = (
        '<li id="sogou_vr_11002601_box_0">'
        '<img src="//img01.sogoucdn.com/v2/thumb?appid=201147&amp;url=abc.jpg"/>'
        '<h3><a href="/link?url=xyz">标题</a></h3>'
        '<span class="all-time-y2">某账号</span>'
        "</li>"
    )
    items = parse_article_search_page(body)

    assert len(items) == 1
    assert items[0]["cover_url"] == "//img01.sogoucdn.com/v2/thumb?appid=201147&url=abc.jpg"


def test_normalize_account_name_strips_spaces_and_case() -> None:
    assert normalize_account_name(" AI 迷思录 ") == normalize_account_name("ai迷思录")
