from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from backend.app.core.config import settings
from backend.app.repositories.oauth_settings_repository import OAuthSettingsManager
from backend.app.services.auth.oauth.contracts import parse_enabled_oauth_providers
from backend.app.services.auth.oauth.runtime_config import (
    EffectiveOAuthConfig,
    effective_oauth_config_from_row,
    invalidate_oauth_config_cache,
    resolve_oauth_config,
)
from backend.app.services.secret_masking import mask_token

_SECRET_FIELDS = (
    "github_client_secret",
    "google_client_secret",
    "wechat_app_secret",
    "qq_client_secret",
    "linuxdo_client_secret",
)
_CLIENT_ID_FIELDS = (
    "github_client_id",
    "google_client_id",
    "wechat_app_id",
    "qq_client_id",
    "linuxdo_client_id",
)


@dataclass(frozen=True, slots=True)
class OAuthConfigProjection:
    enabled_providers: list[str]
    public_base_url: str
    github_client_id: str
    google_client_id: str
    wechat_app_id: str
    qq_client_id: str
    linuxdo_client_id: str
    state_ttl_seconds: int
    handoff_ttl_seconds: int
    source: str
    updated_at: str | None
    github_client_secret_configured: bool
    github_client_secret_masked: str | None
    google_client_secret_configured: bool
    google_client_secret_masked: str | None
    wechat_app_secret_configured: bool
    wechat_app_secret_masked: str | None
    qq_client_secret_configured: bool
    qq_client_secret_masked: str | None
    linuxdo_client_secret_configured: bool
    linuxdo_client_secret_masked: str | None


class OAuthConfigAdminService:
    def __init__(self, repository: OAuthSettingsManager, *, env_config=settings) -> None:
        self._repository = repository
        self._env = env_config

    async def get_config(self) -> OAuthConfigProjection:
        effective = resolve_oauth_config(env=self._env)
        row = await asyncio.to_thread(self._repository.get_oauth_settings)
        return self._to_projection(
            effective,
            row.updated_at.isoformat() if row and row.updated_at else None,
        )

    async def update_config(self, values: Mapping[str, Any]) -> OAuthConfigProjection:
        enabled = parse_enabled_oauth_providers(
            ",".join(str(item) for item in values.get("enabled_providers", []) or [])
            if isinstance(values.get("enabled_providers"), list)
            else str(values.get("enabled_providers") or "")
        )
        base_url = str(values.get("public_base_url") or "").strip().rstrip("/")
        if base_url:
            parsed = urlsplit(base_url)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.query
                or parsed.fragment
                or parsed.username
                or parsed.password
                or "\\" in base_url
            ):
                raise ValueError("OAuth 公网基址必须是无 query/fragment 的 http(s) 绝对地址")
        state_ttl = int(values.get("state_ttl_seconds") or 300)
        handoff_ttl = int(values.get("handoff_ttl_seconds") or 120)
        if not 60 <= state_ttl <= 900:
            raise ValueError("OAuth state TTL 必须在 60-900 秒之间")
        if not 30 <= handoff_ttl <= 600:
            raise ValueError("OAuth handoff TTL 必须在 30-600 秒之间")

        existing = await asyncio.to_thread(self._repository.get_oauth_settings)
        secrets: dict[str, str] = {}
        for field in _SECRET_FIELDS:
            submitted = values.get(field)
            if bool(values.get(f"clear_{field}", False)):
                secrets[field] = ""
            elif submitted:
                value = str(submitted).strip()
                if value.upper().startswith("CHANGEME"):
                    raise ValueError("OAuth secret 不得使用 CHANGEME 示例占位符")
                secrets[field] = value
            else:
                secrets[field] = getattr(existing, field, "") if existing else ""

        saved = await asyncio.to_thread(
            self._repository.upsert_oauth_settings,
            enabled_providers=",".join(enabled),
            public_base_url=base_url,
            github_client_id=str(values.get("github_client_id") or "").strip(),
            github_client_secret=secrets["github_client_secret"],
            google_client_id=str(values.get("google_client_id") or "").strip(),
            google_client_secret=secrets["google_client_secret"],
            wechat_app_id=str(values.get("wechat_app_id") or "").strip(),
            wechat_app_secret=secrets["wechat_app_secret"],
            qq_client_id=str(values.get("qq_client_id") or "").strip(),
            qq_client_secret=secrets["qq_client_secret"],
            linuxdo_client_id=str(values.get("linuxdo_client_id") or "").strip(),
            linuxdo_client_secret=secrets["linuxdo_client_secret"],
            state_ttl_seconds=state_ttl,
            handoff_ttl_seconds=handoff_ttl,
        )
        invalidate_oauth_config_cache()
        # 投影直接基于刚保存的行：与运行时解析路径一致，且不依赖缓存可见性，
        # 保证响应里立即反映本次保存的密文（不回明文，仅 configured/masked）。
        return self._to_projection(
            effective_oauth_config_from_row(saved),
            saved.updated_at.isoformat() if saved.updated_at else None,
        )

    async def reset_config(self) -> OAuthConfigProjection:
        await asyncio.to_thread(self._repository.delete_oauth_settings)
        invalidate_oauth_config_cache()
        return await self.get_config()

    @staticmethod
    def _to_projection(
        config: EffectiveOAuthConfig,
        updated_at: str | None,
    ) -> OAuthConfigProjection:
        secret_projection: dict[str, Any] = {}
        for field in _SECRET_FIELDS:
            value = getattr(config, field)
            secret_projection[f"{field}_configured"] = bool(value)
            secret_projection[f"{field}_masked"] = mask_token(value)
        return OAuthConfigProjection(
            enabled_providers=list(config.enabled_providers),
            public_base_url=config.public_base_url,
            github_client_id=config.github_client_id,
            google_client_id=config.google_client_id,
            wechat_app_id=config.wechat_app_id,
            qq_client_id=config.qq_client_id,
            linuxdo_client_id=config.linuxdo_client_id,
            state_ttl_seconds=config.state_ttl_seconds,
            handoff_ttl_seconds=config.handoff_ttl_seconds,
            source=config.source,
            updated_at=updated_at,
            **secret_projection,
        )
