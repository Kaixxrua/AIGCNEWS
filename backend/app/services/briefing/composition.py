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

# max / xhigh 推理可能思考超过上游约 900 秒的单流上限、一个字没写就被切断；
# 这时用同一模型的 high 档重跑一次，保住当天这一份简报。
_FALLBACK_REASONING_EFFORTS = frozenset({"xhigh", "max"})
_FALLBACK_REASONING_EFFORT = "high"


def _briefing_fallback_model(model: BriefingModel) -> BriefingModel | None:
    if getattr(model, "reasoning_effort", None) not in _FALLBACK_REASONING_EFFORTS:
        return None
    return get_chat_model(reasoning_effort=_FALLBACK_REASONING_EFFORT)


def provide_daily_briefing_service(
    *,
    repositories: ApplicationRepositories,
    model: BriefingModel | None = None,
    fallback_model: BriefingModel | None = None,
    top_k: int = 10,
    briefing_saved: BriefingSavedNotifier | None = None,
    llm_limiter: asyncio.Semaphore | None = None,
    github_hot_board: GitHubHotBoardReader | None = None,
) -> DailyBriefingService:
    """Build a briefing service from borrowed application dependencies.

    github_hot_board 缺省取项目库目录仓储（与首页看板 github 榜同一来源）。
    未显式传 model 时使用运行时聊天模型；其推理档位为 max / xhigh 时，
    缺省配同一模型的 high 档作为零输出失败后的兜底。
    """
    if model is None:
        model = get_chat_model()
        if fallback_model is None:
            fallback_model = _briefing_fallback_model(model)
    return DailyBriefingService(
        top_k=top_k,
        briefing_repository=repositories.briefings,
        document_feed=repositories.documents,
        rank_snapshot_reader=repositories.rank_snapshots,
        github_hot_board=github_hot_board or get_project_catalog_repository(),
        model=model,
        briefing_saved=briefing_saved,
        llm_limiter=llm_limiter,
        fallback_model=fallback_model,
    )
