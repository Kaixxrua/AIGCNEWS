"""Provider-neutral OAuth adapter contracts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, Protocol

OAuthProviderName = Literal["github", "google", "wechat"]
OAUTH_PROVIDERS: Final[tuple[OAuthProviderName, ...]] = ("github", "google", "wechat")


@dataclass(frozen=True, slots=True)
class OAuthProviderConfig:
    """Non-secret provider configuration required before exposing an OAuth button."""

    name: OAuthProviderName
    client_id: str
    client_secret: str

    @property
    def configured(self) -> bool:
        secret = self.client_secret.strip()
        return bool(self.client_id.strip() and secret and not secret.upper().startswith("CHANGEME"))


@dataclass(frozen=True, slots=True)
class OAuthProfile:
    provider_subject: str
    email: str | None = None
    email_verified: bool = False
    username: str = ""
    display_name: str = ""
    avatar_url: str = ""


class OAuthProviderAdapter(Protocol):
    """The deliberately small boundary implemented by provider adapters."""

    use_pkce: bool
    use_nonce: bool

    def authorization_url(
        self,
        *,
        state: str,
        redirect_uri: str,
        code_challenge: str | None = None,
        nonce: str | None = None,
    ) -> str: ...

    async def exchange_code(
        self,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: str | None = None,
        nonce: str | None = None,
    ) -> OAuthProfile: ...


class OAuthAdapterUnavailable(RuntimeError):
    pass


class UnavailableOAuthAdapter:
    use_pkce = False
    use_nonce = False

    def authorization_url(self, **kwargs: object) -> str:
        raise OAuthAdapterUnavailable

    async def exchange_code(self, **kwargs: object) -> OAuthProfile:
        raise OAuthAdapterUnavailable


def parse_enabled_oauth_providers(raw: str | None) -> tuple[OAuthProviderName, ...]:
    """Parse the allowlist while dropping unknown names and preserving registry order."""
    requested = {item.strip().lower() for item in (raw or "").split(",") if item.strip()}
    return tuple(provider for provider in OAUTH_PROVIDERS if provider in requested)
