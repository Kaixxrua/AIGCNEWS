from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class OAuthLoginResolution:
    status: str
    user: dict[str, Any] | None = None


class OAuthIdentityRepository(Protocol):
    """Persistence boundary for stable external OAuth identities."""

    def resolve_first_login(
        self,
        *,
        provider: str,
        provider_subject: str,
        display_email: str | None = None,
        email_verified: bool = False,
        username: str = "",
    ) -> OAuthLoginResolution: ...

    def get_by_provider_subject(
        self, provider: str, provider_subject: str
    ) -> dict[str, Any] | None: ...

    def get_by_verified_email(self, email: str) -> dict[str, Any] | None: ...

    def create_oauth_only_user(
        self,
        *,
        provider: str,
        provider_subject: str,
        display_email: str | None = None,
        email_verified: bool = False,
        username: str = "",
    ) -> dict[str, Any]: ...

    def bind_identity(
        self,
        *,
        user_id: int,
        provider: str,
        provider_subject: str,
        display_email: str | None = None,
        email_verified: bool = False,
    ) -> bool: ...
