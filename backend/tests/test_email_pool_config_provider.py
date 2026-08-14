"""pool_config_provider 的解析优先级与缓存语义契约测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.repositories.email_pool_settings_repository import EmailPoolSettings
from backend.app.services.email import pool_config_provider
from backend.app.services.email.pool_config_provider import (
    configure_email_pool_settings_reader,
    invalidate_email_pool_config_cache,
    reset_email_pool_config_provider,
    resolve_email_pool_config,
)

_DB_JSON = '[{"name":"brevo","host":"smtp-relay.brevo.test","priority":10}]'
_ENV_JSON = '[{"name":"resend","host":"smtp.resend.test","priority":10}]'


@pytest.fixture(autouse=True)
def _reset_provider():
    reset_email_pool_config_provider()
    yield
    reset_email_pool_config_provider()


def _env(**overrides):
    values = {"EMAIL_POOL_JSON": _ENV_JSON}
    values.update(overrides)
    return SimpleNamespace(**values)


def _row(entries_json: str = _DB_JSON) -> EmailPoolSettings:
    return EmailPoolSettings(entries_json=entries_json)


class _StubReader:
    def __init__(
        self, row: EmailPoolSettings | None = None, error: Exception | None = None
    ):
        self._row = row
        self._error = error
        self.calls = 0

    def get_email_pool_settings(self) -> EmailPoolSettings | None:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._row


def test_database_row_wins_over_env() -> None:
    configure_email_pool_settings_reader(_StubReader(_row()))

    config = resolve_email_pool_config(env=_env())

    assert config.source == "database"
    assert config.entries_json == _DB_JSON


def test_missing_row_falls_back_to_environment() -> None:
    configure_email_pool_settings_reader(_StubReader(None))

    config = resolve_email_pool_config(env=_env())

    assert config.source == "environment"
    assert config.entries_json == _ENV_JSON


def test_empty_database_entries_fall_back_to_env() -> None:
    configure_email_pool_settings_reader(_StubReader(_row("  ")))

    config = resolve_email_pool_config(env=_env())

    assert config.source == "environment"


def test_invalid_database_json_falls_back_to_env() -> None:
    # 损坏行不得锁死发送链路：记警告并回退 env（fail-soft）
    configure_email_pool_settings_reader(_StubReader(_row("{broken")))

    config = resolve_email_pool_config(env=_env())

    assert config.source == "environment"


def test_database_row_with_zero_valid_entries_falls_back_to_env() -> None:
    configure_email_pool_settings_reader(_StubReader(_row('[{"name":"x"}]')))

    config = resolve_email_pool_config(env=_env())

    assert config.source == "environment"


def test_unconfigured_when_no_row_and_no_env_pool() -> None:
    configure_email_pool_settings_reader(_StubReader(None))

    config = resolve_email_pool_config(env=_env(EMAIL_POOL_JSON=""))

    assert config.source == "unconfigured"
    assert config.entries_json == ""


def test_invalid_env_json_is_unconfigured() -> None:
    configure_email_pool_settings_reader(_StubReader(None))

    config = resolve_email_pool_config(env=_env(EMAIL_POOL_JSON="{broken"))

    assert config.source == "unconfigured"
    assert config.entries_json == ""


def test_unbound_reader_reads_env_silently() -> None:
    # reader 未绑定（调度器/测试上下文）：静默 env 回退
    config = resolve_email_pool_config(env=_env())

    assert config.source == "environment"
    assert config.entries_json == _ENV_JSON


def test_reader_exception_falls_back_to_env() -> None:
    configure_email_pool_settings_reader(
        _StubReader(error=RuntimeError("table missing"))
    )

    config = resolve_email_pool_config(env=_env())

    assert config.source == "environment"


def test_cache_hit_within_ttl_reads_row_once() -> None:
    reader = _StubReader(_row())
    configure_email_pool_settings_reader(reader)

    first = resolve_email_pool_config(env=_env())
    second = resolve_email_pool_config(env=_env())

    assert first is second
    assert reader.calls == 1


def test_cache_expiry_re_reads_row(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = _StubReader(_row())
    configure_email_pool_settings_reader(reader)
    monkeypatch.setattr(pool_config_provider, "_CACHE_TTL_SECONDS", 0.0)

    resolve_email_pool_config(env=_env())
    resolve_email_pool_config(env=_env())

    assert reader.calls == 2


def test_invalidate_forces_re_read() -> None:
    reader = _StubReader(_row())
    configure_email_pool_settings_reader(reader)

    resolve_email_pool_config(env=_env())
    invalidate_email_pool_config_cache()
    resolve_email_pool_config(env=_env())

    assert reader.calls == 2


def test_reconfigure_reader_drops_cache() -> None:
    stale = _StubReader(_row('[{"name":"stale","host":"smtp.stale.test"}]'))
    fresh = _StubReader(_row('[{"name":"fresh","host":"smtp.fresh.test"}]'))
    configure_email_pool_settings_reader(stale)
    assert "stale" in resolve_email_pool_config(env=_env()).entries_json

    configure_email_pool_settings_reader(fresh)

    assert "fresh" in resolve_email_pool_config(env=_env()).entries_json
    assert fresh.calls == 1
