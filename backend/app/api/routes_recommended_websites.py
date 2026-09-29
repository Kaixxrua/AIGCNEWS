"""Public curated website directory, with administrator-only writes.

This collection is independent of GitHub recommendations and personal bookmarks.
Website URLs are stored as links. The only remote fetch is an administrator's save, which fetches the
website's own icon once and stores a re-encoded copy as a public site asset; visitors never load it from
the website, and a failed fetch never fails the save.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response

from backend.app.api.dependencies import get_postgres_database
from backend.app.core.auth import RequireAdmin
from backend.app.models.schema_recommended_websites import (
    RecommendedWebsiteRequest,
    RecommendedWebsiteResponse,
    RecommendedWebsitesResponse,
)
from backend.app.repositories.postgres_recommended_website_repository import PostgresRecommendedWebsiteRepository
from backend.app.repositories.recommended_website_repository import (
    DuplicateRecommendedWebsiteError,
    RecommendedWebsiteRepository,
)
from backend.app.services.recommended_website_icons import fetch_recommended_website_icon

router = APIRouter()


def get_recommended_website_repository(request: Request) -> RecommendedWebsiteRepository:
    return PostgresRecommendedWebsiteRepository(get_postgres_database(request))


def get_website_icon_fetcher() -> Callable[[str], str]:
    return fetch_recommended_website_icon


Repository = Annotated[RecommendedWebsiteRepository, Depends(get_recommended_website_repository)]
IconFetcher = Annotated[Callable[[str], str], Depends(get_website_icon_fetcher)]
Admin = Annotated[dict[str, Any], Depends(RequireAdmin)]
WebsiteId = Annotated[int, Path(gt=0)]

# An icon that takes longer is left for the next save; the save itself goes ahead without one.
_ICON_TIMEOUT_SECONDS = 20


async def _fetch_icon(fetch_icon: Callable[[str], str], url: str) -> str:
    try:
        return await asyncio.wait_for(asyncio.to_thread(fetch_icon, url), _ICON_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return ""


@router.get("/site/recommended-websites", response_model=RecommendedWebsitesResponse)
async def list_recommended_websites(repository: Repository) -> RecommendedWebsitesResponse:
    """List websites explicitly added by an administrator, without authentication."""
    rows = await asyncio.to_thread(repository.list_websites)
    return RecommendedWebsitesResponse(items=[RecommendedWebsiteResponse.model_validate(row) for row in rows])


@router.post("/ops/recommended-websites", response_model=RecommendedWebsiteResponse, status_code=201)
async def create_recommended_website(
    payload: RecommendedWebsiteRequest, _admin: Admin, repository: Repository, fetch_icon: IconFetcher,
) -> RecommendedWebsiteResponse:
    """Publish one administrator-authored website recommendation, with the website's own icon."""
    icon_url = await _fetch_icon(fetch_icon, payload.url)
    try:
        row = await asyncio.to_thread(repository.create_website, **payload.model_dump(), icon_url=icon_url)
    except DuplicateRecommendedWebsiteError as error:
        raise HTTPException(status_code=409, detail="Website is already recommended") from error
    return RecommendedWebsiteResponse.model_validate(row)


@router.put("/ops/recommended-websites/{website_id}", response_model=RecommendedWebsiteResponse)
async def update_recommended_website(
    website_id: WebsiteId, payload: RecommendedWebsiteRequest, _admin: Admin, repository: Repository,
    fetch_icon: IconFetcher,
) -> RecommendedWebsiteResponse:
    """Replace the displayed content of an existing recommendation and refresh its icon."""
    icon_url = await _fetch_icon(fetch_icon, payload.url)
    try:
        row = await asyncio.to_thread(
            repository.update_website, website_id, **payload.model_dump(), icon_url=icon_url,
        )
    except DuplicateRecommendedWebsiteError as error:
        raise HTTPException(status_code=409, detail="Website is already recommended") from error
    if row is None:
        raise HTTPException(status_code=404, detail="Recommended website not found")
    return RecommendedWebsiteResponse.model_validate(row)


@router.delete("/ops/recommended-websites/{website_id}", status_code=204)
async def delete_recommended_website(website_id: WebsiteId, _admin: Admin, repository: Repository) -> Response:
    """Remove only the public recommendation, leaving every personal bookmark intact."""
    deleted = await asyncio.to_thread(repository.delete_website, website_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Recommended website not found")
    return Response(status_code=204)
