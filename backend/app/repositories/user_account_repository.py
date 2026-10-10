from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


class UserAccountReader(Protocol):
    """Read internal account rows, which may contain password hashes."""

    def get_user_by_id(self, user_id: int) -> dict[str, Any] | None: ...

    def get_user_avatar(self, *, user_id: int, digest: str) -> bytes | None: ...

    def get_user_by_phone(self, phone: str) -> dict[str, Any] | None: ...

    def get_user_by_email(self, email: str) -> dict[str, Any] | None: ...

    def get_onboarding_status(self, *, user_id: int) -> str | None: ...


class UserAccountWriter(Protocol):
    """Create accounts and update already-hashed passwords."""

    def save_onboarding_status(self, *, user_id: int, status: str) -> str | None: ...

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

    def enable_password_login(
        self, *, user_id: int, current_email: str | None, pwd_ver: int,
        email: str, hashed_password: str,
    ) -> dict[str, Any] | None:
        """Set the first password under an email/version snapshot; never merge users."""
        ...

    def update_user_avatar(self, *, user_id: int, png: bytes, digest: str) -> int: ...

    def set_initial_user_avatar(self, *, user_id: int, png: bytes, digest: str) -> int: ...

    def update_user_username(
        self,
        *,
        user_id: int,
        username: str,
    ) -> int:
        """Atomically enforce 72 hours between changes; unchanged names keep the
        deadline. Return 0 for a cooldown, missing user or disabled account."""
        ...

    def update_user_email(
        self,
        *,
        user_id: int,
        current_email: str,
        new_email: str,
    ) -> int:
        """Rebind the login email under a (user_id, current_email) snapshot;
        returns affected row count (0 = snapshot mismatch or user missing)."""
        ...

    def set_membership_tier(
        self,
        *,
        user_id: int,
        tier: str,
        expires_at: datetime | None = None,
    ) -> int:
        """Update the membership tier and expiry (None = permanent); returns affected row count (0 = user missing)."""
        ...

    def create_user_with_email(
        self,
        email: str,
        hashed_password: str,
        role: str = "user",
        username: str = "",
    ) -> int: ...


class UserStatisticsReader(Protocol):
    """Read aggregate user-account statistics."""

    def get_user_count(self) -> int: ...

    def get_today_registered_user_count(self) -> int: ...

    def get_effective_member_count(self) -> int:
        """Count users whose effective tier is member (member tier, not expired)."""
        ...


class UserAccountAdminReader(Protocol):
    """Read paginated user rows for admin/membership operations."""

    def list_users(
        self,
        *,
        query: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """Paginated user rows newest-first with optional fuzzy match on
        email/phone/username; returns (rows, total). Rows carry membership
        tier/expiry columns but no password hashes."""
        ...


class UserAccountRepository(
    UserAccountReader,
    UserAccountWriter,
    UserStatisticsReader,
    UserAccountAdminReader,
    Protocol,
):
    """Combined internal account persistence boundary."""
