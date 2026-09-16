from __future__ import annotations

import asyncio
import unittest

from backend.app.services.chat.attachment_lifecycle import (
    AttachmentLifecycle,
    AttachmentMeta,
    AttachmentRegistry,
    AttachmentStatus,
    AttachmentType,
)


class AttachmentLifecycleTests(unittest.TestCase):
    def test_public_enums_and_meta_defaults_remain_stable(self) -> None:
        self.assertEqual(
            [member.value for member in AttachmentType],
            ["image"],
        )
        self.assertEqual(
            [member.value for member in AttachmentStatus],
            ["uploading", "processing", "ready", "error", "expired"],
        )
        meta = AttachmentMeta(
            id="id",
            user_id=7,
            type=AttachmentType.IMAGE,
            status=AttachmentStatus.READY,
        )
        self.assertEqual(meta.filename, "")
        self.assertEqual(meta.mime_type, "")
        self.assertEqual(meta.size_bytes, 0)
        self.assertEqual(meta.page_count, 0)
        self.assertEqual(meta.text_preview, "")
        self.assertEqual(meta.expires_at, 0.0)
        self.assertEqual(meta.error_msg, "")

    def test_uuid_string_and_fake_clock_are_injectable(self) -> None:
        lifecycle = AttachmentLifecycle(
            AttachmentRegistry(),
            id_factory=lambda: "fixed-uuid",
            clock=lambda: 123.0,
        )

        self.assertEqual(lifecycle.new_id(), "fixed-uuid")
        meta = asyncio.run(
            lifecycle.register_image(
                attachment_id=lifecycle.new_id(),
                user_id=7,
                filename="photo.png",
                mime_type="image/png",
                size_bytes=12,
                expires_at=723.0,
            )
        )
        self.assertEqual(meta.created_at, 123.0)
        self.assertEqual(meta.status, AttachmentStatus.READY)
        self.assertEqual(meta.expires_at, 723.0)


    def test_registry_enforces_owner_and_preserves_list_order_duplicates(self) -> None:
        entries: dict[str, AttachmentMeta] = {}
        registry = AttachmentRegistry(entries)
        first = AttachmentMeta(
            id="first",
            user_id=7,
            type=AttachmentType.IMAGE,
            status=AttachmentStatus.READY,
        )
        second = AttachmentMeta(
            id="second",
            user_id=7,
            type=AttachmentType.IMAGE,
            status=AttachmentStatus.PROCESSING,
        )
        other = AttachmentMeta(
            id="other",
            user_id=8,
            type=AttachmentType.IMAGE,
            status=AttachmentStatus.READY,
        )

        async def exercise() -> None:
            for meta in (first, second, other):
                await registry.register(meta)
            self.assertIs(await registry.get_owned("first", 7), first)
            self.assertIsNone(await registry.get_owned("first", 8))
            self.assertEqual(
                await registry.list_owned(
                    ["second", "missing", "first", "second", "other"], 7
                ),
                [second, first, second],
            )

        asyncio.run(exercise())
        self.assertIs(entries["first"], first)


if __name__ == "__main__":
    unittest.main()
