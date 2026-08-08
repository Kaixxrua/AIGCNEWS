from __future__ import annotations

"""GitHub 项目库 AI 分类与中文描述富化。"""

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict

from langchain_core.messages import HumanMessage, SystemMessage

from backend.app.core.config import settings
from backend.app.core.model_factory import (
    get_chat_model,
    get_configured_reasoning_effort,
)
from backend.app.domain.project_taxonomy import (
    CATEGORY_PROMPT,
    PROMPT_VERSION,
    EnrichmentResult,
    clean_text,
    extract_message_text,
    normalize_enrichment,
    parse_json_object,
)
from backend.app.repositories.project_write_repository import (
    GitHubProjectEnrichmentRepository,
    GitHubProjectIngestionRepository,
    GitHubProjectSemanticSourceRepository,
)
from backend.app.repositories.runtime_provider_repository import (
    RuntimeProviderSettingReader,
)
from backend.app.services.ingestion.github_hot_service import (
    refresh_github_hot_candidates,
)
from backend.app.services.ingestion.github_project_metrics_service import (
    current_github_metric_date,
    refresh_and_compute_github_project_metrics,
)

logger = logging.getLogger(__name__)

DEFAULT_MIN_STARS = 500
DEFAULT_BATCH_LIMIT = 50
# 项目分类/短描述富化的推理强度缺省档：运维页未配置时回落到 medium，
# 不依赖中转网关的默认档；配置后以运维页为准
ENRICHMENT_REASONING_EFFORT = "medium"
_MAX_RETRIES = 4
_RETRY_BASE_DELAY = 15.0
_REQUEST_INTERVAL = 3.0


class _EnrichmentCancelled(Exception):
    """协作式终止信号：未发起模型调用的条目快速退出，且不得记入失败状态。"""


# 进程级终止信号与运行计数：运维面板的「终止富化」对本进程内 enrich_batch
# 生效（手动补跑/重试与每日流水线共用同一入口）；enrich_rows（爬取运行内
# 自动富化）不受影响，保持爬取行为不变。
_cancel_event = threading.Event()
_running_lock = threading.Lock()
_running_batches = 0


def request_github_enrichment_cancel() -> bool:
    """请求终止当前运行的富化批处理；返回是否有批处理在运行。

    没有运行中的批处理时不置位，避免残留的终止信号误伤下一次提交。
    任务已入队但线程尚未进入 enrich_batch 的极短窗口内会返回 False，
    调用方稍后再次请求即可。
    """
    with _running_lock:
        running = _running_batches > 0
    if running:
        _cancel_event.set()
    return running


def github_enrichment_batch_running() -> bool:
    with _running_lock:
        return _running_batches > 0


def _enter_batch() -> None:
    global _running_batches
    with _running_lock:
        _cancel_event.clear()  # 新批次总是以干净的终止信号起步
        _running_batches += 1


def _exit_batch() -> None:
    global _running_batches
    with _running_lock:
        _running_batches = max(0, _running_batches - 1)


