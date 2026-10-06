"""Authenticated personal tracking. All persistence calls run off the event loop."""
from __future__ import annotations

import asyncio
from typing import Annotated, Any, Callable, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response

from backend.app.api.dependencies import get_application_repositories
from backend.app.core.auth import RequireUser
from backend.app.models.schema_tracking import (
    TrackingExport,
    TrackingOverview,
    TrackingPreview,
    TrackingReadInput,
    TrackingRuleInput,
    TrackingSettingsInput,
    TrackingUnread,
)
from backend.app.repositories.application_repository_factory import ApplicationRepositories
from backend.app.repositories.postgres_tracking_repository import PostgresTrackingRepository
from backend.app.services.tracking.content import export_csv
from backend.app.services.tracking.policy import CST, TrackingError

router = APIRouter(prefix="/tracking", tags=["Personal tracking"])


def get_tracking_repository(
    repositories: Annotated[ApplicationRepositories, Depends(get_application_repositories)],
) -> PostgresTrackingRepository:
    if repositories.tracking is None:
        raise HTTPException(503, detail="tracking_unavailable")
    return repositories.tracking


User = Annotated[dict[str, Any], Depends(RequireUser)]
Repository = Annotated[PostgresTrackingRepository, Depends(get_tracking_repository)]
RuleId = Annotated[int, Path(gt=0)]
ExportFormat = Annotated[Literal["csv", "json"], Query(alias="format")]


def _user_id(user: dict[str, Any]) -> int:
    user_id = int(user.get("user_id") or 0)
    if user_id <= 0:
        raise HTTPException(401, detail="unauthorized")
    return user_id


async def _call(operation: Callable[..., Any], *args: Any) -> Any:
    try:
        return await asyncio.to_thread(operation, *args)
    except TrackingError as exc:
        raise HTTPException(exc.status, detail=exc.code) from exc


@router.get("", response_model=TrackingOverview)
async def overview(user: User, repository: Repository) -> Any:
    return await _call(repository.overview, _user_id(user))


@router.get("/unread", response_model=TrackingUnread)
async def unread(user: User, repository: Repository) -> Any:
    return await _call(repository.unread, _user_id(user))


@router.post("/read", response_model=TrackingUnread)
async def mark_read(body: TrackingReadInput, user: User, repository: Repository) -> Any:
    return await _call(repository.mark_read, _user_id(user), body.digest_id)


@router.post("/rules", response_model=TrackingOverview, status_code=201)
async def create_rule(body: TrackingRuleInput, user: User, repository: Repository) -> Any:
    user_id = _user_id(user)
    await _call(repository.save_rule, user_id, body.model_dump())
    return await _call(repository.overview, user_id)


@router.put("/rules/{rule_id}", response_model=TrackingOverview)
async def update_rule(rule_id: RuleId, body: TrackingRuleInput, user: User, repository: Repository) -> Any:
    user_id = _user_id(user)
    await _call(repository.save_rule, user_id, body.model_dump(), rule_id)
    return await _call(repository.overview, user_id)


@router.delete("/rules/{rule_id}", response_model=TrackingOverview)
async def delete_rule(rule_id: RuleId, user: User, repository: Repository) -> Any:
    user_id = _user_id(user)
    await _call(repository.delete_rule, user_id, rule_id)
    return await _call(repository.overview, user_id)


@router.put("/settings", response_model=TrackingOverview)
async def update_settings(body: TrackingSettingsInput, user: User, repository: Repository) -> Any:
    user_id = _user_id(user)
    await _call(repository.save_settings, user_id, body.model_dump())
    return await _call(repository.overview, user_id)


@router.get("/rules/{rule_id}/preview", response_model=TrackingPreview)
async def preview(rule_id: RuleId, user: User, repository: Repository) -> Any:
    return await _call(repository.preview, _user_id(user), rule_id)


@router.get(
    "/export",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}, "application/json": {}}}, 403: {"description": "membership_required"}},
)
async def export(user: User, repository: Repository, export_format: ExportFormat = "csv") -> Response:
    data = await _call(repository.export, _user_id(user))
    if export_format == "json":
        body, media_type = TrackingExport.model_validate(data).model_dump_json(indent=2), "application/json"
    else:
        body, media_type = export_csv(data["digests"]), "text/csv; charset=utf-8"
    day = data["exported_at"].astimezone(CST).date().isoformat()
    return Response(body, media_type=media_type, headers={
        "Content-Disposition": f'attachment; filename="aigcnews-tracking-{day}.{export_format}"',
        "Cache-Control": "no-store",
    })
