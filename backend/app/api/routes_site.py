"""公开站点内容端点：前端据此渲染联系合作页并控制导航入口显隐。

只读、无需鉴权。页面未启用时只返回 {"enabled": false} 占位投影，
草稿内容仅管理员经 /ops 端点可见，避免未发布内容外泄。
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends

from backend.app.api.dependencies import get_site_contact_page_repository
from backend.app.api.routes_recommended_websites import router as recommended_websites_router
from backend.app.models.schema_site import SiteContactPageResponse
from backend.app.repositories.site_contact_page_repository import SiteContactPageRepository

router = APIRouter()
router.include_router(recommended_websites_router)

_DISABLED_PROJECTION = SiteContactPageResponse(enabled=False)


@router.get("/site/contact-page", response_model=SiteContactPageResponse)
async def get_site_contact_page(
    repository: SiteContactPageRepository = Depends(get_site_contact_page_repository),
) -> SiteContactPageResponse:
    """返回已启用的联系合作页配置；未启用时仅返回 enabled=false。"""
    page = await asyncio.to_thread(repository.get_site_contact_page)
    if page is None or not page.enabled:
        return _DISABLED_PROJECTION
    return SiteContactPageResponse(
        enabled=True,
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
