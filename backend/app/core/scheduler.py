from __future__ import annotations

"""智能调度中心（M15 — 多源独立调度）

将单一 cron job 拆分为多任务、多频率的独立调度。
每个数据源可以按照自身特性设置不同的采集频率。

设计原则：
  - 每个数据源独立 APScheduler Job，互不影响
  - 通过不可变任务描述符集中管理所有调度配置
  - max_instances=1 防止同源 job 重叠执行
  - misfire_grace_time=7200 确保服务重启后追赶执行
  - 保留 run_smart_ingestion() 兼容入口：仍可手动调用全量采集
  - 调度器、共享锁与启动对账任务归属 ApplicationSchedulerRuntime
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from backend.app.core.scheduler_registry import (
    CONVERSATION_CLEANUP_JOB,
    DAILY_BRIEFING_JOB,
    SOURCE_JOB_DESCRIPTORS,
    JobDescriptor,
    SchedulerCallback,
    apply_job_config,
    build_trigger,
    project_scheduler_status,
    project_semantic_warmup_job_descriptor,
    resolve_source_job_callback,
)
from backend.app.repositories.application_repository_factory import (
    ApplicationRepositories,
)
from backend.app.repositories.briefing_repository import ActiveBriefingSubscriberReader
from backend.app.repositories.conversation_repository import ConversationCleanupWriter
from backend.app.repositories.rank_snapshot_repository import RankSnapshotRepository
from backend.app.services.x_credentials.probe import probe_all_x_credentials

logger = logging.getLogger(__name__)

_ARXIV_RECONCILE_DAYS = 2
_GITHUB_METRICS_REFRESH_LIMIT = 0  # 0 表示刷新全部符合条件的项目
_GITHUB_METRICS_MIN_STARS = 500
_GITHUB_METRICS_MAX_AGE = timedelta(hours=2, minutes=15)


def _missing_recent_arxiv_daily_dates(
    rank_snapshots: RankSnapshotRepository,
) -> List[str]:
    """Return missing recent HF daily dates, bounded to avoid startup storms."""
    from backend.app.services.ingestion.base_crawler import today_cst

    repository = rank_snapshots
    today = date.fromisoformat(today_cst())
    candidates = [
        (today - timedelta(days=offset)).isoformat()
        for offset in range(_ARXIV_RECONCILE_DAYS, 0, -1)
    ]
    existing = set(
        repository.get_snapshot_dates(
            limit=_ARXIV_RECONCILE_DAYS,
            source="arxiv",
            period="daily",
        )
    )
    return [candidate for candidate in candidates if candidate not in existing]


async def _reconcile_recent_arxiv_daily_snapshots(
    rank_snapshots: RankSnapshotRepository,
    *,
    repositories: ApplicationRepositories,
) -> None:
    snapshots = rank_snapshots
    try:
        missing_dates = await asyncio.to_thread(
            _missing_recent_arxiv_daily_dates,
            snapshots,
        )
    except Exception as exc:
        logger.warning("[Scheduler] 检查 Arxiv 日榜缺口失败，跳过启动补齐: %s", exc)
        return

    for target_date in missing_dates:
        logger.info("[Scheduler] 补齐缺失 Arxiv 日榜快照: %s", target_date)
        try:
            from backend.app.services.ingestion.composition import (
                provide_ingestion_dependencies,
            )
            from backend.app.services.ingestion.pipeline import (
                run_single_source_pipeline,
            )

            arguments: dict[str, Any] = {
                "target_date": target_date,
                "periods": ["daily"],
                "dependencies": provide_ingestion_dependencies(
                    repositories=repositories,
                ),
            }
            await asyncio.to_thread(
                run_single_source_pipeline,
                "arxiv",
                **arguments,
            )
        except Exception as exc:
            logger.error("[Scheduler] Arxiv 日榜快照补齐失败 %s: %s", target_date, exc)


async def _run_single_source_job(
    source_name: str,
    *,
    repositories: ApplicationRepositories,
    github_lock: asyncio.Lock | None = None,
    x_lock: asyncio.Lock | None = None,
) -> None:
    logger.info("[Scheduler] 触发 %s 采集任务...", source_name)
    active_repositories = repositories
    lock = github_lock if source_name == "github" else x_lock if source_name == "x" else None
    try:
        from backend.app.services.ingestion.composition import (
            provide_ingestion_dependencies,
        )
        from backend.app.services.ingestion.pipeline import run_single_source_pipeline

        dependencies = provide_ingestion_dependencies(
            repositories=active_repositories,
        )
        if lock is None:
            result = await asyncio.to_thread(
                run_single_source_pipeline,
                source_name,
                dependencies=dependencies,
            )
        else:
            async with lock:
                result = await asyncio.to_thread(
                    run_single_source_pipeline,
                    source_name,
                    dependencies=dependencies,
                )
        ingested = result.get("ingested_total", 0)
        logger.info("[Scheduler] %s 采集完成，入库 %d 条。", source_name, ingested)
    except Exception as exc:
        logger.error("[Scheduler] %s 采集失败: %s", source_name, exc, exc_info=True)


async def _run_github_project_daily_pipeline_job(
    *,
    repositories: ApplicationRepositories,
    github_lock: asyncio.Lock | None = None,
) -> None:
    logger.info("[Scheduler] 触发 GitHub 项目库每日流水线...")
    active_repositories = repositories
    lock = github_lock or asyncio.Lock()
    try:
        from backend.app.services.ingestion.github_project_enricher import (
            run_github_project_daily_pipeline,
        )

        async with lock:
            result = await asyncio.to_thread(
                run_github_project_daily_pipeline,
                refresh_limit=80,
                enrich_limit=50,
                ingestion=active_repositories.github_ingestion,
                enrichment=active_repositories.github_enrichment,
                semantic_sources=active_repositories.github_semantic_sources,
            )
        logger.info("[Scheduler] GitHub 项目库每日流水线完成：%s", result)
    except Exception as exc:
        logger.error("[Scheduler] GitHub 项目库每日流水线失败: %s", exc, exc_info=True)


def _github_refresh_needed(status: Dict[str, Any]) -> bool:
    target_count = int(status.get("target_count") or 0)
    if target_count == 0:
        return False
    if int(status.get("snapshot_count") or 0) < target_count:
        return True
    if int(status.get("metric_count") or 0) < target_count:
        return True

    latest = status.get("oldest_captured_at")
    if not latest:
        return True
    if isinstance(latest, str):
        try:
            latest = datetime.fromisoformat(latest.replace("Z", "+00:00"))
        except ValueError:
            return True
    if not isinstance(latest, datetime):
        return True
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - latest.astimezone(timezone.utc) > _GITHUB_METRICS_MAX_AGE


async def _refresh_current_github_project_metrics(
    metric_date: str,
    repository: Any,
) -> Dict[str, Any]:
    from backend.app.services.ingestion.github_project_metrics_service import (
        refresh_and_compute_github_project_metrics,
    )

    active_repository = repository
    return await asyncio.to_thread(
        refresh_and_compute_github_project_metrics,
        min_stars=_GITHUB_METRICS_MIN_STARS,
        limit=_GITHUB_METRICS_REFRESH_LIMIT,
        metric_date=metric_date,
        db=active_repository,
    )


async def _run_github_project_metrics_refresh_job(
    *,
    repository: Any,
    github_lock: asyncio.Lock | None = None,
) -> None:
    from backend.app.services.ingestion.github_project_metrics_service import (
        current_github_metric_date,
    )

    metric_date = current_github_metric_date()
    logger.info("[Scheduler] 触发 GitHub 当天指标刷新: %s", metric_date)
    lock = github_lock or asyncio.Lock()
    try:
        async with lock:
            result = await _refresh_current_github_project_metrics(
                metric_date,
                repository,
            )
        logger.info("[Scheduler] GitHub 当天指标刷新完成：%s", result)
    except Exception as exc:
        logger.error("[Scheduler] GitHub 当天指标刷新失败: %s", exc, exc_info=True)


async def _reconcile_current_github_project_metrics(
    repository: Any,
    *,
    github_lock: asyncio.Lock | None = None,
) -> None:
    from backend.app.services.ingestion.github_project_metrics_service import (
        current_github_metric_date,
    )

    metric_date = current_github_metric_date()
    active_repository = repository
    lock = github_lock or asyncio.Lock()
    try:
        async with lock:
            status = await asyncio.to_thread(
                active_repository.get_github_metric_refresh_status,
                metric_date=metric_date,
                min_stars=_GITHUB_METRICS_MIN_STARS,
                limit=_GITHUB_METRICS_REFRESH_LIMIT,
            )
            if not _github_refresh_needed(status):
                logger.info("[Scheduler] GitHub 当天指标完整且新鲜，跳过启动补跑：%s", status)
                return
            logger.info("[Scheduler] GitHub 当天指标缺失或过期，执行启动补跑：%s", status)
            await _refresh_current_github_project_metrics(
                metric_date,
                active_repository,
            )
    except Exception as exc:
        logger.warning("[Scheduler] GitHub 当天指标启动补跑失败: %s", exc, exc_info=True)


async def _run_github_hot_job(repository: Any) -> None:
    logger.info("[Scheduler] 触发 GitHub 热度快照刷新...")
    try:
        from backend.app.services.ingestion.github_hot_service import (
            refresh_github_hot_candidates,
        )

        await asyncio.to_thread(
            refresh_github_hot_candidates,
            80,
            db=repository,
        )
        logger.info("[Scheduler] GitHub 热度快照刷新完成。")
    except Exception as exc:
        logger.error("[Scheduler] GitHub 热度快照刷新失败: %s", exc, exc_info=True)


async def _run_github_project_enrichment_job(repository: Any) -> None:
    logger.info("[Scheduler] 触发 GitHub 项目库 AI 分类富化...")
    try:
        from backend.app.services.ingestion.github_project_enricher import (
            enrich_github_projects,
        )

        result = await asyncio.to_thread(
            enrich_github_projects,
            limit=50,
            db=repository,
        )
        logger.info("[Scheduler] GitHub 项目库 AI 分类富化完成：%s", result)
    except Exception as exc:
        logger.error("[Scheduler] GitHub 项目库 AI 分类富化失败: %s", exc, exc_info=True)


async def _run_smart_ingestion_job(
    reader: Any,
    runner: Callable[[int], Any],
) -> None:
    logger.info("[Scheduler] 触发智能全量采集任务...")
    try:
        from backend.app.services.ingestion.pipeline import run_smart_ingestion

        await asyncio.to_thread(
            run_smart_ingestion,
            20,
            reader=reader,
            runner=runner,
        )
        logger.info("[Scheduler] 智能全量采集任务完成。")
    except Exception as exc:
        logger.error("[Scheduler] 智能全量采集失败: %s", exc, exc_info=True)


_BRIEFING_TASKS: List[Dict[str, str]] = [
    {"source": "all", "period": "daily"},
    {"source": "arxiv", "period": "daily"},
    {"source": "github", "period": "daily"},
    {"source": "news", "period": "daily"},
    {"source": "producthunt", "period": "daily"},
    {"source": "hackernews", "period": "daily"},
    {"source": "x", "period": "daily"},
]


async def _send_briefing_to_subscribers(
    *,
    source: str,
    period: str,
    date_str: str,
    content: str,
    subscriptions: ActiveBriefingSubscriberReader,
) -> int:
    from backend.app.services.email_service import build_email_service

    subscribers = subscriptions.get_active_subscribers(source=source, period=period)
    if not subscribers:
        return 0

    email_svc = build_email_service(None)

    sent = 0
    for subscriber in subscribers:
        email = subscriber.get("email")
        if not email:
            continue
        try:
            await email_svc.send_briefing(
                to_email=email,
                briefing_content=content,
                source=source,
                period=period,
                date_str=date_str,
            )
            sent += 1
        except Exception as exc:
            logger.error(
                "[Scheduler] 订阅简报发送失败: source=%s period=%s email=%s error=%s",
                source,
                period,
                email,
                exc,
                exc_info=True,
            )
    return sent


async def _run_daily_briefing_job(
    repositories: ApplicationRepositories,
) -> None:
    logger.info(
        "[Scheduler] 触发每日自动简报生成（%d 个维度）...", len(_BRIEFING_TASKS)
    )
    from backend.app.services.briefing.composition import provide_daily_briefing_service

    service = provide_daily_briefing_service(repositories=repositories)
    success = 0
    for task in _BRIEFING_TASKS:
        source = task["source"]
        period = task["period"]
        try:
            content_parts: list[str] = []
            report_date = ""
            briefing_id = -1
            async for payload in service.stream_generate(
                target_date=None,
                source=source,
                period=period,
                force_regenerate=False,
                generate_bilingual=True,
            ):
                payload_type = payload.get("type")
                if payload_type == "start":
                    data = payload.get("data") or {}
                    report_date = str(data.get("date") or "")
                elif payload_type == "content":
                    content_parts.append(str(payload.get("data") or ""))
                elif payload_type == "done":
                    data = payload.get("data") or {}
                    briefing_id = int(data.get("briefing_id") or -1)
            success += 1
            logger.info(
                "[Scheduler] 日报生成完成，准备推送订阅用户: source=%s period=%s",
                source,
                period,
            )
            content = "".join(content_parts)
            if briefing_id > 0 and content.strip() and report_date:
                sent = await _send_briefing_to_subscribers(
                    source=source,
                    period=period,
                    date_str=report_date,
                    content=content,
                    subscriptions=repositories.briefing_subscriptions,
                )
                logger.info(
                    "[Scheduler] 订阅简报发送完成: source=%s period=%s sent=%d",
                    source,
                    period,
                    sent,
                )
        except Exception as exc:
            logger.error(
                "[Scheduler] 简报生成失败: source=%s period=%s error=%s",
                source,
                period,
                exc,
                exc_info=True,
            )

    logger.info(
        "[Scheduler] 每日简报生成完毕，%d/%d 成功。", success, len(_BRIEFING_TASKS)
    )


async def _run_project_semantic_warmup_job(
    warmup: Any | None = None,
) -> None:
    try:
        if warmup is None:
            from backend.app.services.project_semantic_search import (
                warmup_project_semantic_search,
            )

            warmup = warmup_project_semantic_search
        result = await asyncio.to_thread(warmup)
        if result.get("status") == "failed":
            logger.warning("[Scheduler] 项目语义搜索预热失败：%s", result)
        else:
            logger.info("[Scheduler] 项目语义搜索预热完成：%s", result)
    except Exception as exc:
        logger.warning("[Scheduler] 项目语义搜索预热失败: %s", exc)


async def _run_conversation_cleanup_job(
    conversation_repository: ConversationCleanupWriter,
) -> None:
    logger.info("[Scheduler] 触发会话历史清理任务...")
    try:
        from backend.app.services.chat.conversation_service import ConversationService

        deleted = await asyncio.to_thread(
            ConversationService(conversation_repository).cleanup_stale_conversations,
        )
        logger.info("[Scheduler] 会话历史清理完成，删除 %d 条旧会话。", deleted)
    except Exception as exc:
        logger.error("[Scheduler] 会话历史清理失败: %s", exc, exc_info=True)


async def _run_x_credentials_probe_job(
    *,
    repositories: ApplicationRepositories,
    x_lock: asyncio.Lock | None = None,
) -> None:
    """Probe all enabled X credentials serially and persist results.

    Shares the X operation lock with the X ingestion job so the two never
    hit X concurrently.
    """
    logger.info("[Scheduler] 触发 X 凭证池测活...")
    try:
        credentials = await asyncio.to_thread(
            repositories.x_credentials.list_enabled_x_credentials,
        )
        handles = await asyncio.to_thread(
            repositories.x_watch_accounts.list_enabled_x_handles,
        )
        handle = handles[0] if handles else ""

        lock = x_lock or asyncio.Lock()
        async with lock:
            results = await asyncio.to_thread(
                probe_all_x_credentials,
                credentials,
                handle,
                update_result=repositories.x_credentials.update_x_credential_test_result,
            )
        succeeded = sum(1 for result in results if result.get("status") == "succeeded")
        logger.info(
            "[Scheduler] X 凭证池测活完成：%d/%d 成功。",
            succeeded,
            len(results),
        )
    except Exception as exc:
        logger.error("[Scheduler] X 凭证池测活失败: %s", exc, exc_info=True)


def _register_job(
    scheduler: AsyncIOScheduler,
    descriptor: JobDescriptor,
    callback: SchedulerCallback,
) -> None:
    job_kwargs: Dict[str, Any] = {
        "trigger": build_trigger(descriptor),
        "id": descriptor.id,
        "name": descriptor.name,
        "replace_existing": descriptor.replace_existing,
        "max_instances": descriptor.max_instances,
        "misfire_grace_time": descriptor.misfire_grace_time,
    }
    if descriptor.coalesce is not None:
        job_kwargs["coalesce"] = descriptor.coalesce
    scheduler.add_job(callback, **job_kwargs)


class ApplicationSchedulerRuntime:
    """Application-owned scheduler, callbacks, locks, and startup tasks."""

    def __init__(
        self,
        repositories: ApplicationRepositories,
        *,
        scheduler: AsyncIOScheduler | None = None,
        semantic_search_enabled: bool = False,
        semantic_search_warmup: Any | None = None,
        shutdown_grace_seconds: float = 30.0,
        timezone_name: str = "Asia/Shanghai",
        job_config_overrides: Mapping[str, Any] | None = None,
    ) -> None:
        self.repositories = repositories
        self.scheduler = scheduler or AsyncIOScheduler(timezone=timezone_name)
        self._semantic_search_enabled = semantic_search_enabled
        self._semantic_search_warmup = semantic_search_warmup
        self._shutdown_grace_seconds = max(0.0, float(shutdown_grace_seconds))
        self._timezone_name = timezone_name
        self._job_config_overrides: Dict[str, Any] = dict(job_config_overrides or {})
        self._github_job_lock = asyncio.Lock()
        self._x_operation_lock = asyncio.Lock()
        self._active_tasks: set[asyncio.Task[Any]] = set()
        self._stopping = False
        self._stop_lock = asyncio.Lock()

    @property
    def x_operation_lock(self) -> asyncio.Lock:
        """Shared lock used to serialize all X/Twitter network requests.

        Routes and scheduled jobs must acquire this lock before issuing X
        requests so manual tests, scheduled probes, and ingestion never run
        concurrently against X.
        """
        return self._x_operation_lock

    async def _run_tracked(
        self,
        operation: Callable[[], Awaitable[Any]],
    ) -> None:
        if self._stopping:
            logger.info("[Scheduler] 正在停止，跳过新调度任务。")
            return
        task = asyncio.create_task(operation())
        self._active_tasks.add(task)
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            # APScheduler cancels its wrapper futures during shutdown. Keep the
            # owned operation alive and join it before repositories are closed.
            await task
        finally:
            if task.done():
                self._active_tasks.discard(task)

    async def _run_single_source_job(self, source_name: str) -> None:
        await self._run_tracked(
            lambda: _run_single_source_job(
                source_name,
                repositories=self.repositories,
                github_lock=self._github_job_lock,
                x_lock=self._x_operation_lock,
            )
        )

    async def _run_github_project_daily_pipeline_job(self) -> None:
        await self._run_tracked(
            lambda: _run_github_project_daily_pipeline_job(
                repositories=self.repositories,
                github_lock=self._github_job_lock,
            )
        )

    async def _run_github_project_metrics_refresh_job(self) -> None:
        await self._run_tracked(
            lambda: _run_github_project_metrics_refresh_job(
                repository=self.repositories.github_ingestion,
                github_lock=self._github_job_lock,
            )
        )

    async def _run_x_credentials_probe_job(self) -> None:
        await self._run_tracked(
            lambda: _run_x_credentials_probe_job(
                repositories=self.repositories,
                x_lock=self._x_operation_lock,
            )
        )

    async def _run_daily_briefing_job(self) -> None:
        await self._run_tracked(
            lambda: _run_daily_briefing_job(self.repositories)
        )

    async def _run_conversation_cleanup_job(self) -> None:
        await self._run_tracked(
            lambda: _run_conversation_cleanup_job(self.repositories.conversations)
        )

    async def _run_project_semantic_warmup_job(self) -> None:
        await self._run_tracked(
            lambda: _run_project_semantic_warmup_job(
                self._semantic_search_warmup,
            )
        )

    def _effective_descriptor(
        self,
        descriptor: JobDescriptor,
    ) -> JobDescriptor | None:
        override = self._job_config_overrides.get(descriptor.id)
        if override is None:
            return descriptor
        return apply_job_config(descriptor, override)

    def _job_callbacks(self) -> Dict[str, Any]:
        return {
            "_run_single_source_job": self._run_single_source_job,
            "_run_github_project_daily_pipeline_job": (
                self._run_github_project_daily_pipeline_job
            ),
            "_run_github_project_metrics_refresh_job": (
                self._run_github_project_metrics_refresh_job
            ),
            "_run_x_credentials_probe_job": self._run_x_credentials_probe_job,
        }

    def _base_descriptor(self, job_id: str) -> JobDescriptor | None:
        for descriptor in SOURCE_JOB_DESCRIPTORS:
            if descriptor.id == job_id:
                return descriptor
        if job_id == DAILY_BRIEFING_JOB.id:
            return DAILY_BRIEFING_JOB
        if job_id == CONVERSATION_CLEANUP_JOB.id:
            return CONVERSATION_CLEANUP_JOB
        if job_id == "project_semantic_warmup" and self._semantic_search_enabled:
            return project_semantic_warmup_job_descriptor(
                timezone=self._timezone_name
            )
        return None

    def _resolve_callback(self, descriptor: JobDescriptor) -> SchedulerCallback | None:
        if descriptor.id == DAILY_BRIEFING_JOB.id:
            return self._run_daily_briefing_job
        if descriptor.id == CONVERSATION_CLEANUP_JOB.id:
            return self._run_conversation_cleanup_job
        if descriptor.source == "project_semantic_warmup":
            if not self._semantic_search_enabled:
                return None
            return self._run_project_semantic_warmup_job
        return resolve_source_job_callback(descriptor.source, self._job_callbacks())

    def apply_config_update(self, config: Any) -> bool:
        """将已保存的任务配置即时应用到运行中的调度器。

        调度器未运行或任务不可在线管理时返回 False，配置将在下次启动时生效。
        """
        self._job_config_overrides[config.job_id] = config

        descriptor = self._base_descriptor(config.job_id)
        if descriptor is None or not self.scheduler.running:
            return False

        effective = self._effective_descriptor(descriptor)
        existing = self.scheduler.get_job(config.job_id)
        if effective is None:
            if existing is not None:
                self.scheduler.remove_job(config.job_id)
                logger.info("[Scheduler] 已停用并移除任务: %s", config.job_id)
            return True
        if existing is not None:
            self.scheduler.reschedule_job(
                config.job_id,
                trigger=build_trigger(effective),
            )
            logger.info(
                "[Scheduler] 已即时更新任务触发器: %s trigger=%s",
                config.job_id,
                build_trigger(effective),
            )
            return True
        callback = self._resolve_callback(effective)
        if callback is None:
            return False
        _register_job(self.scheduler, effective, callback)
        logger.info(
            "[Scheduler] 已启用并注册任务: %s trigger=%s",
            effective.id,
            build_trigger(effective),
        )
        return True

    def start(self) -> None:
        if self.scheduler.running:
            logger.info("[Scheduler] 已在运行，跳过重复启动。")
            return
        self._stopping = False

        callbacks = self._job_callbacks()
        for descriptor in SOURCE_JOB_DESCRIPTORS:
            effective = self._effective_descriptor(descriptor)
            if effective is None:
                logger.info("[Scheduler] 跳过已停用的采集任务: %s", descriptor.id)
                continue
            _register_job(
                self.scheduler,
                effective,
                resolve_source_job_callback(effective.source, callbacks),
            )
            logger.info(
                "[Scheduler] 注册采集任务: %s (%s) trigger=%s",
                effective.id,
                effective.name,
                str(build_trigger(effective)),
            )

        daily_briefing = self._effective_descriptor(DAILY_BRIEFING_JOB)
        if daily_briefing is not None:
            _register_job(
                self.scheduler,
                daily_briefing,
                self._run_daily_briefing_job,
            )
            logger.info(
                "[Scheduler] 注册简报任务: daily_briefing (共 %d 个维度)",
                len(_BRIEFING_TASKS),
            )
        else:
            logger.info("[Scheduler] 跳过已停用的简报任务: daily_briefing")

        if self._semantic_search_enabled:
            semantic_descriptor = self._effective_descriptor(
                project_semantic_warmup_job_descriptor(timezone=self._timezone_name)
            )
            if semantic_descriptor is not None:
                _register_job(
                    self.scheduler,
                    semantic_descriptor,
                    self._run_project_semantic_warmup_job,
                )
                logger.info("[Scheduler] 注册项目语义搜索预热任务（每 %d 分钟）", getattr(semantic_descriptor, "interval_minutes", 30))
            else:
                logger.info("[Scheduler] 跳过已停用的语义搜索预热任务")

        conversation_cleanup = self._effective_descriptor(CONVERSATION_CLEANUP_JOB)
        if conversation_cleanup is not None:
            _register_job(
                self.scheduler,
                conversation_cleanup,
                self._run_conversation_cleanup_job,
            )
            logger.info("[Scheduler] 注册会话清理任务: conversation_cleanup")
        else:
            logger.info("[Scheduler] 跳过已停用的会话清理任务: conversation_cleanup")

        self.scheduler.start()
        loop = asyncio.get_running_loop()
        for coroutine in (
            _reconcile_recent_arxiv_daily_snapshots(
                self.repositories.rank_snapshots,
                repositories=self.repositories,
            ),
            _reconcile_current_github_project_metrics(
                self.repositories.github_ingestion,
                github_lock=self._github_job_lock,
            ),
        ):
            task = loop.create_task(coroutine)
            self._active_tasks.add(task)

        jobs = self.scheduler.get_jobs()
        logger.info("[Scheduler] APScheduler 已启动，共 %d 个调度任务：", len(jobs))
        for job in jobs:
            logger.info("  📅 %s | %s | 下次执行: %s", job.id, job.name, job.next_run_time)

    async def stop(self) -> None:
        async with self._stop_lock:
            if self._stopping:
                return
            self._stopping = True
            if self.scheduler.running:
                self.scheduler.pause()
                self.scheduler.shutdown(wait=False)
                await asyncio.sleep(0)

            tasks = tuple(self._active_tasks)
            if tasks:
                _, pending = await asyncio.wait(
                    tasks,
                    timeout=self._shutdown_grace_seconds,
                )
                if pending:
                    logger.warning(
                        "[Scheduler] %d 个任务超过 %.1f 秒关闭宽限期，"
                        "为保护应用资源额外等待 %.1f 秒后将强制取消。",
                        len(pending),
                        self._shutdown_grace_seconds,
                        self._shutdown_grace_seconds,
                    )
                    _, pending = await asyncio.wait(
                        pending,
                        timeout=self._shutdown_grace_seconds,
                    )
                if pending:
                    logger.error(
                        "[Scheduler] %d 个任务在 %.1f 秒内仍未结束，强制取消 "
                        "(底层 to_thread 线程仍会跑完，仅放弃等待)。",
                        len(pending),
                        self._shutdown_grace_seconds * 2,
                    )
                    for task in pending:
                        task.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
            self._active_tasks.clear()
            logger.info("[Scheduler] APScheduler 及运行中任务已停止。")

    def status(self) -> List[Dict[str, Any]]:
        if not self.scheduler.running:
            return []
        return project_scheduler_status(self.scheduler.get_jobs())


def create_scheduler_runtime(
    repositories: ApplicationRepositories,
    *,
    enabled: bool = True,
    semantic_search_warmup: Any | None = None,
    job_config_overrides: Mapping[str, Any] | None = None,
) -> ApplicationSchedulerRuntime:
    from backend.app.core.config import settings

    timezone_name = "Asia/Shanghai"
    if enabled:
        timezone_name = (
            getattr(settings, "scheduler_timezone", timezone_name)
            or timezone_name
        )
    return ApplicationSchedulerRuntime(
        repositories,
        semantic_search_enabled=bool(
            getattr(settings, "project_semantic_search_enabled", False)
        ),
        semantic_search_warmup=semantic_search_warmup,
        shutdown_grace_seconds=float(
            getattr(settings, "scheduler_shutdown_grace_seconds", 30.0)
        ),
        timezone_name=timezone_name,
        job_config_overrides=job_config_overrides,
    )
