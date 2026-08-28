from __future__ import annotations

"""Framework-light dependency composition for briefing generation."""

from backend.app.core.model_factory import get_chat_model
from backend.app.repositories.application_repository_factory import (
    ApplicationRepositories,
)
from backend.app.services.briefing.daily_briefing import (
    BriefingModel,
    BriefingSavedNotifier,
    DailyBriefingService,
)


def provide_daily_briefing_service(
    *,
    repositories: ApplicationRepositories,
    model: BriefingModel | None = None,
    top_k: int = 10,
    briefing_saved: BriefingSavedNotifier | None = None,
) -> DailyBriefingService:
    """Build a briefing service from borrowed application dependencies."""
    return DailyBriefingService(
        top_k=top_k,
        briefing_repository=repositories.briefings,
        document_feed=repositories.documents,
        rank_snapshot_reader=repositories.rank_snapshots,
        model=model or get_chat_model(),
        briefing_saved=briefing_saved,
    )
