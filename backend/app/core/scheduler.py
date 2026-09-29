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
import os
import subprocess
import sys
import threading
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from backend.app.core.scheduler_registry import (
    CONVERSATION_CLEANUP_JOB,
    DAILY_BRIEFING_JOB,
    PAYMENT_ORDER_CLOSING_JOB,
    SOURCE_JOB_DESCRIPTORS,
    SUBSCRIPTION_DISPATCH_JOB,
    UI_LIBRARY_JOBS,
    JobDescriptor,
    SchedulerCallback,
    apply_job_config,
    build_trigger,
    project_scheduler_status,
    project_semantic_warmup_job_descriptor,
    resolve_source_job_callback,
    x_media_warmup_job_descriptor,
)
from backend.app.repositories.application_repository_factory import (
    ApplicationRepositories,
)
from backend.app.repositories.conversation_repository import ConversationCleanupWriter
from backend.app.repositories.payment_order_repository import PaymentOrderWriter
from backend.app.repositories.rank_snapshot_repository import RankSnapshotRepository
from backend.app.services.briefing.dispatch import (
    BRIEFING_SOURCES,
    BriefingSourceFailureHook,
    run_daily_briefing_dispatch,
)
from backend.app.services.payments.runtime_config import (
    payment_settings_reader_bound,
    resolve_payment_config,
)
from backend.app.services.x_credentials.probe import probe_all_x_credentials

logger = logging.getLogger(__name__)

_ARXIV_RECONCILE_DAYS = 2
_GITHUB_METRICS_REFRESH_LIMIT = 0  # 0 表示刷新全部符合条件的项目
# 300 与每日增长观察仓入库门槛对齐：300-499 的项目也持续刷新快照，
# 保证「快照越过 500 自动进入每日富化」的跨线检测不遗漏
_GITHUB_METRICS_MIN_STARS = 300
_GITHUB_METRICS_MAX_AGE = timedelta(hours=2, minutes=15)

# ── GitHub 锁保底（2026-08-17 富化悬挂致锁死事故后引入）────────────────
# 事故形态：富化 LLM 调用在上游 524 风暴中长时间悬挂，github_lock 被
# 无限期持有，热榜采集逐小时被 max_instances 静默跳过且零入库告警也
# 堵在锁后。三层保底：
#   1) 等锁封顶（GitHub/X 操作锁通用）：持有方异常悬挂时等待方响亮失败
#      （计入连续失败告警），GitHub 锁顺带请求富化批次终止推动自愈；
#   2) 富化补跑整体封顶：超时即放锁，悬挂线程在终止信号/请求超时处收尾；
#   3) 每日流水线整体封顶（刷新+快照+打分+富化全链）。
_JOB_LOCK_WAIT_TIMEOUT = 3 * 3600
_GITHUB_ENRICH_TOP_UP_TIMEOUT = 20 * 60
_GITHUB_DAILY_PIPELINE_TIMEOUT = 2 * 3600
# 新仓快车道：锁忙即让路（只等几秒防与刚释放的锁擦肩），发现+快照整体封顶
_GITHUB_FAST_LANE_LOCK_WAIT = 5
_GITHUB_FAST_LANE_TIMEOUT = 10 * 60


class GitHubFastLaneShare:
    """两小时指标刷新向新仓快车道开放的并行窗口。

    指标刷新持 github 锁抓快照约一小时，快车道原本只能整段让路。窗口
    打开期间快车道改持 participant 锁与之并行；刷新关窗后先等在途的
    快车道收尾再做 logo 与富化补跑，保证快车道绝不越出刷新的持锁期，
    与每日流水线、热榜采集、富化批次仍然互斥。两边的写库与算分由指标
    服务层的写锁串行。
    """

    def __init__(self) -> None:
        self.window = asyncio.Event()
        self.participant = asyncio.Lock()


@asynccontextmanager
async def _open_fast_lane_window(
    share: GitHubFastLaneShare | None,
) -> AsyncIterator[None]:
    """刷新抓快照期间向快车道开窗；退出时关窗并等在途快车道收尾。"""
    if share is None:
        yield
        return
    share.window.set()
    try:
        yield
    finally:
        share.window.clear()
        async with share.participant:
            pass

# 调度任务连续失败告警：阈值内只记日志，达到阈值才经 notify_ops_alert.py 发信
_DEFAULT_ALERT_FAILURE_THRESHOLD = 3
_ALERT_FAILURE_THRESHOLD_ENV = "SCHEDULER_JOB_ALERT_FAILURE_THRESHOLD"
# X 已删推文 janitor：单轮探测数上限（own + 被引合并计数），对 X 配额温和
_DEFAULT_X_JANITOR_MAX_PROBES = 150
_X_JANITOR_MAX_PROBES_ENV = "X_JANITOR_MAX_PROBES_PER_RUN"
_OPS_ALERT_SCRIPT = (
    Path(__file__).resolve().parents[3] / "scripts" / "notify_ops_alert.py"
)

# 单源连续零入库告警：job 正常返回但入库为 0（典型成因是网络/代理断供，
# 不抛异常、不触发失败告警）。按源独立计数，达到阈值告警一次。
# 默认盯热榜型源；x 当日过滤后常为零属常态，dailyhot 为 profile 隔离的
# 可选上游，均不默认纳入，可用环境变量覆盖。
_DEFAULT_ZERO_INGEST_ALERT_THRESHOLD = 3
_ZERO_INGEST_THRESHOLD_ENV = "SCHEDULER_ZERO_INGEST_ALERT_THRESHOLD"
_ZERO_INGEST_SOURCES_ENV = "SCHEDULER_ZERO_INGEST_WATCH_SOURCES"
_DEFAULT_ZERO_INGEST_WATCH_SOURCES = (
    "arxiv",
    "github",
    "news",
    "producthunt",
    "hackernews",
)

# X 链路源任务集合：x_source_enabled=False 时不注册、也不允许经在线配置启用
_X_SOURCE_JOB_SOURCES = frozenset(
    {"x", "x_credentials_probe", "x_closing", "x_deleted_janitor", "x_media_warmup", "ui_library_x_discovery"}
)

# 简报维度失败自动补跑：单维度每日最多补跑 3 次，距上次失败确认 5 分钟后
# 触发（按源失败时刻即时排程，不等全维度 gather 屏障）。计数按
# (目标日期, 维度) 存 Redis（进程重启不丢额度、天然按日重置），Redis
# 缺席/故障退化进程内字典。补跑仍失败且额度耗尽时以 ERROR 落 error_events
# （后台监测页 /monitor/errors），当日不再自动补跑。
_BRIEFING_RETRY_MAX_ATTEMPTS = 3
_BRIEFING_RETRY_DELAY = timedelta(minutes=5)
_BRIEFING_RETRY_KEY_PREFIX = "aigc:briefing:retry"
_BRIEFING_RETRY_KEY_TTL_SECONDS = 2 * 86400
# 一次性补跑 job 的哑火宽限：事件循环繁忙时允许迟到一个小时内补上；
# 进程重启丢 MemoryJobStore 里未触发的补跑，额度已消耗是刻意的保守取向。
_BRIEFING_RETRY_MISFIRE_GRACE_SECONDS = 3600


def _notify_ops_alert(job_id: str, failures: int, detail: str) -> None:
    """经 scripts/notify_ops_alert.py 发送调度器失败告警（fire-and-forget）。

    SMTP 发送放到 daemon 线程，避免阻塞事件循环；脚本缺失或发送失败只记日志，
    告警链路绝不能反过来影响调度任务本身。
    """
    if not _OPS_ALERT_SCRIPT.is_file():
        logger.warning("[Scheduler] 告警脚本不存在，跳过告警: %s", _OPS_ALERT_SCRIPT)
        return

    def _send() -> None:
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(_OPS_ALERT_SCRIPT),
                    "--failed-unit",
                    f"scheduler-job:{job_id}",
                    "--detail",
                    f"连续失败 {failures} 次。{detail}"[:400],
                    "--no-journal",
                ],
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            if result.returncode != 0:
                logger.warning(
                    "[Scheduler] 告警脚本退出码 %d: %s",
                    result.returncode,
                    (result.stderr or "").strip()[:200],
                )
        except Exception as exc:
            logger.warning("[Scheduler] 发送调度器告警失败（非致命）: %s", exc)

    threading.Thread(target=_send, name=f"ops-alert-{job_id}", daemon=True).start()


