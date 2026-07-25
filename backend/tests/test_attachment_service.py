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

    def test_image_cache_uses_600_second_ttl_and_strict_expiry(self) -> None:
        content = ValidatedImage(
            data=b"\xff\xd8\xffdata",
            base64_data="/9j/ZGF0YQ==",
            mime_type="image/jpeg",
            filename="photo.jpg",
        )

        async def exercise() -> None:
            with patch.object(attachment_service.time, "time", return_value=1000.0):
                meta = await attachment_service.upload_image(content, user_id=7)
            self.assertEqual(meta.expires_at, 1600.0)
            self.assertEqual(
                attachment_service._image_cache[meta.id],
                (content.base64_data, content.mime_type, 1600.0),
            )
            with patch.object(attachment_service.time, "time", return_value=1600.0):
                self.assertEqual(
                    await attachment_service.get_image_base64(meta.id, 7),
                    (content.base64_data, content.mime_type),
                )
            with patch.object(attachment_service.time, "time", return_value=1600.001):
                self.assertIs(
                    await attachment_service.get_image_base64(meta.id, 7), None
                )
            self.assertEqual(meta.status, attachment_service.AttachmentStatus.READY)

        asyncio.run(exercise())

    def test_upload_evicts_only_previously_expired_images(self) -> None:
        attachment_service._image_cache.update(
            {
                "expired": ("old", "image/png", 999.0),
                "boundary": ("edge", "image/png", 1000.0),
            }
        )
        content = ValidatedImage(
            data=b"\x89PNG\r\n\x1a\ndata",
            base64_data="iVBORw0KGgpkYXRh",
            mime_type="image/png",
            filename="photo.png",
        )

        with patch.object(attachment_service.time, "time", return_value=1000.0):
            meta = asyncio.run(attachment_service.upload_image(content, user_id=7))

        self.assertNotIn("expired", attachment_service._image_cache)
        self.assertIn("boundary", attachment_service._image_cache)
        self.assertIn(meta.id, attachment_service._image_cache)

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

    def test_pdf_registers_processing_before_sync_write_and_threaded_parse(self) -> None:
        content = ValidatedPdf(data=b"%PDF-1.7\nbody", filename="report.pdf")
        observed: dict[str, object] = {}

        class RecordingFile:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def write(self, data: bytes) -> int:
                meta = next(iter(attachment_service._attachment_registry.values()))
                observed["status_at_write"] = meta.status
                observed["bytes"] = data
                return len(data)

        async def run_in_thread(function, *args):
            observed["thread_call"] = (function, args)
            return "preview" * 100, 3

        with (
            patch.object(attachment_service, "_PDF_UPLOAD_DIR", "/tmp/contracts"),
            patch("builtins.open", return_value=RecordingFile()) as opened,
            patch.object(attachment_service.asyncio, "to_thread", new=run_in_thread),
        ):
            meta = asyncio.run(attachment_service.upload_pdf(content, user_id=7))

        opened.assert_called_once_with(f"/tmp/contracts/{meta.id}.pdf", "wb")
        self.assertEqual(observed["status_at_write"], attachment_service.AttachmentStatus.PROCESSING)
        self.assertEqual(observed["bytes"], content.data)
        self.assertEqual(
            observed["thread_call"],
            (attachment_service._extract_pdf_text, (f"/tmp/contracts/{meta.id}.pdf",)),
        )
        self.assertEqual(meta.status, attachment_service.AttachmentStatus.READY)
        self.assertEqual(meta.page_count, 3)
        self.assertEqual(meta.text_preview, ("preview" * 100)[:500])

    def test_pdf_write_failure_keeps_registration_without_file_cleanup(self) -> None:
        content = ValidatedPdf(data=b"%PDF-1.7\n", filename="report.pdf")
        with (
            tempfile.TemporaryDirectory() as upload_dir,
            patch.object(attachment_service, "_PDF_UPLOAD_DIR", upload_dir),
            patch("builtins.open", side_effect=OSError("disk detail")),
        ):
            meta = asyncio.run(attachment_service.upload_pdf(content, user_id=7))

        self.assertIs(attachment_service._attachment_registry[meta.id], meta)
        self.assertEqual(meta.status, attachment_service.AttachmentStatus.ERROR)
        self.assertEqual(meta.error_msg, "附件保存失败")

    def test_pdf_parse_failure_leaves_written_file_and_registration(self) -> None:
        content = ValidatedPdf(data=b"%PDF-1.7\n", filename="report.pdf")
        with tempfile.TemporaryDirectory() as upload_dir:
            with (
                patch.object(attachment_service, "_PDF_UPLOAD_DIR", upload_dir),
                patch.object(
                    attachment_service,
                    "_extract_pdf_text",
                    side_effect=RuntimeError("parse detail"),
                ),
            ):
                meta = asyncio.run(attachment_service.upload_pdf(content, user_id=7))
                path = os.path.join(upload_dir, f"{meta.id}.pdf")
                self.assertTrue(os.path.exists(path))

        self.assertIs(attachment_service._attachment_registry[meta.id], meta)
        self.assertEqual(meta.status, attachment_service.AttachmentStatus.ERROR)
        self.assertEqual(meta.error_msg, "PDF 解析失败")

    def test_list_preserves_requested_order_duplicates_and_owner_filter(self) -> None:
        first = attachment_service.AttachmentMeta(
            id="first",
            user_id=7,
            type=attachment_service.AttachmentType.IMAGE,
            status=attachment_service.AttachmentStatus.READY,
        )
        second = attachment_service.AttachmentMeta(
            id="second",
            user_id=7,
            type=attachment_service.AttachmentType.PDF,
            status=attachment_service.AttachmentStatus.PROCESSING,
        )
        other = attachment_service.AttachmentMeta(
            id="other",
            user_id=8,
            type=attachment_service.AttachmentType.IMAGE,
            status=attachment_service.AttachmentStatus.READY,
        )
        attachment_service._attachment_registry.update(
            {meta.id: meta for meta in (first, second, other)}
        )

        result = asyncio.run(
            attachment_service.list_attachments(
                ["second", "missing", "first", "second", "other"], 7
            )
        )

        self.assertEqual(result, [second, first, second])

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
