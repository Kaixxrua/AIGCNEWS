from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import patch

from backend.app.services.chat import attachment_service
from backend.app.services.chat.attachment_policy import ValidatedImage
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
            type=attachment_service.AttachmentType.IMAGE,
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



class AttachmentMetaPersistenceTests(unittest.TestCase):
    """Row round-trip via _PostgresMetaStore simulates process restarts."""

    def setUp(self) -> None:
        self._repository = FakeMetaRepository()
        self._store = _PostgresMetaStore(self._repository)
        patcher = patch.object(attachment_service, "_meta_store", self._store)
        patcher.start()
        self.addCleanup(patcher.stop)
        attachment_service._image_cache.clear()


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




    def test_legacy_pdf_metadata_is_not_exposed_or_parsed(self) -> None:
        self._repository.rows["old"] = {"attachment_id": "old", "user_id": 7, "attachment_type": "pdf"}
        self.assertIsNone(asyncio.run(self._store.get_owned("old", 7)))
        self.assertEqual(asyncio.run(self._store.list_owned(["old"], 7)), [])

    def test_reconciliation_preserves_historical_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "old.pdf")
            with open(path, "wb") as file:
                file.write(b"historical data")
            with patch.object(attachment_service, "_meta_repository", self._repository):
                result = attachment_service.reconcile_orphan_attachments(now=100.0)
            self.assertTrue(os.path.isfile(path))
        self.assertEqual(result, {"orphan_files_removed": 0, "expired_rows_removed": 0})


if __name__ == "__main__":
    unittest.main()
