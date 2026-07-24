from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import patch

from backend.app.services.chat import attachment_service
from backend.app.services.chat.attachment_policy import ValidatedImage, ValidatedPdf


class AttachmentServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        attachment_service._attachment_registry.clear()
        attachment_service._image_cache.clear()

    def test_image_is_bound_to_owner_and_uses_decoded_size(self) -> None:
        content = ValidatedImage(
            data=b"\xff\xd8\xffdata",
            base64_data="/9j/ZGF0YQ==",
            mime_type="image/jpeg",
            filename="photo.jpg",
        )

        async def exercise() -> None:
            meta = await attachment_service.upload_image(content, user_id=7)
            self.assertEqual(meta.user_id, 7)
            self.assertEqual(meta.size_bytes, len(content.data))
            self.assertIs(await attachment_service.get_attachment(meta.id, 8), None)
            self.assertIs(await attachment_service.get_image_base64(meta.id, 8), None)
            self.assertEqual(
                await attachment_service.get_image_base64(meta.id, 7),
                (content.base64_data, content.mime_type),
            )
            self.assertEqual(
                await attachment_service.list_attachments([meta.id], 8), []
            )
            self.assertEqual(
                await attachment_service.list_attachments([meta.id], 7), [meta]
            )

        asyncio.run(exercise())

    def test_pdf_text_is_absent_for_other_owner(self) -> None:
        content = ValidatedPdf(data=b"%PDF-1.7\n", filename="report.pdf")
        with tempfile.TemporaryDirectory() as upload_dir:
            with (
                patch.object(attachment_service, "_PDF_UPLOAD_DIR", upload_dir),
                patch.object(
                    attachment_service,
                    "_extract_pdf_text",
                    return_value=("secret", 1),
                ),
            ):
                async def exercise() -> None:
                    meta = await attachment_service.upload_pdf(content, user_id=7)
                    self.assertEqual(meta.status, attachment_service.AttachmentStatus.READY)
                    self.assertEqual(await attachment_service.get_pdf_text(meta.id, 7), "secret")
                    self.assertIs(await attachment_service.get_pdf_text(meta.id, 8), None)
                    self.assertTrue(os.path.exists(os.path.join(upload_dir, f"{meta.id}.pdf")))

                asyncio.run(exercise())

    def test_service_errors_do_not_expose_exception_details(self) -> None:
        content = ValidatedPdf(data=b"%PDF-1.7\n", filename="report.pdf")
        with tempfile.TemporaryDirectory() as upload_dir:
            with (
                patch.object(attachment_service, "_PDF_UPLOAD_DIR", upload_dir),
                patch.object(
                    attachment_service,
                    "_extract_pdf_text",
                    side_effect=RuntimeError("sensitive path"),
                ),
            ):
                meta = asyncio.run(attachment_service.upload_pdf(content, user_id=7))

        self.assertEqual(meta.status, attachment_service.AttachmentStatus.ERROR)
        self.assertEqual(meta.error_msg, "PDF 解析失败")
        self.assertNotIn("sensitive", meta.error_msg)


if __name__ == "__main__":
    unittest.main()
