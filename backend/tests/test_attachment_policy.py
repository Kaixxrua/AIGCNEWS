from __future__ import annotations

import base64
import unittest

from backend.app.services.chat.attachment_policy import (
    AttachmentValidationError,
    MAX_IMAGE_BYTES,
    MAX_PDF_BYTES,
    safe_display_filename,
    validate_image_attachment,
    validate_pdf_attachment,
)


class AttachmentPolicyTests(unittest.TestCase):
    def test_strict_base64_and_data_uri_mime(self) -> None:
        png = b"\x89PNG\r\n\x1a\ncontent"
        encoded = base64.b64encode(png).decode()

        validated = validate_image_attachment(
            f"data:image/png;base64,{encoded}", "image/png", "../safe.png"
        )

        self.assertEqual(validated.data, png)
        self.assertEqual(validated.filename, "safe.png")
        with self.assertRaisesRegex(AttachmentValidationError, "MIME"):
            validate_image_attachment(
                f"data:image/png;base64,{encoded}", "image/jpeg"
            )
        with self.assertRaisesRegex(AttachmentValidationError, "格式"):
            validate_image_attachment("not!base64", "image/png")

    def test_supported_signatures_are_bound_to_declared_mime(self) -> None:
        samples = {
            "image/jpeg": b"\xff\xd8\xffdata",
            "image/png": b"\x89PNG\r\n\x1a\ndata",
            "image/gif": b"GIF89adata",
            "image/webp": b"RIFF\x04\x00\x00\x00WEBPdata",
        }
        for mime_type, data in samples.items():
            with self.subTest(mime_type=mime_type):
                result = validate_image_attachment(
                    base64.b64encode(data).decode(), mime_type
                )
                self.assertEqual(result.mime_type, mime_type)

        png = base64.b64encode(samples["image/png"]).decode()
        with self.assertRaisesRegex(AttachmentValidationError, "不匹配"):
            validate_image_attachment(png, "image/jpeg")

    def test_svg_and_oversized_image_are_rejected(self) -> None:
        svg = base64.b64encode(b"<svg></svg>").decode()
        with self.assertRaisesRegex(AttachmentValidationError, "仅支持"):
            validate_image_attachment(svg, "image/svg+xml")

        oversized = base64.b64encode(
            b"\xff\xd8\xff" + b"x" * (MAX_IMAGE_BYTES - 2)
        ).decode()
        with self.assertRaisesRegex(AttachmentValidationError, "10 MiB"):
            validate_image_attachment(oversized, "image/jpeg")

    def test_pdf_magic_size_and_filename(self) -> None:
        result = validate_pdf_attachment(b"%PDF-1.7\n", "../../report.pdf")
        self.assertEqual(result.filename, "report.pdf")

        with self.assertRaisesRegex(AttachmentValidationError, "内容无效"):
            validate_pdf_attachment(b"not a pdf", "report.pdf")
        with self.assertRaisesRegex(AttachmentValidationError, "50 MiB"):
            validate_pdf_attachment(b"%PDF-" + b"x" * MAX_PDF_BYTES)

    def test_display_filename_removes_paths_and_controls(self) -> None:
        self.assertEqual(safe_display_filename("..\\dir/evil\x00.pdf", "x.pdf"), "evil.pdf")
        self.assertEqual(safe_display_filename("../..", "upload.pdf"), "upload.pdf")


if __name__ == "__main__":
    unittest.main()
