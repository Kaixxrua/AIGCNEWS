from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from backend.app.api.dependencies import (
    get_wechat_account_repository,
    get_wechat_account_service,
    get_wechat_article_repository,
    get_wechat_follow_service,
    get_wechat_login_service,
    get_wechat_sync_service,
)
from backend.app.api.feature_gates import require_wechat_source_enabled
from backend.app.core.auth import RequireAdmin, RequireUser, extract_user_id
from backend.app.models.schema_wechat import (
    WeChatAccountSaveRequest,
    WeChatArticleDetailResponse,
    WeChatArticleListResponse,
    WeChatCatalogListResponse,
    WeChatErrorResponse,
    WeChatFeedResponse,
    WeChatFollowStateResponse,
    WeChatLoginAttemptResponse,
    WeChatOfficialAccountListResponse,
    WeChatOfficialAccountResponse,
    WeChatSessionResponse,
    WeChatSyncSubmitResponse,
)
from backend.app.repositories.wechat_account_repository import (
    WeChatOfficialAccountRepository,
)
from backend.app.repositories.wechat_article_repository import WeChatArticleRepository
from backend.app.services.source_plugins.wechat_source import (
    WeChatAccountServiceProtocol,
    WeChatError,
    WeChatFollowServiceProtocol,
    WeChatLoginServiceProtocol,
    WeChatSyncServiceProtocol,
)

router = APIRouter(
    prefix="/ops/wechat",
    tags=["WeChat"],
    dependencies=[Depends(require_wechat_source_enabled)],
)


def _owner_id(identity: dict[str, Any] = Depends(RequireAdmin)) -> int:
    user_id = extract_user_id(identity)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无法识别当前用户",
        )
    return user_id


def _user_id(identity: dict[str, Any] = Depends(RequireUser)) -> int:
    user_id = extract_user_id(identity)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无法识别当前用户",
        )
    return user_id


def _handle_wechat_error(exc: WeChatError) -> None:
    status_map = {
        "WECHAT_LOGIN_REQUIRED": status.HTTP_409_CONFLICT,
        "WECHAT_QR_EXPIRED": status.HTTP_409_CONFLICT,
        "WECHAT_LOGIN_PENDING": status.HTTP_409_CONFLICT,
        "WECHAT_LOGIN_FAILED": status.HTTP_409_CONFLICT,
        "WECHAT_SESSION_EXPIRED": status.HTTP_409_CONFLICT,
        "WECHAT_ACCOUNT_CONTEXT_INVALID": status.HTTP_409_CONFLICT,
        "WECHAT_PROXY_UNAVAILABLE": status.HTTP_424_FAILED_DEPENDENCY,
        "WECHAT_RATE_LIMITED": status.HTTP_429_TOO_MANY_REQUESTS,
        "WECHAT_UPSTREAM_ERROR": status.HTTP_424_FAILED_DEPENDENCY,
        "WECHAT_ACCOUNT_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "WECHAT_SYNC_RUNNING": status.HTTP_409_CONFLICT,
    }
    raise HTTPException(
        status_code=status_map.get(exc.code, status.HTTP_424_FAILED_DEPENDENCY),
        detail=WeChatErrorResponse(code=exc.code, message=exc.message).model_dump(),
    )


@router.post("/login-sessions", response_model=WeChatLoginAttemptResponse)
async def create_wechat_login_session(
    owner_id: int = Depends(_owner_id),
    service: WeChatLoginServiceProtocol = Depends(get_wechat_login_service),
) -> dict[str, Any]:
    try:
        return await service.start_login_attempt(owner_id)
    except WeChatError as exc:
        _handle_wechat_error(exc)


@router.get("/login-sessions/{attempt_id}/qrcode")
async def get_wechat_qr_code(
    attempt_id: UUID,
    owner_id: int = Depends(_owner_id),
    service: WeChatLoginServiceProtocol = Depends(get_wechat_login_service),
) -> StreamingResponse:
    try:
        content, media_type = await service.get_qr_code_image(owner_id, attempt_id)
    except WeChatError as exc:
        _handle_wechat_error(exc)
    return StreamingResponse(
        iter([content]),
        media_type=media_type,
        headers={"Cache-Control": "no-store"},
    )


@router.get("/login-sessions/{attempt_id}/status", response_model=WeChatLoginAttemptResponse)
async def get_wechat_login_status(
    attempt_id: UUID,
    owner_id: int = Depends(_owner_id),
    service: WeChatLoginServiceProtocol = Depends(get_wechat_login_service),
) -> dict[str, Any]:
    try:
        result = await service.get_login_status(owner_id, attempt_id)
    except WeChatError as exc:
        _handle_wechat_error(exc)
    return {
        "attempt_id": attempt_id,
        "status": result["status"],
        "expires_at": None,
        "error_code": result.get("reason"),
    }


@router.post("/login-sessions/{attempt_id}/complete", response_model=WeChatSessionResponse)
async def complete_wechat_login(
    attempt_id: UUID,
    owner_id: int = Depends(_owner_id),
    service: WeChatLoginServiceProtocol = Depends(get_wechat_login_service),
) -> dict[str, Any]:
    try:
        return await service.complete_login(owner_id, attempt_id)
    except WeChatError as exc:
        _handle_wechat_error(exc)


@router.delete("/login-sessions/{attempt_id}")
async def cancel_wechat_login(
    attempt_id: UUID,
    owner_id: int = Depends(_owner_id),
    service: WeChatLoginServiceProtocol = Depends(get_wechat_login_service),
) -> dict[str, Any]:
    deleted = await service.cancel_login_attempt(owner_id, attempt_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=WeChatErrorResponse(
                code="WECHAT_LOGIN_FAILED", message="登录尝试不存在"
            ).model_dump(),
        )
    return {"status": "cancelled", "attempt_id": str(attempt_id)}


