from datetime import date

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
