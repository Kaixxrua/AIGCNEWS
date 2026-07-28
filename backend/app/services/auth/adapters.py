from __future__ import annotations

from backend.app.core.auth import (
    create_access_token,
    hash_password,
    verify_password,
)
from backend.app.repositories.user_account_repository import UserAccountRepository
from backend.app.services.auth.account_lifecycle import AccountLifecycle, OtpService


class _UnavailableOtpService:
    def __getattr__(self, name: str):
        raise RuntimeError(f"OTP operation is unavailable: {name}")


def build_account_lifecycle(
    *,
    repository: UserAccountRepository,
    otp: OtpService | None = None,
    password_hasher=hash_password,
    password_verifier=verify_password,
    token_issuer=create_access_token,
) -> AccountLifecycle:
    """Adapt the existing account, OTP, password, and JWT boundaries."""
    return AccountLifecycle(
        repository=repository,
        otp=otp or _UnavailableOtpService(),
        hash_password=password_hasher,
        verify_password=password_verifier,
        issue_token=token_issuer,
    )
