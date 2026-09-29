from __future__ import annotations

"""Framework-light dependency composition for briefing generation."""

import asyncio

from backend.app.core.model_factory import get_chat_model
from backend.app.repositories.application_repository_factory import (
    ApplicationRepositories,
)
from backend.app.repositories.project_catalog_factory import (
    get_project_catalog_repository,
)
from backend.app.services.briefing.daily_briefing import (
    BriefingModel,
    BriefingSavedNotifier,
    DailyBriefingService,
)
from backend.app.services.dashboard.query_service import GitHubHotBoardReader


def provide_daily_briefing_service(
    *,
    repositories: ApplicationRepositories,
    model: BriefingModel | None = None,
    top_k: int = 10,
    briefing_saved: BriefingSavedNotifier | None = None,
    llm_limiter: asyncio.Semaphore | None = None,
    github_hot_board: GitHubHotBoardReader | None = None,
) -> DailyBriefingService:
    """Build a briefing service from borrowed application dependencies.

    github_hot_board 缺省取项目库目录仓储（与首页看板 github 榜同一来源）。
    """
    return DailyBriefingService(
        top_k=top_k,
        briefing_repository=repositories.briefings,
        document_feed=repositories.documents,
        rank_snapshot_reader=repositories.rank_snapshots,
        github_hot_board=github_hot_board or get_project_catalog_repository(),
        model=model or get_chat_model(),
        briefing_saved=briefing_saved,
        llm_limiter=llm_limiter,
    )
