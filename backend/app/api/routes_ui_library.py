from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from psycopg import IntegrityError
from pydantic import BaseModel, Field

from backend.app.core.auth import OptionalUser, RequireAdmin, RequireUser, extract_user_id
from backend.app.repositories.postgres_ui_library_repository import (
    CopyLimitExceeded,
    CopyRequestConflict,
    PostgresUiLibraryRepository,
)
from backend.app.services.outbound_target_policy import (
    OutboundTargetPolicyError,
    normalize_http_url,
    resolve_public_ips,
)
from backend.app.services.ui_discovery import SOURCES, X_HANDLES
from backend.app.services.ui_library import (
    PERIOD_HOURS,
    dashboard_catalog,
    known_template,
    quota_policy,
    visible_catalog,
)

router = APIRouter(tags=['UI Library'])


def repository(request: Request) -> PostgresUiLibraryRepository:
    return request.app.state.application_repositories.ui_library


Repo = Annotated[PostgresUiLibraryRepository, Depends(repository)]
User = Annotated[dict[str, Any], Depends(RequireUser)]


def validate_template(template_id: str) -> None:
    if not known_template(template_id):
        raise HTTPException(404, 'UI template not found')


async def validate_visible_template(template_id: str, repo: Repo, user: dict[str, Any]) -> None:
    validate_template(template_id)
    if user.get('role') != 'admin' and template_id in await asyncio.to_thread(repo.deprecated_ids):
        raise HTTPException(404, 'UI template not found')


class VisibilityInput(BaseModel):
    deprecated: bool


@router.get('/ui-library/dashboard')
async def material_dashboard(response: Response, repo: Repo,
                             ids: Annotated[list[str] | None, Query(max_length=16)] = None) -> dict[str, Any]:
    # This public projection always excludes deprecated rows, including for admins.
    response.headers['Cache-Control'] = 'no-store'
    deprecated = await asyncio.to_thread(repo.deprecated_ids)
    return await asyncio.to_thread(dashboard_catalog, deprecated, ids or [])


@router.get('/ui-library/catalog')
@router.get('/ui-library/icons')
async def material_catalog(request: Request, response: Response, repo: Repo,
                           user: Annotated[dict[str, Any] | None, Depends(OptionalUser)],
                           include_deprecated: bool = False, summary: bool = False,
                           template_id: str | None = Query(None, max_length=200)) -> dict[str, Any]:
    if include_deprecated and (not user or user.get('role') != 'admin'):
        raise HTTPException(403, 'Admin required')
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['Vary'] = 'Authorization'
    deprecated = await asyncio.to_thread(repo.deprecated_ids)
    return await asyncio.to_thread(visible_catalog, deprecated, icons=request.url.path.endswith('/icons'),
                                   include_deprecated=include_deprecated, summary=summary, template_id=template_id)


@router.put('/ops/ui-library/{template_id}/visibility')
async def set_material_visibility(template_id: str, body: VisibilityInput, repo: Repo,
                                  user: Annotated[dict[str, Any], Depends(RequireAdmin)]) -> dict[str, Any]:
    validate_template(template_id)
    await asyncio.to_thread(repo.set_deprecated, template_id, body.deprecated, extract_user_id(user))
    return {'id': template_id, 'deprecated': body.deprecated}


class LikeInput(BaseModel):
    liked: bool


class CopyInput(BaseModel):
    kind: Literal['source', 'prompt']
    request_id: UUID


class DiscoverySourceInput(BaseModel):
    name: str
    kind: Literal['github', 'feed']
    repository: str | None = None
    path_patterns: list[str] = Field(default_factory=list)
    feed_url: str | None = None
    enabled: bool = True
    x_auto_publish: bool = False


_REPOSITORY_RE = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')


def validate_discovery_source(body: DiscoverySourceInput) -> dict[str, Any]:
    name = body.name.strip()
    if not name or len(name) > 120:
        raise HTTPException(422, '来源名称长度应为 1–120 个字符')
    if body.kind == 'github':
        repository_name = (body.repository or '').strip()
        patterns = list(dict.fromkeys(pattern.strip() for pattern in body.path_patterns if pattern.strip()))
        if not _REPOSITORY_RE.fullmatch(repository_name):
            raise HTTPException(422, 'GitHub 仓库应填写 owner/repository')
        if not patterns or len(patterns) > 20 or any(len(pattern) > 200 or '..' in pattern or pattern.startswith('/') for pattern in patterns):
            raise HTTPException(422, '请填写 1–20 个安全的仓库文件匹配规则')
        if body.x_auto_publish and any(not pattern.lower().endswith('.html') for pattern in patterns):
            raise HTTPException(422, 'X 自动发布仅支持 HTML 文件规则')
        return {'name': name, 'kind': 'github', 'repository': repository_name,
                'path_patterns': patterns, 'feed_url': None, 'enabled': body.enabled,
                'x_auto_publish': body.x_auto_publish}
    if body.x_auto_publish:
        raise HTTPException(422, 'X 自动发布只能用于 GitHub 来源')
    try:
        feed_url = normalize_http_url(body.feed_url or '', allowed_ports={443})
        if not feed_url.startswith('https://'):
            raise OutboundTargetPolicyError('只支持 HTTPS Feed')
        resolve_public_ips(urlsplit(feed_url).hostname or '', reject_mixed=True)
    except OutboundTargetPolicyError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {'name': name, 'kind': 'feed', 'repository': None,
            'path_patterns': [], 'feed_url': feed_url, 'enabled': body.enabled,
            'x_auto_publish': False}


