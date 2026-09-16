"""Pure membership-tier normalization and expiry policy."""

from __future__ import annotations

from datetime import datetime, timezone

MEMBERSHIP_TIER_FREE = "free"
MEMBERSHIP_TIER_MEMBER = "member"
DEFAULT_MEMBERSHIP_TIER = MEMBERSHIP_TIER_FREE
MEMBERSHIP_TIERS: frozenset[str] = frozenset(
    {MEMBERSHIP_TIER_FREE, MEMBERSHIP_TIER_MEMBER}
)


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