class _ConsecutiveFailureAlerter:
    """按 job 统计连续失败次数的去抖告警器。

    仅当连续失败计数「到达」阈值时告警一次（不为每次失败都发邮件）；
    一次成功后计数重置，再次连续失败到阈值会重新告警。
    """

    def __init__(
        self,
        *,
        threshold: int = _DEFAULT_ALERT_FAILURE_THRESHOLD,
        notifier: Callable[[str, int, str], None] | None = None,
    ) -> None:
        self._threshold = max(1, int(threshold))
        self._notifier = notifier or _notify_ops_alert
        self._consecutive_failures: Dict[str, int] = {}

    def record_success(self, job_id: str) -> None:
        self._consecutive_failures.pop(job_id, None)

    def record_failure(self, job_id: str, detail: str = "") -> None:
        count = self._consecutive_failures.get(job_id, 0) + 1
        self._consecutive_failures[job_id] = count
        if count == self._threshold:
            logger.error(
                "[Scheduler] 任务 %s 已连续失败 %d 次，触发运维告警。",
                job_id,
                count,
            )
            try:
                self._notifier(job_id, count, detail)
            except Exception as exc:
                logger.warning("[Scheduler] 触发运维告警失败（非致命）: %s", exc)
        elif count > self._threshold:
            logger.warning(
                "[Scheduler] 任务 %s 已连续失败 %d 次（告警已发，不再重复）。",
                job_id,
                count,
            )


def _alert_failure_threshold_from_env() -> int:
    raw = os.environ.get(_ALERT_FAILURE_THRESHOLD_ENV, "").strip()
    if not raw:
        return _DEFAULT_ALERT_FAILURE_THRESHOLD
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning(
            "[Scheduler] %s=%r 不是整数，使用默认告警阈值 %d。",
            _ALERT_FAILURE_THRESHOLD_ENV,
            raw,
            _DEFAULT_ALERT_FAILURE_THRESHOLD,
        )
        return _DEFAULT_ALERT_FAILURE_THRESHOLD


def _x_janitor_max_probes_from_env() -> int:
    """X janitor 单轮探测上限：默认 150，clamp [1, 500]，坏值回退默认。"""
    raw = os.environ.get(_X_JANITOR_MAX_PROBES_ENV, "").strip()
    if not raw:
        return _DEFAULT_X_JANITOR_MAX_PROBES
    try:
        return max(1, min(int(raw), 500))
    except ValueError:
        logger.warning(
            "[Scheduler] %s=%r 不是整数，使用默认探测上限 %d。",
            _X_JANITOR_MAX_PROBES_ENV,
            raw,
            _DEFAULT_X_JANITOR_MAX_PROBES,
        )
        return _DEFAULT_X_JANITOR_MAX_PROBES


class _ZeroIngestAlerter:
    """按源统计连续零入库轮次的去抖告警器。

    与 _ConsecutiveFailureAlerter 同一去抖口径：仅当连续零入库「到达」
    阈值时告警一次；某轮入库 > 0 即重置，之后再次连续零入库到阈值会重新
    告警。不在盯防集合内的源直接忽略。
    """

    def __init__(
        self,
        *,
        threshold: int = _DEFAULT_ZERO_INGEST_ALERT_THRESHOLD,
        watch_sources: tuple[str, ...] = _DEFAULT_ZERO_INGEST_WATCH_SOURCES,
        notifier: Callable[[str, int, str], None] | None = None,
    ) -> None:
        self._threshold = max(1, int(threshold))
        self._watch_sources = frozenset(watch_sources)
        self._notifier = notifier or _notify_ops_alert
        self._consecutive_zeros: Dict[str, int] = {}

    def record(self, source: str, ingested: int) -> None:
        if source not in self._watch_sources:
            return
        if ingested > 0:
            self._consecutive_zeros.pop(source, None)
            return
        count = self._consecutive_zeros.get(source, 0) + 1
        self._consecutive_zeros[source] = count
        if count == self._threshold:
            logger.error(
                "[Scheduler] 数据源 %s 已连续 %d 轮零入库，触发运维告警。",
                source,
                count,
            )
            try:
                self._notifier(
                    f"zero-ingest:{source}",
                    count,
                    f"数据源 {source} 连续 {count} 轮采集成功但零入库，"
                    "疑似网络/代理或上游断供。",
                )
            except Exception as exc:
                logger.warning("[Scheduler] 触发零入库告警失败（非致命）: %s", exc)
        elif count > self._threshold:
            logger.warning(
                "[Scheduler] 数据源 %s 已连续 %d 轮零入库（告警已发，不再重复）。",
                source,
                count,
            )


def _zero_ingest_threshold_from_env() -> int:
    raw = os.environ.get(_ZERO_INGEST_THRESHOLD_ENV, "").strip()
    if not raw:
        return _DEFAULT_ZERO_INGEST_ALERT_THRESHOLD
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning(
            "[Scheduler] %s=%r 不是整数，使用默认零入库告警阈值 %d。",
            _ZERO_INGEST_THRESHOLD_ENV,
            raw,
            _DEFAULT_ZERO_INGEST_ALERT_THRESHOLD,
        )
        return _DEFAULT_ZERO_INGEST_ALERT_THRESHOLD


def _zero_ingest_watch_sources_from_env() -> tuple[str, ...]:
    raw = os.environ.get(_ZERO_INGEST_SOURCES_ENV, "").strip()
    if not raw:
        return _DEFAULT_ZERO_INGEST_WATCH_SOURCES
    sources = tuple(item.strip() for item in raw.split(",") if item.strip())
    if not sources:
        logger.warning(
            "[Scheduler] %s=%r 解析为空，使用默认零入库盯防源。",
            _ZERO_INGEST_SOURCES_ENV,
            raw,
        )
        return _DEFAULT_ZERO_INGEST_WATCH_SOURCES
    return sources


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


def _cancel_github_enrichment_safely() -> None:
    """请求终止运行中的 GitHub 富化批次（若有），失败仅记日志。"""
    try:
        from backend.app.services.ingestion.github_project_enricher import (
            request_github_enrichment_cancel,
        )

        if request_github_enrichment_cancel():
            logger.info("[Scheduler] 已向运行中的 GitHub 富化批次发送终止信号。")
    except Exception as exc:  # noqa: BLE001 - 终止请求失败不阻塞主流程
        logger.warning("[Scheduler] 请求 GitHub 富化批次终止失败（非致命）: %s", exc)


async def _acquire_job_lock(
    lock: asyncio.Lock,
    *,
    job_label: str,
    release_stuck_enrichment: bool = False,
) -> bool:
    """有界等锁：超时判定持有方异常悬挂，返回 False 交由 _guarded 计入连续失败告警。

    release_stuck_enrichment=True（GitHub 锁）时顺带请求富化批次终止：
    若持有方正卡在富化批处理，终止信号让它在下个条目检查点退出，
    后续整点实例即可自愈，无需人工重启。
    """
    try:
        await asyncio.wait_for(lock.acquire(), timeout=_JOB_LOCK_WAIT_TIMEOUT)
    except TimeoutError:
        logger.error(
            "[Scheduler] %s 等待调度锁超过 %ds，判定上轮任务悬挂，本轮放弃并告警。",
            job_label,
            _JOB_LOCK_WAIT_TIMEOUT,
        )
        if release_stuck_enrichment:
            _cancel_github_enrichment_safely()
        return False
    return True


