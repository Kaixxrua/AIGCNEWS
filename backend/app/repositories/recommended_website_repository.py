from __future__ import annotations

from typing import Any, Protocol


class DuplicateRecommendedWebsiteError(Exception):
    pass


class RecommendedWebsiteRepository(Protocol):
    def list_websites(self) -> list[dict[str, Any]]: ...

    def create_website(
        self, *, title: str, url: str, description: str, category: str, sort_order: int, icon_url: str = "",
    ) -> dict[str, Any]: ...

    def update_website(
        self, website_id: int, *, title: str, url: str, description: str, category: str, sort_order: int,
        icon_url: str = "",
    ) -> dict[str, Any] | None: ...

    def delete_website(self, website_id: int) -> bool: ...
