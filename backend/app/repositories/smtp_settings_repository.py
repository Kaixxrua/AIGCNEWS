from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class SmtpSettings:
    """单行持久化的 SMTP 投递配置。

    空字符串表示该字段未设置（全列 NOT NULL，无 NULL 分支）；
    password 为明文落库，与 env 配置同水位，脱敏只发生在 API 投影层。
    """

    host: str
    port: int
    username: str
    password: str
    from_email: str
    from_name: str
    use_tls: bool
    updated_at: datetime | None = None


class SmtpSettingsReader(Protocol):
    def get_smtp_settings(self) -> SmtpSettings | None: ...


class SmtpSettingsManager(SmtpSettingsReader, Protocol):
    def upsert_smtp_settings(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        from_email: str,
        from_name: str,
        use_tls: bool,
    ) -> SmtpSettings: ...

    def delete_smtp_settings(self) -> int: ...


class SmtpSettingsRepository(SmtpSettingsManager, Protocol):
    """Persistence boundary for the singleton SMTP settings row."""
