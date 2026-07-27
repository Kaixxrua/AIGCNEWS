"""Redis-backed email OTP state boundary."""

from __future__ import annotations

import hmac
from typing import Literal

OtpPurpose = Literal["registration", "password_reset"]

OTP_CODE_PREFIX = "email:code:"
OTP_LOCK_PREFIX = "email:lock:"
RESET_CODE_PREFIX = "email:reset:code:"
RESET_LOCK_PREFIX = "email:reset:lock:"
RESET_ATTEMPTS_PREFIX = "email:reset:attempts:"
OTP_TTL = 300
LOCK_TTL = 60
RESET_MAX_ATTEMPTS = 5


class OtpStoreUnavailableError(RuntimeError):
    """Raised when OTP state cannot be persisted."""


class OtpCooldownError(RuntimeError):
    """Raised when an OTP lock is already present."""


def otp_keys(email: str, purpose: OtpPurpose) -> tuple[str, str, str | None]:
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
        None,
    )


class RedisOtpStore:
    """Preserve the legacy non-atomic Redis OTP lifecycle."""

    def __init__(self, redis_client) -> None:
        self._redis = redis_client

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
        if attempts_key is not None:
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
        if hmac.compare_digest(stored_str, code):
            if consume:
                await self.consume(email, purpose=purpose)
            return True

        if attempts_key is not None:
            attempts = await self._redis.incr(attempts_key)
            if attempts == 1:
                await self._redis.expire(attempts_key, OTP_TTL)
            if attempts >= RESET_MAX_ATTEMPTS:
                await self._redis.delete(code_key, attempts_key)
        return False

    async def consume(self, email: str, *, purpose: OtpPurpose) -> None:
        if not self.available:
            return
        code_key, _lock_key, attempts_key = otp_keys(email, purpose)
        keys = [code_key]
        if attempts_key is not None:
            keys.append(attempts_key)
        await self._redis.delete(*keys)
