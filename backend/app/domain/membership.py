"""Pure membership-tier normalization and expiry policy."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

MEMBERSHIP_TIER_FREE = "free"
MEMBERSHIP_TIER_MEMBER = "member"
DEFAULT_MEMBERSHIP_TIER = MEMBERSHIP_TIER_FREE
MEMBERSHIP_TIERS: frozenset[str] = frozenset(
    {MEMBERSHIP_TIER_FREE, MEMBERSHIP_TIER_MEMBER}
)


def resolve_access_tier(user: Mapping[str, Any] | None) -> str:
    """Give every active account member-level access without changing billing history.

    Callers must authenticate the account first. Anonymous and disabled identities
    retain the public tier; this policy never changes roles, token scopes or quotas.
    """
    if not user or user.get("disabled"):
        return MEMBERSHIP_TIER_FREE
    raw_id = user.get("user_id") or user.get("id") or user.get("sub")
    if isinstance(raw_id, bool):
        return MEMBERSHIP_TIER_FREE
    try:
        account_id = int(raw_id)
    except (TypeError, ValueError):
        return MEMBERSHIP_TIER_FREE
    return MEMBERSHIP_TIER_MEMBER if account_id > 0 else MEMBERSHIP_TIER_FREE


def normalize_membership_tier(value: object) -> str:
    if isinstance(value, str) and value in MEMBERSHIP_TIERS:
        return value
    return DEFAULT_MEMBERSHIP_TIER


def _coerce_expires_at(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        expiry = value
    elif isinstance(value, str):
        try:
            expiry = datetime.fromisoformat(value.strip())
        except ValueError:
            return None
    else:
        return None
    if expiry.tzinfo is None:
        return expiry.replace(tzinfo=timezone.utc)
    return expiry


def resolve_effective_tier(
    value: object,
    expires_at: object = None,
    *,
    now: datetime | None = None,
) -> str:
    tier = normalize_membership_tier(value)
    if tier != MEMBERSHIP_TIER_MEMBER:
        return tier
    expiry = _coerce_expires_at(expires_at)
    if expiry is None:
        return tier
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return MEMBERSHIP_TIER_FREE if expiry <= current else tier
