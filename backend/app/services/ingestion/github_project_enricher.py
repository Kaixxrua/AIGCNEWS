from __future__ import annotations

"""GitHub 项目库 AI 分类与中文描述富化。"""

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List

from langchain_core.messages import HumanMessage, SystemMessage

from backend.app.core.config import settings
from backend.app.core.model_factory import get_chat_model
from backend.app.repositories.mysql_repo import MySQLRepository
from backend.app.services.ingestion.github_hot_service import refresh_github_hot_candidates

logger = logging.getLogger(__name__)

PROMPT_VERSION = "v2"
DEFAULT_MIN_STARS = 500
DEFAULT_BATCH_LIMIT = 50
_MAX_RETRIES = 4
_RETRY_BASE_DELAY = 15.0
_REQUEST_INTERVAL = 3.0

PROJECT_CATEGORIES: List[Dict[str, str]] = [
    {"slug": "productivity_tools", "name": "AI 效率工具"},
    {"slug": "coding_tools", "name": "AI 编程工具"},
    {"slug": "agents_automation", "name": "AI Agent / 自动化"},
    {"slug": "ai_apps", "name": "AI 产品 / 应用"},
    {"slug": "learning_resources", "name": "AI 教程 / 学习资源"},
    {"slug": "rag_knowledge", "name": "RAG / 知识库"},
    {"slug": "multimodal_tools", "name": "多模态工具"},
    {"slug": "models_infra", "name": "模型 / 推理 / 部署"},
    {"slug": "data_eval_training", "name": "数据 / 评测 / 训练"},
    {"slug": "security_privacy", "name": "安全 / 隐私"},
    {"slug": "other", "name": "其他"},
]
CATEGORY_BY_SLUG = {item["slug"]: item["name"] for item in PROJECT_CATEGORIES}

_SYSTEM_PROMPT = """\
你是一个 AI 开源项目收藏夹的技术策展人。请根据 GitHub 仓库元数据，完成三件事：
1. 从给定分类中选择最合适的 category_slug，优先按“用户拿它来做什么”分类，而不是按底层技术名词分类。
2. 写一句中文短描述，说明这个项目能解决什么问题、适合什么使用场景。
3. 给 1-4 个中文短标签。

可选 category_slug：
- productivity_tools：AI 效率工具。能直接提升个人或团队效率的工具，如笔记、搜索、写作、浏览器、办公、自动化助手。
- coding_tools：AI 编程工具。代码生成、代码审查、IDE 插件、Claude Code/Cursor 相关、测试生成、自动 PR、代码搜索。
- agents_automation：AI Agent / 自动化。智能体框架、多智能体协作、任务编排、MCP、工具调用、自动化任务机器人。
- ai_apps：AI 产品 / 应用。接近成品的 AI 应用或客户端，如聊天产品、AI 搜索、本地应用、垂直场景应用。
- learning_resources：AI 教程 / 学习资源。awesome list、教程、课程、prompt 合集、build-your-own、论文/项目合集。
- rag_knowledge：RAG / 知识库。文档问答、企业知识库、向量检索、GraphRAG、搜索增强。
- multimodal_tools：多模态工具。图像、视频、语音、音频、视觉理解、内容生成工具。
- models_infra：模型 / 推理 / 部署。模型框架、本地模型运行、推理服务、API 网关、模型部署、LLM infra。
- data_eval_training：数据 / 评测 / 训练。数据集、benchmark、eval、微调、训练、模型评估。
- security_privacy：安全 / 隐私。AI 安全、提示词安全、漏洞分析、隐私保护、红队、对齐。
- other：其他。只有在确实无法归入以上类别时才使用。

分类优先级提示：
- awesome、tutorial、course、prompt collection、build-your-own、papers/list 优先归入 learning_resources。
- coding assistant、Claude Code、Cursor、IDE、code review、test generation 优先归入 coding_tools。
- agent、MCP、workflow、automation、multi-agent 优先归入 agents_automation。
- 直接可用的个人效率/办公/搜索/写作/浏览器工具优先归入 productivity_tools。
- API gateway、serving、local runtime、inference、deployment 优先归入 models_infra。

只返回 JSON，不要 Markdown，不要解释。格式：
{"category_slug":"coding_tools","description_zh":"一句 40 到 90 个中文字符的短描述。","tags":["代码助手","开发工具"],"confidence":0.86}
"""


