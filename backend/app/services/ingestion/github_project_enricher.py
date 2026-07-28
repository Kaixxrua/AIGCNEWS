from __future__ import annotations

"""GitHub 项目库 AI 分类与中文描述富化。"""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict

from langchain_core.messages import HumanMessage, SystemMessage

from backend.app.core.config import settings
from backend.app.core.model_factory import get_chat_model
from backend.app.repositories.mysql_repo import MySQLRepository
from backend.app.repositories.project_write_repository import (
    GitHubProjectEnrichmentRepository,
)
from backend.app.repositories.runtime_provider_repository import (
    RuntimeProviderSettingReader,
)
from backend.app.services.ingestion.github_hot_service import refresh_github_hot_candidates
from backend.app.services.ingestion.github_project_metrics_service import (
    current_github_metric_date,
    refresh_and_compute_github_project_metrics,
)
from backend.app.services.ingestion.project_taxonomy import (
    CATEGORY_PROMPT,
    PROMPT_VERSION,
    EnrichmentResult,
    clean_text,
    extract_message_text,
    normalize_enrichment,
    normalize_tags,
    parse_json_object,
)

logger = logging.getLogger(__name__)

DEFAULT_MIN_STARS = 500
DEFAULT_BATCH_LIMIT = 50
_MAX_RETRIES = 4
_RETRY_BASE_DELAY = 15.0
_REQUEST_INTERVAL = 3.0

_SYSTEM_PROMPT = f"""\
你是一个 AI 开源项目收藏夹的技术策展人。请根据 GitHub 仓库元数据，完成四件事：
1. 从给定一级分类中选择最合适的 category_slug，优先按“用户拿它来做什么”分类，而不是按底层技术名词分类。
2. 从该一级分类下选择最合适的 subcategory_slug。
3. 写一句中文短描述，说明这个项目能解决什么问题、适合什么使用场景。
4. 给 1-4 个中文短标签。

{CATEGORY_PROMPT}

只返回 JSON，不要 Markdown，不要解释。格式：
{{"category_slug":"coding_tools","subcategory_slug":"ide_plugins","description_zh":"一句 40 到 90 个中文字符的短描述。","tags":["IDE 插件","代码助手"],"confidence":0.86}}
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
        db: GitHubProjectEnrichmentRepository | None = None,
        *,
        runtime_settings: RuntimeProviderSettingReader | None = None,
    ) -> None:
        self.db = db or MySQLRepository()
        self.llm = get_chat_model(temperature=0)
        self.model_meta = _model_metadata(
            runtime_settings or self.db.runtime_provider_settings
        )

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
        if concurrency <= 1:
            succeeded = 0
            failed = 0
            for repo in candidates:
                ok = self._enrich_and_store(repo)
                if ok:
                    succeeded += 1
                    time.sleep(_REQUEST_INTERVAL)
                else:
                    failed += 1
            return {
                "status": "success",
                "candidates": len(candidates),
                "succeeded": succeeded,
                "failed": failed,
                "concurrency": concurrency,
            }

        succeeded = 0
        failed = 0
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(self._enrich_and_store, repo) for repo in candidates]
            for future in as_completed(futures):
                if future.result():
                    succeeded += 1
                else:
                    failed += 1

        return {
            "status": "success",
            "candidates": len(candidates),
            "succeeded": succeeded,
            "failed": failed,
            "concurrency": concurrency,
        }

    def _enrich_and_store(self, repo: Dict[str, Any]) -> bool:
        repo_id = str(repo.get("repo_id") or "").strip()
        source_fingerprint = str(repo.get("source_fingerprint") or "").strip()
        if not repo_id or not source_fingerprint:
            return False

        try:
            result = self._enrich_one(repo)
            self.db.upsert_github_repo_enrichment(
                {
                    "repo_id": repo_id,
                    "category_slug": result.category_slug,
                    "category_name": result.category_name,
                    "subcategory_slug": result.subcategory_slug,
                    "subcategory_name": result.subcategory_name,
                    "description_zh": result.description_zh,
                    "tags_json": json.dumps(result.tags, ensure_ascii=False),
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

    def _enrich_one(self, repo: Dict[str, Any]) -> EnrichmentResult:
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=_repo_prompt(repo)),
        ]

        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES):
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
) -> Dict[str, Any]:
    return GitHubProjectEnricher().enrich_batch(
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
        )
        metric_result = refresh_and_compute_github_project_metrics(
            min_stars=min_stars,
            metric_date=metric_date,
        )

    enrich_result = enrich_github_projects(
        limit=enrich_limit,
        force=False,
        dry_run=dry_run,
        min_stars=min_stars,
        retry_failed=True,
        refresh_changed=False,
        concurrency=1,
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