_SYSTEM_PROMPT = f"""\
你是一个 AI 开源项目收藏夹的技术策展人。请根据 GitHub 仓库元数据，完成四件事：
1. 从给定一级分类中选择最合适的 category_slug，优先按“用户拿它来做什么”分类，而不是按底层技术名词分类。
2. 从该一级分类下选择最合适的 subcategory_slug。
3. 写一句中文短描述，说明这个项目能解决什么问题、适合什么使用场景。
4. 给 1-4 个中文短标签，并按相同顺序给出等量、自然的英文短标签。

{CATEGORY_PROMPT}

只返回 JSON，不要 Markdown，不要解释。格式：
{{"category_slug":"coding_tools","subcategory_slug":"ide_plugins","description_zh":"一句 40 到 90 个中文字符的短描述。","tags_zh":["IDE 插件","代码助手"],"tags_en":["IDE plugin","Coding assistant"],"confidence":0.86}}
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fallback_description(repo: Dict[str, Any]) -> str:
    name = clean_text(repo.get("full_name") or repo.get("title"), max_len=80)
    language = clean_text(repo.get("language"), max_len=40)
    if language:
        return f"{name} 是一个以 {language} 为主的 AI 开源项目，可作为相关场景的工程参考。"
    return f"{name} 是一个值得关注的 AI 开源项目，可作为相关方向的工程参考。"


def _normalize_enrichment(data: Dict[str, Any], repo: Dict[str, Any]) -> EnrichmentResult:
    return normalize_enrichment(
        data,
        fallback_description=_fallback_description(repo),
        fallback_tag=clean_text(repo.get("language"), max_len=40),
    )


def _repo_prompt(repo: Dict[str, Any]) -> str:
    payload = {
        "full_name": repo.get("full_name") or repo.get("title") or "",
        "description": repo.get("description") or "",
        "language": repo.get("language") or "",
        "topics": repo.get("topics") or [],
        "stars": repo.get("stars") or 0,
        "forks": repo.get("forks") or 0,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _model_metadata(reader: RuntimeProviderSettingReader) -> Dict[str, str]:
    row = reader.get_runtime_provider_setting() or {}
    provider = (row.get("provider") or settings.llm_provider or "").strip()
    model_name = (row.get("model_name") or settings.chat_model_name or "").strip()
    return {"model_provider": provider, "model_name": model_name}


class GitHubProjectEnricher:
    def __init__(
        self,
        db: GitHubProjectEnrichmentRepository,
        *,
        runtime_settings: RuntimeProviderSettingReader | None = None,
    ) -> None:
        self.db = db
        self._llm = None
        self.model_meta = _model_metadata(
            runtime_settings or self.db.runtime_provider_settings
        )

    @property
    def llm(self):
        if self._llm is None:
            self._llm = get_chat_model(
                temperature=0,
                reasoning_effort=get_configured_reasoning_effort(
                    fallback=ENRICHMENT_REASONING_EFFORT
                ),
            )
        return self._llm

    def enrich_batch(
        self,
        *,
        limit: int = DEFAULT_BATCH_LIMIT,
        force: bool = False,
        dry_run: bool = False,
        min_stars: int = DEFAULT_MIN_STARS,
        retry_failed: bool = True,
        refresh_changed: bool = False,
        concurrency: int = 1,
    ) -> Dict[str, Any]:
        candidates = self.db.get_github_projects_needing_enrichment(
            limit=limit,
            min_stars=min_stars,
            prompt_version=PROMPT_VERSION,
            force=force,
            retry_failed=retry_failed,
            refresh_changed=refresh_changed,
        )
        if dry_run:
            return {
                "status": "dry_run",
                "candidates": len(candidates),
                "items": [
                    {
                        "repo_id": item.get("repo_id"),
                        "full_name": item.get("full_name"),
                        "stars": item.get("stars"),
                    }
                    for item in candidates
                ],
            }

        concurrency = max(1, min(int(concurrency or 1), 10))
        _enter_batch()
        try:
            succeeded = 0
            failed = 0
            cancelled = 0
            if concurrency <= 1:
                for repo in candidates:
                    if _cancel_event.is_set():
                        break
                    outcome = self._enrich_and_store(repo, cancel_event=_cancel_event)
                    if outcome is None:
                        cancelled += 1
                    elif outcome:
                        succeeded += 1
                        # 成功后的节流间隔同时充当终止监听窗口：收到信号立即停下
                        if _cancel_event.wait(_REQUEST_INTERVAL):
                            break
                    else:
                        failed += 1
            else:
                with ThreadPoolExecutor(max_workers=concurrency) as executor:
                    futures = [
                        executor.submit(self._enrich_and_store, repo, cancel_event=_cancel_event)
                        for repo in candidates
                    ]
                    for future in as_completed(futures):
                        outcome = future.result()
                        if outcome is None:
                            cancelled += 1
                        elif outcome:
                            succeeded += 1
                        else:
                            failed += 1
            # 循环提前退出时，未处理的条目一律记为已终止：保持待处理，不计失败
            cancelled += len(candidates) - succeeded - failed - cancelled
            return {
                "status": "cancelled" if cancelled > 0 else "success",
                "candidates": len(candidates),
                "succeeded": succeeded,
                "failed": failed,
                "cancelled": cancelled,
                "concurrency": concurrency,
            }
        finally:
            _exit_batch()

    def enrich_rows(
        self, rows: list[Dict[str, Any]], *, concurrency: int = 3
    ) -> Dict[str, Any]:
        """富化一批已选定的行（调用方负责范围筛选），返回处理计数。

        与 enrich_batch 的区别：不向仓储查询候选，直接处理传入行。
        供"单次爬取运行内自动富化"等已精确圈定范围的场景使用。
        """
        concurrency = max(1, min(int(concurrency or 1), 10))
        succeeded = 0
        failed = 0
        if concurrency <= 1:
            for repo in rows:
                if self._enrich_and_store(repo):
                    succeeded += 1
                else:
                    failed += 1
        else:
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = [executor.submit(self._enrich_and_store, repo) for repo in rows]
                for future in as_completed(futures):
                    if future.result():
                        succeeded += 1
                    else:
                        failed += 1
        return {
            "status": "success",
            "processed": len(rows),
            "succeeded": succeeded,
            "failed": failed,
            "concurrency": concurrency,
        }

    def _enrich_and_store(
        self,
        repo: Dict[str, Any],
        *,
        cancel_event: threading.Event | None = None,
    ) -> bool | None:
        """富化并落库单条；返回 True/False，被终止时返回 None（不记失败）。"""
        repo_id = str(repo.get("repo_id") or "").strip()
        source_fingerprint = str(repo.get("source_fingerprint") or "").strip()
        if not repo_id or not source_fingerprint:
            return False

        try:
            result = self._enrich_one(repo, cancel_event=cancel_event)
            self.db.upsert_github_repo_enrichment(
                {
                    "repo_id": repo_id,
                    "category_slug": result.category_slug,
                    "category_name": result.category_name,
                    "subcategory_slug": result.subcategory_slug,
                    "subcategory_name": result.subcategory_name,
                    "description_zh": result.description_zh,
                    "tags_json": json.dumps(result.tags, ensure_ascii=False),
                    "tags_zh_json": json.dumps(result.tags, ensure_ascii=False),
                    "tags_en_json": json.dumps(result.tags_en, ensure_ascii=False),
                    "confidence": result.confidence,
                    "source_fingerprint": source_fingerprint,
                    "prompt_version": PROMPT_VERSION,
                    "status": "succeeded",
                    "error_msg": None,
                    "enriched_at": _utcnow(),
                    "updated_at": _utcnow(),
                    **self.model_meta,
                }
            )
            return True
        except _EnrichmentCancelled:
            logger.info(
                "[GitHubProjectEnricher] 富化批处理已终止，repo=%s 保持待处理",
                repo.get("full_name") or repo_id,
            )
            return None
        except Exception as exc:  # noqa: BLE001 - record per-row failures and continue
            logger.warning(
                "[GitHubProjectEnricher] 富化失败 repo=%s error=%s",
                repo.get("full_name") or repo_id,
                exc,
                exc_info=True,
            )
            self.db.mark_github_repo_enrichment_failed(
                repo_id,
                source_fingerprint=source_fingerprint,
                prompt_version=PROMPT_VERSION,
                error_msg=str(exc),
                **self.model_meta,
            )
            return False

    def backfill_bilingual_tags(
        self, *, after_repo_id: str = "", limit: int = 50,
        min_stars: int = DEFAULT_MIN_STARS, dry_run: bool = False,
    ) -> Dict[str, Any]:
        rows = self.db.list_github_projects_needing_bilingual_tags(
            after_repo_id=after_repo_id,
            limit=limit,
            min_stars=min_stars,
        )
        succeeded = failed = 0
        failures: list[dict[str, Any]] = []
        for row in rows:
            if dry_run:
                continue
            repo_id = str(row.get("repo_id") or "")
            try:
                result = self._enrich_one(row)
                self.db.update_github_repo_system_tags(
                    repo_id=repo_id,
                    tags_zh_json=json.dumps(result.tags, ensure_ascii=False),
                    tags_en_json=json.dumps(result.tags_en, ensure_ascii=False),
                    prompt_version=PROMPT_VERSION,
                    **self.model_meta,
                )
                succeeded += 1
            except Exception as exc:  # noqa: BLE001 - preserve successful enrichment
                failed += 1
                failures.append({"repo_id": repo_id, "error": str(exc)[:300]})
        next_cursor = str(rows[-1]["repo_id"]) if rows else str(after_repo_id or "")
        return {
            "status": "dry_run" if dry_run else ("partial" if failed else "success"),
            "processed": len(rows),
            "succeeded": succeeded,
            "failed": failed,
            "next_cursor": next_cursor,
            "has_more": len(rows) >= max(1, min(int(limit), 500)),
            "failures": failures,
        }

    def _enrich_one(
        self,
        repo: Dict[str, Any],
        *,
        cancel_event: threading.Event | None = None,
    ) -> EnrichmentResult:
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=_repo_prompt(repo)),
        ]

        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            if cancel_event is not None and cancel_event.is_set():
                raise _EnrichmentCancelled("富化批处理已被管理员终止")
            try:
                response = self.llm.invoke(messages)
                data = parse_json_object(extract_message_text(response))
                if not data:
                    raise ValueError("模型未返回可解析 JSON")
                return _normalize_enrichment(data, repo)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                exc_str = str(exc).lower()
                is_retryable = any(
                    marker in exc_str
                    for marker in (
                        "429",
                        "503",
                        "rate_limit",
                        "temporarily unavailable",
                        "service unavailable",
                        "api_error",
                        "timeout",
                    )
                )
                if is_retryable and attempt < _MAX_RETRIES - 1:
                    wait = _RETRY_BASE_DELAY * (2**attempt)
                    logger.warning(
                        "[GitHubProjectEnricher] 模型服务暂不可用/限速，第 %d/%d 次重试，等待 %.0fs...",
                        attempt + 1,
                        _MAX_RETRIES,
                        wait,
                    )
                    # 退避等待监听终止信号：收到即醒，不让取消卡在长 sleep 上
                    if cancel_event is not None:
                        if cancel_event.wait(wait):
                            raise _EnrichmentCancelled("富化批处理已被管理员终止")
                    else:
                        time.sleep(wait)
                    continue
                break

        raise last_error or RuntimeError("GitHub 项目富化失败")


def enrich_github_projects(
    *,
    limit: int = DEFAULT_BATCH_LIMIT,
    force: bool = False,
    dry_run: bool = False,
    min_stars: int = DEFAULT_MIN_STARS,
    retry_failed: bool = True,
    refresh_changed: bool = False,
    concurrency: int = 1,
    db: GitHubProjectEnrichmentRepository,
) -> Dict[str, Any]:
    return GitHubProjectEnricher(db=db).enrich_batch(
        limit=limit,
        force=force,
        dry_run=dry_run,
        min_stars=min_stars,
        retry_failed=retry_failed,
        refresh_changed=refresh_changed,
        concurrency=concurrency,
    )


def run_github_project_daily_pipeline(
    *,
    refresh_limit: int = 80,
    enrich_limit: int = DEFAULT_BATCH_LIMIT,
    min_stars: int = DEFAULT_MIN_STARS,
    dry_run: bool = False,
    ingestion: GitHubProjectIngestionRepository,
    enrichment: GitHubProjectEnrichmentRepository,
    semantic_sources: GitHubProjectSemanticSourceRepository,
) -> Dict[str, Any]:
    """Daily GitHub library pipeline: ingest/update metrics, score, then enrich new projects only.

    Existing successful enrichments are kept stable. The ingestion layer updates
    candidates/snapshots using canonical repo IDs, so cards get fresh stars/forks
    without spending LLM calls unless a newly eligible project has no enrichment.
    Daily metric snapshots and hot scores are pure data processing and do not call
    the LLM.
    """
    metric_date = current_github_metric_date()
    refresh_result: Dict[str, Any] | None = None
    metric_result: Dict[str, Any] | None = None
    if not dry_run:
        refresh_result = refresh_github_hot_candidates(
            limit=refresh_limit,
            observed_date=metric_date,
            db=ingestion,
        )
        metric_result = refresh_and_compute_github_project_metrics(
            min_stars=min_stars,
            metric_date=metric_date,
            db=ingestion,
        )

    enrich_result = enrich_github_projects(
        limit=enrich_limit,
        force=False,
        dry_run=dry_run,
        min_stars=min_stars,
        retry_failed=True,
        refresh_changed=False,
        concurrency=1,
        db=enrichment,
    )
    semantic_result: Dict[str, Any] = {"status": "disabled"}
    if settings.project_semantic_indexing_enabled:
        try:
            from backend.app.services.indexing.github_project_semantic_indexer import (
                sync_github_project_semantic_index,
            )

            semantic_result = sync_github_project_semantic_index(
                min_stars=min_stars,
                dry_run=dry_run,
                db=semantic_sources,
            )
        except Exception as exc:
            logger.warning("GitHub project semantic sync failed without aborting daily pipeline: %s", exc)
            semantic_result = {"status": "failed", "error": str(exc)[:1000]}
    return {
        "status": "success" if not dry_run else "dry_run",
        "refresh": refresh_result,
        "metric_refresh": (metric_result or {}).get("refresh"),
        "daily_metrics": (metric_result or {}).get("metrics"),
        "enrichment": enrich_result,
        "semantic_index": semantic_result,
        "policy": "new_or_failed_only",
        "min_stars": min_stars,
    }
