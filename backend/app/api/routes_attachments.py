"""
附件上传与查询路由。

POST /api/chat/attachments/image    — 上传图片附件（base64）
POST /api/chat/attachments/pdf      — 上传 PDF 附件（multipart/form-data）
GET  /api/chat/attachments/{id}     — 查询附件状态
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, UploadFile, HTTPException
from pydantic import BaseModel, Field

from backend.app.core.auth import RequireUser
from backend.app.services.chat.attachment_service import (
    upload_image,
    upload_pdf,
    get_attachment,
    AttachmentStatus,
)

router = APIRouter()

# ---------------------------------------------------------------------------
# 请求/响应 Schema
# ---------------------------------------------------------------------------


class ImageUploadRequest(BaseModel):
    image_base64: str = Field(..., min_length=10)
    mime_type: str = Field(default="image/jpeg")
    filename: str = Field(default="")


class AttachmentResponse(BaseModel):
    id: str
    type: str
    status: str
    filename: str = ""
    mime_type: str = ""
    size_bytes: int = 0
    page_count: int = 0
    text_preview: str = ""
    error_msg: str = ""


# ---------------------------------------------------------------------------
# 上传图片附件
# ---------------------------------------------------------------------------


@router.post("/chat/attachments/image", response_model=AttachmentResponse)
async def upload_image_attachment(
    request: ImageUploadRequest,
    _: dict = Depends(RequireUser),
) -> AttachmentResponse:
    """上传图片附件（base64 编码），返回 attachment_id。"""
    meta = await upload_image(
        base64_data=request.image_base64,
        mime_type=request.mime_type,
        filename=request.filename,
    )
    return AttachmentResponse(
        id=meta.id,
        type=meta.type.value,
        status=meta.status.value,
        filename=meta.filename,
        mime_type=meta.mime_type,
        size_bytes=meta.size_bytes,
        error_msg=meta.error_msg,
    )


# ---------------------------------------------------------------------------
# 上传 PDF 附件
# ---------------------------------------------------------------------------


@router.post("/chat/attachments/pdf", response_model=AttachmentResponse)
async def upload_pdf_attachment(
    file: UploadFile = File(...),
    _: dict = Depends(RequireUser),
) -> AttachmentResponse:
    """上传 PDF 文件（multipart/form-data），返回 attachment_id。"""
    # 验证文件类型
    content_type = file.content_type or ""
    if "pdf" not in content_type.lower() and not (file.filename or "").lower().endswith(
        ".pdf"
    ):
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件上传")

    # 限制文件大小（50MB）
    file_bytes = await file.read()
    if len(file_bytes) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="PDF 文件大小不能超过 50MB")

    meta = await upload_pdf(
        file_bytes=file_bytes,
        filename=file.filename or "",
    )
    return AttachmentResponse(
        id=meta.id,
        type=meta.type.value,
        status=meta.status.value,
        filename=meta.filename,
        mime_type=meta.mime_type,
        size_bytes=meta.size_bytes,
        page_count=meta.page_count,
        text_preview=meta.text_preview,
        error_msg=meta.error_msg,
    )


# ---------------------------------------------------------------------------
# 查询附件状态
# ---------------------------------------------------------------------------


@router.get("/chat/attachments/{attachment_id}", response_model=AttachmentResponse)
async def get_attachment_status(
    attachment_id: str,
    _: dict = Depends(RequireUser),
) -> AttachmentResponse:
    """查询附件状态与元数据。"""
    meta = await get_attachment(attachment_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="附件不存在或已过期")

    return AttachmentResponse(
        id=meta.id,
        type=meta.type.value,
        status=meta.status.value,
        filename=meta.filename,
        mime_type=meta.mime_type,
        size_bytes=meta.size_bytes,
        page_count=meta.page_count,
        text_preview=meta.text_preview,
        error_msg=meta.error_msg,
    )
