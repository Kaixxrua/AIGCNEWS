from __future__ import annotations

import hashlib
import json
from unittest.mock import MagicMock

from scripts.backfill_arxiv_document_authors import (
    _derive_arxiv_id,
    backfill_authors,
)


def _doc_id(arxiv_id: str) -> str:
    return hashlib.md5(f"arxiv:{arxiv_id}".encode()).hexdigest()


def _row(arxiv_id: str, url: str | None = None) -> dict:
    return {
        "id": _doc_id(arxiv_id),
        "url": url or f"https://arxiv.org/abs/{arxiv_id}",
    }


def test_derive_arxiv_id_covers_both_hosts_and_version_suffix() -> None:
    assert _derive_arxiv_id("https://arxiv.org/abs/2403.12345") == "2403.12345"
    assert _derive_arxiv_id("https://arxiv.org/pdf/2403.12345v2") == "2403.12345"
    assert _derive_arxiv_id("https://huggingface.co/papers/2403.12345") == "2403.12345"
    assert _derive_arxiv_id("https://example.com/other") == ""


def test_dry_run_makes_no_writes_and_counts_skips() -> None:
    documents = MagicMock()
    documents.list_arxiv_documents_missing_authors.return_value = [
        _row("2403.12345"),
        _row("2403.12346", "https://huggingface.co/papers/2403.12346"),
        {"id": "deadbeef", "url": "https://example.com/no-id"},  # missing_id
        {"id": "not-the-md5", "url": "https://arxiv.org/abs/2403.12347"},  # id_mismatch
    ]
    fetcher = MagicMock(
        return_value=[
            {"arxiv_id": "2403.12345", "authors": ["A", "B"]},
            {"arxiv_id": "2403.12346", "authors": ["C"]},
        ]
    )

    result = backfill_authors(documents, fetcher, limit=10, dry_run=True)

    assert result["status"] == "dry_run"
    assert result["scanned"] == 4
    assert result["missing_id"] == 1
    assert result["id_mismatch"] == 1
    assert result["planned_updates"] == 2
    assert result["updated"] == 0
    documents.update_document_authors.assert_not_called()


def test_write_path_updates_with_dumped_json_and_capped_authors() -> None:
    documents = MagicMock()
    documents.list_arxiv_documents_missing_authors.return_value = [
        _row("2403.12345"),
        _row("2403.12346"),  # fetcher 未返回 → 跳过
    ]
    fetcher = MagicMock(
        return_value=[
            {"arxiv_id": "2403.12345", "authors": ["A1", "A2", "A3", "A4", "A5", "A6"]},
        ]
    )

    result = backfill_authors(documents, fetcher, limit=10, sleep_seconds=0)

    assert result["status"] == "success"
    assert result["updated"] == 1
    documents.update_document_authors.assert_called_once_with(
        _doc_id("2403.12345"),
        json.dumps(["A1", "A2", "A3", "A4", "A5"], ensure_ascii=False),
        "2403.12345",
    )


def test_idempotent_resume_passes_cursor_and_reports_last_id() -> None:
    documents = MagicMock()
    documents.list_arxiv_documents_missing_authors.return_value = [_row("2403.12345")]
    fetcher = MagicMock(return_value=[{"arxiv_id": "2403.12345", "authors": ["A"]}])

    result = backfill_authors(documents, fetcher, after_id="cursor-x", limit=1, sleep_seconds=0)

    documents.list_arxiv_documents_missing_authors.assert_called_once_with(
        after_id="cursor-x", limit=1
    )
    assert result["last_id"] == _doc_id("2403.12345")
