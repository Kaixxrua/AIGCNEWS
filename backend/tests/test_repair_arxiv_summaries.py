from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from scripts.repair_arxiv_summaries import (
    HfPageFetcher,
    classify_against_api,
    classify_summary,
    repair_summaries,
)

# HF 摘要里的关键短语是 <a> 链接；旧解析逐节点 strip 会吞掉链接两侧的空格。
_ABSTRACT_HTML = (
    "Multimodal large language models have significantly advanced "
    '<a href="/papers?q=document">document understanding</a>, thanks to '
    "instruction tuning. Code: https://github.com/example/docs"
)
_ABSTRACT = (
    "Multimodal large language models have significantly advanced document "
    "understanding, thanks to instruction tuning. Code: https://github.com/example/docs"
)
_PARTIALLY_COLLAPSED = (
    "Multimodal large language models have significantly advanceddocument "
    "understanding, thanks toinstruction tuning. Code: https://github.com/example/docs"
)
_TLDR = "The paper improves document understanding in multimodal models via instruction tuning."
_COMMENT = "the part that stood out to me is how the benchmark keeps every document auditable."
_REVISED = "A revised abstract that no paragraph on the page contains any more."


def _page(abstract_html: str = _ABSTRACT_HTML) -> str:
    return (
        "<html><body><h1>DocTuner</h1>"
        '<div class="pb-8"><h2>Abstract</h2> <div class="flex flex-col gap-y-2.5">'
        f'<div class="bg-blue-500/6"><p class="text-blue-700">{_TLDR}</p></div> '
        f'<p class="text-gray-600">{abstract_html}</p></div></div>'
        f"<section><p>{_COMMENT}</p></section></body></html>"
    )


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        (_ABSTRACT, ("unchanged", _ABSTRACT)),
        ("".join(_ABSTRACT.split()), ("api_whitespace", _ABSTRACT)),
        (_PARTIALLY_COLLAPSED, ("api_whitespace", _ABSTRACT)),
        # 误取段落、为空都不能凭 API 证明来历，交给 HF 页面判定
        (_TLDR, None),
        ("", None),
    ],
)
def test_classify_against_api(stored: str, expected: tuple[str, str] | None) -> None:
    assert classify_against_api(stored, _ABSTRACT) == expected


def test_classify_against_api_without_api_abstract_defers_to_hf() -> None:
    assert classify_against_api(_PARTIALLY_COLLAPSED, "") is None


def test_classify_against_api_restores_the_legacy_500_char_cut() -> None:
    long_abstract = " ".join([_ABSTRACT] * 8)

    assert classify_against_api(long_abstract[:500], long_abstract) == (
        "api_truncated",
        long_abstract,
    )
    # 截断处的空白也丢了：仍按前缀补全，记作恢复空格
    assert classify_against_api("".join(long_abstract.split())[:500], long_abstract) == (
        "api_whitespace",
        long_abstract,
    )


@pytest.mark.parametrize(
    ("stored", "action"),
    [
        (_ABSTRACT, "unchanged"),
        ("".join(_ABSTRACT.split()), "abstract_prefix"),
        (_PARTIALLY_COLLAPSED, "abstract_prefix"),
        (_TLDR, "other_paragraph"),
        (_COMMENT, "other_paragraph"),
        ("", "fill_empty"),
        (_REVISED, "no_match"),
    ],
)
def test_classify_summary_against_hf_abstract(stored: str, action: str) -> None:
    assert classify_summary(stored, _page()) == (action, _ABSTRACT)


def test_classify_summary_restores_the_full_abstract() -> None:
    long_abstract = " ".join([_ABSTRACT] * 8)

    assert classify_summary(long_abstract[:500], _page(long_abstract)) == (
        "abstract_truncated",
        long_abstract,
    )
    assert classify_summary("".join(long_abstract.split())[:500], _page(long_abstract)) == (
        "abstract_prefix",
        long_abstract,
    )


def test_classify_summary_caps_like_ingestion() -> None:
    # 与入库同口径：只防解析出错把整页正文灌进来
    huge = " ".join([_ABSTRACT] * 40)

    assert classify_summary("", _page(huge)) == ("fill_empty", huge[:4000])


def test_classify_summary_without_abstract_section_is_skipped() -> None:
    html = f"<html><body><h1>Title</h1><p>{_ABSTRACT}</p></body></html>"

    assert classify_summary("".join(_ABSTRACT.split()), html) == ("no_abstract", "")


