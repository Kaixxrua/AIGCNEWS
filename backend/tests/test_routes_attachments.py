from __future__ import annotations

import asyncio
import base64
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from backend.app.api import routes_attachments
from backend.app.services.chat.attachment_service import (
    AttachmentMeta,
    AttachmentStatus,
    AttachmentType,
)
from backend.app.services.chat.attachment_policy import MAX_PDF_BYTES


class AttachmentRouteTests(unittest.TestCase):
    def test_image_route_validates_then_passes_owner(self) -> None:
        request = routes_attachments.ImageUploadRequest(
            image_base64=base64.b64encode(b"\x89PNG\r\n\x1a\ndata").decode(),
            mime_type="image/png",
            filename="../photo.png",
        )
        meta = AttachmentMeta(
            id="image-id",
            user_id=9,
            type=AttachmentType.IMAGE,
            status=AttachmentStatus.READY,
            filename="photo.png",
            mime_type="image/png",
            size_bytes=12,
        )

        with patch.object(
            routes_attachments, "upload_image", new=AsyncMock(return_value=meta)
        ) as upload:
            response = asyncio.run(
                routes_attachments.upload_image_attachment(request, {"user_id": "9"})
            )

        self.assertEqual(response.id, "image-id")
        content = upload.await_args.kwargs["content"]
        self.assertEqual(content.filename, "photo.png")
        self.assertEqual(upload.await_args.kwargs["user_id"], 9)

    def test_invalid_image_returns_stable_400(self) -> None:
        request = routes_attachments.ImageUploadRequest(
            image_base64="not-valid-base64",
            mime_type="image/png",
        )
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(
                routes_attachments.upload_image_attachment(request, {"user_id": 1})
            )
        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail, "图片数据格式无效")

    def test_pdf_route_reads_only_max_plus_one_and_rejects_invalid_magic(self) -> None:
        file = MagicMock()
        file.filename = "fake.pdf"
        file.read = AsyncMock(return_value=b"not-pdf")

        with self.assertRaises(HTTPException) as raised:
            asyncio.run(routes_attachments.upload_pdf_attachment(file, {"user_id": 1}))

        file.read.assert_awaited_once_with(MAX_PDF_BYTES + 1)
        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail, "PDF 文件内容无效")

    def test_cross_owner_status_behaves_absent(self) -> None:
        with patch.object(
            routes_attachments, "get_attachment", new=AsyncMock(return_value=None)
        ) as get_attachment:
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(
                    routes_attachments.get_attachment_status("secret", {"user_id": "4"})
                )

        get_attachment.assert_awaited_once_with("secret", 4)
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.detail, "附件不存在或已过期")


if __name__ == "__main__":
    unittest.main()
