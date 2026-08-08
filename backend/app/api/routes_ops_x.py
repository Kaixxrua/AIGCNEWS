from __future__ import annotations

import asyncio
import re

from fastapi import APIRouter, Depends, HTTPException

from backend.app.api.dependencies import (
    get_x_credential_admin_service,
    get_x_snapshot_admin_service,
    get_x_watch_account_repository,
    get_x_watch_admin_service,
)
from backend.app.core.auth import RequireAdmin
from backend.app.models.schema_ops import (
    XCredentialDeleteResponse,
    XCredentialListResponse,
    XCredentialRequest,
    XCredentialResponse,
    XCredentialTestResponse,
    XSnapshotRebuildRequest,
    XSnapshotRebuildResponse,
    XSnapshotRebuildResultItem,
    XWatchAccountDeleteResponse,
    XWatchAccountListResponse,
    XWatchAccountRequest,
    XWatchAccountResponse,
    XWatchAccountTestResponse,
)
from backend.app.repositories.x_watch_repository import XWatchAccountRepository
from backend.app.services.dashboard.policy import today_local
from backend.app.services.ingestion.cache_invalidation import clear_dashboard_cache_safely
from backend.app.services.x_credentials.admin_service import (
    SafeXCredentialProjection,
    XCredentialAdminNotFoundError,
    XCredentialAdminService,
    XCredentialAdminValidationError,
)
from backend.app.services.x_snapshot_admin import XSnapshotAdminService
from backend.app.services.x_watch.admin_service import (
    SafeXWatchAccountProjection,
    XWatchAdminConflictError,
    XWatchAdminNotFoundError,
    XWatchAdminService,
    XWatchAdminValidationError,
)

router = APIRouter()


# ── X 关注账号 ───────────────────────────────────────────────────────────────


def _x_watch_account_response(
    projection: SafeXWatchAccountProjection,
) -> XWatchAccountResponse:
    return XWatchAccountResponse.model_validate(projection, from_attributes=True)


@router.get("/ops/x-watch-accounts", response_model=XWatchAccountListResponse, tags=["Ops"])
async def list_x_watch_accounts(
    _: dict = Depends(RequireAdmin),
    service: XWatchAdminService = Depends(get_x_watch_admin_service),
) -> XWatchAccountListResponse:
    """列出 X 采集关注账号（数据库 watchlist，空表时按 env 句柄自举）。"""
    projections = await service.list_accounts()
    items = [_x_watch_account_response(item) for item in projections]
    return XWatchAccountListResponse(items=items, total=len(items))


@router.post("/ops/x-watch-accounts", response_model=XWatchAccountResponse, tags=["Ops"])
async def create_x_watch_account(
    request: XWatchAccountRequest,
    _: dict = Depends(RequireAdmin),
    service: XWatchAdminService = Depends(get_x_watch_admin_service),
) -> XWatchAccountResponse:
    """新增 X 关注账号。screen_name 归一化为小写无 @ 形式。"""
    try:
        projection = await service.create_account(request.model_dump())
    except XWatchAdminValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except XWatchAdminConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _x_watch_account_response(projection)


@router.put("/ops/x-watch-accounts/{account_id}", response_model=XWatchAccountResponse, tags=["Ops"])
async def update_x_watch_account(
    account_id: int,
    request: XWatchAccountRequest,
    _: dict = Depends(RequireAdmin),
    service: XWatchAdminService = Depends(get_x_watch_admin_service),
) -> XWatchAccountResponse:
    """整体更新 X 关注账号（handle/开关/排序）。"""
    try:
        projection = await service.update_account(account_id, request.model_dump())
    except XWatchAdminValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except XWatchAdminConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except XWatchAdminNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _x_watch_account_response(projection)


@router.delete("/ops/x-watch-accounts/{account_id}", response_model=XWatchAccountDeleteResponse, tags=["Ops"])
async def delete_x_watch_account(
    account_id: int,
    _: dict = Depends(RequireAdmin),
    service: XWatchAdminService = Depends(get_x_watch_admin_service),
) -> XWatchAccountDeleteResponse:
    """删除 X 关注账号。"""
    try:
        await service.delete_account(account_id)
    except XWatchAdminNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return XWatchAccountDeleteResponse(status="succeeded", message="X 关注账号已删除。", deleted=True, id=account_id)


@router.post("/ops/x-watch-accounts/{account_id}/test", response_model=XWatchAccountTestResponse, tags=["Ops"])
async def test_x_watch_account_route(
    account_id: int,
    _: dict = Depends(RequireAdmin),
    service: XWatchAdminService = Depends(get_x_watch_admin_service),
) -> XWatchAccountTestResponse:
    """探测单个 X 账号：拉取近期推文，同时验证 handle 有效性与 cookie 凭据。"""
    try:
        outcome = await service.test_account(account_id)
    except XWatchAdminNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    assert isinstance(outcome.account, SafeXWatchAccountProjection)
    return XWatchAccountTestResponse(
        status=outcome.result.get("status", "failed"),
        message=outcome.result.get("message", ""),
        account=_x_watch_account_response(outcome.account),
    )


# ── X 账号凭证 ───────────────────────────────────────────────────────────────


def _x_credential_response(
    projection: SafeXCredentialProjection,
) -> XCredentialResponse:
    return XCredentialResponse.model_validate(projection, from_attributes=True)


