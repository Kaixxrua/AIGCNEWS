from __future__ import annotations

import logging
import random
import string

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

_OTP_CODE_PREFIX = "sms:code:"
_OTP_LOCK_PREFIX = "sms:lock:"
_OTP_TTL = 300  # 验证码有效期 5 分钟
_LOCK_TTL = 60  # 防刷冷却 60 秒


def _gen_otp(length: int = 6) -> str:
    """生成 length 位随机数字 OTP。"""
    return "".join(random.choices(string.digits, k=length))


class SmsService:
    """短信验证码服务（支持 Redis 防刷 + dev 模式日志输出）。

    Args:
        redis_client: redis.asyncio.Redis 实例（或同步 redis.Redis，均支持）。
            如果为 None，表示 Redis 不可用，OTP 功能将降级（仅打印日志，不存储）。
        sms_api_key: 云厂商短信 API Key；空字符串表示 dev 模式，仅打印日志。
    """

    def __init__(self, redis_client, sms_api_key: str = "") -> None:
        self._redis = redis_client
        self._sms_api_key = sms_api_key

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_redis_available(self) -> bool:
        return self._redis is not None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def send_otp(self, phone: str) -> None:
        """发送 OTP 验证码。

        防刷逻辑：
        1. 检查 Redis key sms:lock:<phone>，若存在 -> 抛 429
        2. 生成 6 位随机数字 OTP
        3. 写入 Redis: sms:code:<phone> = OTP, TTL=300s
        4. 写入 Redis: sms:lock:<phone> = "1", TTL=60s
        5. 发送短信（dev 模式打印日志；生产模式调用云厂商 API）
        """
        if self._is_redis_available():
            lock_key = f"{_OTP_LOCK_PREFIX}{phone}"
            existing_lock = await self._redis.get(lock_key)
            if existing_lock is not None:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="请求过于频繁，请 60 秒后再试",
                )

        otp = _gen_otp()

        if self._is_redis_available():
            code_key = f"{_OTP_CODE_PREFIX}{phone}"
            lock_key = f"{_OTP_LOCK_PREFIX}{phone}"
            await self._redis.set(code_key, otp, ex=_OTP_TTL)
            await self._redis.set(lock_key, "1", ex=_LOCK_TTL)

        if self._sms_api_key:
            # TODO: 调用云厂商短信 API（如阿里云 / 腾讯云）
            logger.info(
                "[SMS] TODO: 调用云厂商 API 发送短信给 %s，api_key=%s…",
                phone,
                self._sms_api_key[:4] + "****",
            )
        else:
            logger.info("[SMS DEV] phone=%s otp=%s", phone, otp)

    async def verify_otp(self, phone: str, code: str, consume: bool = True) -> bool:
        """验证 OTP 是否正确。

        1. 从 Redis 取 sms:code:<phone>
        2. 比对（字符串等值）
        3. 比对成功且 consume=True -> 删除 Redis key，返回 True
        4. 比对失败 -> 返回 False

        Args:
            phone: 手机号
            code: 用户输入的验证码
            consume: 验证成功后是否立即删除 Redis key（默认 True）。
                     若业务逻辑中后续步骤可能失败，可传 False，
                     待全部成功后再调用 consume_otp() 手动删除。

        当 Redis 不可用时，始终返回 False（不允许无状态验证）。
        """
        if not self._is_redis_available():
            logger.warning("[SMS] Redis 不可用，无法验证 OTP，拒绝请求。")
            return False

        code_key = f"{_OTP_CODE_PREFIX}{phone}"
        stored = await self._redis.get(code_key)

        if stored is None:
            return False

        # decode bytes -> str（redis decode_responses=False 时返回 bytes）
        stored_str = stored.decode("utf-8") if isinstance(stored, bytes) else stored

        if stored_str == code:
            if consume:
                await self._redis.delete(code_key)
            return True

        return False

    async def consume_otp(self, phone: str) -> None:
        """显式删除 Redis 中的 OTP key（在业务流程全部成功后调用）。"""
        if self._is_redis_available():
            code_key = f"{_OTP_CODE_PREFIX}{phone}"
            await self._redis.delete(code_key)