def _row(doc_id: str, arxiv_id: str, summary: str | None) -> dict:
    return {"id": doc_id, "arxiv_id": arxiv_id, "summary": summary}


def _api(*arxiv_ids: str, abstract: str = _ABSTRACT) -> MagicMock:
    # API 原文带换行，入库前按空白规整
    papers = [{"arxiv_id": aid, "abstract": abstract.replace(" ", "\n  ", 1)} for aid in arxiv_ids]
    return MagicMock(return_value=papers)


def test_dry_run_uses_api_first_and_pages_only_for_the_rest() -> None:
    documents = MagicMock()
    documents.list_arxiv_document_summaries.return_value = [
        _row("a", "2609.00001", _ABSTRACT),
        _row("b", "2609.00002", _PARTIALLY_COLLAPSED),
        _row("c", "2609.00003", _TLDR),
        _row("d", "", _TLDR),
        _row("e", "2609.00005", _REVISED),
        _row("f", "2609.00006", None),
    ]
    fetch_abstracts = _api("2609.00001", "2609.00002", "2609.00003", "2609.00005", "2609.00006")
    fetch_page = MagicMock(return_value=_page())

    result = repair_summaries(
        documents, fetch_abstracts, fetch_page, page_sleep_seconds=0, dry_run=True
    )

    assert result["status"] == "dry_run"
    assert result["scanned"] == 6
    assert result["counts"] == {
        "unchanged": 1,
        "api_truncated": 0,
        "api_whitespace": 1,
        "abstract_truncated": 0,
        "abstract_prefix": 0,
        "other_paragraph": 1,
        "fill_empty": 1,
        "no_match": 1,
        "no_abstract": 0,
        "fetch_failed": 0,
        "not_checked": 0,
        "api_failed": 0,
        "missing_id": 1,
    }
    fetch_abstracts.assert_called_once_with(
        ["2609.00001", "2609.00002", "2609.00003", "2609.00005", "2609.00006"]
    )
    assert [call.args[0] for call in fetch_page.call_args_list] == [
        "2609.00003",
        "2609.00005",
        "2609.00006",
    ]
    assert result["pages_fetched"] == 3
    assert result["planned_updates"] == 3
    assert result["planned"] == [
        {"id": "b", "arxiv_id": "2609.00002", "action": "api_whitespace"},
        {"id": "c", "arxiv_id": "2609.00003", "action": "other_paragraph"},
        {"id": "f", "arxiv_id": "2609.00006", "action": "fill_empty"},
    ]
    assert result["skipped"] == [
        {"id": "d", "arxiv_id": "", "action": "missing_id"},
        {"id": "e", "arxiv_id": "2609.00005", "action": "no_match"},
    ]
    assert result["samples"][0] == {
        "id": "b",
        "arxiv_id": "2609.00002",
        "action": "api_whitespace",
        "before": _PARTIALLY_COLLAPSED[:100],
        "after": _ABSTRACT[:100],
    }
    documents.update_document_summary_if_unchanged.assert_not_called()


def test_write_path_passes_the_read_value_for_a_conditional_update() -> None:
    documents = MagicMock()
    documents.list_arxiv_document_summaries.return_value = [
        _row("a", "2609.00001", _PARTIALLY_COLLAPSED),
        _row("b", "2609.00002", None),
        _row("c", "2609.00003", _ABSTRACT),
    ]
    documents.update_document_summary_if_unchanged.side_effect = [True, False]

    result = repair_summaries(
        documents,
        _api("2609.00001", "2609.00003"),
        lambda _arxiv_id: _page(),
        page_sleep_seconds=0,
    )

    assert result["status"] == "success"
    assert result["updated"] == 1
    assert result["raced"] == 1
    assert [call.args for call in documents.update_document_summary_if_unchanged.call_args_list] == [
        ("a", _PARTIALLY_COLLAPSED, _ABSTRACT),
        ("b", None, _ABSTRACT),
    ]


