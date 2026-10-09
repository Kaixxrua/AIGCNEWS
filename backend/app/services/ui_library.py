from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.app.core.config import settings
from backend.app.services.membership.tiers import resolve_effective_tier

PERIOD_HOURS = {'daily': 24, 'weekly': 168, 'monthly': 720}


@lru_cache(maxsize=4)
def _read_catalog(path: str, modified_ns: int, size: int) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def visible_catalog(deprecated: set[str], *, icons: bool = False, include_deprecated: bool = False) -> dict[str, Any]:
    path = Path(settings.ui_library_catalog_path)
    if icons:
        path = path.with_name('icons.json')
    if icons and not path.exists():
        return {'version': 1, 'sets': []}
    stat = path.stat()
    data = _read_catalog(str(path), stat.st_mtime_ns, stat.st_size)

    def visible(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Copy each row: an admin response must never contaminate the cached public catalog.
        return [
            {**item, 'deprecated': item['id'] in deprecated} if include_deprecated else item
            for item in items if include_deprecated or item['id'] not in deprecated
        ]

    if icons:
        return {**data, 'sets': [{**group, 'icons': visible(group['icons'])} for group in data['sets']]}
    icon_catalog = visible_catalog(deprecated, icons=True, include_deprecated=include_deprecated)
    return {**data, 'items': visible(data['items']),
            'icon_count': sum(len(group['icons']) for group in icon_catalog['sets'])}


def dashboard_catalog(deprecated: set[str], template_ids: list[str]) -> dict[str, Any]:
    # Keep counts and previews under the same visibility rule as the library,
    # without sending source files, licenses or the full catalog to the homepage.
    items = visible_catalog(deprecated)['items']
    selected = set(template_ids)
    return {
        'version': 1,
        'total': len(items),
        'items': [
            {key: item[key] for key in ('id', 'poster_url', 'clip_url')}
            for item in items
            if item['id'] in selected and item.get('poster_url') and item.get('clip_url')
        ],
    }


def catalog_ids(path: str) -> frozenset[str]:
    stat = Path(path).stat()
    icons = Path(path).with_name('icons.json')
    try:
        icons_stat: tuple[int, int] | None = (icons.stat().st_mtime_ns, icons.stat().st_size)
    except FileNotFoundError:
        icons_stat = None
    return _catalog_ids(path, stat.st_mtime_ns, stat.st_size, icons_stat)


@lru_cache(maxsize=4)
def _catalog_ids(path: str, modified_ns: int, size: int, icons_stat: tuple[int, int] | None) -> frozenset[str]:
    # The publisher atomically replaces catalog.json. Account APIs see new IDs
    # without interrupting unrelated scheduler jobs to restart the backend.
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    ids = {item['id'] for item in data['items']}
    if icons_stat is not None:
        # Icon ids share the same account, like and copy-quota contracts.
        payload = json.loads(Path(path).with_name('icons.json').read_text(encoding='utf-8'))
        ids.update(icon['id'] for icon_set in payload['sets'] for icon in icon_set['icons'])
    return frozenset(ids)


def known_template(template_id: str) -> bool:
    return template_id in catalog_ids(settings.ui_library_catalog_path)


def quota_policy(user: dict[str, Any] | None, now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    local = current.astimezone(ZoneInfo('Asia/Shanghai'))
    midnight = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    member = bool(user and resolve_effective_tier(user.get('membership_tier'), user.get('membership_expires_at'), now=current) == 'member')
    return {'limit': None if member else 5, 'usage_date': local.date(),
            'resets_at': midnight.isoformat(), 'login_required': user is None}
