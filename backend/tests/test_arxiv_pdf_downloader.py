"""arxiv_pdf_downloader：arXiv XML 解析、PDF 落盘、文本提取与切片索引契约测试。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from backend.app.services.ingestion import arxiv_pdf_downloader
from backend.app.services.ingestion.arxiv_pdf_downloader import (
    _chunk_and_index,
    _download_one_pdf,
    _extract_text_from_local_pdf,
    _fetch_arxiv_metadata_by_ids,
    _parse_arxiv_xml,
    download_and_index_arxiv_pdfs,
)

_SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2403.12345v2</id>
    <title>  A   Title
    With   Spaces </title>
    <summary> Line one
       line two </summary>
    <published>2024-03-01T00:00:00Z</published>
    <author><name>Alice</name></author>
    <author><name>Bob</name></author>
  </entry>
  <entry>
    <id>not-an-arxiv-id</id>
    <title>Skipped</title>
  </entry>
</feed>
"""


def _many_authors_xml(count: int) -> str:
    authors = "\n".join(f"    <author><name>Author{i}</name></author>" for i in range(count))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom">\n'
        "  <entry>\n"
        "    <id>http://arxiv.org/abs/2403.99999v1</id>\n"
        "    <title>T</title>\n"
        f"{authors}\n"
        "  </entry>\n"
        "</feed>\n"
    )


class TestParseArxivXml:
    def test_parses_metadata_and_strips_version(self) -> None:
        papers = _parse_arxiv_xml(_SAMPLE_XML)
        assert len(papers) == 1
        paper = papers[0]
        assert paper["arxiv_id"] == "2403.12345"
        assert paper["title"] == "A Title With Spaces"
        assert paper["abstract"] == "Line one line two"
        assert paper["authors"] == ["Alice", "Bob"]
        assert paper["published_date"] == "2024-03-01T00:00:00Z"
        assert paper["pdf_url"] == "https://arxiv.org/pdf/2403.12345"
        assert paper["original_arxiv_url"] == "https://arxiv.org/abs/2403.12345"
        assert paper["url"] == "https://huggingface.co/papers/2403.12345"
        assert paper["source"] == "arxiv"

    def test_skips_entry_without_valid_arxiv_id(self) -> None:
        papers = _parse_arxiv_xml(_SAMPLE_XML)
        assert [p["arxiv_id"] for p in papers] == ["2403.12345"]

    def test_authors_capped_at_five(self) -> None:
        papers = _parse_arxiv_xml(_many_authors_xml(7))
        assert papers[0]["authors"] == [f"Author{i}" for i in range(5)]

    def test_malformed_xml_returns_empty(self) -> None:
        assert _parse_arxiv_xml("<feed><broken") == []


class TestFetchArxivMetadata:
    def test_empty_ids_short_circuits(self) -> None:
        assert _fetch_arxiv_metadata_by_ids([]) == []

    def test_http_failure_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class BoomClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            def __enter__(self) -> "BoomClient":
                return self

            def __exit__(self, *exc: Any) -> bool:
                return False

            def get(self, *args: Any, **kwargs: Any) -> Any:
                raise ConnectionError("api down")

        monkeypatch.setattr(arxiv_pdf_downloader.httpx, "Client", BoomClient)
        assert _fetch_arxiv_metadata_by_ids(["2403.12345"]) == []

    def test_success_sends_id_list_and_parses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        class FakeClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            def __enter__(self) -> "FakeClient":
                return self

            def __exit__(self, *exc: Any) -> bool:
                return False

            def get(self, url: str, params: Any = None) -> Any:
                captured["url"] = url
                captured["params"] = params
                return SimpleNamespace(text=_SAMPLE_XML, raise_for_status=lambda: None)

        monkeypatch.setattr(arxiv_pdf_downloader.httpx, "Client", FakeClient)
        papers = _fetch_arxiv_metadata_by_ids(["2403.12345", "2312.00001"], timeout=5)
        assert captured["params"] == {"id_list": "2403.12345,2312.00001", "max_results": 2}
        assert [p["arxiv_id"] for p in papers] == ["2403.12345"]


