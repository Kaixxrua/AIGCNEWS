"""站点联系合作页的管理端配置端点。

无 service 层：无 env 回退、无密钥遮蔽、无副作用，路由直接
Pydantic 校验 + 单例行 upsert。"关闭"即回退语义，不提供 delete。

另提供站点公开素材图片上传（二维码、正文插图）：magic-byte 校验
复用聊天附件的纯函数策略表；落盘目录经 /api/media/site 匿名静态
挂载（与 papers 树同为有意的公开设计），禁止存入私有文件。
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from backend.app.api.dependencies import get_site_contact_page_repository
from backend.app.core.auth import RequireAdmin
from backend.app.models.schema_site import SiteContactPageRequest, SiteContactPageResponse
from backend.app.repositories.site_contact_page_repository import (
    SiteContactEntry,
    SiteContactPage,
    SiteContactPageRepository,
    SiteContactServiceCard,
)
from backend.app.services.chat.attachment_policy import (
    MAX_IMAGE_BYTES,
    AttachmentValidationError,
    validate_image_bytes,
)
from backend.app.services.site_assets import store_site_image

router = APIRouter()

_DEFAULT_PAGE = SiteContactPage(
    enabled=False,
    nav_label="",
    title="",
    subtitle="",
)


class SiteImageUploadResponse(BaseModel):
    """站点素材上传结果：url 为站内媒体相对路径，可直接填入配置字段。"""

    url: str
    filename: str = ""
    size_bytes: int = 0
    mime_type: str = ""


@router.post(
    "/ops/site/images",
    response_model=SiteImageUploadResponse,
    tags=["Ops"],
)
async def upload_site_image(
    file: UploadFile = File(...),
    _: dict = Depends(RequireAdmin),
) -> SiteImageUploadResponse:
    """上传站点公开素材图片（multipart/form-data），返回可直接配置的站内 URL。"""
    file_bytes = await file.read(MAX_IMAGE_BYTES + 1)
    try:
        content = validate_image_bytes(
            file_bytes,
            file.content_type or "",
            file.filename or "",
        )
    except AttachmentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    url = await asyncio.to_thread(store_site_image, content.data, content.mime_type)
    return SiteImageUploadResponse(
        url=url,
        filename=content.filename,
        size_bytes=len(content.data),
        mime_type=content.mime_type,
    )


def _to_response(page: SiteContactPage) -> SiteContactPageResponse:
    return SiteContactPageResponse(
        enabled=page.enabled,
        nav_label=page.nav_label,
        title=page.title,
        subtitle=page.subtitle,
        service_cards=[
            {
                "title": card.title,
                "description": card.description,
                "icon": card.icon,
            }
            for card in page.service_cards
        ],
        contact_entries=[
            {
                "label": entry.label,
                "value": entry.value,
                "href": entry.href,
                "qr_image_url": entry.qr_image_url,
            }
            for entry in page.contact_entries
        ],
        body_markdown=page.body_markdown,
        updated_at=page.updated_at.isoformat() if page.updated_at else None,
    )


@router.get(
    "/ops/site/contact-page",
    response_model=SiteContactPageResponse,
    tags=["Ops"],
)
async def get_site_contact_page_config(
    _: dict = Depends(RequireAdmin),
    repository: SiteContactPageRepository = Depends(get_site_contact_page_repository),
) -> SiteContactPageResponse:
    """读取联系合作页配置。行不存在时返回合成默认值（不写行）。"""
    page = await asyncio.to_thread(repository.get_site_contact_page)
    return _to_response(page or _DEFAULT_PAGE)


@router.put(
    "/ops/site/contact-page",
    response_model=SiteContactPageResponse,
    tags=["Ops"],
)
async def update_site_contact_page_config(
    request: SiteContactPageRequest,
    _: dict = Depends(RequireAdmin),
    repository: SiteContactPageRepository = Depends(get_site_contact_page_repository),
) -> SiteContactPageResponse:
    """保存联系合作页配置（单例行 upsert，即时生效）。"""
    try:
        page = await asyncio.to_thread(
            repository.upsert_site_contact_page,
            enabled=request.enabled,
            nav_label=request.nav_label,
            title=request.title,
            subtitle=request.subtitle,
            service_cards=tuple(
                SiteContactServiceCard(
                    title=card.title,
                    description=card.description,
                    icon=card.icon,
                )
                for card in request.service_cards
            ),
            contact_entries=tuple(
                SiteContactEntry(
                    label=entry.label,
                    value=entry.value,
                    href=entry.href,
                    qr_image_url=entry.qr_image_url,
                )
                for entry in request.contact_entries
            ),
            body_markdown=request.body_markdown,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_response(page)
