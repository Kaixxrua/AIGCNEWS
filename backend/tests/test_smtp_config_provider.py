"""smtp_config_provider 的解析优先级与缓存语义契约测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.repositories.smtp_settings_repository import SmtpSettings
from backend.app.services.email import smtp_config_provider
from backend.app.services.email.smtp_config_provider import (
    configure_smtp_settings_reader,
    invalidate_smtp_config_cache,
    reset_smtp_config_provider,
    resolve_smtp_config,
)


@pytest.fixture(autouse=True)
def _reset_provider():
    reset_smtp_config_provider()
    yield
    reset_smtp_config_provider()


def _env(**overrides):
    values = {
        "SMTP_HOST": "env-smtp.example.test",
        "SMTP_PORT": 2525,
        "SMTP_USERNAME": "env-user",
        "SMTP_PASSWORD": "env-password",
        "SMTP_FROM_EMAIL": "env@example.test",
        "SMTP_FROM_NAME": "Env Sender",
        "SMTP_USE_TLS": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _row(**overrides) -> SmtpSettings:
    values = {
        "host": "db-smtp.example.test",
        "port": 465,
        "username": "db-user",
        "password": "db-password",
        "from_email": "db@example.test",
        "from_name": "DB Sender",
        "use_tls": True,
    }
    values.update(overrides)
    return SmtpSettings(**values)


class _StubReader:
    def __init__(self, row: SmtpSettings | None = None, error: Exception | None = None):
        self._row = row
        self._error = error
        self.calls = 0

    def get_smtp_settings(self) -> SmtpSettings | None:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._row


def test_database_row_wins_over_env() -> None:
    configure_smtp_settings_reader(_StubReader(_row()))

    config = resolve_smtp_config(env=_env())

    assert config.source == "database"
    assert config.host == "db-smtp.example.test"
    assert config.port == 465
    assert config.username == "db-user"
    assert config.password == "db-password"
    assert config.from_email == "db@example.test"
    assert config.from_name == "DB Sender"
    assert config.use_tls is True


def test_empty_database_password_chains_env_password() -> None:
    # 唯一保留的 env 链：DB 行密码被清空时回退 env 密码
    configure_smtp_settings_reader(_StubReader(_row(password="")))

    config = resolve_smtp_config(env=_env())

    assert config.source == "database"
    assert config.password == "env-password"


def test_missing_row_falls_back_to_environment() -> None:
    configure_smtp_settings_reader(_StubReader(None))

    config = resolve_smtp_config(env=_env())

    assert config.source == "environment"
    assert config.host == "env-smtp.example.test"
    assert config.port == 2525
    assert config.password == "env-password"
    assert config.use_tls is False


def test_unconfigured_when_no_row_and_no_env_host() -> None:
    configure_smtp_settings_reader(_StubReader(None))

    config = resolve_smtp_config(env=_env(SMTP_HOST=""))

    assert config.source == "unconfigured"
    assert config.host == ""


def test_unbound_reader_reads_env_silently() -> None:
    # reader 未绑定（调度器/测试上下文）：静默 env 回退，行为与改造前一致
    config = resolve_smtp_config(env=_env())

    assert config.source == "environment"
    assert config.host == "env-smtp.example.test"


def test_reader_exception_falls_back_to_env() -> None:
    configure_smtp_settings_reader(_StubReader(error=RuntimeError("table missing")))

    config = resolve_smtp_config(env=_env())

    assert config.source == "environment"
    assert config.host == "env-smtp.example.test"


def test_cache_hit_within_ttl_reads_row_once() -> None:
    reader = _StubReader(_row())
    configure_smtp_settings_reader(reader)

    first = resolve_smtp_config(env=_env())
    second = resolve_smtp_config(env=_env())

    assert first is second
    assert reader.calls == 1


def test_cache_expiry_re_reads_row(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = _StubReader(_row())
    configure_smtp_settings_reader(reader)
    monkeypatch.setattr(smtp_config_provider, "_CACHE_TTL_SECONDS", 0.0)

    resolve_smtp_config(env=_env())
    resolve_smtp_config(env=_env())

    assert reader.calls == 2


def test_invalidate_forces_re_read() -> None:
    reader = _StubReader(_row())
    configure_smtp_settings_reader(reader)

    resolve_smtp_config(env=_env())
    invalidate_smtp_config_cache()
    resolve_smtp_config(env=_env())

    assert reader.calls == 2


def test_reconfigure_reader_drops_cache() -> None:
    stale = _StubReader(_row(host="stale.example.test"))
    fresh = _StubReader(_row(host="fresh.example.test"))
    configure_smtp_settings_reader(stale)
    assert resolve_smtp_config(env=_env()).host == "stale.example.test"

    configure_smtp_settings_reader(fresh)

    assert resolve_smtp_config(env=_env()).host == "fresh.example.test"
    assert fresh.calls == 1
