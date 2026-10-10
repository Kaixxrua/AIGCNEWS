from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from backend.app.monitoring import live_stats_broadcaster

REGISTRATION_PURPOSE = "registration"
PASSWORD_RESET_PURPOSE = "password_reset"
PASSWORD_CHANGE_PURPOSE = "password_change"
PASSWORD_SETUP_PURPOSE = "password_setup"
EMAIL_CHANGE_PURPOSE = "email_change"


class AccountRepository(Protocol):
    """Persistence operations required by account lifecycle coordination."""

    def get_user_by_id(self, user_id: int) -> Mapping[str, Any] | None: ...

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

    def enable_password_login(
        self, *, user_id: int, current_email: str | None, pwd_ver: int,
        email: str, hashed_password: str,
    ) -> Mapping[str, Any] | None: ...

    def update_user_username(
        self,
        *,
        user_id: int,
        username: str,
    ) -> int: ...

    def update_user_email(
        self,
        *,
        user_id: int,
        current_email: str,
        new_email: str,
    ) -> int:
        """Atomically rebind the login email; returns affected row count.

        实现方必须以 (user_id, current_email) 快照为更新条件（current_email
        不匹配时返回 0），并将 email_verified 置真——新邮箱已通过 OTP 证明
        收件控制。邮箱唯一性冲突由 users.email 的唯一约束兜底抛给调用层。
        """
        ...


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


class PasswordSetupUnavailable(AccountLifecycleError):
    """First-password setup is unavailable or the account snapshot changed."""


class ProfileUpdateFailed(AccountLifecycleError):
    """Profile persistence did not update exactly one account."""


class UsernameChangeCooldown(AccountLifecycleError):
    def __init__(self, available_at: datetime) -> None:
        self.available_at = available_at
        super().__init__("Username change is on cooldown")


class EmailChangeUnavailable(AccountLifecycleError):
    """The account has no current email to verify against."""


class EmailChangeSameEmail(AccountLifecycleError):
    """The new email is identical to the current email."""


class EmailAlreadyInUse(AccountLifecycleError):
    """The new email is owned by another account."""


class EmailChangeFailed(AccountLifecycleError):
    """Email rebind persistence did not update exactly one account."""


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
    access_token: str
    token_type: str = "bearer"
    changed: bool = True


