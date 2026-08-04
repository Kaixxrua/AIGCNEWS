"""运维页 GitHub 搜索爬取编排：手动触发 + 本次新抓项目可选自动富化。

- 任务历史复用 ingestion_tasks，task_name 为 "github_search_crawl:{channel}"；
- 富化范围三重去重（渠道标记 + first_seen_at 锚点 + 排除已成功富化），
  与 scripts/enrich_github_projects_run.py 共用同一 SQL 片段，绝不触碰存量；
- 单次运行自动富化上限 RUN_ENRICH_MAX，超出部分由全局富化入口补齐，
  防止 LLM 成本失控与优雅关闭悬挂。
"""
from __future__ import annotations

import logging
import re
import threading
import uuid
from datetime import date, datetime, timezone
from typing import Any

from backend.app.repositories.application_repository_factory import (
    ApplicationRepositories,
)
from backend.app.services.ingestion.github_search_crawl import validate_crawl_window
from backend.app.services.ingestion.task_lifecycle import IngestionTaskLifecycle

logger = logging.getLogger(__name__)

CRAWL_TASK_PREFIX = "github_search_crawl:"
RUN_ENRICH_CONCURRENCY = 3
RUN_ENRICH_BATCH = 200
# 单次运行最多自动富化的项目数（LLM 成本 + 30s 优雅关闭兜底）
RUN_ENRICH_MAX = 500

# plan_crawl 把 min_stars 编进 channel（…_s{min_stars}_…）；状态查询未显式
# 传 min_stars 时从 channel 解析，保证非默认门槛的运行也能统计到正确范围。
_CHANNEL_MIN_STARS = re.compile(r"_s(\d+)_")
DEFAULT_STATUS_MIN_STARS = 500


