from __future__ import annotations

from typing import Any, Protocol


class XWatchAccountConflictError(Exception):
    """A unique X watch account field conflicts with another row."""


class XWatchAccountSeeder(Protocol):
    """Initialize editable X watch account rows from configured defaults."""

    def _seed_default_x_watch_accounts(self) -> None: ...


class XWatchAccountReader(Protocol):
    """Read X watch account rows for the admin surface."""

    def list_x_watch_accounts(self) -> list[dict[str, Any]]: ...

    def get_x_watch_account(
        self,
        account_id: int,
    ) -> dict[str, Any] | None: ...


class XWatchAccountWriter(Protocol):
    """Create, update, and delete X watch accounts."""

    def create_x_watch_account(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...

    def update_x_watch_account(
        self,
        account_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None: ...

    def delete_x_watch_account(self, account_id: int) -> bool: ...


class XWatchTestResultWriter(Protocol):
    """Persist the latest per-account ingestion probe result."""

    def update_x_watch_test_result(
        self,
        account_id: int,
        result: dict[str, Any],
    ) -> dict[str, Any] | None: ...


class XWatchHandleReader(Protocol):
    """Read enabled X handles for the ingestion crawler watchlist."""

    def list_enabled_x_handles(self) -> list[str]: ...


class XWatchAccountRepository(
    XWatchAccountSeeder,
    XWatchAccountReader,
    XWatchAccountWriter,
    XWatchTestResultWriter,
    XWatchHandleReader,
    Protocol,
):
    """Internal persistence boundary for the X ingestion watchlist."""
