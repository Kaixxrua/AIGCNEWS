"""Fixed recovery policy. Model text never supplies action names or arguments."""
import re
from datetime import datetime, timezone

from backend.app.repositories.postgres_ai_ops_repository import RECOVERY_JOBS


def eligible(task, now):
    if not task or task.get("status") != "failed" or task.get("item_count") != 0:
        return False
    try:
        age = (now - datetime.fromisoformat(task["finished_at"])).total_seconds()
    except (KeyError, TypeError, ValueError):
        return False
    message = task.get("error_msg") or ""
    if re.search(r"401|403|429|credential|unauthorized|forbidden|rate.?limit|"
                 r"TypeError|ValueError|KeyError|IntegrityError", message, re.I):
        return False
    return 300 <= age <= 3600 and bool(re.search(
        r"\b(ReadTimeout|ConnectTimeout|ConnectError|TimeoutError)\b|"
        r"connection reset|connection timed out|temporary failure in name resolution", message, re.I))


class AiOpsRecovery:
    def __init__(self, repository, scheduler):
        self.repository, self.scheduler = repository, scheduler

    def run(self, run_id, delivery):
        if delivery.get("status") != "ok" or delivery.get("release_status") != "delivered":
            return {"status": "skipped", "reason": "交付状态缺失、过期或发布未完成"}
        if self.scheduler.state != 1:
            return {"status": "skipped", "reason": "调度器未处于运行状态"}
        for task_name, job_id in RECOVERY_JOBS.items():
            job = self.scheduler.get_job(job_id)
            now = datetime.now(timezone.utc)
            if (job is None or job.max_instances != 1 or job.next_run_time is None
                    or (job.next_run_time - now).total_seconds() < 300):
                continue
            action = self.repository.reserve_recovery(run_id, task_name, job_id, eligible)
            if action is None:
                continue
            try:
                # Retain the registered job, arguments, trigger and concurrency limit.
                job.modify(next_run_time=now)
                self.scheduler.wakeup()
            except Exception:
                self.repository.finish_recovery(run_id, action, "uncertain")
                return {**action, "status": "uncertain", "reason": "提交结果不确定，禁止自动重放"}
            self.repository.finish_recovery(run_id, action, "scheduled")
            return {**action, "status": "scheduled", "reason": "已提交补跑，尚未确认采集恢复"}
        return {"status": "skipped", "reason": "无符合权限、故障条件和预算的补跑任务"}
