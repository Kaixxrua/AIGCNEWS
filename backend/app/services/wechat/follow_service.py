from __future__ import annotations

from typing import Any

from backend.app.repositories.postgres_wechat_follow_repository import (
    WeChatFollowAccountNotFoundError,
)
from backend.app.repositories.wechat_article_repository import WeChatArticleRepository
from backend.app.repositories.wechat_follow_repository import WeChatFollowRepository
from backend.app.services.wechat.errors import WeChatAccountNotFound


def _catalog_account_payload(account: dict[str, Any]) -> dict[str, Any]:
    """Project a catalog row down to the user-facing display fields."""
    return {
        "id": int(account["id"]),
        "nickname": account.get("nickname") or "",
        "alias": account.get("alias") or "",
        "avatar_url": account.get("avatar_url") or "",
        "signature": account.get("signature") or "",
        "sort_order": int(account.get("sort_order") or 0),
        "followed": bool(account.get("followed")),
    }


class WeChatFollowService:
    """User-facing catalog browsing and per-user follows.

    Invariant: the catalog is every enabled row of wechat_official_accounts.
    Accounts are only written through the admin-owned endpoints, so the enabled
    set is exactly the admin-curated platform surface; `enabled` stays the
    admin's kill switch and hides accounts from catalog, feed, and follows.
    """

    def __init__(
        self,
        follow_repository: WeChatFollowRepository,
        article_repository: WeChatArticleRepository,
    ) -> None:
        self._follows = follow_repository
        self._articles = article_repository

    def list_catalog(self, user_id: int) -> list[dict[str, Any]]:
        rows = self._follows.list_catalog_with_follow_state(user_id)
        return [_catalog_account_payload(row) for row in rows]

    def follow(self, user_id: int, account_id: int) -> dict[str, Any]:
        if self._follows.get_enabled_catalog_account(account_id) is None:
            raise WeChatAccountNotFound()
        try:
            self._follows.follow_account(user_id, account_id)
        except WeChatFollowAccountNotFoundError as exc:
            raise WeChatAccountNotFound() from exc
        return {"account_id": account_id, "followed": True}

    def unfollow(self, user_id: int, account_id: int) -> dict[str, Any]:
        self._follows.unfollow_account(user_id, account_id)
        return {"account_id": account_id, "followed": False}

    def get_feed(self, user_id: int, *, per_account: int = 5) -> list[dict[str, Any]]:
        followed_ids = self._follows.list_followed_account_ids(user_id)
        if not followed_ids:
            return []
        articles_by_account = self._articles.list_recent_articles_for_accounts(
            followed_ids,
            per_account=per_account,
        )
        feed = []
        for row in self._follows.list_catalog_with_follow_state(user_id):
            if int(row["id"]) not in articles_by_account or not row.get("followed"):
                continue
            feed.append(
                {
                    "account": _catalog_account_payload(row),
                    "articles": articles_by_account[int(row["id"])],
                }
            )
        return feed

    def get_article_detail(
        self,
        user_id: int,
        account_id: int,
        article_id: int,
    ) -> dict[str, Any]:
        """Return one article's full body, gated by the follow boundary.

        Full text is a follower-facing surface, matching the feed: the user
        must follow the account, otherwise 404 (no existence leak).
        """
        followed_ids = self._follows.list_followed_account_ids(user_id)
        if account_id not in followed_ids:
            raise WeChatAccountNotFound()
        article = self._articles.get_wechat_article(user_id, account_id, article_id)
        if article is None:
            raise WeChatAccountNotFound()
        return article
