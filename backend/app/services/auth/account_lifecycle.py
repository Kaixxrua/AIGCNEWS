from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from backend.app.services.dashboard import live_stats_broadcaster

REGISTRATION_PURPOSE = "registration"
PASSWORD_RESET_PURPOSE = "password_reset"
PASSWORD_CHANGE_PURPOSE = "password_change"


class AccountRepository(Protocol):
    """Persistence operations required by account lifecycle coordination."""

    def get_user_by_email(self, email: str) -> Mapping[str, Any] | None: ...

    def create_user_with_email(
        self,
        email: str,
        hashed_password: str,
        role: str = "user",
        username: str = "",
    ) -> int: ...

    def update_user_password(
        self,
        *,
        user_id: int,
        email: str,
        hashed_password: str,
    ) -> int: ...


class OtpService(Protocol):
    """OTP delivery and one-time verification operations."""

    async def send_otp(
        self,
        email: str,
        *,
        purpose: str = REGISTRATION_PURPOSE,
        deliver: bool = True,
    ) -> None: ...

    async def verify_otp(
        self,
        email: str,
        code: str,
        consume: bool = True,
        *,
        purpose: str = REGISTRATION_PURPOSE,
    ) -> bool: ...

    async def consume_otp(
        self,
        email: str,
        *,
        purpose: str = REGISTRATION_PURPOSE,
    ) -> None: ...


PasswordHasher = Callable[[str], str]
PasswordVerifier = Callable[[str, str], bool]
TokenIssuer = Callable[[dict[str, Any]], str]


class AccountLifecycleError(Exception):
    """Base class for account lifecycle domain failures."""


class InvalidOtp(AccountLifecycleError):
    """The supplied OTP is invalid or cannot identify a reset account."""


class AccountAlreadyExists(AccountLifecycleError):
    """Registration cannot create a second account for the email."""


class InvalidCredentials(AccountLifecycleError):
    """Login credentials do not identify an account."""


class AccountDisabled(AccountLifecycleError):
    """Credentials are valid but the account has been disabled."""


class PasswordResetFailed(AccountLifecycleError):
    """Password persistence did not update exactly one account."""


class PasswordChangeFailed(AccountLifecycleError):
    """Authenticated password change did not update exactly one account."""


@dataclass(frozen=True, slots=True)
class RegistrationResult:
    user_id: int


@dataclass(frozen=True, slots=True)
class ResetOtpRequestResult:
    accepted: bool = True


@dataclass(frozen=True, slots=True)
class PasswordResetResult:
    reset: bool = True


@dataclass(frozen=True, slots=True)
class PasswordChangeResult:
    changed: bool = True


@dataclass(frozen=True, slots=True)
class LoginResult:
    access_token: str
    token_type: str
    role: str


def _normalize_email_domain(email: str) -> str:
    local, separator, domain = email.rpartition("@")
    if not separator:
        return email
    return f"{local}@{domain.lower()}"


