"""会员试用：每个账号一次、7 天，到期自动回落免费档。

开通写的是付费开通同一组列（users.membership_tier / membership_expires_at），
MCP 配额、追踪、会员 feed 等读取侧都经 ``resolve_effective_tier`` 判定，不需要
认识「试用」；membership_trials 表只记谁用过试用（见 0084 迁移）。

状态口径：
- available：没用过试用，且眼下不是有效会员（长期会员、付费有效期内都不能试用）；
- active：会员到期时间仍是试用写下的那个值且未到期——试用期间付了费，
  续费会在试用到期日上顺延（payments.grant 的叠加语义），到期时间随之改变，
  此后按付费会员展示，不再算「试用中」。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.app.domain.membership import (
    MEMBERSHIP_TIER_MEMBER,
    resolve_effective_tier,
)

#: 试用天数（开通时刻起算，按 UTC 时间点到期，不取整到自然日）。
TRIAL_DAYS = 7


@dataclass(frozen=True)
class TrialRecord:
    started_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class TrialSnapshot:
    """一次读取里的会员列与试用记录；trial 为 None 表示没用过试用。"""

    membership_tier: Any
    membership_expires_at: datetime | None
    trial: TrialRecord | None


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def trial_expiry(now: datetime) -> datetime:
    return _utc(now) + timedelta(days=TRIAL_DAYS)


def is_effective_member(snapshot: TrialSnapshot, *, now: datetime) -> bool:
    return (
        resolve_effective_tier(
            snapshot.membership_tier, snapshot.membership_expires_at, now=_utc(now)
        )
        == MEMBERSHIP_TIER_MEMBER
    )


def trial_status(snapshot: TrialSnapshot, *, now: datetime) -> dict[str, Any]:
    """会员页用的试用状态（GET/POST /api/membership/trial 同一形状）。"""
    trial = snapshot.trial
    member = is_effective_member(snapshot, now=now)
    active = (
        trial is not None
        and member
        and isinstance(snapshot.membership_expires_at, datetime)
        and _utc(snapshot.membership_expires_at) == _utc(trial.expires_at)
    )
    return {
        "days": TRIAL_DAYS,
        "available": trial is None and not member,
        "active": active,
        "started_at": _utc(trial.started_at).isoformat() if trial else None,
        "expires_at": _utc(trial.expires_at).isoformat() if trial else None,
    }
