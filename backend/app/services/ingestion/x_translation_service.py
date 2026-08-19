from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from backend.app.core.config import settings
from backend.app.core.model_factory import get_chat_model
from backend.app.repositories.x_translation_repository import XTranslationTaskRepository

logger = logging.getLogger(__name__)

PROMPT_VERSION = "x-translation-v1"
_MAX_RETRIES = 2
_MAX_CONSECUTIVE_FAILURES = 5
_DEFAULT_TRANSLATION_TIMEOUT_SECONDS = 120.0
_URL_RE = re.compile(r"https?://[^\s]+")
_HANDLE_RE = re.compile(r"@[A-Za-z0-9_]+")
_CODE_RE = re.compile(r"```[\s\S]*?```|`[^`]+`")

_SYSTEM_PROMPT = (
    "你是 AI 行业资讯网站的专业翻译。将英文 X 推文翻译为自然准确的简体中文。"
    "只输出译文，不要解释。保留换行、emoji、URL、@提及、#标签；"
    "产品名、模型名、公司名、用户名、库名、版本、命令和代码保持原文不译。"
)


def _text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, list):
        return "".join(str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in content).strip()
    return str(content or "").strip()


def _protect(source: str) -> tuple[str, dict[str, str]]:
    tokens: dict[str, str] = {}
    index = 0
    def replace(match: re.Match[str]) -> str:
        nonlocal index
        token = f"XTRTOKEN{index}X"
        index += 1
        tokens[token] = match.group(0)
        return token
    protected = _CODE_RE.sub(replace, source)
    protected = _URL_RE.sub(replace, protected)
    protected = _HANDLE_RE.sub(replace, protected)
    return protected, tokens


def _restore(value: str, tokens: dict[str, str]) -> str:
    if any(token not in value for token in tokens):
        raise ValueError("translation omitted protected token")
    if any(value.count(token) != 1 for token in tokens):
        raise ValueError("translation duplicated protected token")
    for token, original in tokens.items():
        value = value.replace(token, original)
    return value


class XTranslationProcessor:
    def __init__(self, repository: XTranslationTaskRepository, *, concurrency: int = 3) -> None:
        self.repository = repository
        self.concurrency = max(1, min(int(concurrency), 10))
        self.timeout_seconds = max(
            1.0,
            min(
                float(getattr(settings, "x_translation_timeout_seconds", _DEFAULT_TRANSLATION_TIMEOUT_SECONDS)),
                float(getattr(settings, "llm_request_timeout", _DEFAULT_TRANSLATION_TIMEOUT_SECONDS)),
            ),
        )

    def _model_metadata(self) -> tuple[str, str]:
        reader = getattr(self.repository, "_runtime_provider_settings", None)
        row = reader.get_runtime_provider_setting() if reader else {}
        return (
            str((row or {}).get("provider") or getattr(settings, "llm_provider", "")),
            str((row or {}).get("model_name") or getattr(settings, "chat_model_name", "")),
        )

    def _translate_one(self, task: dict[str, Any]) -> str:
        source = str(task.get("source_text") or "").strip()
        if not source:
            raise ValueError("empty source text")
        protected, tokens = _protect(source)
        model = get_chat_model(temperature=0)
        response = model.invoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=protected),
        ])
        translated = _text(response)
        if not translated or translated.startswith("```"):
            raise ValueError("empty or contaminated translation")
        return _restore(translated, tokens)

    def _translate_with_timeout(self, task: dict[str, Any]) -> str:
        result: list[str] = []
        errors: list[BaseException] = []
        finished = threading.Event()

        def invoke() -> None:
            try:
                result.append(self._translate_one(task))
            except BaseException as exc:
                errors.append(exc)
            finally:
                finished.set()

        thread = threading.Thread(
            target=invoke,
            name=f"x-translation-invoke-{task.get('id', 'unknown')}",
            daemon=True,
        )
        thread.start()
        if not finished.wait(self.timeout_seconds):
            raise TimeoutError(
                f"X translation timed out after {self.timeout_seconds:g} seconds"
            )
        if errors:
            raise errors[0]
        if not result:
            raise RuntimeError("translation worker returned no result")
        return result[0]

    def process(self, limit: int = 200) -> dict[str, int]:
        self.repository.recover_stale_running()
        tasks = self.repository.claim_retryable(
            max(1, int(limit)),
            lease_seconds=max(60, int(self.timeout_seconds * 2)),
        )
        completed = failed = 0
        consecutive_failures = 0
        def run(task: dict[str, Any]) -> tuple[int, str | None, str | None]:
            task_id = int(task["id"])
            claim_token = str(task.get("claim_token") or "")
            for attempt in range(_MAX_RETRIES):
                if not self.repository.increment_attempt(task_id, claim_token):
                    return task_id, None, "translation lease lost"
                try:
                    return task_id, self._translate_with_timeout(task), None
                except Exception as exc:
                    if attempt + 1 < _MAX_RETRIES:
                        time.sleep(min(2 ** attempt, 4))
                    else:
                        return task_id, None, str(exc)[:1000]
            return task_id, None, "translation failed"
        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            futures = [pool.submit(run, task) for task in tasks]
            for future in as_completed(futures):
                task_id, translation, error = future.result()
                task = next(item for item in tasks if int(item["id"]) == task_id)
                claim_token = str(task.get("claim_token") or "")
                if translation is not None:
                    if self.repository.complete_task(task_id, translation, "", "", claim_token):
                        completed += 1
                    consecutive_failures = 0
                else:
                    if self.repository.fail_task(
                        task_id, error or "translation failed", "", "", claim_token
                    ):
                        failed += 1
                        consecutive_failures += 1
                    if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                        remaining = [int(item["id"]) for item in tasks if int(item["id"]) != task_id]
                        self.repository.reset_claimed_to_pending(remaining, claim_token)
                        break
        return {"claimed": len(tasks), "completed": completed, "failed": failed}
