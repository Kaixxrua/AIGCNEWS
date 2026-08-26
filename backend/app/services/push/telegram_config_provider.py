"""Runtime Telegram push configuration resolved from the Monitor singleton."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from backend.app.core.config import settings
from backend.app.repositories.telegram_settings_repository import (
    TelegramSettings,
    TelegramSettingsReader,
)

logger = logging.getLogger(__name__)
TelegramConfigSource = Literal["database", "environment", "unconfigured"]
_CACHE_TTL_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class EffectiveTelegramConfig:
    enabled: bool
    bot_token: str
    bot_username: str
    webhook_secret: str
    link_ttl_seconds: int
    request_timeout_seconds: float
    source: TelegramConfigSource
    updated_at: datetime | None = None

    @property
    def configured(self) -> bool:
        """启用且 token 就位：绑定/投递/webhook 路径的统一可用性口径。"""
        return bool(self.enabled and self.bot_token)


_reader: TelegramSettingsReader | None = None
_cache: tuple[float, EffectiveTelegramConfig] | None = None
_lock = threading.Lock()


def configure_telegram_settings_reader(reader: TelegramSettingsReader | None) -> None:
    global _reader, _cache
    with _lock:
        _reader, _cache = reader, None


def invalidate_telegram_config_cache() -> None:
    global _cache
    with _lock:
        _cache = None


def reset_telegram_config_provider() -> None:
    configure_telegram_settings_reader(None)


def effective_telegram_config_from_env(env: object) -> EffectiveTelegramConfig:
    values = dict(
        enabled=bool(getattr(env, "telegram_push_enabled", False)),
        bot_token=str(getattr(env, "telegram_bot_token", "") or "").strip(),
        bot_username=str(
            getattr(env, "telegram_bot_username", "") or ""
        ).strip().lstrip("@"),
        webhook_secret=str(getattr(env, "telegram_webhook_secret", "") or "").strip(),
        link_ttl_seconds=max(30, int(getattr(env, "telegram_link_ttl_seconds", 300))),
        request_timeout_seconds=float(
            getattr(env, "telegram_request_timeout_seconds", 5.0)
        ),
    )
    configured = bool(
        values["enabled"]
        or values["bot_token"]
        or values["bot_username"]
        or values["webhook_secret"]
    )
    return EffectiveTelegramConfig(
        **values,
        source="environment" if configured else "unconfigured",
    )


def effective_telegram_config_from_row(row: TelegramSettings) -> EffectiveTelegramConfig:
    return EffectiveTelegramConfig(
        enabled=bool(row.enabled),
        bot_token=row.bot_token,
        bot_username=row.bot_username,
        webhook_secret=row.webhook_secret,
        link_ttl_seconds=int(row.link_ttl_seconds),
        request_timeout_seconds=float(row.request_timeout_seconds),
        source="database",
        updated_at=row.updated_at,
    )


def _unconfigured() -> EffectiveTelegramConfig:
    return EffectiveTelegramConfig(
        enabled=False,
        bot_token="",
        bot_username="",
        webhook_secret="",
        link_ttl_seconds=300,
        request_timeout_seconds=5.0,
        source="unconfigured",
    )


def resolve_telegram_config(*, env=settings) -> EffectiveTelegramConfig:
    global _cache
    with _lock:
        # env 值保留为兼容/测试缝，逐请求直读。短命缓存只针对绑定的 DB
        # reader：多 worker 最终一致，同时避免陈旧 env 凭据掩盖运行时变更。
        if _reader is None:
            return effective_telegram_config_from_env(env)
        if _cache is not None and time.monotonic() - _cache[0] < _CACHE_TTL_SECONDS:
            return _cache[1]

        try:
            row = _reader.get_telegram_settings()
        except Exception:
            # 绑定 reader 意味着生产装配生效。迁移缺失/表不存在绝不静默回落
            # env 凭据：enabled 是功能开关、webhook secret 是安全控制，fail-closed。
            logger.warning(
                "[Telegram] 读取 telegram_settings 失败，推送 fail-closed",
                exc_info=True,
            )
            config = _unconfigured()
        else:
            config = (
                effective_telegram_config_from_row(row)
                if row is not None
                else effective_telegram_config_from_env(env)
            )

        _cache = (time.monotonic(), config)
        return config
