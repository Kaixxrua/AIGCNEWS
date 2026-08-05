from __future__ import annotations

from typing import Any, Protocol


class WeChatOfficialAccountRepository(Protocol):
    """Persistence boundary for official accounts selected by one owner."""

    def list_wechat_accounts(self, owner_id: int) -> list[dict[str, Any]]: ...

    def get_wechat_account(
        self,
        owner_id: int,
        account_id: int,
    ) -> dict[str, Any] | None: ...

    def upsert_wechat_account(
        self,
        owner_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...

    def update_wechat_account_sync_result(
        self,
        owner_id: int,
        account_id: int,
        result: dict[str, Any],
    ) -> dict[str, Any] | None: ...

    def delete_wechat_account(self, owner_id: int, account_id: int) -> bool: ...
