"""会员档位运营授予：人工收款确认后由管理员按邮箱授予/吊销会员。

第一版无在线支付（个体工商户执照与商户号就绪前），授予动作即收款台账；
tier 以库内为准，RequireUser 每请求查库，授予/吊销下一个请求即生效。

到期语义（0048）：member 可附带 expires_at（到期后生效档位自动回落
free，库内档位列不回写）；tier=free 即吊销，同时清空到期时间。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr

from backend.app.api.dependencies import get_user_account_repository
from backend.app.core.auth import RequireAdmin
from backend.app.repositories.user_account_repository import UserAccountRepository
from backend.app.services.membership.tiers import (
    MEMBERSHIP_TIER_FREE,
    normalize_membership_tier,
    resolve_effective_tier,
)

router = APIRouter()


class MembershipGrantRequest(BaseModel):
    email: EmailStr
    tier: Literal["free", "member"]
    # 仅 member 档有意义；NULL/缺省 = 长期有效。naive datetime 按 UTC 解释，
    # 与库内 timestamptz 口径一致（前端按北京时间末日 23:59:+08:00 显式给时区）。
    expires_at: datetime | None = None


def _serialize_membership_user(row: dict[str, Any]) -> dict[str, Any]:
    expires_at = row.get("membership_expires_at")
    created_at = row.get("created_at")
    # 生效档位与 RequireUser 同一权威（resolve_effective_tier）：
    # member 过期按 free，NULL 到期时间 = 长期有效
    effective_tier = resolve_effective_tier(
        row.get("membership_tier"),
        expires_at,
    )
    return {
        "user_id": int(row["id"]),
        "email": row.get("email"),
        "phone": row.get("phone"),
        "username": row.get("username"),
        "role": row.get("role") or "user",
        "disabled": bool(row.get("disabled") or False),
        "membership_tier": normalize_membership_tier(row.get("membership_tier")),
        "membership_expires_at": (
            expires_at.isoformat() if isinstance(expires_at, datetime) else expires_at
        ),
        "created_at": (
            created_at.isoformat() if isinstance(created_at, datetime) else created_at
        ),
        "effective_tier": effective_tier,
    }


@router.get("/ops/membership/users", tags=["Ops"])
async def list_membership_users(
    query: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: dict = Depends(RequireAdmin),
    repository: UserAccountRepository = Depends(get_user_account_repository),
) -> dict[str, Any]:
    """会员运营用户列表：email/phone/username 模糊搜索 + 分页，每行带生效档位。"""
    rows, total = await asyncio.to_thread(
        repository.list_users,
        query=query,
        page=page,
        page_size=page_size,
    )
    return {
        "items": [_serialize_membership_user(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


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
    # 吊销（free）一律清空到期时间；member 保留传入到期时间（None = 长期有效）
    expires_at = body.expires_at if tier != MEMBERSHIP_TIER_FREE else None
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    updated = await asyncio.to_thread(
        repository.set_membership_tier,
        user_id=int(user["id"]),
        tier=tier,
        expires_at=expires_at,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {
        "user_id": int(user["id"]),
        "email": user.get("email"),
        "membership_tier": tier,
        "membership_expires_at": expires_at.isoformat() if expires_at else None,
        "revoked": tier == MEMBERSHIP_TIER_FREE,
    }
