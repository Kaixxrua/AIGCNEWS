"""运行时邮件池配置解析：DB 行覆盖 EMAIL_POOL_JSON env，模块级绑定 + 短 TTL 缓存。

与 smtp_config_provider 同构：main.py lifespan 注入仓储 reader，之后所有
邮件发送路径经 resolve_email_pool_config 取生效池配置，保存即失效缓存、
60s TTL 兜底后台任务。DB 行内容损坏（解析不出有效 entry）时记警告并
回退 env——fail-soft，发送链路永不因配置面故障中断。
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Literal

from backend.app.core.config import settings
from backend.app.repositories.email_pool_settings_repository import (
    EmailPoolSettingsReader,
)
from backend.app.services.email.pool_transport import parse_email_pool_entries

logger = logging.getLogger(__name__)

EmailPoolConfigSource = Literal["database", "environment", "unconfigured"]

_CACHE_TTL_SECONDS = 60.0


@dataclass(frozen=True)
class EffectiveEmailPoolConfig:
    """一次解析得到的生效池配置（entries_json 原始文本 + 来源）。"""

    entries_json: str
    source: EmailPoolConfigSource


_reader: EmailPoolSettingsReader | None = None
_cache: tuple[float, EffectiveEmailPoolConfig] | None = None
_lock = threading.Lock()


def configure_email_pool_settings_reader(
    reader: EmailPoolSettingsReader | None,
) -> None:
    """Bind runtime email pool settings to the application-owned repository reader."""
    global _reader, _cache
    with _lock:
        _reader = reader
        _cache = None


def invalidate_email_pool_config_cache() -> None:
    """Drop the cached resolution so the next resolve re-reads the row."""
    global _cache
    with _lock:
        _cache = None


def reset_email_pool_config_provider() -> None:
    """测试专用：解除 reader 绑定并清空缓存。"""
    configure_email_pool_settings_reader(None)


def _has_valid_entries(entries_json: str) -> bool:
    """仅作有效性门槛：能解析出 ≥1 个 entry 才算有效池配置。"""
    return bool(parse_email_pool_entries(entries_json))


def resolve_email_pool_config(*, env=settings) -> EffectiveEmailPoolConfig:
    """Resolve the effective email pool config: DB row wins, env is the fallback.

    DB 行存在但 entries 为空或解析无效时回退 env（与 smtp 侧"行优先"
    略有差异：池以"有效 entry 数"为有效性口径，避免损坏行锁死发送链路）。
    """
    global _cache
    with _lock:
        cached = _cache
        if cached is not None:
            cached_at, config = cached
            if time.monotonic() - cached_at < _CACHE_TTL_SECONDS:
                return config

        row = None
        if _reader is not None:
            try:
                row = _reader.get_email_pool_settings()
            except Exception:
                logger.warning(
                    "[EMAIL_POOL] 读取 email_pool_settings 失败，回退 env 配置",
                    exc_info=True,
                )

        if row is not None and row.entries_json.strip():
            if _has_valid_entries(row.entries_json):
                config = EffectiveEmailPoolConfig(
                    entries_json=row.entries_json, source="database"
                )
            else:
                logger.warning(
                    "[EMAIL_POOL] email_pool_settings 行内容无效，回退 env 配置"
                )
                config = _resolve_from_env(env)
        else:
            config = _resolve_from_env(env)

        _cache = (time.monotonic(), config)
        return config


def _resolve_from_env(env) -> EffectiveEmailPoolConfig:
    entries_json = env.EMAIL_POOL_JSON
    if entries_json.strip() and _has_valid_entries(entries_json):
        return EffectiveEmailPoolConfig(entries_json=entries_json, source="environment")
    return EffectiveEmailPoolConfig(entries_json="", source="unconfigured")
