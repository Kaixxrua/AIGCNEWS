from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from backend.app.core.auth import OptionalUser, RequireAdmin, RequireUser, extract_user_id
from backend.app.repositories.postgres_ui_library_repository import (
    CopyLimitExceeded, CopyRequestConflict, PostgresUiLibraryRepository,
)
from backend.app.services.ui_library import PERIOD_HOURS, known_template, quota_policy

router = APIRouter(tags=['UI Library'])


def repository(request: Request) -> PostgresUiLibraryRepository:
    return request.app.state.application_repositories.ui_library


Repo = Annotated[PostgresUiLibraryRepository, Depends(repository)]
User = Annotated[dict[str, Any], Depends(RequireUser)]


def validate_template(template_id: str) -> None:
    if not known_template(template_id):
        raise HTTPException(404, 'UI template not found')


class LikeInput(BaseModel):
    liked: bool


class CopyInput(BaseModel):
    kind: Literal['source', 'prompt']
    request_id: UUID


@router.get('/ui-library/engagement')
async def engagement(repo: Repo, user: Annotated[dict[str, Any] | None, Depends(OptionalUser)],
                     period: Literal['daily', 'weekly', 'monthly'] = 'daily') -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    rows = await asyncio.to_thread(repo.engagement, extract_user_id(user or {}), now - timedelta(hours=PERIOD_HOURS[period]), now)
    return {'items': rows, 'period': period, 'window_end': now.isoformat()}


@router.put('/ui-library/{template_id}/like')
async def like(template_id: str, body: LikeInput, user: User, repo: Repo) -> dict[str, bool]:
    validate_template(template_id)
    await asyncio.to_thread(repo.set_like, extract_user_id(user), template_id, body.liked)
    return {'liked': body.liked}


@router.get('/ui-library/copy-quota')
async def copy_quota(user: User, repo: Repo) -> dict[str, Any]:
    policy = quota_policy(user)
    used = await asyncio.to_thread(repo.copy_usage, extract_user_id(user), policy.pop('usage_date'))
    return {**policy, 'used': used, 'remaining': None if policy['limit'] is None else max(0, policy['limit'] - used)}


@router.post('/ui-library/{template_id}/copy')
async def copy(template_id: str, body: CopyInput, user: User, repo: Repo) -> dict[str, Any]:
    validate_template(template_id)
    policy = quota_policy(user)
    try:
        used = await asyncio.to_thread(repo.consume_copy, extract_user_id(user), template_id, body.kind,
                                       str(body.request_id), policy.pop('usage_date'), policy['limit'])
    except CopyLimitExceeded:
        raise HTTPException(429, {'code': 'ui_copy_limit', 'limit': 5, 'remaining': 0, 'resets_at': policy['resets_at']}) from None
    except CopyRequestConflict:
        raise HTTPException(409, 'Copy request ID already used for another action') from None
    return {**policy, 'used': used, 'remaining': None if policy['limit'] is None else max(0, policy['limit'] - used)}


@router.get('/ops/ui-library/discovery')
async def discovery_report(repo: Repo, _: Annotated[dict[str, Any], Depends(RequireAdmin)],
                           limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    return await asyncio.to_thread(repo.discovery_report, limit)
