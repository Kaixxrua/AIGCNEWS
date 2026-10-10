from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from backend.app.core.auth import RequireAdmin, RequireUser, extract_user_id
from backend.app.repositories.postgres_account_visit_repository import PostgresAccountVisitRepository
from backend.app.repositories.postgres_email_monitor_repository import PostgresEmailMonitorRepository
from backend.app.services.dashboard.visit_platforms import classify_platform

router = APIRouter()


def account_visits(request: Request) -> PostgresAccountVisitRepository:
    return PostgresAccountVisitRepository(request.app.state.postgres_database)


def email_monitor(request: Request) -> PostgresEmailMonitorRepository:
    return PostgresEmailMonitorRepository(request.app.state.postgres_database)


@router.post("/dashboard/account-visit")
async def record_account_visit(
    request: Request, response: Response,
    user: dict = Depends(RequireUser),
    visits: PostgresAccountVisitRepository = Depends(account_visits),
):
    response.headers["Cache-Control"] = "no-store"
    user_id = extract_user_id(user)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid account")
    if classify_platform(request.headers.get("user-agent")) == "bot":
        return {"recorded": False}
    # Never accept account IDs, dates or registration timestamps from the body.
    result = await asyncio.to_thread(visits.record, user_id)
    return {**result, "user_id": user_id}


@router.get("/monitor/user-return-visits")
async def user_return_visits(
    response: Response,
    days: int = Query(default=30, ge=1, le=90),
    _: dict = Depends(RequireAdmin),
    visits: PostgresAccountVisitRepository = Depends(account_visits),
):
    response.headers["Cache-Control"] = "no-store"
    return await asyncio.to_thread(visits.stats, days)


@router.get("/monitor/email")
async def email_status(
    response: Response,
    _: dict = Depends(RequireAdmin),
    monitor: PostgresEmailMonitorRepository = Depends(email_monitor),
):
    response.headers["Cache-Control"] = "no-store"
    # Reading the panel never sends an email or bypasses the five-minute lease.
    return await asyncio.to_thread(monitor.read)
