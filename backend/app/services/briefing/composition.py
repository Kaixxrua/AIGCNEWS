from __future__ import annotations

"""Framework-light dependency composition for briefing generation."""

from backend.app.core.model_factory import get_chat_model
from backend.app.repositories.application_repository_context import (
    get_configured_application_repositories,
)
from backend.app.repositories.application_repository_factory import ApplicationRepositories
from backend.app.services.briefing.daily_briefing import BriefingModel, DailyBriefingService


def provide_daily_briefing_service(
    *,
    repositories: ApplicationRepositories | None = None,
    model: BriefingModel | None = None,
    top_k: int = 10,
) -> DailyBriefingService:
    """Build a briefing service from borrowed application dependencies."""
    borrowed = repositories or get_configured_application_repositories()
    return DailyBriefingService(
        top_k=top_k,
        briefing_repository=borrowed.briefings,
        document_feed=borrowed.documents,
        rank_snapshot_reader=borrowed.rank_snapshots,
        model=model or get_chat_model(),
    )
