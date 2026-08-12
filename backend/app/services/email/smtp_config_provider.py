"""运行时 SMTP 配置解析：DB 行覆盖 env，模块级绑定 + 短 TTL 缓存。

绑定方式对齐 model_factory.configure_runtime_provider_settings：main.py
lifespan 注入仓储 reader，之后所有邮件发送路径（路由、调度器后台任务）
经 resolve_smtp_config 取生效配置，无需重启即可热生效。reader 未绑定
（测试、独立脚本）或 DB 读取失败时静默回退 env，行为与改造前一致。
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Literal

from backend.app.core.config import settings
from backend.app.repositories.smtp_settings_repository import SmtpSettingsReader

logger = logging.getLogger(__name__)

SmtpConfigSource = Literal["database", "environment", "unconfigured"]

_CACHE_TTL_SECONDS = 60.0


@dataclass(frozen=True)
class EffectiveSmtpConfig:
    """一次解析得到的生效 SMTP 配置（DB 行优先，env 兜底）。"""

    host: str
    port: int
    username: str
    password: str
    from_email: str
    from_name: str
    use_tls: bool
    source: SmtpConfigSource


_reader: SmtpSettingsReader | None = None
_cache: tuple[float, EffectiveSmtpConfig] | None = None
_lock = threading.Lock()


def configure_smtp_settings_reader(reader: SmtpSettingsReader | None) -> None:
    """Bind runtime SMTP settings to the application-owned repository reader."""
    global _reader, _cache
    with _lock:
        _reader = reader
        _cache = None


def invalidate_smtp_config_cache() -> None:
    """Drop the cached resolution so the next resolve re-reads the row."""
    global _cache
    with _lock:
        _cache = None


def reset_smtp_config_provider() -> None:
    """测试专用：解除 reader 绑定并清空缓存。"""
    configure_smtp_settings_reader(None)


def resolve_smtp_config(*, env=settings) -> EffectiveSmtpConfig:
    """Resolve the effective SMTP config: DB row wins, env is the fallback.

    60s TTL 缓存限制每封邮件一次 DB 命中的开销；保存/测试路径经
    invalidate_smtp_config_cache 立即失效。reader 抛错（如迁移未应用、
    表不存在）按无行处理并回退 env——非致命设计。
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
                row = _reader.get_smtp_settings()
            except Exception:
                logger.warning(
                    "[SMTP] 读取 smtp_settings 失败，回退 env 配置", exc_info=True
                )

        if row is not None:
            config = EffectiveSmtpConfig(
                host=row.host,
                port=row.port,
                username=row.username,
                # 唯一保留的 env 链：DB 行密码被清空时回退 env 密码
                password=row.password or env.SMTP_PASSWORD,
                from_email=row.from_email,
                from_name=row.from_name,
                use_tls=row.use_tls,
                source="database",
            )
        else:
            source: SmtpConfigSource = (
                "environment" if env.SMTP_HOST else "unconfigured"
            )
            config = EffectiveSmtpConfig(
                host=env.SMTP_HOST,
                port=env.SMTP_PORT,
                username=env.SMTP_USERNAME,
                password=env.SMTP_PASSWORD,
                from_email=env.SMTP_FROM_EMAIL,
                from_name=env.SMTP_FROM_NAME,
                use_tls=env.SMTP_USE_TLS,
                source=source,
            )

        _cache = (time.monotonic(), config)
        return config
