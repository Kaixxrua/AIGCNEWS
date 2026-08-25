"""Telegram Bot 推送：deep-link 一次性绑定与 Bot API 投递。

渠道模型（安全边界，Red）：
- 绑定 nonce 只以 SHA-256 哈希入库，原始 nonce 仅存在于一次性 deep-link
  响应中，状态查询不回放；
- chat_id 是投递凭据：只存于密封的 encrypted_config；provider_key 为
  chat_id 的 HMAC-SHA256 指纹（以推送渠道加密密钥为 pepper），用于
  全局防重复绑定；target 只存指纹截断占位，API 展示用 display_target
  （末 4 位掩码），任何响应/日志都不出现原始 chat_id；
- Bot token 只来自部署配置；投递异常文案为静态字符串，绝不携带
  httpx 异常对象文本（其 request.url 含 token）。
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import httpx

from backend.app.core.config import settings
from backend.app.repositories.push_channel_repository import PushChannelRepository
from backend.app.repositories.telegram_link_attempt_repository import (
    TelegramLinkAttemptRepository,
)
from backend.app.services.push.channel_service import (
    CHANNEL_TYPE_TELEGRAM,
    PushChannelService,
)
from backend.app.services.push.errors import (
    ProviderCredentialInvalidError,
    ProviderRateLimitedError,
    TelegramDeliveryError,
    TelegramNotConfiguredError,
)
from backend.app.services.push.secrets import (
    build_push_channel_secret_box,
    seal_channel_config,
)
from backend.app.services.push.webhook_service import (
    PROVIDER_TELEGRAM,
    chunk_markdown_for_provider,
)

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"
_LINK_OK_TITLE = "AIGCNEWS 推送渠道"
_LINK_OK_CONTENT = (
    "✅ Telegram 渠道连接成功。\n\n"
    "回到 aigcnews.cn 的订阅页，为该渠道选择来源后即可接收 AI 垂直简报。"
)

_SECRET_BOX_UNSET = object()


def _hash_nonce(nonce: str) -> str:
    return hashlib.sha256(nonce.encode("utf-8")).hexdigest()


def _display_target(chat_id: str) -> str:
    suffix = chat_id[-4:] if len(chat_id) >= 4 else chat_id
    return f"Telegram 私聊 · ****{suffix}"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class TelegramBotClient:
    """Telegram Bot API 投递器：plain text 按字节预算分块顺序发送。

    错误分类：429 → ProviderRateLimitedError（含 retry_after）；
    400/401/403/404 → ProviderCredentialInvalidError（渠道永久失效）；
    其余 HTTP ≥400 与网络异常 → TelegramDeliveryError（可重试）。
    """

    def __init__(
        self,
        *,
        token: str,
        timeout_seconds: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
        api_base: str = TELEGRAM_API_BASE,
    ) -> None:
        self._token = token
        self._timeout_seconds = timeout_seconds
        self._transport = transport
        self._api_base = api_base.rstrip("/")

    async def send_message(self, *, chat_id: str, title: str, content: str) -> None:
        if not self._token:
            raise TelegramNotConfiguredError("Telegram 推送未启用")
        text = f"{title}\n\n{content}"
        chunks = chunk_markdown_for_provider(PROVIDER_TELEGRAM, text)
        url = f"{self._api_base}/bot{self._token}/sendMessage"
        async with httpx.AsyncClient(
            timeout=self._timeout_seconds,
            transport=self._transport,
            follow_redirects=False,
            headers={"User-Agent": "AIGCNews-Telegram/1.0"},
        ) as client:
            for chunk in chunks:
                await self._post(client, url, chat_id, chunk)

    async def _post(
        self,
        client: httpx.AsyncClient,
        url: str,
        chat_id: str,
        text: str,
    ) -> None:
        try:
            response = await client.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "disable_web_page_preview": True,
                },
            )
        except httpx.HTTPError as exc:
            # detail 固定静态文案：httpx 异常的 request.url 含 bot token
            raise TelegramDeliveryError("Telegram 请求失败") from exc
        if response.status_code == 429:
            retry_after = self._retry_after(response)
            raise ProviderRateLimitedError(
                f"Telegram 限流，请 {retry_after} 秒后重试"
            )
        if response.status_code in {400, 401, 403, 404}:
            raise ProviderCredentialInvalidError(
                "Telegram 渠道已失效（会话可能被删除或已拉黑机器人）"
            )
        if response.status_code >= 400:
            raise TelegramDeliveryError(
                f"Telegram 返回 HTTP {response.status_code}"
            )

    @staticmethod
    def _retry_after(response: httpx.Response) -> int:
        try:
            data = response.json()
        except ValueError:
            return 5
        if not isinstance(data, dict):
            return 5
        params = data.get("parameters")
        if not isinstance(params, dict):
            return 5
        try:
            return max(1, int(params.get("retry_after") or 5))
        except (TypeError, ValueError):
            return 5


def build_telegram_bot_client(
    *,
    config: Any = settings,
    transport: httpx.AsyncBaseTransport | None = None,
) -> TelegramBotClient | None:
    """按部署配置构建投递器；未启用或未配置 token 时返回 None。"""
    if not getattr(config, "telegram_push_enabled", False):
        return None
    token = str(getattr(config, "telegram_bot_token", "") or "")
    if not token:
        return None
    return TelegramBotClient(
        token=token,
        timeout_seconds=float(getattr(config, "telegram_request_timeout_seconds", 5.0)),
        transport=transport,
    )


class TelegramLinkService:
    """Telegram deep-link 绑定：nonce 签发、状态查询、webhook 消费建渠道。"""

    def __init__(
        self,
        *,
        attempts: TelegramLinkAttemptRepository,
        channels: PushChannelRepository,
        config: Any = settings,
        secret_box: Any = _SECRET_BOX_UNSET,
    ) -> None:
        self._attempts = attempts
        self._channels = channels
        self._enabled = bool(getattr(config, "telegram_push_enabled", False))
        self._bot_username = str(
            getattr(config, "telegram_bot_username", "") or ""
        ).strip().lstrip("@")
        self._ttl_seconds = max(30, int(getattr(config, "telegram_link_ttl_seconds", 300)))
        # provider_key 的 HMAC pepper 复用渠道加密密钥材料（部署机密）
        self._pepper = str(getattr(config, "push_channel_encryption_key", "") or "")
        self._secret_box = secret_box

    async def create_link(self, *, user: dict[str, Any]) -> dict[str, Any]:
        """为当前用户签发一次性 deep-link；nonce 仅入哈希，原文只随响应返回。"""
        if not self._enabled or not self._bot_username:
            raise TelegramNotConfiguredError("Telegram 推送未启用")
        PushChannelService.require_direct_channel_entitlement(user)
        user_id = int(user.get("user_id") or 0)
        nonce = secrets.token_urlsafe(32)
        attempt_id = uuid4()
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self._ttl_seconds)
        await asyncio.to_thread(
            self._attempts.create_attempt,
            attempt_id=attempt_id,
            user_id=user_id,
            nonce_hash=_hash_nonce(nonce),
            expires_at=expires_at,
        )
        return {
            "attempt_id": str(attempt_id),
            "deep_link": f"https://t.me/{self._bot_username}?start={nonce}",
            "expires_at": expires_at,
            "status": "pending",
        }

    async def get_link_status(
        self,
        *,
        user_id: int,
        attempt_id: UUID,
    ) -> dict[str, Any] | None:
        """Owner 范围的状态查询；不回放 deep_link（nonce 已不可重建）。"""
        attempt = await asyncio.to_thread(
            self._attempts.get_attempt,
            user_id=user_id,
            attempt_id=attempt_id,
        )
        if attempt is None:
            return None
        status_value = str(attempt["status"])
        expires_at = attempt["expires_at"]
        if status_value == "pending" and _as_utc(expires_at) <= datetime.now(timezone.utc):
            status_value = "expired"
        return {
            "attempt_id": str(attempt["attempt_id"]),
            "deep_link": "",
            "expires_at": expires_at,
            "status": status_value,
        }

    async def complete_link(self, *, nonce: str, chat_id: str, chat_type: str) -> str:
        """消费一次性 nonce 并把 Telegram 私聊绑定为已验证渠道。

        返回 ok / ignored / invalid / conflict；webhook 侧对 Telegram 一律
        回 200，任何失败只记录安全日志，不向对方泄露绑定归属。
        """
        if chat_type != "private":
            return "ignored"
        if not nonce:
            return "invalid"
        attempt = await asyncio.to_thread(
            self._attempts.consume_attempt,
            nonce_hash=_hash_nonce(nonce),
            chat_id=chat_id,
        )
        if attempt is None:
            return "invalid"
        user_id = int(attempt["user_id"])
        provider_key = self._provider_key(chat_id)
        existing = await asyncio.to_thread(
            self._channels.find_channel_by_provider_key,
            channel_type=CHANNEL_TYPE_TELEGRAM,
            provider_key=provider_key,
        )
        if existing is not None and int(existing["user_id"]) != user_id:
            logger.warning(
                "[Telegram] chat 已被其他用户绑定，拒绝重复绑定: attempt=%s",
                attempt["attempt_id"],
            )
            return "conflict"
        channel = existing
        if channel is None:
            encrypted_config = seal_channel_config(
                self._resolve_secret_box(), {"chat_id": chat_id}
            )
            channel = await asyncio.to_thread(
                self._channels.create_channel,
                user_id=user_id,
                channel_type=CHANNEL_TYPE_TELEGRAM,
                target=f"tg:{provider_key[:32]}",
                encrypted_config=encrypted_config,
                verified=True,
                provider_key=provider_key,
                display_target=_display_target(chat_id),
            )
            if channel is None:
                # 并发回调撞唯一约束：回读现况并按归属校验
                channel = await asyncio.to_thread(
                    self._channels.find_channel_by_provider_key,
                    channel_type=CHANNEL_TYPE_TELEGRAM,
                    provider_key=provider_key,
                )
                if channel is None or int(channel["user_id"]) != user_id:
                    return "conflict"
        await asyncio.to_thread(
            self._attempts.attach_channel,
            attempt_id=UUID(str(attempt["attempt_id"])),
            channel_id=int(channel["id"]),
        )
        return "ok"

    def _provider_key(self, chat_id: str) -> str:
        if not self._pepper:
            raise TelegramNotConfiguredError("推送渠道加密密钥未配置")
        return hmac.new(
            self._pepper.encode("utf-8"),
            chat_id.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _resolve_secret_box(self) -> Any:
        if self._secret_box is _SECRET_BOX_UNSET:
            self._secret_box = build_push_channel_secret_box()
        return self._secret_box


__all__ = [
    "TELEGRAM_API_BASE",
    "TelegramBotClient",
    "TelegramLinkService",
    "build_telegram_bot_client",
]