async def _run_single_source_job(
    source_name: str,
    *,
    repositories: ApplicationRepositories,
    github_lock: asyncio.Lock | None = None,
    x_lock: asyncio.Lock | None = None,
    zero_ingest_reporter: Callable[[str, int], None] | None = None,
    target_date: str | None = None,
) -> bool:
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
                target_date=target_date,
            )
        else:
            if not await _acquire_job_lock(
                lock,
                job_label=f"{source_name} 采集",
                release_stuck_enrichment=source_name == "github",
            ):
                return False
            try:
                result = await asyncio.to_thread(
                    run_single_source_pipeline,
                    source_name,
                    dependencies=dependencies,
                    target_date=target_date,
                )
            finally:
                lock.release()
        ingested = result.get("ingested_total", 0)
        if source_name == "x":
            # X rolling-window 完整性失败时，pipeline 返回 ingested_total 可能 >0
            # （其他周期/历史数据），但任务已被 orchestrator 记为 failed。调度层
            # 不能仅凭入库计数判定成功，必须回读刚结束任务的终态，让
            # x_window_incomplete 进入连续失败告警与重试面。
            task_name = (
                f"single:x:{target_date}" if target_date else "single:x"
            )
            latest_task = await asyncio.to_thread(
                active_repositories.ingestion_tasks.get_latest_task_by_name,
                task_name,
            )
            if latest_task and latest_task.get("status") == "failed":
                logger.error(
                    "[Scheduler] x 采集任务被标记失败（task_id=%s）: %s",
                    latest_task.get("id"),
                    latest_task.get("error_msg"),
                )
                return False
        logger.info("[Scheduler] %s 采集完成，入库 %d 条。", source_name, ingested)
        if zero_ingest_reporter is not None:
            try:
                zero_ingest_reporter(source_name, int(ingested))
            except Exception as exc:
                logger.warning("[Scheduler] 零入库上报失败（非致命）: %s", exc)
        return True
    except Exception as exc:
        logger.error("[Scheduler] %s 采集失败: %s", source_name, exc, exc_info=True)
        return False


async def _run_github_project_daily_pipeline_job(
    *,
    repositories: ApplicationRepositories,
    github_lock: asyncio.Lock | None = None,
) -> bool:
    logger.info("[Scheduler] 触发 GitHub 项目库每日流水线...")
    active_repositories = repositories
    lock = github_lock or asyncio.Lock()
    try:
        from backend.app.repositories.postgres_github_logo_repository import PostgresGitHubLogoRepository
        from backend.app.services.ingestion.github_project_enricher import (
            run_github_project_daily_pipeline,
        )

        if not await _acquire_job_lock(
            lock,
            job_label="GitHub 项目库每日流水线",
            release_stuck_enrichment=True,
        ):
            return False
        try:
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        run_github_project_daily_pipeline,
                        refresh_limit=80,
                        enrich_concurrency=5,
                        ingestion=active_repositories.github_ingestion,
                        enrichment=active_repositories.github_enrichment,
                        semantic_sources=active_repositories.github_semantic_sources,
                        logo_repository=PostgresGitHubLogoRepository(),
                    ),
                    timeout=_GITHUB_DAILY_PIPELINE_TIMEOUT,
                )
            except TimeoutError:
                # 封顶只放开锁与本次等待：后台线程继续跑到终止信号/
                # 请求超时处自行收尾，写入均为幂等 upsert。
                logger.error(
                    "[Scheduler] GitHub 项目库每日流水线超过 %ds 封顶，"
                    "已释放锁并请求富化批次终止。",
                    _GITHUB_DAILY_PIPELINE_TIMEOUT,
                )
                _cancel_github_enrichment_safely()
                return False
        finally:
            lock.release()
        logger.info("[Scheduler] GitHub 项目库每日流水线完成：%s", result)
        return True
    except Exception as exc:
        logger.error("[Scheduler] GitHub 项目库每日流水线失败: %s", exc, exc_info=True)
        return False


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


async def _fetch_growth_corroboration(
    metric_date: str,
    documents: Any,
) -> set[str] | None:
    """拉取反作弊跨渠道佐证集合；documents 缺失或查询失败时返回 None（跳过佐证）。"""
    if documents is None:
        return None
    from backend.app.services.ingestion.github_project_metrics_service import (
        corroboration_window,
    )

    since, until = corroboration_window(metric_date)
    try:
        return await asyncio.to_thread(
            documents.list_github_repo_mentions,
            since_date=since,
            until_date=until,
        )
    except Exception as exc:  # noqa: BLE001 - 佐证失败不阻塞指标计算
        logger.warning(
            "[Scheduler] GitHub 反作弊佐证查询失败（本轮按无佐证打标）: %s", exc
        )
        return None


async def _refresh_current_github_project_metrics(
    metric_date: str,
    repository: Any,
    documents: Any = None,
) -> Dict[str, Any]:
    from backend.app.services.ingestion.github_project_metrics_service import (
        refresh_and_compute_github_project_metrics,
    )

    corroborated = await _fetch_growth_corroboration(metric_date, documents)
    active_repository = repository
    return await asyncio.to_thread(
        refresh_and_compute_github_project_metrics,
        min_stars=_GITHUB_METRICS_MIN_STARS,
        limit=_GITHUB_METRICS_REFRESH_LIMIT,
        metric_date=metric_date,
        corroborated_repo_ids=corroborated,
        db=active_repository,
    )


async def _enrich_newly_eligible_github_projects(repository: Any) -> Dict[str, Any]:
    """指标刷新后的富化补跑：让刚越过 500 线的项目两小时内上榜。

    每两小时指标刷新是新越线项目诞生的精确时刻（快照刷新后才满足
    COALESCE(snapshot.stars) >= 500 的富化口径），挂在其后直接全量清空
    待处理队列，不再等次日 02:00 主流水线。retry_failed=False：只补从未
    富化的新候选，failed 条目留待每日流水线重试，避免持续性失败每两小时
    白烧模型调用；空队列时首轮候选查询即返回零，不产生任何模型调用。
    """
    from backend.app.services.ingestion.github_project_enricher import (
        enrich_all_pending_github_projects,
    )

    return await asyncio.to_thread(
        enrich_all_pending_github_projects,
        concurrency=5,
        retry_failed=False,
        db=repository,
    )


async def _run_github_project_metrics_refresh_job(
    *,
    repository: Any,
    enrichment: Any,
    documents: Any = None,
    github_lock: asyncio.Lock | None = None,
    logo_repository: Any = None,
    fast_lane_share: GitHubFastLaneShare | None = None,
) -> bool:
    from backend.app.services.ingestion.github_project_metrics_service import (
        current_github_metric_date,
    )

    metric_date = current_github_metric_date()
    logger.info("[Scheduler] 触发 GitHub 当天指标刷新: %s", metric_date)
    lock = github_lock or asyncio.Lock()
    try:
        if not await _acquire_job_lock(
            lock,
            job_label="GitHub 当天指标刷新",
            release_stuck_enrichment=True,
        ):
            return False
        try:
            async with _open_fast_lane_window(fast_lane_share):
                result = await _refresh_current_github_project_metrics(
                    metric_date,
                    repository,
                    documents,
                )
            if logo_repository is not None:
                from backend.app.services.ingestion.github_project_logos import refresh_project_logos

                try:
                    logos = await asyncio.to_thread(
                        refresh_project_logos, logo_repository,
                        limit=0, interval=0.1, max_seconds=120,
                    )
                    logger.info("[Scheduler] GitHub ranking artwork refresh: %s", logos)
                except Exception:
                    logger.exception("[Scheduler] GitHub artwork refresh failed; metrics remain available")
            # 补跑与每日流水线的富化阶段共用同一把 github 锁，杜绝并发批次
            # 重复烧模型调用；补跑失败不拖累已完成的指标刷新
            top_up: Dict[str, Any] | None = None
            try:
                top_up = await asyncio.wait_for(
                    _enrich_newly_eligible_github_projects(enrichment),
                    timeout=_GITHUB_ENRICH_TOP_UP_TIMEOUT,
                )
            except TimeoutError:
                # 封顶放锁，悬挂线程在终止信号/请求超时处自行收尾；
                # 指标刷新本身已完成，任务仍算成功
                logger.error(
                    "[Scheduler] GitHub 富化补跑超过 %ds 封顶，"
                    "已释放锁并请求批次终止（指标刷新不受影响）。",
                    _GITHUB_ENRICH_TOP_UP_TIMEOUT,
                )
                _cancel_github_enrichment_safely()
            except Exception as exc:  # noqa: BLE001 - 非致命，记入日志即可
                logger.error("[Scheduler] GitHub 富化补跑失败（非致命）: %s", exc, exc_info=True)
        finally:
            lock.release()
        logger.info(
            "[Scheduler] GitHub 当天指标刷新完成：%s，富化补跑：%s",
            result,
            top_up,
        )
        return True
    except Exception as exc:
        logger.error("[Scheduler] GitHub 当天指标刷新失败: %s", exc, exc_info=True)
        return False