def test_failed_api_batch_is_skipped_instead_of_falling_back_to_pages() -> None:
    documents = MagicMock()
    documents.list_arxiv_document_summaries.return_value = [
        _row(f"id{i}", f"2609.{i:05d}", _PARTIALLY_COLLAPSED) for i in range(3)
    ]
    # 取数函数吞掉网络错误返回空表：第二批整批失败
    fetch_abstracts = MagicMock(
        side_effect=[[{"arxiv_id": "2609.00000", "abstract": _ABSTRACT}], []]
    )
    fetch_page = MagicMock(return_value=_page())

    result = repair_summaries(
        documents, fetch_abstracts, fetch_page, batch_size=2, api_sleep_seconds=0, dry_run=True
    )

    assert [call.args[0] for call in fetch_abstracts.call_args_list] == [
        ["2609.00000", "2609.00001"],
        ["2609.00002"],
    ]
    assert result["counts"]["api_whitespace"] == 1
    assert result["counts"]["api_failed"] == 1
    # 首批里 API 未返回的那篇照常查 HF；整批失败的不查
    assert [call.args[0] for call in fetch_page.call_args_list] == ["2609.00001"]
    assert result["counts"]["abstract_prefix"] == 1


def test_consecutive_page_failures_trip_the_breaker() -> None:
    documents = MagicMock()
    documents.list_arxiv_document_summaries.return_value = [
        _row(f"id{i}", f"2609.{i:05d}", _TLDR) for i in range(5)
    ]
    fetch_page = MagicMock(side_effect=RuntimeError("HTTP 503"))

    result = repair_summaries(
        documents,
        MagicMock(return_value=[{"arxiv_id": "x", "abstract": "unrelated"}]),
        fetch_page,
        page_sleep_seconds=0,
        max_consecutive_failures=2,
    )

    assert fetch_page.call_count == 2
    assert result["counts"]["fetch_failed"] == 2
    assert result["counts"]["not_checked"] == 3
    documents.update_document_summary_if_unchanged.assert_not_called()


def test_forwards_pagination_and_reports_progress() -> None:
    documents = MagicMock()
    documents.list_arxiv_document_summaries.return_value = [
        _row(f"id{i:03d}", f"2609.{i:05d}", _ABSTRACT) for i in range(200)
    ]
    fetch_abstracts = MagicMock(
        side_effect=lambda ids: [{"arxiv_id": aid, "abstract": _ABSTRACT} for aid in ids]
    )
    lines: list[str] = []

    result = repair_summaries(
        documents,
        fetch_abstracts,
        MagicMock(),
        after_id="id",
        limit=200,
        api_sleep_seconds=0,
        dry_run=True,
        progress=lines.append,
    )

    documents.list_arxiv_document_summaries.assert_called_once_with(after_id="id", limit=200)
    assert fetch_abstracts.call_count == 4
    assert result["counts"]["unchanged"] == 200
    assert result["pages_fetched"] == 0
    assert result["last_id"] == "id199"
    assert [line.split()[1] for line in lines] == ["100/200", "200/200"]


def _fetcher(responses: list[httpx.Response]) -> tuple[HfPageFetcher, list[float], list[str]]:
    requested: list[str] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        return queue.pop(0)

    sleeps: list[float] = []
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://hf.test")
    return HfPageFetcher(client, reserve=50, sleep=sleeps.append), sleeps, requested


def test_hf_fetcher_waits_for_window_reset_when_quota_runs_low(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("scripts.repair_arxiv_summaries._hf_papers_base", lambda: "https://hf.test/papers")
    fetch, sleeps, requested = _fetcher(
        [
            httpx.Response(200, text="ok-1", headers={"ratelimit": '"pages";r=80;t=200'}),
            httpx.Response(200, text="ok-2", headers={"ratelimit": '"pages";r=49;t=120'}),
        ]
    )

    assert fetch("2609.00001") == "ok-1"
    assert sleeps == []
    assert fetch("2609.00002") == "ok-2"
    assert sleeps == [121]
    assert requested == ["/papers/2609.00001", "/papers/2609.00002"]


def test_hf_fetcher_retries_once_after_429(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scripts.repair_arxiv_summaries._hf_papers_base", lambda: "https://hf.test/papers")
    fetch, sleeps, _ = _fetcher(
        [
            httpx.Response(429, headers={"ratelimit": '"pages";r=0;t=145'}),
            httpx.Response(200, text="ok", headers={"ratelimit": '"pages";r=99;t=300'}),
        ]
    )

    assert fetch("2609.00001") == "ok"
    assert sleeps == [146]


def test_hf_fetcher_gives_up_after_second_429(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scripts.repair_arxiv_summaries._hf_papers_base", lambda: "https://hf.test/papers")
    fetch, sleeps, _ = _fetcher([httpx.Response(429), httpx.Response(429)])

    with pytest.raises(httpx.HTTPStatusError):
        fetch("2609.00001")
    assert sleeps == [61]
