"""Bounded PDF text extraction and page images for background paper processing."""

from __future__ import annotations

import base64
import io
import logging
import math
import re
import threading
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)
_PDFIUM_LOCK = threading.Lock()
_FIGURE = re.compile(r"\b(?:fig(?:ure)?\.?|table)\s*\d+|[图表]\s*\d+", re.IGNORECASE)


def extract_text(path: str, *, max_pages: int = 50, max_chars: int = 40_000) -> str:
    """Read text without OCR; blank or damaged documents produce an empty string."""
    if not path or not Path(path).is_file() or max_pages <= 0 or max_chars <= 0:
        return ""
    for parser in ("pdfplumber", "pypdf"):
        try:
            if parser == "pdfplumber":
                import pdfplumber

                document = pdfplumber.open(path)
            else:
                from pypdf import PdfReader

                document = PdfReader(path)
            with closing(document):
                parts: list[str] = []
                length = 0
                for page in document.pages[:max_pages]:
                    try:
                        text = page.extract_text() or ""
                    except Exception as exc:
                        logger.debug("Skipping unreadable PDF page (%s): %s", parser, exc)
                        continue
                    if text:
                        parts.append(text)
                        length += len(text)
                    if length >= max_chars:
                        break
                text = re.sub(r"\n{3,}", "\n\n", "\n".join(parts)).strip()
                if text:
                    return text[:max_chars]
        except Exception as exc:
            logger.debug("PDF text parser %s failed for %s: %s", parser, path, exc)
    return ""


@dataclass(frozen=True)
class PdfPageImage:
    page_number: int
    data_url: str


def render_page_images(
    path: str, *, max_images: int = 2, max_pages: int = 12, max_edge: int = 1200,
) -> list[PdfPageImage]:
    """Render diagram pages, including vector graphics, with bounded image sizes."""
    if not path or not Path(path).is_file() or max_images <= 0 or max_pages <= 0:
        return []
    images: list[PdfPageImage] = []
    try:
        import pypdfium2 as pdfium

        # PDFium does not support concurrent calls, even for distinct documents.
        with _PDFIUM_LOCK, closing(pdfium.PdfDocument(path)) as document:
            count = min(len(document), max_pages)
            candidates: list[int] = []
            for index in range(count):
                try:
                    with closing(document[index]) as page, closing(page.get_textpage()) as textpage:
                        if _FIGURE.search(textpage.get_text_range()):
                            candidates.append(index)
                except Exception:
                    continue
            # A page image also lets a vision model read scanned, textless papers.
            candidates.extend(index for index in range(count) if index not in candidates)
            for index in candidates:
                if len(images) >= max_images:
                    break
                try:
                    with closing(document[index]) as page:
                        width, height = page.get_size()
                        if not all(math.isfinite(size) and size > 0 for size in (width, height)):
                            continue
                        scale = min(1.5, max_edge / max(width, height))
                        with closing(page.render(scale=scale)) as bitmap, bitmap.to_pil() as original:
                            with original.convert("RGB") as picture, io.BytesIO() as output:
                                picture.save(output, format="JPEG", quality=80)
                                data = output.getvalue()
                    if len(data) <= 512_000:
                        images.append(PdfPageImage(index + 1, "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")))
                except Exception as exc:
                    logger.debug("Skipping PDF page image %s: %s", index + 1, exc)
    except Exception as exc:
        logger.debug("PDF rendering failed for %s: %s", path, exc)
    return images
