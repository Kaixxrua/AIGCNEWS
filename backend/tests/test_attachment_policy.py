from __future__ import annotations

import base64
import unittest

from backend.app.services.chat.attachment_policy import (
    MAX_IMAGE_BYTES,
    AttachmentValidationError,
    image_extension,
    safe_display_filename,
    validate_image_attachment,
    validate_image_bytes,
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


    def test_display_filename_removes_paths_and_controls(self) -> None:
        self.assertEqual(safe_display_filename("..\\dir/evil\x00.pdf", "x.pdf"), "evil.pdf")
        self.assertEqual(safe_display_filename("../..", "upload.pdf"), "upload.pdf")

    def test_validate_image_bytes_multipart_entry(self) -> None:
        """bytes 入口（multipart 上传）与 base64 入口共享同一套规则表。"""
        png = b"\x89PNG\r\n\x1a\ncontent"
        validated = validate_image_bytes(png, "image/png", "../qr.png")
        self.assertEqual(validated.data, png)
        self.assertEqual(validated.mime_type, "image/png")
        self.assertEqual(validated.filename, "qr.png")

        with self.assertRaisesRegex(AttachmentValidationError, "仅支持"):
            validate_image_bytes(b"<svg></svg>", "image/svg+xml")
        with self.assertRaisesRegex(AttachmentValidationError, "不匹配"):
            validate_image_bytes(b"\xff\xd8\xffjpeg", "image/png")
        with self.assertRaisesRegex(AttachmentValidationError, "10 MiB"):
            validate_image_bytes(b"\xff\xd8\xff" + b"x" * MAX_IMAGE_BYTES, "image/jpeg")
        with self.assertRaisesRegex(AttachmentValidationError, "图片数据格式无效"):
            validate_image_bytes(b"", "image/png")

    def test_image_extension_maps_allowed_mimes(self) -> None:
        self.assertEqual(image_extension("image/png"), ".png")
        self.assertEqual(image_extension("image/jpeg"), ".jpg")
        self.assertEqual(image_extension("image/webp"), ".webp")


if __name__ == "__main__":
    unittest.main()
