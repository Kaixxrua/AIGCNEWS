from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.app.api.dependencies import get_application_repositories
from backend.app.repositories.application_repository_factory import ApplicationRepositories
from backend.app.services.dashboard.new_words import public_snapshot, today

router = APIRouter()


@router.get("/dashboard/new-words")
def get_new_words(
    date: date | None = Query(default=None),
    repositories: ApplicationRepositories = Depends(get_application_repositories),
):
    day = date or today()
    if day > today():
        raise HTTPException(422, "Future dates are not available")
    if repositories.new_words is None:
        raise HTTPException(503, "New words are unavailable")
    return public_snapshot(repositories.new_words, day)


@router.get("/dashboard/new-words/history")
def get_new_words_history(
    before: date | None = Query(default=None),
    limit: int = Query(default=14, ge=1, le=31),
    repositories: ApplicationRepositories = Depends(get_application_repositories),
):
    latest = today() + timedelta(days=1)
    cutoff = before or latest
    if cutoff > latest:
        raise HTTPException(422, "Future dates are not available")
    if repositories.new_words is None:
        raise HTTPException(503, "New words are unavailable")
    days = repositories.new_words.snapshot_dates(cutoff, limit + 1)
    # Reuse live citation/source checks; old snapshots cannot bypass deletion.
    snapshots = [public_snapshot(repositories.new_words, day) for day in days[:limit]]
    return {"items": [snapshot for snapshot in snapshots if snapshot["items"]],
            "next_before": days[limit - 1].isoformat() if len(days) > limit else None}
