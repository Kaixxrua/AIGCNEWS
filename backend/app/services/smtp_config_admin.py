"""SMTP 配置的管理员读写与测试投递。

投影层绝不回传明文密码：password_configured/password_masked 仅供界面
展示状态；update_config 的 password=None/"" 表示保留现状（DB 行优先，
无行时回落到 env），clear_password=True 显式擦除。保存后缓存即时失效，
60s TTL 兜底所有后台发送路径。
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from backend.app.core.config import settings
from backend.app.repositories.smtp_settings_repository import SmtpSettingsManager
from backend.app.services.email.smtp_config_provider import (
    EffectiveSmtpConfig,
    invalidate_smtp_config_cache,
    resolve_smtp_config,
)
from backend.app.services.email.smtp_transport import SmtpDeliveryError, SmtpTransport
from backend.app.services.secret_masking import mask_token

logger = logging.getLogger(__name__)

_FROM_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# 主机字段只允许纯主机名或 IPv4 字面量：":///@" 可注入协议、端口或凭证
_HOST_FORBIDDEN_CHARS = re.compile(r"[\s/@:]")
_DENIED_HOSTNAMES = {"localhost", "metadata.google.internal"}


def _validate_smtp_host(host: str) -> str:
    """归一化并拦截危险 SMTP 目标（渗透审计 SSRF-3），返回规范化主机名。

    允许私网段（RFC1918）：内网邮件中继是合法部署形态；拦截回环、链路
    本地、组播、未指定与保留地址及 localhost 系主机名，防本机服务探测
    与凭证外送。不做保存期 DNS：docker 内部主机名仅在发送时网络视图可
    解析，保存期解析会误杀合法配置。IPv6 字面量因与端口分隔符冲突不在
    面板路径支持（env 路径不受影响）。
    """
    normalized = host.strip().lower().rstrip(".")
    if not normalized or len(normalized) > 253 or _HOST_FORBIDDEN_CHARS.search(normalized):
        raise ValueError("SMTP 主机名不合法：仅允许主机名或 IPv4 地址，不含协议/端口/凭证")
    if normalized in _DENIED_HOSTNAMES or normalized.endswith(".localhost"):
        raise ValueError("SMTP 主机不允许指向本机或保留地址")
    try:
        ip = ipaddress.ip_address(normalized)
    except ValueError:
        return normalized
    if (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    ):
        raise ValueError("SMTP 主机不允许指向本机或保留地址")
    return normalized


def _classify_delivery_failure(error_type: str) -> str:
    """按异常类名归类为排查文案（类名本身不回显，防指纹化内部栈）。"""
    name = error_type.lower()
    if any(marker in name for marker in ("auth", "login", "credential")):
        return "SMTP 鉴权失败，请检查用户名与密码"
    if any(marker in name for marker in ("connect", "timeout", "tls", "ssl", "gaierror")):
        return "无法连接 SMTP 服务器，请检查主机、端口与 TLS 设置"
    if any(marker in name for marker in ("recipient", "sender", "address", "data")):
        return "邮件被服务器拒绝，请检查发件与收件地址"
    return "邮件发送失败，请检查 SMTP 配置"


class SmtpConfigError(Exception):
    """SMTP 配置管理域错误基类（detail 可安全回显）。"""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class SmtpNotConfiguredError(SmtpConfigError):
    """DB 与 env 均未配置 SMTP（路由层映射 400）。"""


class SmtpTestDeliveryError(SmtpConfigError):
    """测试邮件投递失败（路由层映射 502）。"""


@dataclass(frozen=True)
class SmtpConfigProjection:
    host: str
    port: int
    username: str
    password_configured: bool
    password_masked: str | None
    from_email: str
    from_name: str
    use_tls: bool
    source: str
    updated_at: str | None


TransportFactory = Callable[[EffectiveSmtpConfig], SmtpTransport]


def _default_transport_factory(config: EffectiveSmtpConfig) -> SmtpTransport:
    return SmtpTransport(
        host=config.host,
        port=config.port,
        username=config.username,
        password=config.password,
        from_email=config.from_email,
        from_name=config.from_name,
        use_tls=config.use_tls,
    )


class SmtpConfigAdminService:
    def __init__(
        self,
        repository: SmtpSettingsManager,
        *,
        env_config=settings,
        transport_factory: TransportFactory | None = None,
    ) -> None:
        self._repository = repository
        self._env = env_config
        self._transport_factory = transport_factory or _default_transport_factory

    async def get_config(self) -> SmtpConfigProjection:
        effective = resolve_smtp_config(env=self._env)
        updated_at = await asyncio.to_thread(self._saved_updated_at)
        return self._to_projection(effective, updated_at)

    async def update_config(self, values: Mapping[str, Any]) -> SmtpConfigProjection:
        host = str(values.get("host") or "").strip()
        if not host:
            # 文档化语义：清空 host 即删除 DB 覆盖行，整体回退 env
            await asyncio.to_thread(self._repository.delete_smtp_settings)
            invalidate_smtp_config_cache()
            return await self.get_config()

        port = int(values.get("port") or 587)
        if not 1 <= port <= 65535:
            raise ValueError("端口必须在 1-65535 之间")
        host = _validate_smtp_host(host)
        from_email = str(values.get("from_email") or "").strip()
        if not _FROM_EMAIL_PATTERN.match(from_email):
            raise ValueError("发件邮箱格式不正确")
        username = str(values.get("username") or "").strip()
        from_name = str(values.get("from_name") or "").strip()
        use_tls = bool(values.get("use_tls", True))
        clear_password = bool(values.get("clear_password", False))
        password = values.get("password")

        if clear_password:
            stored_password = ""
        elif password:
            stored_password = str(password)
        else:
            existing = await asyncio.to_thread(self._repository.get_smtp_settings)
            stored_password = existing.password if existing is not None else ""

        saved = await asyncio.to_thread(
            self._repository.upsert_smtp_settings,
            host=host,
            port=port,
            username=username,
            password=stored_password,
            from_email=from_email,
            from_name=from_name,
            use_tls=use_tls,
        )
        invalidate_smtp_config_cache()
        effective = resolve_smtp_config(env=self._env)
        return self._to_projection(
            effective,
            saved.updated_at.isoformat() if saved.updated_at else None,
        )

    async def send_test_email(self, to_email: str) -> dict[str, Any]:
        """按最新生效配置向指定邮箱投递一封测试邮件。"""
        invalidate_smtp_config_cache()
        effective = resolve_smtp_config(env=self._env)
        if effective.source == "unconfigured" or not effective.host:
            raise SmtpNotConfiguredError(
                "SMTP 未配置：请先保存配置或设置 SMTP_HOST 环境变量"
            )

        transport = self._transport_factory(effective)
        body = (
            "这是一封来自 AIGCNEWS 的 SMTP 配置测试邮件。\n\n"
            f"发件配置来源：{effective.source}\n"
            f"SMTP 主机：{effective.host}:{effective.port}\n"
            "如果您收到此邮件，说明当前配置可以正常投递。"
        )
        started = time.monotonic()
        try:
            await transport.send_plain(
                to_email, "AIGCNEWS SMTP 配置测试邮件", body
            )
        except SmtpDeliveryError as exc:
            # 原始异常链只进服务端日志；回显按类名归类的排查文案，
            # 不回显类名本身（可指纹化内部栈，渗透审计 SSRF-3）
            logger.warning("[SMTP] 测试邮件投递失败：%s", exc.error_type, exc_info=True)
            raise SmtpTestDeliveryError(
                _classify_delivery_failure(exc.error_type)
            ) from exc
        latency_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "[SMTP] 测试邮件已发送 to=%s host=%s latency_ms=%d",
            to_email,
            effective.host,
            latency_ms,
        )
        return {
            "status": "success",
            "message": f"测试邮件已发送至 {to_email}",
            "to_email": to_email,
            "latency_ms": latency_ms,
        }

    def _saved_updated_at(self) -> str | None:
        row = self._repository.get_smtp_settings()
        if row is None or row.updated_at is None:
            return None
        return row.updated_at.isoformat()

    def _to_projection(
        self, effective: EffectiveSmtpConfig, updated_at: str | None
    ) -> SmtpConfigProjection:
        return SmtpConfigProjection(
            host=effective.host,
            port=effective.port,
            username=effective.username,
            password_configured=bool(effective.password),
            password_masked=mask_token(effective.password),
            from_email=effective.from_email,
            from_name=effective.from_name,
            use_tls=effective.use_tls,
            source=effective.source,
            updated_at=updated_at,
        )
