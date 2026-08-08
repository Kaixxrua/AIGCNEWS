from __future__ import annotations

import logging
from typing import Any

from backend.app.repositories.wechat_account_repository import (
    WeChatOfficialAccountRepository,
)
from backend.app.repositories.wechat_session_repository import WeChatSessionRepository
from backend.app.services.wechat.errors import (
    WeChatAccountNotFound,
    WeChatAuthRequired,
    WeChatSessionExpired,
)
from backend.app.services.wechat.parser import parse_search_biz_response
from backend.app.services.wechat.transport import WeChatMpTransport

logger = logging.getLogger(__name__)


def _normalize_account(account: dict[str, Any]) -> dict[str, Any]:
    return {
        "fakeid": str(account.get("fakeid") or "").strip(),
        "nickname": str(account.get("nickname") or "").strip(),
        "alias": str(account.get("alias") or "").strip(),
        "avatar_url": str(account.get("round_head_img") or account.get("avatar_url") or "").strip(),
        "signature": str(account.get("signature") or "").strip(),
    }


class WeChatAccountService:
    """Search and persist WeChat official accounts using the current session."""

    def __init__(
        self,
        account_repository: WeChatOfficialAccountRepository,
        session_repository: WeChatSessionRepository,
        transport: WeChatMpTransport,
    ) -> None:
        self._accounts = account_repository
        self._sessions = session_repository
        self._transport = transport

    def _require_session(self, owner_id: int) -> dict[str, Any]:
        session = self._sessions.get_wechat_session(owner_id)
        if session is None:
            raise WeChatAuthRequired()
        if session.get("status") != "active":
            raise WeChatSessionExpired()
        return session

    async def search_accounts(
        self,
        owner_id: int,
        keyword: str,
        *,
        begin: int = 0,
        size: int = 5,
    ) -> tuple[list[dict[str, Any]], int]:
        session = self._require_session(owner_id)
        try:
            response = await self._transport.search_biz(
                keyword=keyword,
                token=session["token"],
                cookies={
                    item.strip().split("=", 1)[0]: item.strip().split("=", 1)[1]
                    for item in session["cookie"].split(";")
                    if "=" in item
                },
                begin=begin,
                size=size,
            )
            accounts, total = parse_search_biz_response(response.json())
        except WeChatSessionExpired:
            self._sessions.mark_wechat_session_invalid(owner_id, "WECHAT_SESSION_EXPIRED")
            raise
        return [_normalize_account(a) for a in accounts], total

    async def save_account(
        self,
        owner_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._accounts.upsert_wechat_account(owner_id, payload)

    async def list_accounts(self, owner_id: int) -> list[dict[str, Any]]:
        return self._accounts.list_wechat_accounts(owner_id)

    async def get_account(self, owner_id: int, account_id: int) -> dict[str, Any]:
        account = self._accounts.get_wechat_account(owner_id, account_id)
        if account is None:
            raise WeChatAccountNotFound()
        return account

    async def delete_account(self, owner_id: int, account_id: int) -> bool:
        return self._accounts.delete_wechat_account(owner_id, account_id)
