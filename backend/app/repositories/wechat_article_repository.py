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

    def count_wechat_articles(self, owner_id: int, account_id: int) -> int: ...

    def upsert_wechat_articles(
        self,
        owner_id: int,
        account_id: int,
        articles: list[dict[str, Any]],
    ) -> int: ...
