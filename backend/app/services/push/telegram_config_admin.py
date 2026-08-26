"""Monitor 面板 Telegram 推送配置管理：脱敏投影、getMe 校验、webhook 一键注册。

安全口径（与 OAuth 配置同款）：
- 投影绝不回明文 secret：只有 *_configured 布尔 + *_masked 脱敏值；
- DB 行存在即整体覆盖 env（空列不逐字段回落 env）；
- 所有 Telegram Bot API 出站的错误文案为静态字符串，绝不携带 httpx 异常
  对象文本（其 request.url 含 bot token）。
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

import httpx

from backend.app.core.config import settings
from backend.app.repositories.telegram_settings_repository import TelegramSettingsManager
from backend.app.services.push.telegram_config_provider import (
    EffectiveTelegramConfig,
    effective_telegram_config_from_row,
    invalidate_telegram_config_cache,
    resolve_telegram_config,
)
from backend.app.services.push.telegram_service import TELEGRAM_API_BASE
from backend.app.services.secret_masking import mask_token

logger = logging.getLogger(__name__)

_SECRET_FIELDS = ("bot_token", "webhook_secret")
_WEBHOOK_PATH = "/api/push/providers/telegram/webhook"


@dataclass(frozen=True, slots=True)
class TelegramWebhookStatusProjection:
    url: str
    pending_update_count: int | None
    last_error_message: str | None


@dataclass(frozen=True, slots=True)
class TelegramConfigProjection:
    enabled: bool
    bot_username: str
    link_ttl_seconds: int
    request_timeout_seconds: float
    source: str
    updated_at: str | None
    bot_token_configured: bool
    bot_token_masked: str | None
    webhook_secret_configured: bool
    webhook_secret_masked: str | None
    webhook: TelegramWebhookStatusProjection | None


class TelegramConfigAdminService:
    def __init__(
        self,
        repository: TelegramSettingsManager,
        *,
        env_config=settings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._repository = repository
        self._env = env_config
        self._transport = transport

    async def get_config(self) -> TelegramConfigProjection:
        effective = resolve_telegram_config(env=self._env)
        row = await asyncio.to_thread(self._repository.get_telegram_settings)
        projection = self._to_projection(
            effective,
            row.updated_at.isoformat() if row and row.updated_at else None,
        )
        return await self._attach_webhook_status(projection, effective)

    async def update_config(self, values: Mapping[str, Any]) -> TelegramConfigProjection:
        enabled = bool(values.get("enabled", False))
        link_ttl = int(values.get("link_ttl_seconds") or 300)
        timeout = float(values.get("request_timeout_seconds") or 5.0)
        if not 60 <= link_ttl <= 3600:
            raise ValueError("Telegram 绑定链接有效期必须在 60-3600 秒之间")
        if not 1 <= timeout <= 30:
            raise ValueError("Telegram 请求超时必须在 1-30 秒之间")

        existing = await asyncio.to_thread(self._repository.get_telegram_settings)
        secrets: dict[str, str] = {}
        for field in _SECRET_FIELDS:
            submitted = values.get(field)
            if bool(values.get(f"clear_{field}", False)):
                secrets[field] = ""
            elif submitted:
                value = str(submitted).strip()
                if value.upper().startswith("CHANGEME"):
                    raise ValueError("Telegram secret 不得使用 CHANGEME 示例占位符")
                secrets[field] = value
            else:
                secrets[field] = getattr(existing, field, "") if existing else ""

        bot_username = str(values.get("bot_username") or "").strip().lstrip("@")
        token = secrets["bot_token"]
        new_token_submitted = bool(
            values.get("bot_token") and not values.get("clear_bot_token")
        )
        # 保存时校验：新 token 必过 getMe；启用且无 username 时用生效 token
        # 回填 username。getMe 成功则以 Telegram 返回的 username 为准。
        needs_getme = bool(token) and (
            new_token_submitted
            or (enabled and not bot_username and not (existing and existing.bot_username))
        )
        if needs_getme:
            bot_username = await self._get_me_username(token, timeout=timeout)
        elif not bot_username and existing:
            bot_username = existing.bot_username

        saved = await asyncio.to_thread(
            self._repository.upsert_telegram_settings,
            enabled=enabled,
            bot_token=token,
            bot_username=bot_username,
            webhook_secret=secrets["webhook_secret"],
            link_ttl_seconds=link_ttl,
            request_timeout_seconds=timeout,
        )
        invalidate_telegram_config_cache()
        # 投影直接基于刚保存的行：与运行时解析路径一致，且不依赖缓存可见性。
        effective = effective_telegram_config_from_row(saved)
        projection = self._to_projection(
            effective,
            saved.updated_at.isoformat() if saved.updated_at else None,
        )
        return await self._attach_webhook_status(projection, effective)

    async def reset_config(self) -> TelegramConfigProjection:
        await asyncio.to_thread(self._repository.delete_telegram_settings)
        invalidate_telegram_config_cache()
        return await self.get_config()

    async def register_webhook(self) -> TelegramConfigProjection:
        """一键注册 webhook：URL 由 public_base_url 派生（绝不取 Host 头）。"""
        effective = resolve_telegram_config(env=self._env)
        if not effective.configured:
            raise ValueError("请先启用 Telegram 推送并配置 Bot token")
        if not effective.webhook_secret:
            raise ValueError("请先配置 Webhook secret（回调校验所需）")
        base_url = str(getattr(self._env, "public_base_url", "") or "").strip().rstrip("/")
        if not base_url:
            raise ValueError("PUBLIC_BASE_URL 未配置，无法推导 webhook 回调地址")
        await self._call_bot_api(
            effective.bot_token,
            "setWebhook",
            payload={
                "url": f"{base_url}{_WEBHOOK_PATH}",
                "secret_token": effective.webhook_secret,
                "drop_pending_updates": True,
            },
            timeout=effective.request_timeout_seconds,
            invalid_token_detail="Telegram Bot token 无效，无法注册 webhook",
        )
        return await self.get_config()

    async def _get_me_username(self, token: str, *, timeout: float) -> str:
        result = await self._call_bot_api(
            token,
            "getMe",
            timeout=timeout,
            invalid_token_detail="Telegram Bot token 无效（getMe 校验未通过）",
        )
        username = str(result.get("username") or "") if isinstance(result, dict) else ""
        if not username:
            raise ValueError("Telegram getMe 响应缺少 username")
        return username

    async def _attach_webhook_status(
        self,
        projection: TelegramConfigProjection,
        effective: EffectiveTelegramConfig,
    ) -> TelegramConfigProjection:
        status = await self._fetch_webhook_status(effective)
        return replace(projection, webhook=status)

    async def _fetch_webhook_status(
        self,
        effective: EffectiveTelegramConfig,
    ) -> TelegramWebhookStatusProjection | None:
        """getWebhookInfo 状态回显；无 token 或 API 不可达时返回 None 不炸读路径。"""
        if not effective.bot_token:
            return None
        try:
            result = await self._call_bot_api(
                effective.bot_token,
                "getWebhookInfo",
                timeout=effective.request_timeout_seconds,
                invalid_token_detail="Telegram Bot token 无效",
            )
        except ValueError as exc:
            logger.warning("[Telegram] getWebhookInfo 失败: %s", exc)
            return None
        if not isinstance(result, dict):
            return None
        pending = result.get("pending_update_count")
        return TelegramWebhookStatusProjection(
            url=str(result.get("url") or ""),
            pending_update_count=int(pending) if isinstance(pending, int) else None,
            last_error_message=(
                str(result["last_error_message"])
                if result.get("last_error_message")
                else None
            ),
        )

    async def _call_bot_api(
        self,
        token: str,
        method: str,
        *,
        payload: dict[str, Any] | None = None,
        timeout: float = 5.0,
        invalid_token_detail: str,
    ) -> Any:
        url = f"{TELEGRAM_API_BASE}/bot{token}/{method}"
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                transport=self._transport,
                follow_redirects=False,
                headers={"User-Agent": "AIGCNews-Telegram/1.0"},
            ) as client:
                if payload is None:
                    response = await client.get(url)
                else:
                    response = await client.post(url, json=payload)
        except httpx.HTTPError as exc:
            # 静态文案：httpx 异常的 request.url 含 bot token
            raise ValueError("无法连接 Telegram Bot API") from exc
        if response.status_code in {400, 401, 404}:
            raise ValueError(invalid_token_detail)
        try:
            data = response.json()
        except ValueError as exc:
            raise ValueError("Telegram Bot API 响应异常") from exc
        if response.status_code != 200 or not isinstance(data, dict) or not data.get("ok"):
            raise ValueError("Telegram Bot API 调用失败，请稍后重试")
        return data.get("result")

    @staticmethod
    def _to_projection(
        config: EffectiveTelegramConfig,
        updated_at: str | None,
    ) -> TelegramConfigProjection:
        return TelegramConfigProjection(
            enabled=config.enabled,
            bot_username=config.bot_username,
            link_ttl_seconds=config.link_ttl_seconds,
            request_timeout_seconds=config.request_timeout_seconds,
            source=config.source,
            updated_at=updated_at,
            bot_token_configured=bool(config.bot_token),
            bot_token_masked=mask_token(config.bot_token),
            webhook_secret_configured=bool(config.webhook_secret),
            webhook_secret_masked=mask_token(config.webhook_secret),
            webhook=None,
        )
