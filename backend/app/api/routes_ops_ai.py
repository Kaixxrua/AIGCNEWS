from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.app.api.dependencies import get_operations_runtime
from backend.app.core.auth import RequireAdmin
from backend.app.core.operations import ApplicationOperationsRuntime

router = APIRouter(prefix="/ops/ai", tags=["Ops"], dependencies=[Depends(RequireAdmin)])


def get_ai_ops(request: Request):
    service = getattr(request.app.state, "ai_ops_service", None)
    if service is None:
        raise HTTPException(503, "AI 运维尚未启动")
    return service


class Config(BaseModel):
    enabled: bool
    interval_minutes: int = Field(15, ge=5, le=120)


@router.get("/runs")
async def list_runs(service=Depends(get_ai_ops)):
    return {"items": await asyncio.to_thread(service.repository.list),
            "config": await asyncio.to_thread(service.repository.config)}


@router.put("/config")
async def configure(config: Config, service=Depends(get_ai_ops)):
    await asyncio.to_thread(service.repository.configure, config.enabled, config.interval_minutes)
    return config


@router.post("/runs", status_code=202)
async def start_run(service=Depends(get_ai_ops),
                    operations: ApplicationOperationsRuntime = Depends(get_operations_runtime)):
    run_id = await asyncio.to_thread(service.repository.create, "manual")
    if not run_id:
        raise HTTPException(409, "已有巡检正在运行")
    if not operations.submit(service.run, run_id):
        await asyncio.to_thread(service.repository.finish, run_id, "interrupted")
        raise HTTPException(503, "服务正在停止")
    return {"id": run_id}


@router.get("/runs/{run_id}")
async def get_run(run_id: UUID, service=Depends(get_ai_ops)):
    row = await asyncio.to_thread(service.repository.get, str(run_id))
    if row is None:
        raise HTTPException(404, "巡检不存在")
    return row


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: UUID, service=Depends(get_ai_ops)):
    await get_run(run_id, service)
    await asyncio.to_thread(service.repository.finish, str(run_id), "cancelled")
    return await get_run(run_id, service)
