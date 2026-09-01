from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol


@dataclass(frozen=True, slots=True)
class OAuthLoginResolution:
    status: str
    user: dict[str, Any] | None = None


# bind_identity 的结构化结果：
# - bound：本次写入建立了新绑定；
# - already_bound：该外部身份早已属于同一用户（幂等成功，不是错误）；
# - owned_by_other：该外部身份属于其他账户，必须拒绝且绝不转移。
OAuthBindStatus = Literal["bound", "already_bound", "owned_by_other"]


@dataclass(frozen=True, slots=True)
class OAuthBindResult:
    status: OAuthBindStatus


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

    def list_identities_for_user(
        self,
        user_id: int,
    ) -> list[dict[str, Any]]: ...

    def bind_identity(
        self,
        *,
        user_id: int,
        provider: str,
        provider_subject: str,
        display_email: str | None = None,
        email_verified: bool = False,
    ) -> OAuthBindResult: ...