@router.get('/ui-library/engagement')
async def engagement(repo: Repo, user: Annotated[dict[str, Any] | None, Depends(OptionalUser)],
                     period: Literal['daily', 'weekly', 'monthly'] = 'daily') -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    rows = await asyncio.to_thread(repo.engagement, extract_user_id(user or {}), now - timedelta(hours=PERIOD_HOURS[period]), now)
    deprecated = await asyncio.to_thread(repo.deprecated_ids)
    rows = [row for row in rows if row['template_id'] not in deprecated]
    return {'items': rows, 'period': period, 'window_end': now.isoformat()}


@router.put('/ui-library/{template_id}/like')
async def like(template_id: str, body: LikeInput, user: User, repo: Repo) -> dict[str, bool]:
    await validate_visible_template(template_id, repo, user)
    await asyncio.to_thread(repo.set_like, extract_user_id(user), template_id, body.liked)
    return {'liked': body.liked}


@router.get('/ui-library/copy-quota')
async def copy_quota(user: User, repo: Repo) -> dict[str, Any]:
    policy = quota_policy(user)
    used = await asyncio.to_thread(repo.copy_usage, extract_user_id(user), policy.pop('usage_date'))
    return {**policy, 'used': used, 'remaining': None if policy['limit'] is None else max(0, policy['limit'] - used)}


@router.post('/ui-library/{template_id}/copy')
async def copy(template_id: str, body: CopyInput, user: User, repo: Repo) -> dict[str, Any]:
    await validate_visible_template(template_id, repo, user)
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


@router.get('/ops/ui-library/discovery-sources')
async def discovery_sources(repo: Repo, _: Annotated[dict[str, Any], Depends(RequireAdmin)]) -> dict[str, Any]:
    display_names = {
        'uiverse': 'Uiverse Galaxy', 'motion-primitives': 'Motion Primitives',
        'magic-ui': 'Magic UI', 'hyperui': 'HyperUI', 'magic-portfolio': 'Magic Portfolio',
    }
    return {
        'builtin': [
            {'id': source.id, 'name': display_names[source.id], 'kind': 'github', 'repository': source.repo,
             'path_patterns': list(source.paths), 'enabled': True, 'editable': False}
            for source in SOURCES
        ] + [
            {'id': 'codrops', 'name': 'Codrops', 'kind': 'github', 'repository': 'codrops',
             'path_patterns': [], 'enabled': True, 'editable': False},
        ] + [
            {'id': f'x:{handle}', 'name': f'@{handle}', 'kind': 'x', 'handle': handle,
             'profile_url': f'https://x.com/{handle}', 'path_patterns': [],
             'enabled': True, 'editable': False}
            for handle in X_HANDLES
        ],
        'custom': await asyncio.to_thread(repo.list_source_configs),
    }


@router.post('/ops/ui-library/discovery-sources', status_code=201)
async def create_discovery_source(body: DiscoverySourceInput, repo: Repo,
                                  _: Annotated[dict[str, Any], Depends(RequireAdmin)]) -> dict[str, Any]:
    values = await asyncio.to_thread(validate_discovery_source, body)
    try:
        item = await asyncio.to_thread(repo.create_source_config, values)
    except IntegrityError:
        raise HTTPException(409, '该发现来源已存在') from None
    return {'item': item}


@router.put('/ops/ui-library/discovery-sources/{config_id}')
async def update_discovery_source(config_id: int, body: DiscoverySourceInput, repo: Repo,
                                  _: Annotated[dict[str, Any], Depends(RequireAdmin)]) -> dict[str, Any]:
    values = await asyncio.to_thread(validate_discovery_source, body)
    try:
        item = await asyncio.to_thread(repo.update_source_config, config_id, values)
    except IntegrityError:
        raise HTTPException(409, '该发现来源已存在') from None
    if item is None:
        raise HTTPException(404, '发现来源不存在')
    return {'item': item}


@router.delete('/ops/ui-library/discovery-sources/{config_id}', status_code=204)
async def delete_discovery_source(config_id: int, repo: Repo,
                                  _: Annotated[dict[str, Any], Depends(RequireAdmin)]) -> None:
    if not await asyncio.to_thread(repo.delete_source_config, config_id):
        raise HTTPException(404, '发现来源不存在')
