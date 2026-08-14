from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class EmailPoolSettings:
    """单行持久化的邮件池配置。

    entries_json 为 JSON 数组文本，空字符串表示未设置（回退 env
    EMAIL_POOL_JSON）；元素字段对齐 pool_transport.EmailPoolEntry。
    其中凭据明文落库，与 smtp_settings.password 同水位（爆破半径
    1→N），脱敏只发生在 API 投影层。
    """

    entries_json: str
    updated_at: datetime | None = None


class EmailPoolSettingsReader(Protocol):
    def get_email_pool_settings(self) -> EmailPoolSettings | None: ...


class EmailPoolSettingsManager(EmailPoolSettingsReader, Protocol):
    def upsert_email_pool_settings(self, *, entries_json: str) -> EmailPoolSettings: ...

    def delete_email_pool_settings(self) -> int: ...


class EmailPoolSettingsRepository(EmailPoolSettingsManager, Protocol):
    """Persistence boundary for the singleton email pool settings row."""
