"""邮件池配置的管理员读写与测试投递。

投影层绝不回传明文密码：password_configured/password_masked 仅供界面
展示状态；update_config 以 entry 的 name 为键做密码保留（password=None
保留同名已存密码，clear_password=True 显式擦除，改名视为新 entry）。
保存后缓存即时失效，60s TTL 兜底所有后台发送路径。测试投递走真实
EmailPoolTransport（含 legacy-smtp 兜底合并与配额计数），验证的就是
生产 failover 链路。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from backend.app.core.config import settings
from backend.app.repositories.email_pool_settings_repository import (
    EmailPoolSettingsManager,
)
from backend.app.services.email.host_guard import FROM_EMAIL_PATTERN, validate_email_host
from backend.app.services.email.pool_config_provider import (
    invalidate_email_pool_config_cache,
    resolve_email_pool_config,
)
from backend.app.services.email.pool_transport import (
    EmailPoolEntry,
    EmailPoolQuotaStore,
    EmailPoolTransport,
    merge_legacy_entry,
    parse_email_pool_entries,
)
from backend.app.services.email.smtp_config_provider import (
    invalidate_smtp_config_cache,
    resolve_smtp_config,
)
from backend.app.services.email.smtp_transport import SmtpDeliveryError
from backend.app.services.secret_masking import mask_token

logger = logging.getLogger(__name__)

_MAX_ENTRIES = 20
_ENTRY_JSON_KEYS = (
    "name",
    "host",
    "port",
    "username",
    "password",
    "from_email",
    "from_name",
    "use_tls",
    "daily_limit",
    "monthly_limit",
    "priority",
)


class EmailPoolConfigError(Exception):
    """邮件池配置管理域错误基类（detail 可安全回显）。"""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class EmailPoolNotConfiguredError(EmailPoolConfigError):
    """DB 与 env 均未配置有效邮件池（路由层映射 400）。"""


class EmailPoolTestDeliveryError(EmailPoolConfigError):
    """池内全部服务商投递失败（路由层映射 502）。"""


@dataclass(frozen=True)
class EmailPoolEntryProjection:
    name: str
    host: str
    port: int
    username: str
    password_configured: bool
    password_masked: str | None
    from_email: str
    from_name: str
    use_tls: bool
    daily_limit: int
    monthly_limit: int
    priority: int


@dataclass(frozen=True)
class EmailPoolConfigProjection:
    entries: list[EmailPoolEntryProjection]
    source: str
    updated_at: str | None


PoolTransportFactory = Callable[[list[EmailPoolEntry]], EmailPoolTransport]


class EmailPoolConfigAdminService:
    def __init__(
        self,
        repository: EmailPoolSettingsManager,
        *,
        redis_client=None,
        env_config=settings,
        transport_factory: PoolTransportFactory | None = None,
    ) -> None:
        self._repository = repository
        self._redis = redis_client
        self._env = env_config
        self._transport_factory = transport_factory or self._default_transport_factory

    def _default_transport_factory(
        self, entries: list[EmailPoolEntry]
    ) -> EmailPoolTransport:
        return EmailPoolTransport(entries, quota=EmailPoolQuotaStore(self._redis))

    async def get_config(self) -> EmailPoolConfigProjection:
        effective = resolve_email_pool_config(env=self._env)
        updated_at = await asyncio.to_thread(self._saved_updated_at)
        return self._to_projection(effective.entries_json, effective.source, updated_at)

    async def update_config(
        self, values: Mapping[str, Any]
    ) -> EmailPoolConfigProjection:
        raw_entries = values.get("entries") or []
        if not isinstance(raw_entries, list):
            raise ValueError("entries 必须是数组")
        if not raw_entries:
            # 文档化语义：空列表即删除 DB 覆盖行，整体回退 EMAIL_POOL_JSON env
            await asyncio.to_thread(self._repository.delete_email_pool_settings)
            invalidate_email_pool_config_cache()
            return await self.get_config()
        if len(raw_entries) > _MAX_ENTRIES:
            raise ValueError(f"邮件池最多 {_MAX_ENTRIES} 个服务商")

        existing_row = await asyncio.to_thread(
            self._repository.get_email_pool_settings
        )
        stored_passwords = (
            {
                entry.name: entry.password
                for entry in parse_email_pool_entries(existing_row.entries_json)
            }
            if existing_row is not None
            else {}
        )

        normalized: list[EmailPoolEntry] = []
        seen_names: set[str] = set()
        for index, item in enumerate(raw_entries):
            if not isinstance(item, Mapping):
                raise ValueError(f"第 {index + 1} 个服务商不是对象")
            entry = self._normalize_entry(item, stored_passwords)
            if entry.name in seen_names:
                raise ValueError(f"服务商名称重复：{entry.name}")
            seen_names.add(entry.name)
            normalized.append(entry)

        canonical = json.dumps(
            [
                {key: getattr(entry, key) for key in _ENTRY_JSON_KEYS}
                for entry in sorted(normalized, key=lambda entry: entry.priority)
            ],
            ensure_ascii=False,
        )
        saved = await asyncio.to_thread(
            self._repository.upsert_email_pool_settings, entries_json=canonical
        )
        invalidate_email_pool_config_cache()
        effective = resolve_email_pool_config(env=self._env)
        return self._to_projection(
            effective.entries_json,
            effective.source,
            saved.updated_at.isoformat() if saved.updated_at else None,
        )

    async def send_test_email(self, to_email: str) -> dict[str, Any]:
        """经真实邮件池（含 failover 与配额计数）向指定邮箱投递测试邮件。"""
        # 测试必须命中最新配置：池与 legacy 合并源两个缓存都即时失效
        invalidate_email_pool_config_cache()
        invalidate_smtp_config_cache()
        effective_pool = resolve_email_pool_config(env=self._env)
        legacy = resolve_smtp_config(env=self._env)
        entries = merge_legacy_entry(
            parse_email_pool_entries(
                effective_pool.entries_json,
                default_from_email=legacy.from_email,
                default_from_name=legacy.from_name,
            ),
            host=legacy.host,
            port=legacy.port,
            username=legacy.username,
            password=legacy.password,
            from_email=legacy.from_email,
            from_name=legacy.from_name,
            use_tls=legacy.use_tls,
        )
        if not entries:
            raise EmailPoolNotConfiguredError(
                "邮件池未配置：请先保存池配置或设置 EMAIL_POOL_JSON 环境变量"
            )

        transport = self._transport_factory(entries)
        body = (
            "这是一封来自 AIGCNEWS 的邮件池配置测试邮件。\n\n"
            f"池配置来源：{effective_pool.source}\n"
            f"池内服务商：{', '.join(entry.name for entry in entries)}\n"
            "如果您收到此邮件，说明邮件池可以正常投递。"
        )
        started = time.monotonic()
        try:
            provider = await transport.send_plain(
                to_email, "AIGCNEWS 邮件池配置测试邮件", body
            )
        except SmtpDeliveryError as exc:
            # 各 entry 的原始异常已进服务端日志（pool_transport 逐条记录）；
            # 回显通用文案，不带类名（防指纹化内部栈，对齐 SMTP 测试口径）
            logger.warning(
                "[EMAIL_POOL] 测试邮件池内全部投递失败 to=%s", to_email
            )
            raise EmailPoolTestDeliveryError(
                "邮件池内全部服务商投递失败或不可用，请检查各服务商配置与配额"
            ) from exc
        latency_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "[EMAIL_POOL] 测试邮件已发送 to=%s provider=%s latency_ms=%d",
            to_email,
            provider,
            latency_ms,
        )
        return {
            "status": "success",
            "message": f"测试邮件已经过 {provider} 投递至 {to_email}",
            "to_email": to_email,
            "provider": provider,
            "latency_ms": latency_ms,
        }

    def _normalize_entry(
        self, item: Mapping[str, Any], stored_passwords: Mapping[str, str]
    ) -> EmailPoolEntry:
        name = str(item.get("name") or "").strip()
        if not 1 <= len(name) <= 64:
            raise ValueError("服务商名称长度须在 1-64 之间")
        host = validate_email_host(str(item.get("host") or ""))
        try:
            port = int(item.get("port") or 587)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name}：端口必须是数字") from exc
        if not 1 <= port <= 65535:
            raise ValueError(f"{name}：端口必须在 1-65535 之间")
        from_email = str(item.get("from_email") or "").strip()
        if from_email and not FROM_EMAIL_PATTERN.match(from_email):
            raise ValueError(f"{name}：发件邮箱格式不正确")
        try:
            daily_limit = max(0, int(item.get("daily_limit") or 0))
            monthly_limit = max(0, int(item.get("monthly_limit") or 0))
            priority = int(item.get("priority", 100))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name}：限额与优先级必须是数字") from exc

        if bool(item.get("clear_password", False)):
            password = ""
        elif item.get("password"):
            password = str(item["password"])
        else:
            password = stored_passwords.get(name, "")

        return EmailPoolEntry(
            name=name,
            host=host,
            port=port,
            username=str(item.get("username") or "").strip(),
            password=password,
            from_email=from_email,
            from_name=str(item.get("from_name") or "").strip(),
            use_tls=bool(item.get("use_tls", True)),
            daily_limit=daily_limit,
            monthly_limit=monthly_limit,
            priority=priority,
        )

    def _saved_updated_at(self) -> str | None:
        row = self._repository.get_email_pool_settings()
        if row is None or row.updated_at is None:
            return None
        return row.updated_at.isoformat()

    def _to_projection(
        self, entries_json: str, source: str, updated_at: str | None
    ) -> EmailPoolConfigProjection:
        legacy = resolve_smtp_config(env=self._env)
        entries = parse_email_pool_entries(
            entries_json,
            default_from_email=legacy.from_email,
            default_from_name=legacy.from_name,
        )
        return EmailPoolConfigProjection(
            entries=[
                EmailPoolEntryProjection(
                    name=entry.name,
                    host=entry.host,
                    port=entry.port,
                    username=entry.username,
                    password_configured=bool(entry.password),
                    password_masked=mask_token(entry.password),
                    from_email=entry.from_email,
                    from_name=entry.from_name,
                    use_tls=entry.use_tls,
                    daily_limit=entry.daily_limit,
                    monthly_limit=entry.monthly_limit,
                    priority=entry.priority,
                )
                for entry in entries
            ],
            source=source,
            updated_at=updated_at,
        )