def plan_crawl(
    *,
    min_stars: int,
    max_stars: int,
    limit: int,
    created_start: date,
    created_end: date,
    pushed_after: str = "",
    enrich: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """生成一次爬取运行的计划（纯函数，非法输入抛 ValueError）。

    channel 携带时间戳与随机后缀保证唯一；first_seen_after 锚点向下取整到秒，
    晚于锚点写入的本次新行才会进入自动富化范围。
    """
    pushed_after = (pushed_after or "").strip()
    validate_crawl_window(
        min_stars=min_stars,
        max_stars=max_stars,
        created_start=created_start,
        created_end=created_end,
        pushed_after=pushed_after,
    )
    moment = now or datetime.now(timezone.utc)
    anchor = moment.replace(microsecond=0).isoformat()
    channel = (
        f"admin_crawl_{moment.strftime('%Y%m%d_%H%M%S')}"
        f"_s{min_stars}_{uuid.uuid4().hex[:6]}"
    )
    return {
        "min_stars": int(min_stars),
        "max_stars": int(max_stars),
        "limit": int(limit),
        "created_start": created_start,
        "created_end": created_end,
        "pushed_after": pushed_after,
        "enrich": bool(enrich),
        "channel": channel,
        "first_seen_after": anchor,
        "task_name": f"{CRAWL_TASK_PREFIX}{channel}",
    }


class GitHubProjectCrawlAdminService:
    """GitHub 搜索爬取 + 运行范围自动富化的管理员编排入口。"""

    # 服务实例按请求构造，锁必须挂在类上才能跨实例互斥
    _crawl_lock = threading.Lock()

    def __init__(self, repositories: ApplicationRepositories) -> None:
        self._repositories = repositories

    def try_acquire_crawl(self) -> bool:
        return self._crawl_lock.acquire(blocking=False)

    def release_crawl(self) -> None:
        self._crawl_lock.release()

    def crawl_dry_run(self, plan: dict[str, Any]) -> dict[str, Any]:
        """只做分片计数（不翻页、不写库），供前端预估数据量。"""
        from backend.app.services.ingestion.github_search_crawl import (
            crawl_github_search,
        )

        return crawl_github_search(
            min_stars=plan["min_stars"],
            max_stars=plan["max_stars"],
            limit=plan["limit"],
            created_start=plan["created_start"],
            created_end=plan["created_end"],
            pushed_after=plan["pushed_after"],
            channel=plan["channel"],
            dry_run=True,
            ingestion=None,
        )

    def crawl_and_enrich(self, plan: dict[str, Any]) -> dict[str, Any]:
        """后台体：爬取 → 可选运行范围富化 → 任务收尾；无论如何释放互斥锁。"""
        from backend.app.services.ingestion.github_search_crawl import (
            crawl_github_search,
        )

        lifecycle = IngestionTaskLifecycle(self._repositories.ingestion_tasks)
        task_id = lifecycle.start(plan["task_name"])
        try:
            summary = crawl_github_search(
                min_stars=plan["min_stars"],
                max_stars=plan["max_stars"],
                limit=plan["limit"],
                created_start=plan["created_start"],
                created_end=plan["created_end"],
                pushed_after=plan["pushed_after"],
                channel=plan["channel"],
                dry_run=False,
                ingestion=self._repositories.github_ingestion,
            )
            enrichment_result: dict[str, Any] | None = None
            if plan.get("enrich") and int(summary.get("new_candidates") or 0) > 0:
                enrichment_result = self._enrich_run_scope(plan)
            lifecycle.succeed(task_id, item_count=int(summary.get("upserted") or 0))
            logger.info(
                "[Ops] GitHub 搜索爬取完成 channel=%s upserted=%s enrichment=%s",
                plan["channel"],
                summary.get("upserted"),
                enrichment_result,
            )
            return {"status": "success", "crawl": summary, "enrichment": enrichment_result}
        except Exception as exc:  # noqa: BLE001 - 任务行落 failed 并记录日志
            lifecycle.fail(task_id, exc)
            logger.exception(
                "[Ops] GitHub 搜索爬取失败 channel=%s error=%s", plan["channel"], exc
            )
            return {"status": "failed", "error": str(exc)}
        finally:
            self.release_crawl()

    def _enrich_run_scope(self, plan: dict[str, Any]) -> dict[str, Any]:
        """富化本次运行新入库的候选（上限 RUN_ENRICH_MAX，超出由全局富化补齐）。"""
        from backend.app.services.ingestion.github_project_enricher import (
            GitHubProjectEnricher,
        )

        enrichment = self._repositories.github_enrichment
        pending = enrichment.count_github_run_enrichment_candidates(
            channel=plan["channel"],
            first_seen_after=plan["first_seen_after"],
            min_stars=plan["min_stars"],
        )
        target = min(pending, RUN_ENRICH_MAX)
        result: dict[str, Any] = {
            "pending": pending,
            "target": target,
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
            "capped": pending > target,
        }
        if target <= 0:
            return result

        enricher = GitHubProjectEnricher(db=enrichment)
        after_repo_id = ""
        while result["processed"] < target:
            rows = enrichment.list_github_run_enrichment_candidates(
                channel=plan["channel"],
                first_seen_after=plan["first_seen_after"],
                min_stars=plan["min_stars"],
                after_repo_id=after_repo_id,
                limit=min(RUN_ENRICH_BATCH, target - result["processed"]),
            )
            if not rows:
                break
            after_repo_id = str(rows[-1]["repo_id"])
            batch = enricher.enrich_rows(rows, concurrency=RUN_ENRICH_CONCURRENCY)
            result["succeeded"] += int(batch.get("succeeded") or 0)
            result["failed"] += int(batch.get("failed") or 0)
            result["processed"] += len(rows)
            logger.info(
                "[Ops] 运行范围富化 channel=%s 进度 %d/%d（成功 %d，失败 %d）",
                plan["channel"],
                result["processed"],
                target,
                result["succeeded"],
                result["failed"],
            )
        return result

    def crawl_status(
        self,
        *,
        channel: str = "",
        first_seen_after: str = "",
        min_stars: int | None = None,
    ) -> dict[str, Any]:
        """查询某次（默认最近一次）爬取运行的任务状态与实时计数。

        min_stars 未显式给出时，优先从 channel 内嵌的 _s{min_stars}_ 片段
        解析（plan_crawl 生成），解析失败回落 DEFAULT_STATUS_MIN_STARS。
        """
        channel = (channel or "").strip()
        first_seen_after = (first_seen_after or "").strip()
        if first_seen_after:
            try:
                datetime.fromisoformat(first_seen_after)
            except ValueError:
                raise ValueError("first_seen_after 必须是 ISO 8601 时间") from None

        tasks = self._repositories.ingestion_tasks
        task: dict[str, Any] | None = None
        if channel:
            task = tasks.get_latest_task_by_name(f"{CRAWL_TASK_PREFIX}{channel}")
        else:
            task = tasks.get_latest_task_by_prefix(CRAWL_TASK_PREFIX)
            if task:
                channel = str(task.get("task_name") or "")[len(CRAWL_TASK_PREFIX):]

        if min_stars is None:
            match = _CHANNEL_MIN_STARS.search(channel)
            min_stars = int(match.group(1)) if match else DEFAULT_STATUS_MIN_STARS

        anchor = first_seen_after
        if not anchor and task:
            anchor = _iso(task.get("started_at"))
        counts: dict[str, Any] = {}
        if channel and anchor:
            counts = self._repositories.github_enrichment.get_github_run_crawl_status(
                channel=channel,
                first_seen_after=anchor,
                min_stars=min_stars,
            )

        task_status = str(task.get("status") or "") if task else ""
        return {
            "status": task_status or "idle",
            "channel": channel,
            "first_seen_after": anchor,
            "task_id": int(task["id"]) if task and task.get("id") is not None else None,
            "task_status": task_status,
            "item_count": int(task.get("item_count") or 0) if task else 0,
            "error_msg": (str(task.get("error_msg")) if task.get("error_msg") else None)
            if task
            else None,
            "started_at": _iso(task.get("started_at")) if task else None,
            "finished_at": _iso(task.get("finished_at")) if task else None,
            "candidates_upserted": int(counts.get("candidates_upserted") or 0),
            "scope_total": int(counts.get("scope_total") or 0),
            "enriched_succeeded": int(counts.get("enriched_succeeded") or 0),
            "enriched_failed": int(counts.get("enriched_failed") or 0),
        }


def _iso(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