@router.get("/session", response_model=WeChatSessionResponse)
async def get_wechat_session(
    owner_id: int = Depends(_owner_id),
    service: WeChatLoginServiceProtocol = Depends(get_wechat_login_service),
) -> dict[str, Any]:
    return await service.get_session_summary(owner_id)


@router.get("/accounts/search", response_model=WeChatOfficialAccountListResponse)
async def search_wechat_accounts(
    q: str = Query(..., min_length=1, max_length=255),
    begin: int = Query(0, ge=0),
    size: int = Query(5, ge=1, le=20),
    owner_id: int = Depends(_owner_id),
    service: WeChatAccountServiceProtocol = Depends(get_wechat_account_service),
) -> dict[str, Any]:
    try:
        items, total = await service.search_accounts(owner_id, q, begin=begin, size=size)
    except WeChatError as exc:
        _handle_wechat_error(exc)
    return {
        "items": items,
        "total": total,
        "begin": begin,
        "size": size,
    }


@router.get("/accounts", response_model=WeChatOfficialAccountListResponse)
async def list_wechat_accounts(
    owner_id: int = Depends(_owner_id),
    service: WeChatAccountServiceProtocol = Depends(get_wechat_account_service),
) -> dict[str, Any]:
    items = await service.list_accounts(owner_id)
    return {"items": items, "total": len(items), "begin": 0, "size": len(items)}


@router.post("/accounts", response_model=WeChatOfficialAccountResponse)
async def save_wechat_account(
    request: WeChatAccountSaveRequest,
    owner_id: int = Depends(_owner_id),
    service: WeChatAccountServiceProtocol = Depends(get_wechat_account_service),
) -> dict[str, Any]:
    try:
        return await service.save_account(owner_id, request.model_dump())
    except WeChatError as exc:
        _handle_wechat_error(exc)


@router.get("/accounts/{account_id}/articles", response_model=WeChatArticleListResponse)
async def list_wechat_account_articles(
    account_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    owner_id: int = Depends(_owner_id),
    account_repository: WeChatOfficialAccountRepository = Depends(
        get_wechat_account_repository
    ),
    article_repository: WeChatArticleRepository = Depends(get_wechat_article_repository),
) -> dict[str, Any]:
    account = account_repository.get_wechat_account(owner_id, account_id)
    if account is None:
        _handle_wechat_error(WeChatError("WECHAT_ACCOUNT_NOT_FOUND", "公众号不存在"))
    articles = article_repository.list_wechat_articles(
        owner_id, account_id, offset=offset, limit=limit
    )
    total = article_repository.count_wechat_articles(owner_id, account_id)
    return {"items": articles, "total": total, "offset": offset, "limit": limit}


@router.post("/accounts/{account_id}/sync", response_model=WeChatSyncSubmitResponse)
async def sync_wechat_account(
    account_id: int,
    owner_id: int = Depends(_owner_id),
    service: WeChatSyncServiceProtocol = Depends(get_wechat_sync_service),
) -> dict[str, Any]:
    try:
        return await service.submit_sync(owner_id, account_id)
    except WeChatError as exc:
        _handle_wechat_error(exc)


@router.get("/catalog", response_model=WeChatCatalogListResponse)
async def list_wechat_catalog(
    user_id: int = Depends(_user_id),
    service: WeChatFollowServiceProtocol = Depends(get_wechat_follow_service),
) -> dict[str, Any]:
    items = service.list_catalog(user_id)
    return {"items": items, "total": len(items)}


@router.post(
    "/accounts/{account_id}/follow", response_model=WeChatFollowStateResponse
)
async def follow_wechat_account(
    account_id: int,
    user_id: int = Depends(_user_id),
    service: WeChatFollowServiceProtocol = Depends(get_wechat_follow_service),
) -> dict[str, Any]:
    try:
        return service.follow(user_id, account_id)
    except WeChatError as exc:
        _handle_wechat_error(exc)


@router.delete(
    "/accounts/{account_id}/follow", response_model=WeChatFollowStateResponse
)
async def unfollow_wechat_account(
    account_id: int,
    user_id: int = Depends(_user_id),
    service: WeChatFollowServiceProtocol = Depends(get_wechat_follow_service),
) -> dict[str, Any]:
    return service.unfollow(user_id, account_id)


@router.get("/feed", response_model=WeChatFeedResponse)
async def get_wechat_feed(
    per_account: int = Query(5, ge=1, le=10),
    user_id: int = Depends(_user_id),
    service: WeChatFollowServiceProtocol = Depends(get_wechat_follow_service),
) -> dict[str, Any]:
    items = service.get_feed(user_id, per_account=per_account)
    return {"items": items, "per_account": per_account}


@router.get(
    "/accounts/{account_id}/articles/{article_id}",
    response_model=WeChatArticleDetailResponse,
)
async def get_wechat_article_detail(
    account_id: int,
    article_id: int,
    owner_id: int = Depends(_owner_id),
    service: WeChatFollowServiceProtocol = Depends(get_wechat_follow_service),
) -> dict[str, Any]:
    """Admin-only full text for the operator's own reading.

    普通用户展示层只提供摘要 + 原文链接（feed/catalog），全文不对外公开：
    公众号文章著作权归原作者，全文面向全部注册用户传播构成信息网络传播
    风险，故详情收敛为管理员自用（参照 we-mp-rss 自部署自用形态）。
    """
    try:
        return service.get_article_detail(owner_id, account_id, article_id)
    except WeChatError as exc:
        _handle_wechat_error(exc)
