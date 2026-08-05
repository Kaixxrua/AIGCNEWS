from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from backend.app.repositories.scheduler_job_config_repository import (
    SchedulerJobConfig,
    SchedulerJobConfigRepository,
)

DEFAULT_JOB_CONFIGS: dict[str, SchedulerJobConfig] = {
    "arxiv_papers": SchedulerJobConfig(
        job_id="arxiv_papers",
        start_time=time(0, 0),
        end_time=time(23, 59),
        interval_minutes=60,
    ),
    "github_trending": SchedulerJobConfig(
        job_id="github_trending",
        start_time=time(0, 0),
        end_time=time(23, 59),
        interval_minutes=60,
    ),
    "news_techmeme": SchedulerJobConfig(
        job_id="news_techmeme",
        start_time=time(0, 0),
        end_time=time(23, 59),
        interval_minutes=60,
    ),
    "producthunt": SchedulerJobConfig(
        job_id="producthunt",
        start_time=time(0, 0),
        end_time=time(23, 59),
        interval_minutes=60,
    ),
    "hackernews": SchedulerJobConfig(
        job_id="hackernews",
        start_time=time(0, 0),
        end_time=time(23, 59),
        interval_minutes=60,
    ),
    "x_watchlist": SchedulerJobConfig(
        job_id="x_watchlist",
        start_time=time(0, 0),
        end_time=time(23, 59),
        interval_minutes=120,
    ),
    "x_credentials_probe": SchedulerJobConfig(
        job_id="x_credentials_probe",
        start_time=time(0, 0),
        end_time=time(23, 59),
        interval_minutes=120,
    ),
    "github_project_daily_pipeline": SchedulerJobConfig(
        job_id="github_project_daily_pipeline",
        start_time=time(2, 0),
        end_time=time(2, 1),
        interval_minutes=1440,
    ),
    "github_project_metrics_refresh": SchedulerJobConfig(
        job_id="github_project_metrics_refresh",
        start_time=time(1, 17),
        end_time=time(23, 17),
        interval_minutes=120,
    ),
    "daily_briefing": SchedulerJobConfig(
        job_id="daily_briefing",
        start_time=time(8, 0),
        end_time=time(8, 1),
        interval_minutes=1440,
    ),
    "project_semantic_warmup": SchedulerJobConfig(
        job_id="project_semantic_warmup",
        start_time=time(0, 0),
        end_time=time(23, 59),
        interval_minutes=30,
    ),
    "conversation_cleanup": SchedulerJobConfig(
        job_id="conversation_cleanup",
        start_time=time(3, 30),
        end_time=time(3, 31),
        interval_minutes=10080,
    ),
}


_JOB_NAMES: dict[str, str] = {
    "arxiv_papers": "HuggingFace Papers 论文采集",
    "github_trending": "GitHub Trending 热榜采集",
    "news_techmeme": "Techmeme 科技新闻采集",
    "producthunt": "Product Hunt 新品采集",
    "hackernews": "Hacker News AI 热帖采集",
    "x_watchlist": "X 关注账号推文采集",
    "x_credentials_probe": "X 凭证池定时测活",
    "github_project_daily_pipeline": "GitHub 项目库每日流水线（入库、快照、热度打分、富化新增）",
    "github_project_metrics_refresh": "GitHub 项目库当天指标每两小时刷新",
    "daily_briefing": "每日自动简报生成（全维度）",
    "project_semantic_warmup": "项目语义搜索链路预热",
    "conversation_cleanup": "会话历史定期清理（7 天清 5 条）",
}


@dataclass(frozen=True)
class SchedulerJobConfigProjection:
    job_id: str
    name: str
    start_time: time
    end_time: time
    interval_minutes: int
    enabled: bool


class SchedulerConfigAdminService:
    """Read and update persistent scheduler job configurations.

    Falls back to hard-coded defaults when no database row exists so the admin
    UI always presents a complete list of jobs.
    """

    def __init__(self, repository: SchedulerJobConfigRepository) -> None:
        self._repository = repository

    def list_configs(self) -> list[SchedulerJobConfigProjection]:
        saved = {
            config.job_id: config
            for config in self._repository.list_scheduler_job_configs()
        }
        projections: list[SchedulerJobConfigProjection] = []
        for job_id, default in DEFAULT_JOB_CONFIGS.items():
            config = saved.get(job_id, default)
            projections.append(self._to_projection(config))
        return projections

    def update_config(
        self,
        job_id: str,
        *,
        start_time: time,
        end_time: time,
        interval_minutes: int,
        enabled: bool,
    ) -> SchedulerJobConfigProjection:
        default = DEFAULT_JOB_CONFIGS.get(job_id)
        if default is None:
            raise ValueError(f"未知定时任务: {job_id}")
        if start_time > end_time:
            raise ValueError("开始时间不能晚于结束时间")
        if interval_minutes <= 0:
            raise ValueError("轮询时间必须大于 0 分钟")

        updated = self._repository.upsert_scheduler_job_config(
            job_id,
            start_time=start_time,
            end_time=end_time,
            interval_minutes=interval_minutes,
            enabled=enabled,
        )
        return self._to_projection(updated)

    def _to_projection(self, config: SchedulerJobConfig) -> SchedulerJobConfigProjection:
        return SchedulerJobConfigProjection(
            job_id=config.job_id,
            name=_JOB_NAMES.get(config.job_id, config.job_id),
            start_time=config.start_time,
            end_time=config.end_time,
            interval_minutes=config.interval_minutes,
            enabled=config.enabled,
        )
