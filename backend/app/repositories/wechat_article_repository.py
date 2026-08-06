from __future__ import annotations

from typing import Any, Protocol


class WeChatArticleRepository(Protocol):
    """Persistence boundary for idempotent WeChat article metadata."""

    def list_wechat_articles(
        self,
        owner_id: int,
        account_id: int,
        *,
        offset: int = 0,
        limit: int = 20,
    ) -> list[dict[str, Any]]: ...

    def get_wechat_article(
        self,
        owner_id: int,
        account_id: int,
        article_id: int,
    ) -> dict[str, Any] | None:
        """Return one article including content_html, or None if missing."""
        ...

    def count_wechat_articles(self, owner_id: int, account_id: int) -> int: ...

    def upsert_wechat_articles(
        self,
        owner_id: int,
        account_id: int,
        articles: list[dict[str, Any]],
    ) -> int: ...

    def list_recent_articles_for_accounts(
        self,
        account_ids: list[int],
        *,
        per_account: int = 5,
    ) -> dict[int, list[dict[str, Any]]]:
        """Return up to `per_account` newest articles for each given account id."""
        ...