@router.get("/ops/x-credentials", response_model=XCredentialListResponse, tags=["Ops"])
async def list_x_credentials(
    _: dict = Depends(RequireAdmin),
    service: XCredentialAdminService = Depends(get_x_credential_admin_service),
) -> XCredentialListResponse:
    """列出 X 采集凭证（仅返回配置状态与脱敏值，不返回明文 cookie）。"""
    projections = await service.list_credentials()
    items = [_x_credential_response(item) for item in projections]
    return XCredentialListResponse(items=items, total=len(items))


@router.post("/ops/x-credentials", response_model=XCredentialResponse, tags=["Ops"])
async def create_x_credential(
    request: XCredentialRequest,
    _: dict = Depends(RequireAdmin),
    service: XCredentialAdminService = Depends(get_x_credential_admin_service),
) -> XCredentialResponse:
    """新增 X 采集凭证。auth_token 与 ct0 只写入，不明文返回。"""
    try:
        projection = await service.create_credential(request.model_dump())
    except XCredentialAdminValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _x_credential_response(projection)


@router.put("/ops/x-credentials/{credential_id}", response_model=XCredentialResponse, tags=["Ops"])
async def update_x_credential(
    credential_id: int,
    request: XCredentialRequest,
    _: dict = Depends(RequireAdmin),
    service: XCredentialAdminService = Depends(get_x_credential_admin_service),
) -> XCredentialResponse:
    """更新 X 采集凭证。两个 secret 留空表示保留当前值，不能更新为半残 pair。"""
    try:
        projection = await service.update_credential(credential_id, request.model_dump())
    except XCredentialAdminValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except XCredentialAdminNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _x_credential_response(projection)


@router.delete("/ops/x-credentials/{credential_id}", response_model=XCredentialDeleteResponse, tags=["Ops"])
async def delete_x_credential(
    credential_id: int,
    _: dict = Depends(RequireAdmin),
    service: XCredentialAdminService = Depends(get_x_credential_admin_service),
) -> XCredentialDeleteResponse:
    """删除 X 采集凭证。"""
    try:
        await service.delete_credential(credential_id)
    except XCredentialAdminNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return XCredentialDeleteResponse(
        status="succeeded",
        message="X 凭证已删除。",
        deleted=True,
        id=credential_id,
    )


@router.post("/ops/x-credentials/{credential_id}/test", response_model=XCredentialTestResponse, tags=["Ops"])
async def test_x_credential_route(
    credential_id: int,
    _: dict = Depends(RequireAdmin),
    service: XCredentialAdminService = Depends(get_x_credential_admin_service),
    watch_repository: XWatchAccountRepository = Depends(get_x_watch_account_repository),
) -> XCredentialTestResponse:
    """测试单个 X 凭证：使用第一个启用 watch handle 做真实请求，不允许 fallback。"""
    handle = _first_enabled_x_handle(watch_repository)
    try:
        outcome = await service.test_credential(credential_id, handle)
    except XCredentialAdminNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    assert isinstance(outcome.credential, SafeXCredentialProjection)
    return XCredentialTestResponse(
        status=outcome.result.get("status", "failed"),
        message=outcome.result.get("message", ""),
        credential=_x_credential_response(outcome.credential),
    )


def _first_enabled_x_handle(watch_repository: XWatchAccountRepository) -> str:
    """返回第一个启用的 X watch handle；没有时让 probe 返回稳定失败标记。"""
    handles = watch_repository.list_enabled_x_handles()
    if handles:
        return str(handles[0] or "")
    return ""


# ── X 快照补拉 ───────────────────────────────────────────────────────────────


@router.post(
    "/ops/x/snapshots/rebuild",
    response_model=XSnapshotRebuildResponse,
    tags=["Ops"],
)
async def rebuild_x_snapshots(
    request: XSnapshotRebuildRequest,
    _: dict = Depends(RequireAdmin),
    service: XSnapshotAdminService = Depends(get_x_snapshot_admin_service),
) -> XSnapshotRebuildResponse:
    """从已入库 X 推文重建日榜快照（补拉历史日期）。

    按推文发布时间的 CST 物理日归属补写 document_rank_snapshots，修复
    X 采集上线前/漏跑导致的日期模式空白；不重新请求 X API。target_date
    为空时重建全部有推文的历史日期；upsert 幂等，不覆盖更优数据。
    """
    target_date = (request.target_date or "").strip()
    if target_date:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", target_date):
            raise HTTPException(
                status_code=400, detail="target_date 格式错误，应为 YYYY-MM-DD"
            )
        if target_date > today_local().isoformat():
            raise HTTPException(status_code=400, detail="不能补拉未来日期的快照")

    outcome = await asyncio.to_thread(service.rebuild, target_date or None)
    if outcome["results"]:
        await clear_dashboard_cache_safely()

    total = sum(item["upserted"] for item in outcome["results"])
    if total:
        message = (
            f"X 快照补拉完成：{len(outcome['results'])} 个日期共 {total} 条入榜。"
        )
    else:
        message = "没有可补拉的已入库 X 推文。"
    return XSnapshotRebuildResponse(
        status="succeeded",
        message=message,
        results=[
            XSnapshotRebuildResultItem(**item) for item in outcome["results"]
        ],
        skipped_no_date=int(outcome["skipped_no_date"]),
    )
