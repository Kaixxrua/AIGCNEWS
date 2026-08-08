from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import patch

from backend.app.services.chat import attachment_service
from backend.app.services.chat.attachment_policy import ValidatedImage, ValidatedPdf
from backend.app.services.chat.attachment_service import _PostgresMetaStore


class InMemoryMetaStore:
    """In-memory substitute for the PostgreSQL-backed meta store."""

    def __init__(self) -> None:
        self.entries: dict[str, attachment_service.AttachmentMeta] = {}

    async def register(self, meta: attachment_service.AttachmentMeta) -> None:
        self.entries[meta.id] = meta

    async def save(self, meta: attachment_service.AttachmentMeta) -> None:
        self.entries[meta.id] = meta

    async def get_owned(self, attachment_id: str, user_id: int):
        meta = self.entries.get(attachment_id)
        return meta if meta is not None and meta.user_id == user_id else None

    async def list_owned(self, attachment_ids, user_id: int):
        result = []
        for attachment_id in attachment_ids:
            meta = self.entries.get(attachment_id)
            if meta is not None and meta.user_id == user_id:
                result.append(meta)
        return result


class FakeMetaRepository:
    """Row-level fake of PostgresAttachmentMetaRepository for restart tests."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def upsert_attachment_meta(self, **row) -> None:
        self.rows[row["attachment_id"]] = dict(row)

    def get_attachment_meta(self, attachment_id: str, *, user_id=None):
        row = self.rows.get(attachment_id)
        if row is None or (user_id is not None and row["user_id"] != user_id):
            return None
        return dict(row)

    def list_attachment_meta(self, attachment_ids, *, user_id: int):
        return [
            dict(self.rows[attachment_id])
            for attachment_id in attachment_ids
            if attachment_id in self.rows and self.rows[attachment_id]["user_id"] == user_id
        ]

    def existing_attachment_ids(self, attachment_ids) -> set[str]:
        return {attachment_id for attachment_id in attachment_ids if attachment_id in self.rows}

    def delete_expired_attachment_meta(self, now_ts: float) -> int:
        expired = [
            attachment_id
            for attachment_id, row in self.rows.items()
            if row["expires_at"] > 0 and row["expires_at"] < now_ts
        ]
        for attachment_id in expired:
            del self.rows[attachment_id]
        return len(expired)


class AttachmentServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._store = InMemoryMetaStore()
        patcher = patch.object(attachment_service, "_meta_store", self._store)
        patcher.start()
        self.addCleanup(patcher.stop)
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
                    "extract_pdf_text",
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
        store = self._store

        class RecordingFile:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def write(self, data: bytes) -> int:
                meta = next(iter(store.entries.values()))
                observed["status_at_write"] = meta.status
                observed["bytes"] = data
                return len(data)

        async def run_in_thread(function, *args):
            observed["thread_call"] = (function, args)
            return "preview" * 100, 3

        with (
            patch.object(attachment_service, "_PDF_UPLOAD_DIR", "/tmp/contracts"),
            patch("builtins.open", return_value=RecordingFile()) as opened,
            patch(
                "backend.app.services.chat.attachment_storage.asyncio.to_thread",
                new=run_in_thread,
            ),
        ):
            meta = asyncio.run(attachment_service.upload_pdf(content, user_id=7))

        opened.assert_called_once_with(f"/tmp/contracts/{meta.id}.pdf", "wb")
        self.assertEqual(observed["status_at_write"], attachment_service.AttachmentStatus.PROCESSING)
        self.assertEqual(observed["bytes"], content.data)
        self.assertEqual(
            observed["thread_call"],
            (attachment_service.extract_pdf_text, (f"/tmp/contracts/{meta.id}.pdf",)),
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

        self.assertIs(self._store.entries[meta.id], meta)
        self.assertEqual(meta.status, attachment_service.AttachmentStatus.ERROR)
        self.assertEqual(meta.error_msg, "附件保存失败")

    def test_pdf_parse_failure_leaves_written_file_and_registration(self) -> None:
        content = ValidatedPdf(data=b"%PDF-1.7\n", filename="report.pdf")
        with tempfile.TemporaryDirectory() as upload_dir:
            with (
                patch.object(attachment_service, "_PDF_UPLOAD_DIR", upload_dir),
                patch.object(
                    attachment_service,
                    "extract_pdf_text",
                    side_effect=RuntimeError("parse detail"),
                ),
            ):
                meta = asyncio.run(attachment_service.upload_pdf(content, user_id=7))
                path = os.path.join(upload_dir, f"{meta.id}.pdf")
                self.assertTrue(os.path.exists(path))

        self.assertIs(self._store.entries[meta.id], meta)
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
        self._store.entries.update({meta.id: meta for meta in (first, second, other)})

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
                    "extract_pdf_text",
                    side_effect=RuntimeError("sensitive path"),
                ),
            ):
                meta = asyncio.run(attachment_service.upload_pdf(content, user_id=7))

        self.assertEqual(meta.status, attachment_service.AttachmentStatus.ERROR)
        self.assertEqual(meta.error_msg, "PDF 解析失败")
        self.assertNotIn("sensitive", meta.error_msg)


class AttachmentMetaPersistenceTests(unittest.TestCase):
    """Row round-trip via _PostgresMetaStore simulates process restarts."""

    def setUp(self) -> None:
        self._repository = FakeMetaRepository()
        self._store = _PostgresMetaStore(self._repository)
        patcher = patch.object(attachment_service, "_meta_store", self._store)
        patcher.start()
        self.addCleanup(patcher.stop)
        attachment_service._image_cache.clear()

    def test_pdf_metadata_survives_restart_with_owner_scope(self) -> None:
        content = ValidatedPdf(data=b"%PDF-1.7\nbody", filename="report.pdf")
        with tempfile.TemporaryDirectory() as upload_dir:
            with (
                patch.object(attachment_service, "_PDF_UPLOAD_DIR", upload_dir),
                patch.object(
                    attachment_service,
                    "extract_pdf_text",
                    return_value=("full text", 4),
                ),
            ):
                meta = asyncio.run(attachment_service.upload_pdf(content, user_id=7))
                pdf_path = os.path.join(upload_dir, f"{meta.id}.pdf")
                self.assertTrue(os.path.exists(pdf_path))

                # 模拟进程重启：同一“数据库”上的全新仓储/服务适配实例。
                restarted = _PostgresMetaStore(self._repository)
                patcher = patch.object(attachment_service, "_meta_store", restarted)
                patcher.start()
                self.addCleanup(patcher.stop)

                async def exercise() -> None:
                    restored = await attachment_service.get_attachment(meta.id, 7)
                    self.assertIsNotNone(restored)
                    self.assertEqual(restored.id, meta.id)
                    self.assertEqual(restored.user_id, 7)
                    self.assertEqual(restored.type, attachment_service.AttachmentType.PDF)
                    self.assertEqual(restored.status, attachment_service.AttachmentStatus.READY)
                    self.assertEqual(restored.filename, "report.pdf")
                    self.assertEqual(restored.page_count, 4)
                    self.assertEqual(restored.text_preview, "full text"[:500])
                    self.assertIs(await attachment_service.get_attachment(meta.id, 8), None)
                    # 落盘文件仍在，下载/引用链路正常。
                    self.assertEqual(
                        await attachment_service.get_pdf_text(meta.id, 7), "full text"
                    )

                asyncio.run(exercise())

    def test_image_metadata_row_carries_ttl_expiry(self) -> None:
        content = ValidatedImage(
            data=b"\xff\xd8\xffdata",
            base64_data="/9j/ZGF0YQ==",
            mime_type="image/jpeg",
            filename="photo.jpg",
        )
        with patch.object(attachment_service.time, "time", return_value=1000.0):
            meta = asyncio.run(attachment_service.upload_image(content, user_id=7))

        row = self._repository.rows[meta.id]
        self.assertEqual(row["attachment_type"], "image")
        self.assertEqual(row["expires_at"], 1600.0)
        self.assertIsNone(row["storage_path"])

    def test_reconcile_removes_orphan_files_and_expired_rows(self) -> None:
        repository = FakeMetaRepository()
        content = ValidatedPdf(data=b"%PDF-1.7\n", filename="keep.pdf")
        with tempfile.TemporaryDirectory() as upload_dir:
            with (
                patch.object(attachment_service, "_PDF_UPLOAD_DIR", upload_dir),
                patch.object(
                    attachment_service,
                    "extract_pdf_text",
                    return_value=("text", 1),
                ),
                patch.object(attachment_service, "_meta_repository", repository),
                patch.object(
                    attachment_service, "_meta_store", _PostgresMetaStore(repository)
                ),
            ):
                meta = asyncio.run(attachment_service.upload_pdf(content, user_id=7))
                # 过期图片元数据行（TTL 到期）与未过期行各一。
                repository.upsert_attachment_meta(
                    attachment_id="expired-image",
                    user_id=7,
                    attachment_type="image",
                    status="ready",
                    created_at=100.0,
                    expires_at=700.0,
                )
                repository.upsert_attachment_meta(
                    attachment_id="fresh-image",
                    user_id=7,
                    attachment_type="image",
                    status="ready",
                    created_at=100.0,
                    expires_at=1700.0,
                )
                orphan_path = os.path.join(upload_dir, "orphan-id.pdf")
                with open(orphan_path, "wb") as file:
                    file.write(b"%PDF-1.7\norphan")

                with patch.object(attachment_service.time, "time", return_value=1000.0):
                    result = attachment_service.reconcile_orphan_attachments(
                        upload_dir=upload_dir
                    )

                self.assertEqual(
                    result, {"orphan_files_removed": 1, "expired_rows_removed": 1}
                )
                self.assertFalse(os.path.exists(orphan_path))
                self.assertTrue(
                    os.path.exists(os.path.join(upload_dir, f"{meta.id}.pdf"))
                )
                self.assertNotIn("expired-image", repository.rows)
                self.assertIn("fresh-image", repository.rows)
                self.assertIn(meta.id, repository.rows)


if __name__ == "__main__":
    unittest.main()
