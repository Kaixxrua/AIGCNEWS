"""Bounded personal tracking, shared by HTTP reads and scheduled dispatch."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from backend.app.services.membership.tiers import resolve_effective_tier

CST = timezone(timedelta(hours=8))
FREE_RULE_LIMIT = 1
MEMBER_RULE_LIMIT = 10
DIGEST_ITEM_LIMIT = 50


class TrackingError(Exception):
    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def rule_limit(user: dict[str, Any], now: datetime | None = None) -> int:
    tier = resolve_effective_tier(
        user.get("membership_tier"), user.get("membership_expires_at"), now=now,
    )
    return MEMBER_RULE_LIMIT if tier == "member" else FREE_RULE_LIMIT


def active_rules(rules: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return [row for row in sorted(rules, key=lambda row: row["id"]) if row["enabled"]][:limit]
