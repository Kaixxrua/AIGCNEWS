from backend.app.services.briefing import paper_evidence
from backend.app.services.papers.pdf_content import PdfPageImage
from backend.tests.pdf_fixtures import write_text_pdf


def test_daily_paper_evidence_contains_text_and_attributed_images(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_evidence.settings, "papers_storage_dir", str(tmp_path))
    write_text_pdf(tmp_path / "2403.12345.pdf", ["Figure 1: New method"])
    context, blocks = paper_evidence.paper_pdf_evidence([
        {"id": "one", "arxiv_id": "2403.12345", "source": "arxiv", "title": "New method", "url": "https://arxiv.org/abs/2403.12345"},
    ], source="arxiv")
    assert "Figure 1: New method" in context
    assert "New method" in blocks[0]["text"]
    assert "第 1 页" in blocks[0]["text"]
    assert blocks[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_missing_or_outside_paper_storage_is_not_read(tmp_path, monkeypatch):
    storage = tmp_path / "papers"
    storage.mkdir()
    outside = write_text_pdf(tmp_path / "private.pdf", ["Private"])
    monkeypatch.setattr(paper_evidence.settings, "papers_storage_dir", str(storage))
    context, blocks = paper_evidence.paper_pdf_evidence([
        {"source": "arxiv", "local_pdf_path": str(outside)},
        {"source": "arxiv", "arxiv_id": "../private"},
        {"source": "arxiv", "arxiv_id": "2403.12345"},
    ], source="arxiv")
    assert (context, blocks) == ("", [])
    assert paper_evidence.paper_pdf_evidence([], source="x") == ("", [])


def test_evidence_limits_duplicate_papers_and_image_count(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_evidence.settings, "papers_storage_dir", str(tmp_path))
    monkeypatch.setattr(paper_evidence, "extract_text", lambda path, max_chars: "x" * max_chars)
    monkeypatch.setattr(paper_evidence, "render_page_images", lambda path, max_images: [PdfPageImage(1, "data:image/jpeg;base64,test")])
    docs = []
    for index in range(12):
        path = tmp_path / f"{index}.pdf"
        path.write_bytes(b"fixture")
        docs.append({"source": "arxiv", "local_pdf_path": str(path), "title": str(index)})
    context, blocks = paper_evidence.paper_pdf_evidence(docs + docs, source="all")
    assert context.count("PDF 正文节选：") == 10
    assert sum(block["type"] == "image_url" for block in blocks) == 6
