from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from backend.app.api.dependencies import (
    get_operations_runtime,
    get_x_translation_task_repository,
)
from backend.app.core.auth import RequireAdmin
from backend.app.core.operations import ApplicationOperationsRuntime
from backend.app.models.schema_x_translation import (
    XTranslationRetryRequest,
    XTranslationRetryResponse,
    XTranslationStatusResponse,
)
from backend.app.repositories.x_translation_repository import XTranslationTaskRepository
from backend.app.services.ingestion.x_translation_service import XTranslationProcessor

router = APIRouter()


@router.get(
    "/ops/x-translations/status",
    response_model=XTranslationStatusResponse,
    tags=["Ops"],
)
async def x_translation_status(
    _: dict = Depends(RequireAdmin),
    repository: XTranslationTaskRepository = Depends(get_x_translation_task_repository),
) -> XTranslationStatusResponse:
    summary = await asyncio.to_thread(repository.get_status_summary)
    summary["batch_running"] = await asyncio.to_thread(repository.batch_running)
    return XTranslationStatusResponse.model_validate(summary)


@router.post(
    "/ops/x-translations/retry",
    response_model=XTranslationRetryResponse,
    tags=["Ops"],
)
async def retry_x_translations(
    request: XTranslationRetryRequest,
    _: dict = Depends(RequireAdmin),
    repository: XTranslationTaskRepository = Depends(get_x_translation_task_repository),
    operations: ApplicationOperationsRuntime = Depends(get_operations_runtime),
) -> XTranslationRetryResponse:
    # 先回收租约过期/陈旧的 running 任务，避免半开连接留下的僵死任务
    # 永久阻断手动重试（batch_running 409）。
    await asyncio.to_thread(repository.recover_stale_running)
    if await asyncio.to_thread(repository.batch_running):
        raise HTTPException(status_code=409, detail="X 翻译任务已有批次运行中")
    retryable = await asyncio.to_thread(repository.count_retryable)
    if not retryable:
        return XTranslationRetryResponse(
            status="noop", message="当前没有待重试的 X 翻译任务", result={"retryable": 0}
        )
    processor = XTranslationProcessor(repository, concurrency=request.concurrency)
    if not operations.submit(processor.process, request.limit):
        raise HTTPException(status_code=503, detail="应用正在关闭，无法提交翻译任务")
    return XTranslationRetryResponse(
        status="queued",
        message=f"已提交 X 翻译重试任务（最多 {request.limit} 条）",
        result={"retryable": retryable, "limit": request.limit},
    )