@pytest.fixture
def storage_dir(tmp_path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "papers"
    monkeypatch.setattr(arxiv_pdf_downloader.settings, "papers_storage_dir", str(target))
    return target


def _pdf_client(content: bytes = b"%PDF-1.4 fake", content_type: str = "application/pdf") -> type:
    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *exc: Any) -> bool:
            return False

        def get(self, url: str) -> Any:
            return SimpleNamespace(
                headers={"content-type": content_type},
                content=content,
                raise_for_status=lambda: None,
            )

    return FakeClient


class TestDownloadOnePdf:
    def test_existing_large_file_skips_http(self, storage_dir, monkeypatch: pytest.MonkeyPatch) -> None:
        storage_dir.mkdir(parents=True)
        existing = storage_dir / "2403.12345.pdf"
        existing.write_bytes(b"x" * 2048)

        class GuardClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                raise AssertionError("不应发起 HTTP 请求")

        monkeypatch.setattr(arxiv_pdf_downloader.httpx, "Client", GuardClient)
        assert _download_one_pdf("2403.12345", "https://arxiv.org/pdf/2403.12345", sleep_seconds=0) == str(existing)

    def test_success_writes_file_and_returns_path(self, storage_dir, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(arxiv_pdf_downloader.httpx, "Client", _pdf_client())
        local = _download_one_pdf("2403.12345", "https://arxiv.org/pdf/2403.12345", sleep_seconds=0)
        assert local == str(storage_dir / "2403.12345.pdf")
        assert (storage_dir / "2403.12345.pdf").read_bytes() == b"%PDF-1.4 fake"

    def test_non_pdf_content_type_rejected(self, storage_dir, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            arxiv_pdf_downloader.httpx, "Client", _pdf_client(content_type="text/html")
        )
        assert _download_one_pdf("2403.12345", "https://arxiv.org/pdf/2403.12345", sleep_seconds=0) is None
        assert not (storage_dir / "2403.12345.pdf").exists()

    def test_http_error_returns_none_and_cleans_partial_file(
        self, storage_dir, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        storage_dir.mkdir(parents=True)
        partial = storage_dir / "2403.12345.pdf"
        partial.write_bytes(b"tiny")  # 小于 1024，视为残破文件

        class BoomClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            def __enter__(self) -> "BoomClient":
                return self

            def __exit__(self, *exc: Any) -> bool:
                return False

            def get(self, url: str) -> Any:
                raise ConnectionError("down")

        monkeypatch.setattr(arxiv_pdf_downloader.httpx, "Client", BoomClient)
        assert _download_one_pdf("2403.12345", "https://arxiv.org/pdf/2403.12345", sleep_seconds=0) is None
        assert not partial.exists()


class TestExtractText:
    def test_missing_file_returns_empty(self, tmp_path) -> None:
        assert _extract_text_from_local_pdf(str(tmp_path / "nope.pdf")) == ""

    def test_extracts_text_without_pymupdf(self, tmp_path) -> None:
        from backend.tests.pdf_fixtures import write_text_pdf

        pdf_path = write_text_pdf(tmp_path / "paper.pdf", ["Hello arXiv world"])
        text = _extract_text_from_local_pdf(str(pdf_path))
        assert "Hello arXiv world" in text


def _paper() -> dict[str, Any]:
    return {
        "arxiv_id": "2403.12345",
        "title": "T",
        "abstract": "abs",
        "published_date": "2024-03-01",
        "url": "https://huggingface.co/papers/2403.12345",
        "pdf_url": "https://arxiv.org/pdf/2403.12345",
        "raw_score": "7",
        "source_channel": "huggingface_daily_html",
    }


class FakeMilvus:
    def __init__(self) -> None:
        self.added: tuple[Any, bool] | None = None

    def add_documents(self, docs: list, already_split: bool = False) -> None:
        self.added = (docs, already_split)


class TestChunkAndIndex:
    def test_empty_text_returns_false(self) -> None:
        assert _chunk_and_index(_paper(), "doc1", "", FakeMilvus(), None) is False

    def test_chunks_written_with_stable_metadata(self) -> None:
        milvus = FakeMilvus()
        full_text = "word " * 800  # 约 4000 字符，超过 3000 的 chunk_size → 多 chunk
        assert _chunk_and_index(_paper(), "doc1", full_text, milvus, None) is True
        assert milvus.added is not None
        docs, already_split = milvus.added
        assert already_split is True
        assert len(docs) >= 2
        for index, doc in enumerate(docs):
            expected_id = "doc1" if index == 0 else f"doc1_chunk{index}"
            assert doc.metadata["id"] == expected_id
            assert doc.metadata["chunk_index"] == index
            assert doc.metadata["total_chunks"] == len(docs)
            assert doc.metadata["raw_score"] == 7.0
            assert doc.metadata["title"] == "T"
        assert docs[0].page_content == "Abstract:\nabs"  # 小片段独立成首个 chunk
        assert any("Full Paper:" in doc.page_content for doc in docs[1:])

    def test_milvus_failure_returns_false(self) -> None:
        class BoomMilvus:
            def add_documents(self, *args: Any, **kwargs: Any) -> None:
                raise RuntimeError("milvus down")

        assert _chunk_and_index(_paper(), "doc1", "some text", BoomMilvus(), None) is False


class FakeDocumentWriter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def update_document_pdf_path(self, doc_id: str, local_path: str) -> None:
        self.calls.append((doc_id, local_path))


class TestDownloadAndIndexPipeline:
    def test_no_pending_papers_returns_zero(self) -> None:
        assert download_and_index_arxiv_pdfs([]) == (0, 0)
        assert download_and_index_arxiv_pdfs([{"arxiv_id": "2403.1"}]) == (0, 0)  # 缺 pdf_url
        assert download_and_index_arxiv_pdfs([{"pdf_url": "u"}]) == (0, 0)  # 缺 arxiv_id

    def test_happy_path_downloads_updates_writer_and_indexes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            arxiv_pdf_downloader,
            "_download_one_pdf",
            lambda arxiv_id, pdf_url, sleep_seconds=0: f"storage/papers/{arxiv_id}.pdf",
        )
        monkeypatch.setattr(arxiv_pdf_downloader, "_extract_text_from_local_pdf", lambda path: "full text")
        monkeypatch.setattr(arxiv_pdf_downloader, "_chunk_and_index", lambda **kwargs: True)
        monkeypatch.setattr(
            "backend.app.services.ingestion.pipeline._doc_id",
            lambda paper: f"doc-{paper['arxiv_id']}",
        )
        writer = FakeDocumentWriter()
        downloaded, indexed = download_and_index_arxiv_pdfs(
            [{"arxiv_id": "2403.1", "pdf_url": "https://arxiv.org/pdf/2403.1"}],
            document_writer=writer,
            sleep_between=0,
        )
        assert (downloaded, indexed) == (1, 1)
        assert writer.calls == [("doc-2403.1", "storage/papers/2403.1.pdf")]

    def test_download_failure_skips_writer_and_index(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(arxiv_pdf_downloader, "_download_one_pdf", lambda *args, **kwargs: None)
        writer = FakeDocumentWriter()
        downloaded, indexed = download_and_index_arxiv_pdfs(
            [{"arxiv_id": "2403.1", "pdf_url": "u"}],
            document_writer=writer,
            sleep_between=0,
        )
        assert (downloaded, indexed) == (0, 0)
        assert writer.calls == []

    def test_empty_extraction_counts_download_but_not_index(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            arxiv_pdf_downloader, "_download_one_pdf", lambda *args, **kwargs: "storage/papers/2403.1.pdf"
        )
        monkeypatch.setattr(arxiv_pdf_downloader, "_extract_text_from_local_pdf", lambda path: "")
        monkeypatch.setattr(
            "backend.app.services.ingestion.pipeline._doc_id", lambda paper: "doc-2403.1"
        )
        downloaded, indexed = download_and_index_arxiv_pdfs(
            [{"arxiv_id": "2403.1", "pdf_url": "u"}], sleep_between=0
        )
        assert (downloaded, indexed) == (1, 0)
