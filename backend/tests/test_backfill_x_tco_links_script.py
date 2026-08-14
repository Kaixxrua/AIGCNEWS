from __future__ import annotations

import json

from scripts import backfill_x_tco_links as backfill


def test_find_tco_links_dedupes_preserving_order() -> None:
    text = "a https://t.co/One b https://t.co/Two c https://t.co/One"
    assert backfill.find_tco_links(text) == ["https://t.co/One", "https://t.co/Two"]
    assert backfill.find_tco_links("") == []


def test_rewrite_text_expands_mapped_and_keeps_unmapped() -> None:
    text = "看 https://t.co/Aaa 与 https://t.co/Bbb"
    mapping = {"https://t.co/Aaa": "https://z.ai/blog/glm-5.3"}
    # 已解析的原位展开；未解析的保留原值（不静默丢链接）
    assert backfill.rewrite_text(text, mapping) == (
        "看 https://z.ai/blog/glm-5.3 与 https://t.co/Bbb"
    )
    assert backfill.rewrite_text(text, {}) == text
    assert backfill.rewrite_text("", mapping) == ""


def test_rewrite_json_field_rewrites_quote_text_keys() -> None:
    raw = json.dumps(
        {
            "url": "https://x.com/a/status/1",
            "text": "看这里 https://t.co/Aaa",
            "translation_zh": "译文 https://t.co/Aaa",
        },
        ensure_ascii=False,
    )
    out = backfill._rewrite_json_field(
        raw, backfill._QUOTE_TEXT_KEYS, {"https://t.co/Aaa": "https://example.org/a"}
    )
    payload = json.loads(out)
    assert payload["text"] == "看这里 https://example.org/a"
    assert payload["translation_zh"] == "译文 https://example.org/a"
    # 非目标键（推文 URL）不动
    assert payload["url"] == "https://x.com/a/status/1"


def test_rewrite_json_field_passthrough_when_no_change_or_bad_json() -> None:
    raw = json.dumps({"text": "无链接"}, ensure_ascii=False)
    assert backfill._rewrite_json_field(raw, ("text",), {"https://t.co/Aaa": "x"}) == raw
    assert backfill._rewrite_json_field("not-json", ("text",), {"https://t.co/Aaa": "x"}) == "not-json"
    assert backfill._rewrite_json_field(None, ("text",), {"https://t.co/Aaa": "x"}) is None
    # 空映射直通（不解析 JSON，零副作用）
    assert backfill._rewrite_json_field(raw, ("text",), {}) == raw


def test_rewrite_row_covers_text_and_json_fields() -> None:
    row = {
        "id": "doc1",
        "title": "标题 https://t.co/Aaa",
        "summary": "正文 https://t.co/Aaa",
        "translation_zh": "译文 https://t.co/Aaa",
        "quote": json.dumps({"text": "引用 https://t.co/Aaa"}, ensure_ascii=False),
        "link_card": json.dumps({"url": "https://t.co/Aaa", "title": "卡"}, ensure_ascii=False),
    }
    updates = backfill.rewrite_row(row, {"https://t.co/Aaa": "https://example.org/a"})
    assert updates["title"] == "标题 https://example.org/a"
    assert updates["summary"] == "正文 https://example.org/a"
    assert updates["translation_zh"] == "译文 https://example.org/a"
    assert json.loads(updates["quote"])["text"] == "引用 https://example.org/a"
    assert json.loads(updates["link_card"])["url"] == "https://example.org/a"


def test_rewrite_row_empty_when_nothing_mapped() -> None:
    row = {
        "id": "doc2",
        "title": "标题 https://t.co/Aaa",
        "summary": None,
        "translation_zh": None,
        "quote": None,
        "link_card": None,
    }
    assert backfill.rewrite_row(row, {}) == {}


def test_resolve_tco_links_skips_failures() -> None:
    calls: list[str] = []

    def fake_resolver(link: str, *, proxy: str, timeout: float) -> str:
        calls.append(link)
        return "https://example.org/a" if link.endswith("Aaa") else ""

    mapping = backfill.resolve_tco_links(
        ["https://t.co/Aaa", "https://t.co/Bbb"],
        proxy="socks5h://127.0.0.1:11080",
        interval=0,
        resolver=fake_resolver,
    )
    assert mapping == {"https://t.co/Aaa": "https://example.org/a"}
    assert calls == ["https://t.co/Aaa", "https://t.co/Bbb"]


def test_curl_redirect_url_rejects_tco_target_and_failures(monkeypatch) -> None:
    class _Proc:
        returncode = 0
        stdout = "https://t.co/StillShort"

    monkeypatch.setattr(backfill.subprocess, "run", lambda *a, **k: _Proc())
    # 目标仍是 t.co → 防环，视为未展开
    assert backfill.curl_redirect_url("https://t.co/Aaa", proxy="", timeout=1) == ""

    class _FailProc:
        returncode = 28
        stdout = ""

    monkeypatch.setattr(backfill.subprocess, "run", lambda *a, **k: _FailProc())
    assert backfill.curl_redirect_url("https://t.co/Aaa", proxy="", timeout=1) == ""


def test_curl_redirect_url_returns_location(monkeypatch) -> None:
    captured: list[list[str]] = []

    class _Proc:
        returncode = 0
        stdout = "https://z.ai/blog/glm-5.3"

    def fake_run(cmd, **kwargs):  # noqa: ANN001 - 测试替身
        captured.append(cmd)
        return _Proc()

    monkeypatch.setattr(backfill.subprocess, "run", fake_run)
    out = backfill.curl_redirect_url(
        "https://t.co/Aaa", proxy="socks5h://127.0.0.1:11080", timeout=1
    )
    assert out == "https://z.ai/blog/glm-5.3"
    # 代理参数随调用传递（t.co 境内直连不可达）
    assert "-x" in captured[0]
    assert "socks5h://127.0.0.1:11080" in captured[0]
