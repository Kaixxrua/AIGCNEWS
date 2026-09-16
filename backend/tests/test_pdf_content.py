import base64
import io

import pdfplumber
from PIL import Image

from backend.app.services.papers.pdf_content import extract_text, render_page_images
from backend.tests.pdf_fixtures import write_text_pdf


def test_text_extraction_preserves_page_order_and_limits(tmp_path):
    path = write_text_pdf(tmp_path / "paper.pdf", ["First page", "", "Last page"])
    assert extract_text(str(path)) == "First page\nLast page"
    assert extract_text(str(path), max_pages=2) == "First page"
    assert extract_text(str(path), max_chars=5) == "First"


def test_text_falls_back_when_primary_parser_fails(tmp_path, monkeypatch):
    path = write_text_pdf(tmp_path / "paper.pdf", ["Fallback text"])
    def fail(*args, **kwargs):
        raise ValueError("unreadable")
    monkeypatch.setattr(pdfplumber, "open", fail)
    assert extract_text(str(path)) == "Fallback text"


def test_missing_invalid_and_blank_documents_degrade_to_empty(tmp_path):
    for path in (tmp_path / "missing.pdf", tmp_path / "invalid.pdf"):
        if path.name == "invalid.pdf":
            path.write_bytes(b"invalid PDF")
        assert extract_text(str(path)) == ""
        assert render_page_images(str(path)) == []
    blank = write_text_pdf(tmp_path / "blank.pdf", [""])
    assert extract_text(str(blank)) == ""


def test_page_images_prioritize_figures_and_bound_dimensions(tmp_path):
    path = write_text_pdf(tmp_path / "paper.pdf", ["Introduction", "Figure 1: Results", "Appendix"])
    images = render_page_images(str(path), max_images=1, max_edge=400)
    assert len(images) == 1
    assert images[0].page_number == 2
    assert images[0].data_url.startswith("data:image/jpeg;base64,")
    with Image.open(io.BytesIO(base64.b64decode(images[0].data_url.split(",", 1)[1]))) as image:
        assert image.format == "JPEG"
        assert max(image.size) <= 400
        assert image.getextrema() != ((255, 255), (255, 255), (255, 255))


def test_scanned_or_blank_page_can_be_rendered_for_vision(tmp_path):
    path = write_text_pdf(tmp_path / "scanned.pdf", [""])
    assert len(render_page_images(str(path), max_images=1)) == 1
    assert render_page_images(str(path), max_images=0) == []
