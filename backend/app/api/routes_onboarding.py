from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict

from backend.app.api.dependencies import get_user_account_repository
from backend.app.core.auth import RequireUser
from backend.app.repositories.user_account_repository import UserAccountRepository

router = APIRouter(prefix="/auth/me/onboarding", tags=["Auth"])


class OnboardingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["skipped", "completed"]


class OnboardingState(BaseModel):
    status: Literal["unseen", "skipped", "completed"]


def _response(status: str | None, response: Response) -> OnboardingState:
    if status is None:
        raise HTTPException(status_code=401, detail="账号不存在或已被禁用")
    response.headers["Cache-Control"] = "no-store"
    return OnboardingState(status=status)


@router.get("", response_model=OnboardingState)
async def get_onboarding(
    response: Response,
    current_user: dict[str, Any] = Depends(RequireUser),
    repository: UserAccountRepository = Depends(get_user_account_repository),
) -> OnboardingState:
    status = await asyncio.to_thread(repository.get_onboarding_status, user_id=int(current_user["user_id"]))
    return _response(status, response)


@router.put("", response_model=OnboardingState)
async def save_onboarding(
    body: OnboardingUpdate,
    response: Response,
    current_user: dict[str, Any] = Depends(RequireUser),
    repository: UserAccountRepository = Depends(get_user_account_repository),
) -> OnboardingState:
    status = await asyncio.to_thread(
        repository.save_onboarding_status,
        user_id=int(current_user["user_id"]),
        status=body.status,
    )
    return _response(status, response)
