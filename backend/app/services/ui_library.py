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


def catalog_ids(path: str) -> frozenset[str]:
    stat = Path(path).stat()
    return _catalog_ids(path, stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=4)
def _catalog_ids(path: str, modified_ns: int, size: int) -> frozenset[str]:
    # The publisher atomically replaces catalog.json. Account APIs see new IDs
    # without interrupting unrelated scheduler jobs to restart the backend.
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    return frozenset(item['id'] for item in data['items'])


def known_template(template_id: str) -> bool:
    return template_id in catalog_ids(settings.ui_library_catalog_path)


def quota_policy(user: dict[str, Any] | None, now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    local = current.astimezone(ZoneInfo('Asia/Shanghai'))
    midnight = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    member = bool(user and resolve_effective_tier(user.get('membership_tier'), user.get('membership_expires_at'), now=current) == 'member')
    return {'limit': None if member else 5, 'usage_date': local.date(),
            'resets_at': midnight.isoformat(), 'login_required': user is None}
