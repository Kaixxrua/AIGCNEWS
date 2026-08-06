from __future__ import annotations

from typing import Any, Protocol


class WeChatFollowRepository(Protocol):
    """Persistence boundary for per-user follows of the platform account catalog.

    The catalog is every enabled row of wechat_official_accounts; accounts are
    only written through the admin-owned endpoints, so the enabled set is the
    curated platform surface visible to all users.
    """

    def list_catalog_with_follow_state(self, user_id: int) -> list[dict[str, Any]]:
        """Return all enabled catalog accounts with a `followed` flag for the user."""
        ...

    def get_enabled_catalog_account(self, account_id: int) -> dict[str, Any] | None:
        """Return the enabled catalog account by id, or None when absent/disabled."""
        ...

    def follow_account(self, user_id: int, account_id: int) -> bool:
        """Insert the follow if missing; True when a new row was created."""
        ...

    def unfollow_account(self, user_id: int, account_id: int) -> bool:
        """Delete the follow if present; True when a row was removed."""
        ...

    def list_followed_account_ids(self, user_id: int) -> list[int]:
        """Return ids of enabled accounts the user follows."""
        ...
