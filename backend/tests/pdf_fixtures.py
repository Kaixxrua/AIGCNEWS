"""Small generated PDF fixtures independent of the text and image extractors."""

from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def write_text_pdf(path: Path, texts: list[str]) -> Path:
    with PdfWriter() as writer:
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        for text in texts:
            page = writer.add_blank_page(width=612, height=792)
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
            })
            if text:
                stream = DecodedStreamObject()
                escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                stream.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET\n0.8 0.2 0.2 rg 72 500 160 80 re f\n".encode("ascii"))
                page[NameObject("/Contents")] = writer._add_object(stream)
        writer.write(path)
    return path
