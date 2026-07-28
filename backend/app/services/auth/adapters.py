from __future__ import annotations

from backend.app.core.auth import (
    create_access_token,
    hash_password,
    verify_password,
)
from backend.app.repositories.user_account_repository import UserAccountRepository
from backend.app.services.auth.account_lifecycle import AccountLifecycle, OtpService


def build_account_lifecycle(
    *,
    repository: UserAccountRepository,
    otp: OtpService,
) -> AccountLifecycle:
    """Adapt the existing account, OTP, password, and JWT boundaries."""
    return AccountLifecycle(
        repository=repository,
        otp=otp,
        hash_password=hash_password,
        verify_password=verify_password,
        issue_token=create_access_token,
    )