async def _enrich_fast_lane_github_projects(
    *,
    enrichment: Any,
    semantic_sources: Any,
    hydrate_readmes: bool,
    run_enrichment: bool = True,
) -> Dict[str, Any]:
    from backend.app.services.ingestion.github_fast_lane import hydrate_github_readmes

    readme: Dict[str, Any] | None = None
    if hydrate_readmes and semantic_sources is not None:
        readme = await asyncio.to_thread(hydrate_github_readmes, semantic_sources)
    return {
        "readme_bootstrap": readme,
        "enrichment": (
            await _enrich_newly_eligible_github_projects(enrichment)
            if run_enrichment
            else "deferred_to_metrics_refresh"
        ),
    }


async def _run_github_fast_lane_job(
    *,
    repository: Any,
    enrichment: Any,
    semantic_sources: Any = None,
    documents: Any = None,
    github_lock: asyncio.Lock | None = None,
    fast_lane_share: GitHubFastLaneShare | None = None,
) -> bool:
    """新仓快车道：发现近几天新建的越线仓库，建快照、算指标、补富化。

    与其他 GitHub 任务共用 github 锁以免并发写同批行和叠加 Search 限速，
    但绝不排队：锁被每日流水线/热榜占着时本轮直接让路（这些任务本身就
    覆盖了发现或快照），15 分钟后下一轮再来。让路不算失败。两小时指标
    刷新抓快照期间例外：经 fast_lane_share 窗口与之并行，只做发现、快照、
    算分与 README 补齐，富化留给刷新随后的补跑。
    """
    from backend.app.services.ingestion.github_project_enricher import (
        github_enrichment_batch_running,
    )
    from backend.app.services.ingestion.github_project_metrics_service import (
        current_github_metric_date,
    )

    lock = github_lock or asyncio.Lock()
    shared = False
    if lock.locked():
        if (
            fast_lane_share is None
            or not fast_lane_share.window.is_set()
            or fast_lane_share.participant.locked()
        ):
            logger.info("[Scheduler] GitHub 快车道：其他 GitHub 任务持锁中，本轮让路。")
            return True
        # 未上锁时 acquire 立即返回、不让出事件循环，与上面的窗口检查之间无竞态
        await fast_lane_share.participant.acquire()
        shared = True
        logger.info("[Scheduler] GitHub 快车道：指标刷新正在抓快照，本轮与之并行。")
    else:
        try:
            await asyncio.wait_for(lock.acquire(), timeout=_GITHUB_FAST_LANE_LOCK_WAIT)
        except TimeoutError:
            logger.info("[Scheduler] GitHub 快车道：锁已被排队任务接手，本轮让路。")
            return True
    held = fast_lane_share.participant if shared and fast_lane_share is not None else lock
    try:
        try:
            from backend.app.services.ingestion.github_fast_lane import run_github_fast_lane

            corroborated = await _fetch_growth_corroboration(
                current_github_metric_date(), documents
            )
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        run_github_fast_lane,
                        ingestion=repository,
                        corroborated_repo_ids=corroborated,
                    ),
                    timeout=_GITHUB_FAST_LANE_TIMEOUT,
                )
            except TimeoutError:
                # 放锁不等线程：写入均为幂等 upsert，悬挂线程自行收尾
                logger.error(
                    "[Scheduler] GitHub 快车道超过 %ds 封顶，已释放锁。",
                    _GITHUB_FAST_LANE_TIMEOUT,
                )
                return False
        except Exception as exc:
            logger.error("[Scheduler] GitHub 快车道失败: %s", exc, exc_info=True)
            return False

        top_up: Dict[str, Any] | None = None
        if github_enrichment_batch_running():
            # 运维面板手动批次不走调度锁；让它跑完，本轮只建快照
            logger.info("[Scheduler] GitHub 快车道：已有富化批次在跑，本轮跳过富化。")
        else:
            try:
                top_up = await asyncio.wait_for(
                    _enrich_fast_lane_github_projects(
                        enrichment=enrichment,
                        semantic_sources=semantic_sources,
                        hydrate_readmes=bool(result.get("readme_candidates")),
                        # 并行时不开富化批次：刷新关窗后的补跑会接手，避免两批并发
                        run_enrichment=not shared,
                    ),
                    timeout=_GITHUB_ENRICH_TOP_UP_TIMEOUT,
                )
            except TimeoutError:
                logger.error(
                    "[Scheduler] GitHub 快车道富化超过 %ds 封顶，"
                    "已释放锁并请求批次终止（快照与指标不受影响）。",
                    _GITHUB_ENRICH_TOP_UP_TIMEOUT,
                )
                _cancel_github_enrichment_safely()
            except Exception as exc:  # noqa: BLE001 - 非致命，记入日志即可
                logger.error("[Scheduler] GitHub 快车道富化失败（非致命）: %s", exc, exc_info=True)
    finally:
        held.release()
    logger.info(
        "[Scheduler] GitHub 快车道完成：命中 %s，新入库 %s %s，富化：%s",
        result.get("hits"),
        result.get("new_candidates"),
        result.get("new_repo_ids"),
        top_up,
    )
    return True


async def _run_github_project_metrics_closing_job(
    *,
    repository: Any,
    documents: Any = None,
    github_lock: asyncio.Lock | None = None,
) -> bool:
    """GitHub 指标关榜轮：次日 00:33 把最终观测写入昨日切片并重算。

    收齐 23:17 末轮常规刷新之后到日界结束的尾巴增长；昨日切片随之
    冻结（github 源 01:00 揭榜）。窗口守卫在服务层：迟到出窗直接
    失败报警，绝不写入已定稿切片。
    """
    from backend.app.services.ingestion.github_project_metrics_service import (
        closing_github_metric_date,
        refresh_and_compute_github_project_metrics,
    )

    metric_date = closing_github_metric_date()
    logger.info("[Scheduler] 触发 GitHub 指标关榜刷新: %s", metric_date)
    lock = github_lock or asyncio.Lock()
    try:
        if not await _acquire_job_lock(
            lock,
            job_label="GitHub 指标关榜刷新",
            release_stuck_enrichment=True,
        ):
            return False
        try:
            corroborated = await _fetch_growth_corroboration(metric_date, documents)
            result = await asyncio.to_thread(
                refresh_and_compute_github_project_metrics,
                min_stars=_GITHUB_METRICS_MIN_STARS,
                limit=_GITHUB_METRICS_REFRESH_LIMIT,
                metric_date=metric_date,
                closing=True,
                corroborated_repo_ids=corroborated,
                db=repository,
            )
        finally:
            lock.release()
        logger.info("[Scheduler] GitHub 指标关榜刷新完成：%s", result)
        return True
    except Exception as exc:
        logger.error("[Scheduler] GitHub 指标关榜刷新失败: %s", exc, exc_info=True)
        return False


async def _reconcile_current_github_project_metrics(
    repository: Any,
    *,
    github_lock: asyncio.Lock | None = None,
    fast_lane_share: GitHubFastLaneShare | None = None,
) -> None:
    from backend.app.services.ingestion.github_project_metrics_service import (
        current_github_metric_date,
    )

    metric_date = current_github_metric_date()
    active_repository = repository
    lock = github_lock or asyncio.Lock()
    try:
        if not await _acquire_job_lock(
            lock,
            job_label="GitHub 指标启动补跑",
            release_stuck_enrichment=True,
        ):
            return
        try:
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
            async with _open_fast_lane_window(fast_lane_share):
                await _refresh_current_github_project_metrics(
                    metric_date,
                    active_repository,
                )
        finally:
            lock.release()
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


