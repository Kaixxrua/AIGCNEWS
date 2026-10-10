"""MCP 一次性安装码：让「复制给 Agent 的提示词」不再携带长期 Token。

网页登录后签一枚安装码放进提示词；Agent 在用户电脑上用它向兑换端点换 Token，直接写进客户端配置。
Token 只在兑换的那一次 HTTP 响应里出现，不经过聊天记录。

- 安装码 10 分钟过期，只能兑换一次（GETDEL 原子消费）；Redis 里只存它的 SHA-256 摘要做键。
- 兑换先消费再校验：码一旦提交，无论后续校验是否通过都作废，不能拿同一枚码反复试。
- 载荷绑定签发时的口令版本（pwd_ver）：改密码会同时作废尚未兑换的安装码，与登录态同口径。
- Redis 不可用时一律失败（fail closed），与 MCP OAuth 授权码同法。
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

INSTALL_CODE_TTL_SECONDS = 600
INSTALL_CODE_KEY_PREFIX = "auth:mcp-install:code:"
INSTALL_CODE_PREFIX = "aigc_ic_"
MAX_INSTALL_CODE_LENGTH = 128

InstallCodePurpose = Literal["mcp", "dsh"]


class McpInstallCodeUnavailableError(RuntimeError):
    """Redis is unavailable, so install codes must fail closed."""


class InstallCodePayload(BaseModel):
    """安装码绑定的上下文：兑换时按它签发对应用途的 Token。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: int
    purpose: InstallCodePurpose
    pwd_ver: int | None = None


def install_code_key(code: str) -> str:
    return INSTALL_CODE_KEY_PREFIX + hashlib.sha256(code.encode("utf-8")).hexdigest()


class InstallCodeStore:
    """一次性安装码：签发写 Redis（带过期），兑换用 GETDEL 原子取出并作废。"""

    def __init__(self, redis_client: Any, *, ttl_seconds: int = INSTALL_CODE_TTL_SECONDS) -> None:
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds

    @property
    def ttl_seconds(self) -> int:
        return self._ttl_seconds

    async def issue(self, payload: InstallCodePayload) -> str:
        if self._redis is None:
            raise McpInstallCodeUnavailableError
        code = INSTALL_CODE_PREFIX + secrets.token_urlsafe(32)
        try:
            await self._redis.set(install_code_key(code), payload.model_dump_json(), ex=self._ttl_seconds)
        except Exception as exc:
            raise McpInstallCodeUnavailableError from exc
        return code

    async def consume(self, code: Any) -> InstallCodePayload | None:
        """取出并作废安装码；格式不对、不存在、过期、已用过或数据损坏都返回 None。"""
        if self._redis is None:
            raise McpInstallCodeUnavailableError
        if not isinstance(code, str) or not code.startswith(INSTALL_CODE_PREFIX) or len(code) > MAX_INSTALL_CODE_LENGTH:
            return None
        try:
            value = await self._getdel(install_code_key(code))
        except Exception as exc:
            raise McpInstallCodeUnavailableError from exc
        if value is None:
            return None
        try:
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            return InstallCodePayload.model_validate_json(value)
        except (UnicodeDecodeError, ValidationError, ValueError):
            return None

    async def _getdel(self, key: str) -> Any:
        getdel = getattr(self._redis, "getdel", None)
        if getdel is not None:
            return await getdel(key)
        # 与授权码同法：没有 GETDEL 的 Redis 用服务端 Lua 保证一次性消费
        return await self._redis.eval(
            "local value = redis.call('GET', KEYS[1]); if value then redis.call('DEL', KEYS[1]); end; return value",
            1,
            key,
        )
