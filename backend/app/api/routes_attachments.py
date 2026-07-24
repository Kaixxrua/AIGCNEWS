"""
附件上传与查询路由。

POST /api/chat/attachments/image    — 上传图片附件（base64）
POST /api/chat/attachments/pdf      — 上传 PDF 附件（multipart/form-data）
GET  /api/chat/attachments/{id}     — 查询附件状态
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile, HTTPException
from pydantic import BaseModel, Field

from backend.app.core.auth import RequireUser
from backend.app.services.chat.attachment_service import (
    upload_image,
    upload_pdf,
    get_attachment,
)
from backend.app.services.chat.attachment_policy import (
    AttachmentValidationError,
    MAX_PDF_BYTES,
    validate_image_attachment,
    validate_pdf_attachment,
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
    user: dict = Depends(RequireUser),
) -> AttachmentResponse:
    """上传图片附件（base64 编码），返回 attachment_id。"""
    try:
        content = validate_image_attachment(
            request.image_base64,
            request.mime_type,
            request.filename,
        )
    except AttachmentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    meta = await upload_image(content=content, user_id=int(user["user_id"]))
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
    user: dict = Depends(RequireUser),
) -> AttachmentResponse:
    """上传 PDF 文件（multipart/form-data），返回 attachment_id。"""
    file_bytes = await file.read(MAX_PDF_BYTES + 1)
    try:
        content = validate_pdf_attachment(file_bytes, file.filename or "")
    except AttachmentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    meta = await upload_pdf(content=content, user_id=int(user["user_id"]))
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
    user: dict = Depends(RequireUser),
) -> AttachmentResponse:
    """查询附件状态与元数据。"""
    meta = await get_attachment(attachment_id, int(user["user_id"]))
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
