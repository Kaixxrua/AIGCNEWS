"""Public curated website directory, with administrator-only writes.

This collection is independent of GitHub recommendations and personal bookmarks.
Website URLs are stored as links; these endpoints never fetch remote content.
"""

from __future__ import annotations

import asyncio
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

router = APIRouter()


def get_recommended_website_repository(request: Request) -> RecommendedWebsiteRepository:
    return PostgresRecommendedWebsiteRepository(get_postgres_database(request))


Repository = Annotated[RecommendedWebsiteRepository, Depends(get_recommended_website_repository)]
Admin = Annotated[dict[str, Any], Depends(RequireAdmin)]
WebsiteId = Annotated[int, Path(gt=0)]


@router.get("/site/recommended-websites", response_model=RecommendedWebsitesResponse)
async def list_recommended_websites(repository: Repository) -> RecommendedWebsitesResponse:
    """List websites explicitly added by an administrator, without authentication."""
    rows = await asyncio.to_thread(repository.list_websites)
    return RecommendedWebsitesResponse(items=[RecommendedWebsiteResponse.model_validate(row) for row in rows])


@router.post("/ops/recommended-websites", response_model=RecommendedWebsiteResponse, status_code=201)
async def create_recommended_website(
    payload: RecommendedWebsiteRequest, _admin: Admin, repository: Repository,
) -> RecommendedWebsiteResponse:
    """Publish one administrator-authored website recommendation."""
    try:
        row = await asyncio.to_thread(repository.create_website, **payload.model_dump())
    except DuplicateRecommendedWebsiteError as error:
        raise HTTPException(status_code=409, detail="Website is already recommended") from error
    return RecommendedWebsiteResponse.model_validate(row)


@router.put("/ops/recommended-websites/{website_id}", response_model=RecommendedWebsiteResponse)
async def update_recommended_website(
    website_id: WebsiteId, payload: RecommendedWebsiteRequest, _admin: Admin, repository: Repository,
) -> RecommendedWebsiteResponse:
    """Replace the displayed content of an existing recommendation."""
    try:
        row = await asyncio.to_thread(repository.update_website, website_id, **payload.model_dump())
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
