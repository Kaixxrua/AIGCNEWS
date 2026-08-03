"""Redis-backed email OTP state boundary."""

from __future__ import annotations

import hmac
from collections.abc import Callable
from typing import Literal

OtpPurpose = Literal["registration", "password_reset"]

OTP_CODE_PREFIX = "email:code:"
OTP_LOCK_PREFIX = "email:lock:"
OTP_ATTEMPTS_PREFIX = "email:attempts:"
RESET_CODE_PREFIX = "email:reset:code:"
RESET_LOCK_PREFIX = "email:reset:lock:"
RESET_ATTEMPTS_PREFIX = "email:reset:attempts:"
OTP_TTL = 300
LOCK_TTL = 60
MAX_ATTEMPTS = 5


class OtpStoreUnavailableError(RuntimeError):
    """Raised when OTP state cannot be persisted."""


class OtpCooldownError(RuntimeError):
    """Raised when an OTP lock is already present."""


def otp_keys(email: str, purpose: OtpPurpose) -> tuple[str, str, str]:
    """返回 (code_key, lock_key, attempts_key)；两种用途都必须有尝试计数键。

    历史上 registration 的 attempts_key 为 None（无限次尝试），6 位验证码
    在 5 分钟 TTL 内可被穷举，因此两种用途统一为 MAX_ATTEMPTS 次上限。
    """
    email_lower = email.lower()
    if purpose == "password_reset":
        return (
            f"{RESET_CODE_PREFIX}{email_lower}",
            f"{RESET_LOCK_PREFIX}{email_lower}",
            f"{RESET_ATTEMPTS_PREFIX}{email_lower}",
        )
    return (
        f"{OTP_CODE_PREFIX}{email_lower}",
        f"{OTP_LOCK_PREFIX}{email_lower}",
        f"{OTP_ATTEMPTS_PREFIX}{email_lower}",
    )


class RedisOtpStore:
    """Preserve the legacy non-atomic Redis OTP lifecycle."""

    def __init__(
        self,
        redis_client,
        *,
        compare_digest: Callable[[str, str], bool] = hmac.compare_digest,
    ) -> None:
        self._redis = redis_client
        self._compare_digest = compare_digest

    @property
    def available(self) -> bool:
        return self._redis is not None

    async def store(self, email: str, code: str, *, purpose: OtpPurpose) -> None:
        if not self.available:
            raise OtpStoreUnavailableError

        code_key, lock_key, attempts_key = otp_keys(email, purpose)
        # Deliberately preserve the existing non-atomic GET then SET cooldown.
        if await self._redis.get(lock_key) is not None:
            raise OtpCooldownError

        await self._redis.set(code_key, code, ex=OTP_TTL)
        await self._redis.set(lock_key, "1", ex=LOCK_TTL)
        await self._redis.delete(attempts_key)

    async def verify(
        self,
        email: str,
        code: str,
        *,
        purpose: OtpPurpose,
        consume: bool,
    ) -> bool:
        if not self.available:
            return False

        code_key, _lock_key, attempts_key = otp_keys(email, purpose)
        stored = await self._redis.get(code_key)
        if stored is None:
            return False

        stored_str = stored.decode("utf-8") if isinstance(stored, bytes) else str(stored)
        if self._compare_digest(stored_str, code):
            if consume:
                await self.consume(email, purpose=purpose)
            return True

        attempts = await self._redis.incr(attempts_key)
        if attempts == 1:
            await self._redis.expire(attempts_key, OTP_TTL)
        if attempts >= MAX_ATTEMPTS:
            await self._redis.delete(code_key, attempts_key)
        return False

    async def consume(self, email: str, *, purpose: OtpPurpose) -> None:
        if not self.available:
            return
        code_key, _lock_key, attempts_key = otp_keys(email, purpose)
        await self._redis.delete(code_key, attempts_key)
