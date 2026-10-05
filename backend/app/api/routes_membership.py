"""会员试用：每个账号一次的 7 天会员（GET 查状态 / POST 开通）。

开通写的是付费开通同一组列，读取侧统一经 resolve_effective_tier 判定，
到期自动回落免费档，不需要定时任务；规则见 services/membership/trial.py。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status

from backend.app.core.auth import RequireUser, extract_user_id
from backend.app.core.postgres_database import postgres_database
from backend.app.repositories.membership_trial_repository import MembershipTrialRepository
from backend.app.repositories.postgres_membership_trial_repository import (
    PostgresMembershipTrialRepository,
)
from backend.app.services.membership.trial import trial_status

logger = logging.getLogger(__name__)

router = APIRouter()

#: 409 的 detail 码，前端按码给文案
TRIAL_ALREADY_USED = "trial_already_used"
ALREADY_MEMBER = "already_member"


def get_membership_trial_repository() -> MembershipTrialRepository:
    return PostgresMembershipTrialRepository(postgres_database)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require_user_id(user: dict[str, Any]) -> int:
    user_id = extract_user_id(user)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户身份无效",
        )
    return user_id


@router.get("/membership/trial")
async def get_membership_trial(
    response: Response,
    user: dict[str, Any] = Depends(RequireUser),
    trials: MembershipTrialRepository = Depends(get_membership_trial_repository),
) -> dict[str, Any]:
    """当前账号的试用状态：能否开通、是否试用中、试用起止时间。"""
    user_id = _require_user_id(user)
    snapshot = await asyncio.to_thread(trials.get_trial_snapshot, user_id)
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户身份无效",
        )
    response.headers["Cache-Control"] = "no-store"
    return trial_status(snapshot, now=_now())


@router.post("/membership/trial")
async def start_membership_trial(
    response: Response,
    user: dict[str, Any] = Depends(RequireUser),
    trials: MembershipTrialRepository = Depends(get_membership_trial_repository),
) -> dict[str, Any]:
    """开通 7 天会员试用：每个账号一次；眼下是有效会员时不开通。"""
    user_id = _require_user_id(user)
    now = _now()
    result = await asyncio.to_thread(trials.start_trial, user_id=user_id, now=now)
    if result.outcome == "user_missing" or result.snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户身份无效",
        )
    if result.outcome == "already_used":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=TRIAL_ALREADY_USED)
    if result.outcome == "already_member":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ALREADY_MEMBER)
    payload = trial_status(result.snapshot, now=now)
    logger.info(
        "membership trial started user_id=%s expires_at=%s",
        user_id,
        payload["expires_at"],
    )
    response.headers["Cache-Control"] = "no-store"
    return payload