@dataclass(frozen=True, slots=True)
class EmailChangeResult:
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
        username: str,
    ) -> RegistrationResult:
        normalized_email = _normalize_email_domain(email)
        # 防御性裁剪：路由层已 422 拦截空值/超长，这里统一 trim 保持仓储入参干净
        normalized_username = username.strip()
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
            normalized_username,
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

    async def update_username(
        self,
        *,
        user_id: int,
        username: str,
    ) -> None:
        affected_rows = await asyncio.to_thread(
            self._repository.update_user_username,
            user_id=int(user_id),
            username=username.strip(),
        )
        if affected_rows != 1:
            user = await asyncio.to_thread(self._repository.get_user_by_id, int(user_id))
            available_at = user.get("username_change_available_at") if user else None
            if user and not user.get("disabled") and isinstance(available_at, datetime):
                raise UsernameChangeCooldown(available_at)
            raise ProfileUpdateFailed

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
        user_id: int,
    ) -> ResetOtpRequestResult:
        """向已认证账号的数据库当前邮箱发码，不信任 JWT 中的 email。"""
        user = await asyncio.to_thread(self._repository.get_user_by_id, int(user_id))
        email = _normalize_email_domain(str(user.get("email") or "")) if user else ""
        if not email:
            raise InvalidCredentials
        await self._otp.send_otp(
            email,
            purpose=PASSWORD_CHANGE_PURPOSE,
            deliver=True,
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
        user_id: int,
        email_code: str,
        new_password: str,
    ) -> PasswordChangeResult:
        """已登录用户凭邮箱验证码改密（验证码替代当前密码校验）。

        已确认产品决策：强制邮箱验证码，不保留免 SMTP 的旧口令回退路径。
        与 reset_password 同构：先验码（consume=False）→ 更新 → 消耗。
        """
        user = await asyncio.to_thread(self._repository.get_user_by_id, int(user_id))
        normalized_email = (
            _normalize_email_domain(str(user.get("email") or "")) if user else ""
        )
        if not normalized_email:
            raise InvalidCredentials
        verified = await self._otp.verify_otp(
            normalized_email,
            email_code,
            consume=False,
            purpose=PASSWORD_CHANGE_PURPOSE,
        )
        if not verified:
            raise InvalidOtp

        hashed_password = self._hash_password(new_password)
        affected_rows = await asyncio.to_thread(
            self._repository.update_user_password,
            user_id=int(user_id),
            email=normalized_email,
            hashed_password=hashed_password,
        )
        if affected_rows != 1:
            raise PasswordChangeFailed

        latest_user = await asyncio.to_thread(
            self._repository.get_user_by_id, int(user_id)
        )
        if latest_user is None:
            raise PasswordChangeFailed
        access_token = self._issue_token(
            {
                "user_id": latest_user["id"],
                "role": latest_user["role"],
                "email": latest_user.get("email"),
                "pwd_ver": int(latest_user.get("pwd_ver") or 1),
            }
        )
        await self._otp.consume_otp(
            normalized_email, purpose=PASSWORD_CHANGE_PURPOSE
        )
        return PasswordChangeResult(access_token=access_token)

    async def _password_setup_account(self, *, user_id: int, email: str) -> Mapping[str, Any]:
        user = await asyncio.to_thread(self._repository.get_user_by_id, int(user_id))
        if (
            user is None or user.get("disabled")
            or user.get("password_login_enabled") is not False
            or (user.get("email") and str(user["email"]).lower() != email.lower())
        ):
            raise PasswordSetupUnavailable
        return user

    async def request_password_setup_otp(self, *, user_id: int, email: str) -> None:
        await self._password_setup_account(user_id=user_id, email=email)
        # Do not disclose another account's email ownership before verification.
        await self._otp.send_otp(email.lower(), purpose=PASSWORD_SETUP_PURPOSE, deliver=True)

    async def setup_password(
        self, *, user_id: int, email: str, email_code: str, new_password: str,
    ) -> PasswordChangeResult:
        email = email.lower()
        user = await self._password_setup_account(user_id=user_id, email=email)
        if not await self._otp.verify_otp(
            email, email_code, consume=False, purpose=PASSWORD_SETUP_PURPOSE,
        ):
            raise InvalidOtp
        owner = await asyncio.to_thread(self._repository.get_user_by_email, email)
        if owner is not None and int(owner["id"]) != int(user_id):
            raise EmailAlreadyInUse
        updated = await asyncio.to_thread(
            self._repository.enable_password_login,
            user_id=int(user_id), current_email=user.get("email"),
            pwd_ver=int(user.get("pwd_ver") or 1), email=email,
            hashed_password=self._hash_password(new_password),
        )
        if updated is None:
            raise PasswordSetupUnavailable
        await self._otp.consume_otp(email, purpose=PASSWORD_SETUP_PURPOSE)
        return PasswordChangeResult(access_token=self._issue_token({
            "user_id": updated["id"], "email": updated["email"],
            "role": updated["role"], "pwd_ver": updated["pwd_ver"],
        }))

    async def _current_email_for_change(
        self,
        *,
        user_id: int,
    ) -> tuple[Mapping[str, Any], str]:
        """读取数据库当前邮箱；无邮箱账号（如纯 OAuth）本单元不支持换绑。"""
        user = await asyncio.to_thread(self._repository.get_user_by_id, int(user_id))
        current_email = (
            _normalize_email_domain(str(user.get("email") or "")) if user else ""
        )
        if user is None or not current_email:
            raise EmailChangeUnavailable
        return user, current_email

    async def request_email_change_current_otp(
        self,
        *,
        user_id: int,
    ) -> ResetOtpRequestResult:
        """向数据库当前邮箱发换绑验证码（不信任 JWT email 声明）。"""
        _user, current_email = await self._current_email_for_change(user_id=user_id)
        await self._otp.send_otp(
            current_email,
            purpose=EMAIL_CHANGE_PURPOSE,
            deliver=True,
        )
        return ResetOtpRequestResult()

    async def request_email_change_new_otp(
        self,
        *,
        user_id: int,
        new_email: str,
    ) -> ResetOtpRequestResult:
        """向新邮箱发换绑验证码。

        与注册/重置一致地始终投递：不在发送阶段检查归属，避免把
        “邮箱是否已注册”变成可探测的应答差分；归属冲突在 confirm 统一裁决。
        """
        _user, current_email = await self._current_email_for_change(user_id=user_id)
        normalized_new = _normalize_email_domain(new_email.strip()).lower()
        if normalized_new == current_email.lower():
            raise EmailChangeSameEmail
        await self._otp.send_otp(
            normalized_new,
            purpose=EMAIL_CHANGE_PURPOSE,
            deliver=True,
        )
        return ResetOtpRequestResult()

    async def change_email(
        self,
        *,
        user_id: int,
        new_email: str,
        current_code: str,
        new_code: str,
    ) -> EmailChangeResult:
        """双验证码换绑登录邮箱：当前邮箱 + 新邮箱均须各自验真。

        顺序约束（与 change_password 同构）：先验双码（consume=False，避免
        验码消耗后归属冲突导致用户卡死）→ 归属预检 → 快照条件原子更新 →
        仅更新成功后消耗两枚验证码。不做 token 轮换：RequireUser 只校验
        disabled/role/pwd_ver，JWT email 声明仅为展示信息，DB 投影权威。
        """
        _user, current_email = await self._current_email_for_change(user_id=user_id)
        normalized_new = _normalize_email_domain(new_email.strip()).lower()
        if normalized_new == current_email.lower():
            raise EmailChangeSameEmail

        current_verified = await self._otp.verify_otp(
            current_email,
            current_code,
            consume=False,
            purpose=EMAIL_CHANGE_PURPOSE,
        )
        if not current_verified:
            raise InvalidOtp
        new_verified = await self._otp.verify_otp(
            normalized_new,
            new_code,
            consume=False,
            purpose=EMAIL_CHANGE_PURPOSE,
        )
        if not new_verified:
            raise InvalidOtp

        owner = await asyncio.to_thread(
            self._repository.get_user_by_email, normalized_new
        )
        if owner is not None and int(owner["id"]) != int(user_id):
            raise EmailAlreadyInUse

        affected_rows = await asyncio.to_thread(
            self._repository.update_user_email,
            user_id=int(user_id),
            current_email=current_email,
            new_email=normalized_new,
        )
        if affected_rows != 1:
            raise EmailChangeFailed

        await self._otp.consume_otp(current_email, purpose=EMAIL_CHANGE_PURPOSE)
        await self._otp.consume_otp(normalized_new, purpose=EMAIL_CHANGE_PURPOSE)
        return EmailChangeResult()
