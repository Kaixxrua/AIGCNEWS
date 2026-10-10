"""Redis-backed email OTP state boundary."""

from __future__ import annotations

import hmac
from collections.abc import Callable
from typing import Literal

OtpPurpose = Literal["registration", "password_reset", "push_channel_verify", "password_change", "password_setup", "email_change"]

OTP_CODE_PREFIX = "email:code:"
OTP_LOCK_PREFIX = "email:lock:"
OTP_ATTEMPTS_PREFIX = "email:attempts:"
RESET_CODE_PREFIX = "email:reset:code:"
RESET_LOCK_PREFIX = "email:reset:lock:"
RESET_ATTEMPTS_PREFIX = "email:reset:attempts:"
PUSH_CODE_PREFIX = "email:push:code:"
PUSH_LOCK_PREFIX = "email:push:lock:"
PUSH_ATTEMPTS_PREFIX = "email:push:attempts:"
CHANGE_CODE_PREFIX = "email:change:code:"
CHANGE_LOCK_PREFIX = "email:change:lock:"
CHANGE_ATTEMPTS_PREFIX = "email:change:attempts:"
# 换绑邮箱专用命名空间：与改密（email:change:*）及其他用途完全隔离；
# 同一 purpose 下按邮箱地址分键，当前邮箱与新邮箱的验证码天然互不覆盖。
EMAIL_CHANGE_CODE_PREFIX = "email:emailchange:code:"
EMAIL_CHANGE_LOCK_PREFIX = "email:emailchange:lock:"
EMAIL_CHANGE_ATTEMPTS_PREFIX = "email:emailchange:attempts:"
OTP_TTL = 300
LOCK_TTL = 60
MAX_ATTEMPTS = 5

# Keep the cooldown and code write indivisible. Attempts survive resends.
_STORE_SCRIPT = """
if redis.call('EXISTS', KEYS[2]) == 1 then return 0 end
redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
redis.call('SET', KEYS[2], '1', 'EX', ARGV[3])
return 1
"""

# Python performs the constant-time comparison; Redis validates that its snapshot
# is still current and atomically claims the code or charges a failed attempt.
_VERIFY_SCRIPT = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
if ARGV[2] == '1' then
    if ARGV[3] == '1' then redis.call('DEL', KEYS[1], KEYS[2]) end
    return 1
end
local attempts = redis.call('INCR', KEYS[2])
if attempts == 1 then redis.call('EXPIRE', KEYS[2], ARGV[4]) end
if attempts >= tonumber(ARGV[5]) then redis.call('DEL', KEYS[1], KEYS[2]) end
return 0
"""


class OtpStoreUnavailableError(RuntimeError):
    """Raised when OTP state cannot be persisted."""


class OtpCooldownError(RuntimeError):
    """Raised when an OTP lock is already present."""


def otp_keys(email: str, purpose: OtpPurpose) -> tuple[str, str, str]:
    """返回 (code_key, lock_key, attempts_key)；所有用途都必须有尝试计数键。

    历史上 registration 的 attempts_key 为 None（无限次尝试），6 位验证码
    在 5 分钟 TTL 内可被穷举，因此所有用途统一为 MAX_ATTEMPTS 次上限。
    """
    email_lower = email.lower()
    if purpose == "password_setup":
        return (
            f"email:setup:code:{email_lower}",
            f"email:setup:lock:{email_lower}",
            f"email:setup:attempts:{email_lower}",
        )
    if purpose == "password_reset":
        return (
            f"{RESET_CODE_PREFIX}{email_lower}",
            f"{RESET_LOCK_PREFIX}{email_lower}",
            f"{RESET_ATTEMPTS_PREFIX}{email_lower}",
        )
    if purpose == "push_channel_verify":
        return (
            f"{PUSH_CODE_PREFIX}{email_lower}",
            f"{PUSH_LOCK_PREFIX}{email_lower}",
            f"{PUSH_ATTEMPTS_PREFIX}{email_lower}",
        )
    if purpose == "password_change":
        return (
            f"{CHANGE_CODE_PREFIX}{email_lower}",
            f"{CHANGE_LOCK_PREFIX}{email_lower}",
            f"{CHANGE_ATTEMPTS_PREFIX}{email_lower}",
        )
    if purpose == "email_change":
        return (
            f"{EMAIL_CHANGE_CODE_PREFIX}{email_lower}",
            f"{EMAIL_CHANGE_LOCK_PREFIX}{email_lower}",
            f"{EMAIL_CHANGE_ATTEMPTS_PREFIX}{email_lower}",
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

        code_key, lock_key, _attempts_key = otp_keys(email, purpose)
        if not await self._redis.eval(
            _STORE_SCRIPT, 2, code_key, lock_key, code, OTP_TTL, LOCK_TTL
        ):
            raise OtpCooldownError
        # 不在重发时清零 attempts：6 位验证码的猜测预算必须按邮箱窗口累计，
        # 否则攻击者每 60 秒重发一次即可无限续杯穷举（AUTH-D）。
        # attempts 键随首次错误尝试建立并按 OTP_TTL 过期；验真成功 consume
        # 或错误满 MAX_ATTEMPTS 销毁时才随 code 一并删除。

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
        return bool(await self._redis.eval(
            _VERIFY_SCRIPT, 2, code_key, attempts_key, stored_str,
            int(self._compare_digest(stored_str, code)), int(consume),
            OTP_TTL, MAX_ATTEMPTS,
        ))

    async def consume(self, email: str, *, purpose: OtpPurpose) -> None:
        if not self.available:
            return
        code_key, _lock_key, attempts_key = otp_keys(email, purpose)
        await self._redis.delete(code_key, attempts_key)