async def _run_daily_briefing_job(
    repositories: ApplicationRepositories,
    *,
    redis_client: Any | None = None,
    on_source_failed: BriefingSourceFailureHook | None = None,
) -> None:
    """一行委托：每日简报生成与订阅派发编排归属于 services/briefing。"""
    await run_daily_briefing_dispatch(
        repositories,
        redis_client=redis_client,
        on_source_failed=on_source_failed,
    )


async def _run_daily_briefing_retry_job(
    repositories: ApplicationRepositories,
    *,
    target_date: str,
    source: str,
    redis_client: Any | None = None,
    on_source_failed: BriefingSourceFailureHook | None = None,
) -> None:
    """单维度简报补跑：复用日常派发链（取数/生成/落库/订阅派发），收窄到一个
    维度并沿用原目标日期；再失败仍经同一钩子回报，构成补跑链。"""
    await run_daily_briefing_dispatch(
        repositories,
        redis_client=redis_client,
        sources=[source],
        target_date=target_date,
        on_source_failed=on_source_failed,
    )


async def _run_subscription_dispatch_job(
    repositories: ApplicationRepositories,
    *,
    redis_client: Any | None = None,
) -> bool:
    """订阅简报派发：枚举频率 × 来源读缓存，经 push_deliveries 幂等投递。"""
    logger.info("[Scheduler] 触发订阅简报派发（全频率幂等投递）...")
    from backend.app.services.push.dispatch_service import SubscriptionDispatchService
    from backend.app.services.push.secrets import build_push_channel_secret_box
    from backend.app.services.push.webhook_service import WebhookSender

    service = SubscriptionDispatchService(
        subscriptions=repositories.user_subscriptions,
        deliveries=repositories.push_deliveries,
        briefings=repositories.briefings,
        secret_box=build_push_channel_secret_box(),
        webhook_sender=WebhookSender(),
        redis_client=redis_client,
    )
    try:
        summary = await service.dispatch_all()
        logger.info("[Scheduler] 订阅简报派发完成：%s", summary)
        succeeded = True
    except Exception as exc:
        logger.error("[Scheduler] 订阅简报派发失败: %s", exc, exc_info=True)
        succeeded = False
    tracking = getattr(repositories, "tracking", None)
    if tracking is not None:
        from backend.app.services.tracking.dispatch import dispatch_tracking

        try:
            result = await dispatch_tracking(tracking, service)
            logger.info("[Scheduler] 个人情报派发完成：%s", result)
            succeeded = succeeded and result["failed"] == 0
        except Exception:
            logger.exception("[Scheduler] 个人情报派发失败")
            succeeded = False
    return succeeded


async def _run_project_semantic_warmup_job(
    warmup: Any | None = None,
) -> bool:
    try:
        if warmup is None:
            from backend.app.services.project_semantic_search import (
                warmup_project_semantic_search,
            )

            warmup = warmup_project_semantic_search
        result = await asyncio.to_thread(warmup)
        if result.get("status") == "failed":
            logger.warning("[Scheduler] 项目语义搜索预热失败：%s", result)
            return False
        logger.info("[Scheduler] 项目语义搜索预热完成：%s", result)
        return True
    except Exception as exc:
        logger.warning("[Scheduler] 项目语义搜索预热失败: %s", exc)
        return False


async def _run_x_media_warmup_job(repositories: ApplicationRepositories) -> bool:
    """X 媒体边缘缓存周期兜底预热。服务本身是 async，直接 await（不经
    to_thread）；不占用 x_operation_lock——只打本地边缘入口，不碰 X API。"""
    try:
        from backend.app.services.x_media_warmup import run_x_media_warmup_cycle

        await run_x_media_warmup_cycle(repositories.documents)
        return True
    except Exception as exc:
        logger.warning("[Scheduler] X 媒体边缘缓存预热失败: %s", exc)
        return False


async def _run_conversation_cleanup_job(
    conversation_repository: ConversationCleanupWriter,
) -> bool:
    logger.info("[Scheduler] 触发会话历史清理任务...")
    try:
        from backend.app.services.chat.conversation_service import ConversationService

        deleted = await asyncio.to_thread(
            ConversationService(conversation_repository).cleanup_stale_conversations,
        )
        logger.info("[Scheduler] 会话历史清理完成，删除 %d 条旧会话。", deleted)
        return True
    except Exception as exc:
        logger.error("[Scheduler] 会话历史清理失败: %s", exc, exc_info=True)
        return False


# 支付订单超时关单：单轮批量上限，积压由后续轮次收敛（5 分钟一轮）。
_PAYMENT_ORDER_CLOSING_BATCH_LIMIT = 200


async def _run_payment_order_closing_job(orders: PaymentOrderWriter) -> bool:
    """支付订单超时关单：pending 且 expires_at <= now 批量转 expired。

    条件更新天然幂等（已 paid/closed 的行不动）；仓储异常吞掉返回
    False 计入连续失败告警，绝不向上抛断调度循环。过期单仍可经回调走
    expired→paid 迟到支付特许边，关单不等于拒付。
    """
    try:
        expired = await asyncio.to_thread(
            orders.mark_expired_overdue,
            now=datetime.now(timezone.utc),
            limit=_PAYMENT_ORDER_CLOSING_BATCH_LIMIT,
        )
        if expired:
            logger.info("[Scheduler] 支付订单超时关单：本轮过期 %d 笔。", expired)
        return True
    except Exception as exc:
        logger.error("[Scheduler] 支付订单超时关单失败: %s", exc, exc_info=True)
        return False


async def _run_x_credentials_probe_job(
    *,
    repositories: ApplicationRepositories,
    x_lock: asyncio.Lock | None = None,
) -> bool:
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
        logger.info(
            "[Scheduler] X 凭证池测活输入：启用凭证 %d 个，watch handle %s。",
            len(credentials),
            "可用" if handle else "缺失",
        )

        lock = x_lock or asyncio.Lock()
        async with lock:
            results = await asyncio.to_thread(
                probe_all_x_credentials,
                credentials,
                handle,
                update_result=repositories.x_credentials.update_x_credential_test_result,
            )
        succeeded = sum(1 for result in results if result.get("status") == "succeeded")
        marker_counts: dict[str, int] = {}
        for result in results:
            if result.get("status") == "succeeded":
                continue
            marker = str(result.get("message") or "unknown")
            marker_counts[marker] = marker_counts.get(marker, 0) + 1
        logger.info(
            "[Scheduler] X 凭证池测活完成：%d/%d 成功，失败标记 %s。",
            succeeded,
            len(results),
            marker_counts or "无",
        )
        return True
    except Exception as exc:
        logger.error("[Scheduler] X 凭证池测活失败: %s", exc, exc_info=True)
        return False


async def _run_x_deleted_janitor_job(
    *,
    repositories: ApplicationRepositories,
    x_lock: asyncio.Lock | None = None,
) -> bool:
    """探测存量 X 文档，删除原作者已删推文、清作者已删引用卡。

    与 X 采集/测活共享操作锁（仅探测调用期间持有）。janitor 中止
    （凭据/限流/传输面不可用）视为整轮失败，进入连续失败告警。
    """
    from backend.app.services.x_janitor.deleted_tweets import XDeletedTweetJanitor

    logger.info("[Scheduler] 触发 X 已删除推文清理...")
    try:
        janitor = XDeletedTweetJanitor(
            repositories.documents,
            repositories.x_credentials,
            max_probes_per_run=_x_janitor_max_probes_from_env(),
            x_lock=x_lock,
        )
        report = await janitor.run()
        if report.aborted is not None:
            logger.error("[Scheduler] X 已删除推文清理中止：%s", report.aborted)
            return False
        return True
    except Exception as exc:
        logger.error("[Scheduler] X 已删除推文清理失败: %s", exc, exc_info=True)
        return False


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


