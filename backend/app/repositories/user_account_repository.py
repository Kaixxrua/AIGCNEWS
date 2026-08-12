from __future__ import annotations

from typing import Any, Protocol


class UserAccountReader(Protocol):
    """Read internal account rows, which may contain password hashes."""

    def get_user_by_id(self, user_id: int) -> dict[str, Any] | None: ...

    def get_user_by_phone(self, phone: str) -> dict[str, Any] | None: ...

    def get_user_by_email(self, email: str) -> dict[str, Any] | None: ...


class UserAccountWriter(Protocol):
    """Create accounts and update already-hashed passwords."""

    def create_user(
        self,
        phone: str,
        username: str,
        hashed_password: str,
        role: str = "user",
    ) -> int: ...

    def update_user_password(
        self,
        *,
        user_id: int,
        email: str,
        hashed_password: str,
    ) -> int: ...

    def create_user_with_email(
        self,
        email: str,
        hashed_password: str,
        role: str = "user",
        username: str = "",
        *,
        promote_if_first: bool = False,
    ) -> int: ...


class UserStatisticsReader(Protocol):
    """Read aggregate user-account statistics."""

    def get_user_count(self) -> int: ...

    def get_today_registered_user_count(self) -> int: ...


class UserAccountRepository(
    UserAccountReader,
    UserAccountWriter,
    UserStatisticsReader,
    Protocol,
):
    """Combined internal account persistence boundary."""
