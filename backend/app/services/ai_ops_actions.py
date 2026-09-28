"""Bounded write actions the AI ops agent may select.

Code derives every candidate from live state and re-checks it right before it
runs; the model only picks candidate ids. Each action wraps an existing
operation (task lifecycle, X translation retry, daily briefing dispatch) and is
limited by budgets counted from the run audit trail. Nothing here edits code,
configuration, credentials or deployments.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

from backend.app.services.briefing.daily_briefing import get_briefing_cache_key
from backend.app.services.briefing.dispatch import BRIEFING_SOURCES, run_daily_briefing_dispatch
from backend.app.services.ingestion.x_translation_service import XTranslationProcessor

CST = timezone(timedelta(hours=8))
# Longest successful ingestion observed is ~1.4h and job locks wait at most 3h.
ORPHAN_AGE = timedelta(hours=6)
ORPHAN_LIMIT = 200
ORPHAN_MESSAGE = "orphaned: 运行超过 6 小时无结束记录（进程重启中断遗留），由 AI 运维收尾"
X_TRANSLATION_STALL = timedelta(minutes=30)
X_TRANSLATION_LIMIT = 200
# Daily briefings start 08:00 CST and the scheduler retries each source 3 times.
BRIEFING_EARLIEST = time(10, 30)
# Regenerating while the shared chat model still fails would only fail again.
BRIEFING_ERROR_QUIET = timedelta(minutes=30)
BRIEFING_LOGGER = "backend.app.services.briefing."


@dataclass(frozen=True)
class ActionSpec:
    title: str
    per_target: int
    per_action: int
    spacing_seconds: int


ACTIONS = {
    "ingestion_orphan_close": ActionSpec("僵死采集任务收尾", 4, 4, 3600),
    "x_translation_retry": ActionSpec("X 译文重试", 6, 6, 3600),
    "briefing_regenerate": ActionSpec("简报补生成", 2, 10, 3600),
}


@dataclass(frozen=True)
class Candidate:
    action: str
    target: str
    facts: dict

    @property
    def id(self):
        return f"{self.action}:{self.target}"

    def offer(self):
        return {"id": self.id, "title": ACTIONS[self.action].title, "facts": self.facts}


def _age_seconds(value, now):
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (now - value).total_seconds()


class AiOpsActions:
    def __init__(self, repository, repositories, scheduler, operations=None, redis_client=None,
                 now=lambda: datetime.now(timezone.utc)):
        self.repository, self.repositories, self.scheduler = repository, repositories, scheduler
        self.operations, self.redis_client, self.now = operations, redis_client, now
        self._builders = {"ingestion_orphan_close": self._orphan_candidates,
                          "x_translation_retry": self._x_translation_candidates,
                          "briefing_regenerate": self._briefing_candidates}

    def candidates(self):
        if not self.repository.config()["recovery_enabled"]:
            return []
        offered = []
        for action, spec in ACTIONS.items():
            usage = self.repository.action_usage(action, spec.spacing_seconds)
            if sum(row["used"] for row in usage.values()) >= spec.per_action:
                continue
            # Budget is re-checked atomically at admission; this only avoids
            # offering the model choices that would certainly be refused.
            offered += [c for c in self._builders[action]()
                        if usage.get(c.target, {}).get("used", 0) < spec.per_target
                        and not usage.get(c.target, {}).get("recent")]
        return offered

    def _orphan_candidates(self):
        rows = self.repository.stale_running_tasks(ORPHAN_AGE, ORPHAN_LIMIT)
        if not rows:
            return []
        names = Counter(":".join(row["task_name"].split(":")[:2]) for row in rows)
        return [Candidate("ingestion_orphan_close", "all", {
            "tasks": len(rows), "by_task": dict(names), "oldest_started_at": rows[0]["started_at"],
            "effect": "标记为 failed 并注明中断遗留；解除对同源自动补跑的阻塞"})]

    def _x_translation_candidates(self):
        if self.operations is None:
            return []
        queue = self.repositories.x_translation_tasks
        summary = queue.get_status_summary()
        idle = _age_seconds(summary.get("latest_success_at"), self.now())
        if not summary.get("retryable") or (idle is not None and idle < X_TRANSLATION_STALL.total_seconds()):
            return []
        if queue.batch_running():
            return []
        return [Candidate("x_translation_retry", "queue", {
            "retryable": summary["retryable"], "latest_success_at": summary.get("latest_success_at"),
            "latest_failure_error": (summary.get("latest_failure_error") or "")[:200],
            "effect": f"提交一批最多 {X_TRANSLATION_LIMIT} 条的译文重试"})]

    def _briefing_candidates(self):
        now = self.now().astimezone(CST)
        if (self.operations is None or now.time() < BRIEFING_EARLIEST
                or self.scheduler.get_job("daily_briefing") is None):
            return []
        last_error = self.repository.latest_error_at(BRIEFING_LOGGER)
        quiet = _age_seconds(last_error, self.now())
        if quiet is not None and quiet < BRIEFING_ERROR_QUIET.total_seconds():
            return []
        date = now.date().isoformat()
        # State the verified fault and upstream explicitly; otherwise the model reads
        # old errors as history, or blames unrelated dependencies such as Ollama.
        return [Candidate("briefing_regenerate", f"{date}:{source}", {
                    "date": date, "source": source,
                    "fault": "今日该维度简报当前不存在（已按缓存键实时核实），属持续中的故障",
                    "scheduler": "08:00 生成及其自动补跑均已结束，今日不会再自动生成",
                    "upstream": "与本运维代理使用同一运行时聊天模型配置，不依赖 Ollama",
                    "latest_briefing_error_at": last_error,
                    "effect": "按日常派发链生成该维度今日简报并投递订阅；执行前若已生成则跳过"})
                for source in BRIEFING_SOURCES
                if self.scheduler.get_job(f"daily_briefing_retry_{source}") is None
                and self.repositories.briefings.get_briefing_by_date(
                    get_briefing_cache_key(date, source)) is None]

    async def execute(self, run_id, candidate):
        spec = ACTIONS[candidate.action]
        fresh = await asyncio.to_thread(self._builders[candidate.action])
        if candidate.id not in {c.id for c in fresh}:
            return {"id": candidate.id, "status": "skipped", "reason": "前置条件已不成立"}
        reservation = await asyncio.to_thread(
            self.repository.reserve_action, run_id, candidate.action, candidate.target,
            per_target=spec.per_target, per_action=spec.per_action,
            spacing_seconds=spec.spacing_seconds, title=spec.title)
        if reservation is None:
            return {"id": candidate.id, "status": "skipped", "reason": "自愈开关关闭、调查已结束或超出预算"}
        try:
            status, detail = await getattr(self, "_run_" + candidate.action)(candidate)
        except Exception as exc:
            status, detail = "uncertain", {"error_type": type(exc).__name__}
        await asyncio.to_thread(self.repository.finish_action, run_id, reservation, status,
                                spec.title, detail)
        return {**detail, **reservation, "status": status}

    async def _run_ingestion_orphan_close(self, candidate):
        return "completed", await asyncio.to_thread(self._close_orphans)

    def _close_orphans(self):
        tasks = self.repositories.ingestion_tasks
        closed = Counter()
        for row in self.repository.stale_running_tasks(ORPHAN_AGE, ORPHAN_LIMIT):
            task = tasks.get_task(row["id"])
            if not task or task.get("status") != "running":
                continue
            tasks.finish_task(row["id"], status="failed", error_msg=ORPHAN_MESSAGE,
                              item_count=int(task.get("item_count") or 0))
            closed[":".join(row["task_name"].split(":")[:2])] += 1
        return {"closed": sum(closed.values()), "by_task": dict(closed)}

    async def _run_x_translation_retry(self, candidate):
        # Same sequence as POST /ops/x-translations/retry.
        queue = self.repositories.x_translation_tasks
        await asyncio.to_thread(queue.recover_stale_running)
        if await asyncio.to_thread(queue.batch_running):
            return "skipped", {"reason": "已有翻译批次运行中"}
        retryable = await asyncio.to_thread(queue.count_retryable)
        if not retryable:
            return "skipped", {"reason": "没有待重试任务"}
        processor = XTranslationProcessor(queue)
        if not self.operations.submit(processor.process, X_TRANSLATION_LIMIT):
            return "skipped", {"reason": "应用正在关闭"}
        return "submitted", {"retryable": retryable, "limit": X_TRANSLATION_LIMIT}

    async def _run_briefing_regenerate(self, candidate):
        date, source = candidate.target.split(":")
        # Same path as the scheduler's per-source retry job, without its retry hook.
        if not self.operations.submit(run_daily_briefing_dispatch, self.repositories,
                                      redis_client=self.redis_client, sources=[source],
                                      target_date=date):
            return "skipped", {"reason": "应用正在关闭"}
        return "submitted", {"date": date, "source": source}


def select_actions(decision, candidates):
    """Map a model decision onto code-built candidates; everything else is ignored."""
    chosen = decision.get("actions")
    if not isinstance(chosen, list):
        raise ValueError("invalid_action_decision")
    by_id = {c.id: c for c in candidates}
    picked, ignored = [], []
    for item in chosen:
        cid = item.get("id") if isinstance(item, dict) else None
        if isinstance(cid, str) and cid in by_id and all(c.id != cid for c, _ in picked):
            picked.append((by_id[cid], str(item.get("reason", ""))[:200]))
        else:
            ignored.append(str(cid)[:80])
    return picked, ignored


def deferred_reasons(decision, candidates, picked):
    """The model's stated reasons for leaving candidates alone; audit only, never acted on."""
    skipped = decision.get("skipped")
    known = {c.id for c in candidates} - {c.id for c, _ in picked}
    deferred = {}
    for item in skipped if isinstance(skipped, list) else []:
        cid = item.get("id") if isinstance(item, dict) else None
        if isinstance(cid, str) and cid in known and cid not in deferred:
            deferred[cid] = str(item.get("reason", ""))[:200]
    return [{"id": cid, "reason": reason} for cid, reason in deferred.items()]