@dataclass
class EnrichmentResult:
    category_slug: str
    category_name: str
    description_zh: str
    tags: List[str]
    confidence: float


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: Any, *, max_len: int = 512) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    text = text.replace("```", "").strip()
    return text[:max_len]


def _parse_json_object(raw: str) -> Dict[str, Any]:
    cleaned = re.sub(r"```(?:json)?", "", raw or "").replace("```", "").strip()
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            return {}
        try:
            data = json.loads(match.group())
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}


def _clamp_confidence(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, numeric))


def _normalize_tags(value: Any, language: str = "") -> List[str]:
    if isinstance(value, list):
        raw_tags = value
    elif value:
        raw_tags = str(value).split(",")
    else:
        raw_tags = []

    tags: List[str] = []
    for item in raw_tags:
        tag = _clean_text(item, max_len=24)
        if tag and tag not in tags:
            tags.append(tag)
        if len(tags) >= 4:
            break

    if not tags and language:
        tags.append(language)
    return tags or ["开源项目"]


def _fallback_description(repo: Dict[str, Any]) -> str:
    name = _clean_text(repo.get("full_name") or repo.get("title"), max_len=80)
    language = _clean_text(repo.get("language"), max_len=40)
    if language:
        return f"{name} 是一个以 {language} 为主的 AI 开源项目，可作为相关场景的工程参考。"
    return f"{name} 是一个值得关注的 AI 开源项目，可作为相关方向的工程参考。"


def _normalize_enrichment(data: Dict[str, Any], repo: Dict[str, Any]) -> EnrichmentResult:
    category_slug = _clean_text(data.get("category_slug"), max_len=64)
    if category_slug not in CATEGORY_BY_SLUG:
        category_slug = "other"

    description_zh = _clean_text(data.get("description_zh"), max_len=160)
    if not description_zh:
        description_zh = _fallback_description(repo)

    tags = _normalize_tags(data.get("tags"), _clean_text(repo.get("language"), max_len=40))
    return EnrichmentResult(
        category_slug=category_slug,
        category_name=CATEGORY_BY_SLUG[category_slug],
        description_zh=description_zh,
        tags=tags,
        confidence=_clamp_confidence(data.get("confidence")),
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


def _model_metadata(db: MySQLRepository) -> Dict[str, str]:
    row = db.get_runtime_provider_setting() or {}
    provider = (row.get("provider") or settings.llm_provider or "").strip()
    model_name = (row.get("model_name") or settings.chat_model_name or "").strip()
    return {"model_provider": provider, "model_name": model_name}


class GitHubProjectEnricher:
    def __init__(self, db: MySQLRepository | None = None) -> None:
        self.db = db or MySQLRepository()
        self.llm = get_chat_model(temperature=0)
        self.model_meta = _model_metadata(self.db)

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
                raw = response.content if hasattr(response, "content") else str(response)
                data = _parse_json_object(str(raw))
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
    """Daily GitHub library pipeline: ingest/update metrics, then enrich new projects only.

    Existing successful enrichments are kept stable. The ingestion layer updates
    candidates/snapshots using canonical repo IDs, so cards get fresh stars/forks
    without spending LLM calls unless a newly eligible project has no enrichment.
    """
    refresh_result: Dict[str, Any] | None = None
    if not dry_run:
        refresh_result = refresh_github_hot_candidates(limit=refresh_limit)

    enrich_result = enrich_github_projects(
        limit=enrich_limit,
        force=False,
        dry_run=dry_run,
        min_stars=min_stars,
        retry_failed=True,
        refresh_changed=False,
        concurrency=1,
    )
    return {
        "status": "success" if not dry_run else "dry_run",
        "refresh": refresh_result,
        "enrichment": enrich_result,
        "policy": "new_or_failed_only",
        "min_stars": min_stars,
    }
