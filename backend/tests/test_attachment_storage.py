from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.services.chat import attachment_storage


class FakeClock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class ImageCacheTests(unittest.TestCase):
    def test_put_uses_600_second_ttl_and_decoded_payload_contract(self) -> None:
        clock = FakeClock(1000.0)
        cache = attachment_storage.ImageCache(clock=clock)

        expires_at = asyncio.run(cache.put("image", "encoded", "image/png"))

        self.assertEqual(expires_at, 1600.0)
        self.assertEqual(cache._entries["image"], ("encoded", "image/png", 1600.0))
        self.assertEqual(asyncio.run(cache.get("image")), ("encoded", "image/png"))

    def test_expiry_boundaries_match_existing_cache(self) -> None:
        clock = FakeClock(1000.0)
        cache = attachment_storage.ImageCache(clock=clock)
        cache._entries.update(
            {
                "expired": ("old", "image/png", 999.0),
                "boundary": ("edge", "image/png", 1000.0),
            }
        )

        asyncio.run(cache.put("new", "new-data", "image/jpeg"))

        self.assertNotIn("expired", cache._entries)
        self.assertIn("boundary", cache._entries)
        clock.now = 1600.0
        self.assertEqual(asyncio.run(cache.get("new")), ("new-data", "image/jpeg"))
        clock.now = 1600.001
        self.assertIsNone(asyncio.run(cache.get("new")))


class PdfStorageTests(unittest.TestCase):
    def test_path_write_and_exists_use_uuid_pdf_filename(self) -> None:
        with tempfile.TemporaryDirectory() as upload_dir:
            storage = attachment_storage.PdfStorage(upload_dir)
            storage.write("attachment-id", b"%PDF-1.7\n")

            expected = os.path.join(upload_dir, "attachment-id.pdf")
            self.assertEqual(storage.path_for("attachment-id"), expected)
            self.assertTrue(storage.exists("attachment-id"))
            with open(expected, "rb") as file:
                self.assertEqual(file.read(), b"%PDF-1.7\n")

    def test_extract_text_wraps_sync_extractor_in_to_thread(self) -> None:
        extractor = MagicMock(return_value=("text", 2))
        storage = attachment_storage.PdfStorage("/tmp/uploads", extractor=extractor)

        with patch.object(
            attachment_storage.asyncio,
            "to_thread",
            new=AsyncMock(return_value=("text", 2)),
        ) as to_thread:
            result = asyncio.run(storage.extract_text("attachment-id"))

        self.assertEqual(result, ("text", 2))
        to_thread.assert_awaited_once_with(
            extractor, "/tmp/uploads/attachment-id.pdf"
        )

    def test_extract_pdf_text_preserves_page_order_and_closes_document(self) -> None:
        pages = [MagicMock(), MagicMock()]
        pages[0].get_text.return_value = "first"
        pages[1].get_text.return_value = "second"
        document = MagicMock()
        document.__len__.return_value = 2
        document.__iter__.return_value = iter(pages)
        fitz = MagicMock()
        fitz.open.return_value = document

        with patch.dict("sys.modules", {"fitz": fitz}):
            result = attachment_storage.extract_pdf_text("report.pdf")

        self.assertEqual(result, ("first\nsecond", 2))
        fitz.open.assert_called_once_with("report.pdf")
        document.close.assert_called_once_with()


class PrivateUploadDirContractTests(unittest.TestCase):
    """私有聊天附件目录必须位于 /api/media/papers 匿名静态挂载树之外。"""

    def test_default_upload_dir_is_outside_papers_storage_tree(self) -> None:
        papers_dir = os.path.abspath(
            getattr(attachment_storage.settings, "papers_storage_dir", "storage/papers")
        )
        upload_dir = os.path.abspath(attachment_storage.DEFAULT_PDF_UPLOAD_DIR)

        self.assertNotEqual(
            os.path.commonpath([papers_dir, upload_dir]),
            papers_dir,
            "聊天附件目录落在公开静态挂载树内，匿名用户可绕过属主校验下载私有 PDF",
        )

    def test_service_module_uses_same_private_dir(self) -> None:
        from backend.app.services.chat import attachment_service

        self.assertEqual(
            os.path.abspath(attachment_service._PDF_UPLOAD_DIR),
            os.path.abspath(attachment_storage.DEFAULT_PDF_UPLOAD_DIR),
        )

    def test_migrate_legacy_uploads_moves_pdfs_and_removes_legacy_dir(self) -> None:
        with tempfile.TemporaryDirectory() as legacy_dir, tempfile.TemporaryDirectory() as target_dir:
            for name in ("a.pdf", "b.pdf", "keep.txt"):
                with open(os.path.join(legacy_dir, name), "wb") as file:
                    file.write(b"%PDF-1.7\n")

            moved = attachment_storage.migrate_legacy_pdf_uploads(legacy_dir, target_dir)

            self.assertEqual(moved, 2)
            self.assertTrue(os.path.exists(os.path.join(target_dir, "a.pdf")))
            self.assertTrue(os.path.exists(os.path.join(target_dir, "b.pdf")))
            # 非 PDF 残留导致目录保留，但 PDF 已全部迁出
            self.assertFalse(os.path.exists(os.path.join(legacy_dir, "a.pdf")))

    def test_migrate_legacy_uploads_noop_when_dirs_match(self) -> None:
        with tempfile.TemporaryDirectory() as same_dir:
            self.assertEqual(
                attachment_storage.migrate_legacy_pdf_uploads(same_dir, same_dir), 0
            )


if __name__ == "__main__":
    unittest.main()