class AccountLifecycle:
    """Coordinate inactive account flows without transport-framework concerns."""

    def __init__(
        self,
        *,
        repository: AccountRepository,
        otp: OtpService,
        hash_password: PasswordHasher,
        verify_password: PasswordVerifier,
        issue_token: TokenIssuer,
    ) -> None:
        self._repository = repository
        self._otp = otp
        self._hash_password = hash_password
        self._verify_password = verify_password
        self._issue_token = issue_token

    async def register(
        self,
        *,
        email: str,
        email_code: str,
        password: str,
    ) -> RegistrationResult:
        normalized_email = _normalize_email_domain(email)
        verified = await self._otp.verify_otp(
            normalized_email,
            email_code,
            consume=False,
            purpose=REGISTRATION_PURPOSE,
        )
        if not verified:
            raise InvalidOtp

        existing = await asyncio.to_thread(
            self._repository.get_user_by_email, normalized_email
        )
        if existing is not None:
            raise AccountAlreadyExists

        hashed_password = self._hash_password(password)
        user_id = await asyncio.to_thread(
            self._repository.create_user_with_email,
            normalized_email,
            hashed_password,
            "user",
            "",
        )
        await self._otp.consume_otp(
            normalized_email, purpose=REGISTRATION_PURPOSE
        )
        # 注册成功 → 首页实时计数（registered_users）变更，推送 SSE 订阅者。
        live_stats_broadcaster.notify_live_stats_changed("user-registered")
        return RegistrationResult(user_id=user_id)

    async def login(
        self,
        *,
        email: str,
        password: str,
    ) -> LoginResult:
        normalized_email = _normalize_email_domain(email)
        user = await asyncio.to_thread(
            self._repository.get_user_by_email, normalized_email
        )
        if user is None or not bool(user.get("password_login_enabled", True)):
            raise InvalidCredentials
        if not self._verify_password(password, str(user["hashed_password"])):
            raise InvalidCredentials
        # 密码核验通过后才判定禁用：避免向密码错误的调用方泄露账号禁用状态
        if user.get("disabled"):
            raise AccountDisabled

        role = str(user["role"])
        access_token = self._issue_token(
            {
                "user_id": user["id"],
                "role": user["role"],
                "email": user["email"],
                # 口令版本声明：改密递增库内 pwd_ver 后，本 token 在下一个
                # 请求即被 RequireUser 判定失效（改密即撤销旧会话）
                "pwd_ver": int(user.get("pwd_ver") or 1),
            }
        )
        return LoginResult(
            access_token=access_token,
            token_type="bearer",
            role=role,
        )

    async def request_password_reset_otp(
        self,
        *,
        email: str,
    ) -> ResetOtpRequestResult:
        normalized_email = email.lower()
        user = await asyncio.to_thread(
            self._repository.get_user_by_email, normalized_email
        )
        await self._otp.send_otp(
            normalized_email,
            purpose=PASSWORD_RESET_PURPOSE,
            deliver=user is not None,
        )
        return ResetOtpRequestResult()

    async def request_change_password_otp(
        self,
        *,
        email: str,
    ) -> ResetOtpRequestResult:
        """已登录改密的发码路径：账号已注销（JWT 滞留）时不真实投递。"""
        normalized_email = _normalize_email_domain(email)
        user = await asyncio.to_thread(
            self._repository.get_user_by_email, normalized_email
        )
        await self._otp.send_otp(
            normalized_email,
            purpose=PASSWORD_CHANGE_PURPOSE,
            deliver=user is not None,
        )
        return ResetOtpRequestResult()

    async def reset_password(
        self,
        *,
        email: str,
        email_code: str,
        new_password: str,
    ) -> PasswordResetResult:
        normalized_email = email.lower()
        verified = await self._otp.verify_otp(
            normalized_email,
            email_code,
            consume=False,
            purpose=PASSWORD_RESET_PURPOSE,
        )
        user = await asyncio.to_thread(
            self._repository.get_user_by_email, normalized_email
        )
        if not verified or user is None:
            raise InvalidOtp

        hashed_password = self._hash_password(new_password)
        affected_rows = await asyncio.to_thread(
            self._repository.update_user_password,
            user_id=int(user["id"]),
            email=normalized_email,
            hashed_password=hashed_password,
        )
        if affected_rows != 1:
            raise PasswordResetFailed

        await self._otp.consume_otp(
            normalized_email, purpose=PASSWORD_RESET_PURPOSE
        )
        return PasswordResetResult()

    async def change_password(
        self,
        *,
        email: str,
        email_code: str,
        new_password: str,
    ) -> PasswordChangeResult:
        """已登录用户凭邮箱验证码改密（验证码替代当前密码校验）。

        已确认产品决策：强制邮箱验证码，不保留免 SMTP 的旧口令回退路径。
        与 reset_password 同构：先验码（consume=False）→ 更新 → 消耗。
        """
        normalized_email = _normalize_email_domain(email)
        verified = await self._otp.verify_otp(
            normalized_email,
            email_code,
            consume=False,
            purpose=PASSWORD_CHANGE_PURPOSE,
        )
        user = await asyncio.to_thread(
            self._repository.get_user_by_email, normalized_email
        )
        if not verified or user is None:
            raise InvalidOtp

        hashed_password = self._hash_password(new_password)
        affected_rows = await asyncio.to_thread(
            self._repository.update_user_password,
            user_id=int(user["id"]),
            email=normalized_email,
            hashed_password=hashed_password,
        )
        if affected_rows != 1:
            raise PasswordChangeFailed

        await self._otp.consume_otp(
            normalized_email, purpose=PASSWORD_CHANGE_PURPOSE
        )
        return PasswordChangeResult()
