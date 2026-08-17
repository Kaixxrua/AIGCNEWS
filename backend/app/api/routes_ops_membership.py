"""会员档位运营授予：人工收款确认后由管理员按邮箱授予/吊销会员。

第一版无在线支付（个体工商户执照与商户号就绪前），授予动作即收款台账；
tier 以库内为准，RequireUser 每请求查库，授予/吊销下一个请求即生效。
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from backend.app.api.dependencies import get_user_account_repository
from backend.app.core.auth import RequireAdmin
from backend.app.repositories.user_account_repository import UserAccountRepository
from backend.app.services.membership.tiers import (
    MEMBERSHIP_TIER_FREE,
    normalize_membership_tier,
)

router = APIRouter()


class MembershipGrantRequest(BaseModel):
    email: EmailStr
    tier: Literal["free", "member"]


@router.post("/ops/membership/grant", tags=["Ops"])
async def grant_membership(
    body: MembershipGrantRequest,
    _: dict = Depends(RequireAdmin),
    repository: UserAccountRepository = Depends(get_user_account_repository),
) -> dict[str, Any]:
    """按邮箱授予/吊销会员档位（tier=free 即吊销），库内写下一个请求生效。"""
    email = str(body.email).strip().lower()
    user = await asyncio.to_thread(repository.get_user_by_email, email)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    tier = normalize_membership_tier(body.tier)
    updated = await asyncio.to_thread(
        repository.set_membership_tier,
        user_id=int(user["id"]),
        tier=tier,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {
        "user_id": int(user["id"]),
        "email": user.get("email"),
        "membership_tier": tier,
        "revoked": tier == MEMBERSHIP_TIER_FREE,
    }
