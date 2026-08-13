"""站点联系合作页的管理端配置端点。

无 service 层：无 env 回退、无密钥遮蔽、无副作用，路由直接
Pydantic 校验 + 单例行 upsert。"关闭"即回退语义，不提供 delete。
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from backend.app.api.dependencies import get_site_contact_page_repository
from backend.app.core.auth import RequireAdmin
from backend.app.models.schema_site import SiteContactPageRequest, SiteContactPageResponse
from backend.app.repositories.site_contact_page_repository import (
    SiteContactEntry,
    SiteContactPage,
    SiteContactPageRepository,
    SiteContactServiceCard,
)

router = APIRouter()

_DEFAULT_PAGE = SiteContactPage(
    enabled=False,
    nav_label="",
    title="",
    subtitle="",
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