# 当前已 start 的调度运行时：手动运维入口（不经 app.state 的服务层）
# 通过它复用 github/x 串行锁；stop() 时清除。
_ACTIVE_RUNTIME: ApplicationSchedulerRuntime | None = None


def get_active_scheduler_runtime() -> ApplicationSchedulerRuntime | None:
    """Return the currently started scheduler runtime, if any."""
    return _ACTIVE_RUNTIME


class ApplicationSchedulerRuntime:
    """Application-owned scheduler, callbacks, locks, and startup tasks."""

    def __init__(
        self,
        repositories: ApplicationRepositories,
        *,
        scheduler: AsyncIOScheduler | None = None,
        semantic_search_enabled: bool = False,
        semantic_search_warmup: Any | None = None,
        x_media_warmup_enabled: bool = False,
        payments_enabled: bool = False,
        # 默认 True：直接构造运行时的既有调用方（多为测试）保持旧行为；
        # 策略收口在 create_scheduler_runtime（读 settings，默认关闭）。
        x_source_enabled: bool = True,
        shutdown_grace_seconds: float = 30.0,
        timezone_name: str = "Asia/Shanghai",
        job_config_overrides: Mapping[str, Any] | None = None,
        alert_failure_threshold: int = _DEFAULT_ALERT_FAILURE_THRESHOLD,
        alert_notifier: Callable[[str, int, str], None] | None = None,
        zero_ingest_threshold: int = _DEFAULT_ZERO_INGEST_ALERT_THRESHOLD,
        zero_ingest_watch_sources: tuple[str, ...] = _DEFAULT_ZERO_INGEST_WATCH_SOURCES,
        zero_ingest_notifier: Callable[[str, int, str], None] | None = None,
        # 邮件池配额计数/熔断依赖 Redis；None 时护栏 fail-open（仅纯 failover），
        # 与 EmailPoolQuotaStore 契约一致。
        redis_client: Any | None = None,
    ) -> None:
        self.repositories = repositories
        self.scheduler = scheduler or AsyncIOScheduler(timezone=timezone_name)
        self._semantic_search_enabled = semantic_search_enabled
        self._semantic_search_warmup = semantic_search_warmup
        self._x_media_warmup_enabled = x_media_warmup_enabled
        self._payments_enabled = payments_enabled
        self._x_source_enabled = x_source_enabled
        self._shutdown_grace_seconds = max(0.0, float(shutdown_grace_seconds))
        self._timezone_name = timezone_name
        self._job_config_overrides: Dict[str, Any] = dict(job_config_overrides or {})
        self._github_job_lock = asyncio.Lock()
        self._github_fast_lane_share = GitHubFastLaneShare()
        self._x_operation_lock = asyncio.Lock()
        self._failure_alerter = _ConsecutiveFailureAlerter(
            threshold=alert_failure_threshold,
            notifier=alert_notifier,
        )
        self._zero_ingest_alerter = _ZeroIngestAlerter(
            threshold=zero_ingest_threshold,
            watch_sources=zero_ingest_watch_sources,
            notifier=zero_ingest_notifier,
        )
        self._active_tasks: set[asyncio.Task[Any]] = set()
        self._redis_client = redis_client
        # Redis 缺席时的进程内补跑计数兜底：(目标日期, 维度) -> 已排程补跑次数。
        self._briefing_retry_counters: Dict[tuple[str, str], int] = {}
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

    @property
    def github_job_lock(self) -> asyncio.Lock:
        """Shared lock used to serialize all GitHub ingestion/metrics jobs.

        Manual admin-triggered GitHub ingestion must acquire the same lock so
        it never runs concurrently with the scheduled GitHub jobs.
        """
        return self._github_job_lock

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

    async def _guarded(
        self,
        job_id: str,
        operation: Callable[[], Awaitable[Any]],
    ) -> None:
        """Run one scheduled operation and feed the failure alerter.

        模块级 job 函数内部捕获异常并返回 False（成功返回 True）；未预期的
        异常在此计入连续失败后再原样抛出，保持 APScheduler 既有错误处理。
        """
        try:
            outcome = await operation()
        except Exception as exc:
            self._failure_alerter.record_failure(job_id, str(exc))
            raise
        if outcome is False:
            self._failure_alerter.record_failure(job_id, "job reported failure")
        else:
            self._failure_alerter.record_success(job_id)

    async def _run_single_source_job(self, source_name: str) -> None:
        await self._run_tracked(
            lambda: self._guarded(
                f"source:{source_name}",
                lambda: _run_single_source_job(
                    source_name,
                    repositories=self.repositories,
                    github_lock=self._github_job_lock,
                    x_lock=self._x_operation_lock,
                    zero_ingest_reporter=self._zero_ingest_alerter.record,
                ),
            )
        )

    async def _run_single_source_closing_job(self, source_name: str) -> None:
        """关榜轮：次日 00:3x 以昨日（调度时区）为目标日期补采一轮。

        收齐 hourly 末轮（23:0x）之后到源日界结束的尾巴内容，写入昨日
        切片（CST 源 01:00 揭榜前的最后一笔）。零入库是关榜轮常态，
        不接零入库告警；misfire 宽限由 descriptor 限制在关榜窗口内。
        """
        yesterday = (
            datetime.now(ZoneInfo(self._timezone_name)) - timedelta(days=1)
        ).date().isoformat()
        await self._run_tracked(
            lambda: self._guarded(
                f"source:{source_name}_closing",
                lambda: _run_single_source_job(
                    source_name,
                    repositories=self.repositories,
                    github_lock=self._github_job_lock,
                    x_lock=self._x_operation_lock,
                    zero_ingest_reporter=None,
                    target_date=yesterday,
                ),
            )
        )

    async def _run_x_closing_job(self) -> None:
        await self._run_single_source_closing_job("x")

    async def _run_hackernews_closing_job(self) -> None:
        await self._run_single_source_closing_job("hackernews")

    async def _run_news_closing_job(self) -> None:
        await self._run_single_source_closing_job("news")

    async def _run_github_project_daily_pipeline_job(self) -> None:
        await self._run_tracked(
            lambda: self._guarded(
                "github_project_daily_pipeline",
                lambda: _run_github_project_daily_pipeline_job(
                    repositories=self.repositories,
                    github_lock=self._github_job_lock,
                ),
            )
        )

    async def _run_github_project_metrics_refresh_job(self) -> None:
        from backend.app.repositories.postgres_github_logo_repository import PostgresGitHubLogoRepository

        await self._run_tracked(
            lambda: self._guarded(
                "github_project_metrics_refresh",
                lambda: _run_github_project_metrics_refresh_job(
                    repository=self.repositories.github_ingestion,
                    enrichment=self.repositories.github_enrichment,
                    documents=self.repositories.documents,
                    github_lock=self._github_job_lock,
                    logo_repository=PostgresGitHubLogoRepository(),
                    fast_lane_share=self._github_fast_lane_share,
                ),
            )
        )

    async def _run_github_fast_lane_job(self) -> None:
        await self._run_tracked(
            lambda: self._guarded(
                "github_fast_lane",
                lambda: _run_github_fast_lane_job(
                    repository=self.repositories.github_ingestion,
                    enrichment=self.repositories.github_enrichment,
                    semantic_sources=self.repositories.github_semantic_sources,
                    documents=self.repositories.documents,
                    github_lock=self._github_job_lock,
                    fast_lane_share=self._github_fast_lane_share,
                ),
            )
        )

    async def _run_github_project_metrics_closing_job(self) -> None:
        await self._run_tracked(
            lambda: self._guarded(
                "github_project_metrics_closing",
                lambda: _run_github_project_metrics_closing_job(
                    repository=self.repositories.github_ingestion,
                    documents=self.repositories.documents,
                    github_lock=self._github_job_lock,
                ),
            )
        )

    async def _run_x_credentials_probe_job(self) -> None:
        await self._run_tracked(
            lambda: self._guarded(
                "x_credentials_probe",
                lambda: _run_x_credentials_probe_job(
                    repositories=self.repositories,
                    x_lock=self._x_operation_lock,
                ),
            )
        )

    async def _run_x_deleted_janitor_job(self) -> None:
        await self._run_tracked(
            lambda: self._guarded(
                "x_deleted_janitor",
                lambda: _run_x_deleted_janitor_job(
                    repositories=self.repositories,
                    x_lock=self._x_operation_lock,
                ),
            )
        )

    async def _run_daily_briefing_job(self) -> None:
        await self._run_tracked(
            lambda: self._guarded(
                "daily_briefing",
                lambda: _run_daily_briefing_job(
                    self.repositories,
                    redis_client=self._redis_client,
                    on_source_failed=self._handle_briefing_source_failed,
                ),
            )
        )

    async def _run_daily_briefing_retry_job(
        self, target_date: str, source: str
    ) -> None:
        await self._run_tracked(
            lambda: self._guarded(
                f"daily_briefing_retry:{source}",
                lambda: _run_daily_briefing_retry_job(
                    self.repositories,
                    target_date=target_date,
                    source=source,
                    redis_client=self._redis_client,
                    on_source_failed=self._handle_briefing_source_failed,
                ),
            )
        )

    async def _next_briefing_retry_attempt(
        self, target_date: str, source: str
    ) -> int:
        """(目标日期, 维度) 补跑额度计数 +1 并返回新值。

        Redis 计数保证进程重启不丢额度；Redis 缺席/故障时退化进程内字典
        （fail-open：补跑是增益能力，不能因计数面故障反过来压制补跑）。
        """
        if self._redis_client is not None:
            try:
                key = f"{_BRIEFING_RETRY_KEY_PREFIX}:{target_date}:{source}"
                used = int(await self._redis_client.incr(key))
                if used == 1:
                    await self._redis_client.expire(
                        key, _BRIEFING_RETRY_KEY_TTL_SECONDS
                    )
                return used
            except Exception:
                logger.warning(
                    "[Briefing] 补跑计数 Redis 读写失败，退化进程内计数: "
                    "date=%s source=%s",
                    target_date,
                    source,
                    exc_info=True,
                )
        stale = [
            key for key in self._briefing_retry_counters if key[0] != target_date
        ]
        for key in stale:
            del self._briefing_retry_counters[key]
        key = (target_date, source)
        used = self._briefing_retry_counters.get(key, 0) + 1
        self._briefing_retry_counters[key] = used
        return used

    async def _handle_briefing_source_failed(
        self, *, target_date: str, source: str, error: str
    ) -> None:
        """单维度简报失败钩子：额度内排程 5 分钟后的一次性补跑 job。

        在维度失败确认当刻触发（而非全维度收尾后），因此间隔语义严格是
        「上次失败 5 分钟后」。额度耗尽落 ERROR（经 error_events 上监测页），
        当日不再自动补跑。补跑 job 为一次性 date 触发器，按维度独立 id，
        出现在调度面板的 job 列表里可直接观察。
        """
        if self._stopping:
            logger.info(
                "[Briefing] 调度器停止中，跳过补跑排程: date=%s source=%s",
                target_date,
                source,
            )
            return
        attempt = await self._next_briefing_retry_attempt(target_date, source)
        if attempt > _BRIEFING_RETRY_MAX_ATTEMPTS:
            logger.error(
                "[Briefing] 简报自动补跑已达每日上限: date=%s source=%s "
                "retries=%d last_error=%s；今日不再自动补跑，待人工介入。",
                target_date,
                source,
                _BRIEFING_RETRY_MAX_ATTEMPTS,
                error,
            )
            return
        run_date = datetime.now(self.scheduler.timezone) + _BRIEFING_RETRY_DELAY

        async def _retry() -> None:
            await self._run_daily_briefing_retry_job(target_date, source)

        self.scheduler.add_job(
            _retry,
            trigger="date",
            run_date=run_date,
            id=f"daily_briefing_retry_{source}",
            name=f"简报自动补跑（第 {attempt}/{_BRIEFING_RETRY_MAX_ATTEMPTS} 次）: {source}",
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=_BRIEFING_RETRY_MISFIRE_GRACE_SECONDS,
        )
        logger.warning(
            "[Briefing] 简报维度失败，已排程 %s 自动补跑（第 %d/%d 次）: "
            "date=%s source=%s error=%s",
            run_date.isoformat(),
            attempt,
            _BRIEFING_RETRY_MAX_ATTEMPTS,
            target_date,
            source,
            error,
        )

    async def _run_subscription_dispatch_job(self) -> None:
        await self._run_tracked(
            lambda: self._guarded(
                "subscription_dispatch",
                lambda: _run_subscription_dispatch_job(
                    self.repositories, redis_client=self._redis_client
                ),
            )
        )

    async def _run_conversation_cleanup_job(self) -> None:
        await self._run_tracked(
            lambda: self._guarded(
                "conversation_cleanup",
                lambda: _run_conversation_cleanup_job(self.repositories.conversations),
            )
        )

    async def _run_project_semantic_warmup_job(self) -> None:
        await self._run_tracked(
            lambda: self._guarded(
                "project_semantic_warmup",
                lambda: _run_project_semantic_warmup_job(
                    self._semantic_search_warmup,
                ),
            )
        )

    async def _run_x_media_warmup_job(self) -> None:
        await self._run_tracked(
            lambda: self._guarded(
                "x_media_warmup",
                lambda: _run_x_media_warmup_job(self.repositories),
            )
        )

    async def _run_payment_order_closing_job(self) -> None:
        await self._run_tracked(
            lambda: self._guarded(
                "payment_order_closing",
                lambda: _run_payment_order_closing_job(self.repositories.orders),
            )
        )

    async def _run_ui_library_discovery_job(self) -> None:
        from backend.app.core.config import settings
        from backend.app.services.ui_discovery import discover_web
        async def run() -> bool:
            async with asyncio.timeout(900):
                async with self._github_job_lock:
                    return await discover_web(self.repositories.ui_library, token=settings.github_token, proxy=settings.outbound_proxy)
        await self._run_tracked(lambda: self._guarded("ui_library_discovery", run))

    async def _run_ui_library_x_discovery_job(self) -> None:
        from backend.app.services.source_plugins import load_x_transport_class
        from backend.app.services.ui_discovery import discover_x
        async def run() -> bool:
            async with asyncio.timeout(900):
                async with self._x_operation_lock:
                    transport_class = load_x_transport_class()
                    if transport_class is None:
                        raise RuntimeError("X transport unavailable")
                    transport = transport_class(credential_provider=self.repositories.x_credentials.list_enabled_x_credentials)
                    return await discover_x(self.repositories.ui_library, transport)
        await self._run_tracked(lambda: self._guarded("ui_library_x_discovery", run))

    def _is_source_job_suppressed(self, descriptor: JobDescriptor) -> bool:
        """特性开关关闭的源任务不注册、不允许在线启用（X 链路透出前不占调度面）。"""
        return (
            descriptor.source in _X_SOURCE_JOB_SOURCES
            and not self._x_source_enabled
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
            "_run_ui_library_discovery_job": self._run_ui_library_discovery_job,
            "_run_ui_library_x_discovery_job": self._run_ui_library_x_discovery_job,
            "_run_github_project_daily_pipeline_job": (
                self._run_github_project_daily_pipeline_job
            ),
            "_run_github_project_metrics_refresh_job": (
                self._run_github_project_metrics_refresh_job
            ),
            "_run_github_project_metrics_closing_job": (
                self._run_github_project_metrics_closing_job
            ),
            "_run_github_fast_lane_job": self._run_github_fast_lane_job,
            "_run_x_credentials_probe_job": self._run_x_credentials_probe_job,
            "_run_x_deleted_janitor_job": self._run_x_deleted_janitor_job,
            "_run_x_closing_job": self._run_x_closing_job,
            "_run_hackernews_closing_job": self._run_hackernews_closing_job,
            "_run_news_closing_job": self._run_news_closing_job,
        }

    def _payments_enabled_effective(self) -> bool:
        """支付开关热生效口径：reader 已绑定（生产形态）时以 DB 覆盖行/env 解析
        为准——面板保存即热翻转，关单任务无需重启调度器；未绑定（测试/工具
        形态）回落构造参数。配置面故障 fail-closed 到构造参数。"""
        if not payment_settings_reader_bound():
            return self._payments_enabled
        try:
            return resolve_payment_config().enabled
        except Exception:
            logger.warning(
                "[Scheduler] 解析支付配置失败，关单任务回落构造开关", exc_info=True
            )
            return self._payments_enabled

    def _base_descriptor(self, job_id: str) -> JobDescriptor | None:
        for descriptor in (*SOURCE_JOB_DESCRIPTORS, *UI_LIBRARY_JOBS):
            if descriptor.id == job_id:
                return descriptor
        if job_id == DAILY_BRIEFING_JOB.id:
            return DAILY_BRIEFING_JOB
        if job_id == SUBSCRIPTION_DISPATCH_JOB.id:
            return SUBSCRIPTION_DISPATCH_JOB
        if job_id == CONVERSATION_CLEANUP_JOB.id:
            return CONVERSATION_CLEANUP_JOB
        if job_id == "payment_order_closing" and self._payments_enabled_effective():
            return PAYMENT_ORDER_CLOSING_JOB
        if job_id == "project_semantic_warmup" and self._semantic_search_enabled:
            return project_semantic_warmup_job_descriptor(
                timezone=self._timezone_name
            )
        if job_id == "x_media_warmup" and self._x_media_warmup_enabled:
            return x_media_warmup_job_descriptor(timezone=self._timezone_name)
        return None

    def _resolve_callback(self, descriptor: JobDescriptor) -> SchedulerCallback | None:
        if descriptor.id == DAILY_BRIEFING_JOB.id:
            return self._run_daily_briefing_job
        if descriptor.id == SUBSCRIPTION_DISPATCH_JOB.id:
            return self._run_subscription_dispatch_job
        if descriptor.id == CONVERSATION_CLEANUP_JOB.id:
            return self._run_conversation_cleanup_job
        if descriptor.source == "payment_order_closing":
            if not self._payments_enabled_effective():
                return None
            return self._run_payment_order_closing_job
        if descriptor.source == "project_semantic_warmup":
            if not self._semantic_search_enabled:
                return None
            return self._run_project_semantic_warmup_job
        if descriptor.source == "x_media_warmup":
            if not self._x_media_warmup_enabled:
                return None
            return self._run_x_media_warmup_job
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
        if self._is_source_job_suppressed(descriptor):
            if existing is not None:
                self.scheduler.remove_job(config.job_id)
                logger.info("[Scheduler] 特性开关关闭，移除任务: %s", config.job_id)
            return True
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
            if self._is_source_job_suppressed(descriptor):
                logger.info("[Scheduler] 跳过特性开关关闭的采集任务: %s", descriptor.id)
                continue
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
                len(BRIEFING_SOURCES),
            )
        else:
            logger.info("[Scheduler] 跳过已停用的简报任务: daily_briefing")

        subscription_dispatch = self._effective_descriptor(SUBSCRIPTION_DISPATCH_JOB)
        if subscription_dispatch is not None:
            _register_job(
                self.scheduler,
                subscription_dispatch,
                self._run_subscription_dispatch_job,
            )
            logger.info("[Scheduler] 注册订阅派发任务: subscription_dispatch")
        else:
            logger.info("[Scheduler] 跳过已停用的订阅派发任务: subscription_dispatch")

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

        if self._x_media_warmup_enabled:
            x_media_base = x_media_warmup_job_descriptor(timezone=self._timezone_name)
            if self._is_source_job_suppressed(x_media_base):
                logger.info("[Scheduler] 跳过特性开关关闭的 X 媒体预热任务")
            else:
                x_media_descriptor = self._effective_descriptor(x_media_base)
                if x_media_descriptor is not None:
                    _register_job(
                        self.scheduler,
                        x_media_descriptor,
                        self._run_x_media_warmup_job,
                    )
                    logger.info("[Scheduler] 注册 X 媒体边缘缓存预热任务（每 30 分钟）")
                else:
                    logger.info("[Scheduler] 跳过已停用的 X 媒体预热任务")

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

        if self._payments_enabled_effective():
            payment_closing = self._effective_descriptor(PAYMENT_ORDER_CLOSING_JOB)
            if payment_closing is not None:
                _register_job(
                    self.scheduler,
                    payment_closing,
                    self._run_payment_order_closing_job,
                )
                logger.info("[Scheduler] 注册支付订单超时关单任务: payment_order_closing")
            else:
                logger.info("[Scheduler] 跳过已停用的支付关单任务: payment_order_closing")
        else:
            logger.info("[Scheduler] 支付开关关闭，跳过支付订单超时关单任务。")

        for base in UI_LIBRARY_JOBS:
            descriptor = self._effective_descriptor(base)
            if descriptor is not None and not self._is_source_job_suppressed(descriptor):
                _register_job(self.scheduler, descriptor, self._resolve_callback(descriptor))

        self.scheduler.start()
        # 登记为活动运行时：手动运维入口（IngestionAdminService）借此复用
        # github/x 串行锁，与调度任务保持同一互斥口径。
        global _ACTIVE_RUNTIME
        _ACTIVE_RUNTIME = self
        loop = asyncio.get_running_loop()
        for coroutine in (
            _reconcile_recent_arxiv_daily_snapshots(
                self.repositories.rank_snapshots,
                repositories=self.repositories,
            ),
            _reconcile_current_github_project_metrics(
                self.repositories.github_ingestion,
                github_lock=self._github_job_lock,
                fast_lane_share=self._github_fast_lane_share,
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
            global _ACTIVE_RUNTIME
            if _ACTIVE_RUNTIME is self:
                _ACTIVE_RUNTIME = None
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


def _effective_x_source_enabled() -> bool:
    """X 链路有效可用性 = 开关开 AND 源插件可导入（fail closed）。

    开关开但私有插件缺失（如容器重建时丢了部署 overlay）时，若照常注册
    X 任务，orchestrator 无 x 爬虫，每轮采集必炸，错误日志以调度频率刷屏。
    此处按源整体抑制：启动一条 warning，任务不注册、在线配置亦无法启用
    （沿用 _is_source_job_suppressed 语义）。loader 进程内缓存导入结果，
    启动期一次解析后 XCrawler 构造复用缓存，无双倍开销。
    """
    from backend.app.core.config import settings

    if not bool(getattr(settings, "x_source_enabled", False)):
        return False
    # 函数内导入：loader 自身在调用时才读 settings，避免模块级循环依赖。
    from backend.app.services.source_plugins import load_x_transport_class

    if load_x_transport_class() is None:
        logger.warning(
            "[Scheduler] X_SOURCE_ENABLED=true 但 X 源插件不可导入，"
            "X 链路任务整体抑制（fail closed，与 loader 语义一致）"
        )
        return False
    return True


def create_scheduler_runtime(
    repositories: ApplicationRepositories,
    *,
    enabled: bool = True,
    semantic_search_warmup: Any | None = None,
    job_config_overrides: Mapping[str, Any] | None = None,
    redis_client: Any | None = None,
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
        x_media_warmup_enabled=bool(
            getattr(settings, "x_media_warmup_enabled", False)
        ),
        payments_enabled=bool(getattr(settings, "payments_enabled", False)),
        x_source_enabled=_effective_x_source_enabled(),
        shutdown_grace_seconds=float(
            getattr(settings, "scheduler_shutdown_grace_seconds", 30.0)
        ),
        timezone_name=timezone_name,
        job_config_overrides=job_config_overrides,
        alert_failure_threshold=_alert_failure_threshold_from_env(),
        zero_ingest_threshold=_zero_ingest_threshold_from_env(),
        zero_ingest_watch_sources=_zero_ingest_watch_sources_from_env(),
        redis_client=redis_client,
    )
