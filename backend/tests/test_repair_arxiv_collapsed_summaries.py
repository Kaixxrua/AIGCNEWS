from __future__ import annotations

from unittest.mock import MagicMock

from scripts.repair_arxiv_collapsed_summaries import repair_summaries

_ABSTRACT = (
    "Long visual token sequences often account for a substantial fraction of the "
    "computational overhead in multimodal large language models."
)


def _collapsed(text: str, limit: int = 500) -> str:
    return "".join(text.split())[:limit]


def _row(doc_id: str, arxiv_id: str, summary: str) -> dict:
    return {"id": doc_id, "arxiv_id": arxiv_id, "summary": summary}


def test_dry_run_plans_matching_rows_without_writing() -> None:
    documents = MagicMock()
    documents.list_arxiv_documents_with_collapsed_summary.return_value = [
        _row("a", "2609.34972", _collapsed(_ABSTRACT)),
        _row("b", "", "Somecollapsedsummarywithoutanarxividatallsoitcannotberepairedfromtheapi"),
    ]
    fetcher = MagicMock(return_value=[{"arxiv_id": "2609.34972", "abstract": _ABSTRACT}])

    result = repair_summaries(documents, fetcher, dry_run=True, sleep_seconds=0)

    assert result["status"] == "dry_run"
    assert result["scanned"] == 2
    assert result["missing_id"] == 1
    assert result["planned_updates"] == 1
    assert result["updated"] == 0
    fetcher.assert_called_once_with(["2609.34972"])
    documents.update_collapsed_document_summary.assert_not_called()


def test_write_path_normalizes_whitespace_and_truncates_like_ingestion() -> None:
    long_abstract = " ".join([_ABSTRACT] * 6)  # > 500 字符，入库口径只留前 500
    api_abstract = long_abstract.replace(" often ", "\n  often ", 1)
    documents = MagicMock()
    documents.list_arxiv_documents_with_collapsed_summary.return_value = [
        _row("a", "2609.34972", _collapsed(long_abstract)),
    ]
    documents.update_collapsed_document_summary.return_value = True
    fetcher = MagicMock(return_value=[{"arxiv_id": "2609.34972", "abstract": api_abstract}])

    result = repair_summaries(documents, fetcher, sleep_seconds=0)

    assert result["updated"] == 1
    documents.update_collapsed_document_summary.assert_called_once_with(
        "a", _collapsed(long_abstract), long_abstract[:500]
    )


def test_mismatched_or_missing_api_abstract_is_skipped() -> None:
    documents = MagicMock()
    documents.list_arxiv_documents_with_collapsed_summary.return_value = [
        _row("a", "2609.00001", _collapsed(_ABSTRACT)),
        _row("b", "2609.00002", _collapsed(_ABSTRACT)),
    ]
    fetcher = MagicMock(
        return_value=[{"arxiv_id": "2609.00001", "abstract": "A different paper about something else entirely."}]
    )

    result = repair_summaries(documents, fetcher, sleep_seconds=0)

    assert result["mismatch"] == 1
    assert result["not_found"] == 1
    assert result["mismatches"] == [{"id": "a", "arxiv_id": "2609.00001"}]
    documents.update_collapsed_document_summary.assert_not_called()


def test_concurrent_rewrite_is_counted_as_raced_not_updated() -> None:
    documents = MagicMock()
    documents.list_arxiv_documents_with_collapsed_summary.return_value = [
        _row("a", "2609.34972", _collapsed(_ABSTRACT)),
    ]
    documents.update_collapsed_document_summary.return_value = False
    fetcher = MagicMock(return_value=[{"arxiv_id": "2609.34972", "abstract": _ABSTRACT}])

    result = repair_summaries(documents, fetcher, sleep_seconds=0)

    assert result["updated"] == 0
    assert result["raced"] == 1


def test_batches_ids_and_forwards_pagination_args() -> None:
    documents = MagicMock()
    documents.list_arxiv_documents_with_collapsed_summary.return_value = [
        _row(f"id{i}", f"2609.{i:05d}", _collapsed(_ABSTRACT)) for i in range(5)
    ]
    fetcher = MagicMock(return_value=[])

    result = repair_summaries(
        documents, fetcher, after_id="id", limit=5, batch_size=2, sleep_seconds=0, dry_run=True
    )

    documents.list_arxiv_documents_with_collapsed_summary.assert_called_once_with(after_id="id", limit=5)
    assert [call.args[0] for call in fetcher.call_args_list] == [
        ["2609.00000", "2609.00001"],
        ["2609.00002", "2609.00003"],
        ["2609.00004"],
    ]
    assert result["not_found"] == 5
    assert result["last_id"] == "id4"
