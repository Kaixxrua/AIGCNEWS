from __future__ import annotations

import pytest

from backend.tests import postgres_test_safety as safety


class FakeConnection:
    def __init__(self, row):
        self.row = row
        self.statements: list[str] = []

    def execute(self, statement, params=None):
        self.statements.append(str(statement))
        return self

    def fetchone(self):
        return self.row


@pytest.fixture
def valid_env() -> dict[str, str]:
    return {
        "TEST_POSTGRES_DSN": "host=127.0.0.1 port=5433 user=aigcnews_test dbname=aigcnews_test password=secret",
        "TEST_POSTGRES_RUN_ID": "ci-run-123",
    }


def test_parse_requires_explicit_safe_identity_and_ignores_application_settings(valid_env):
    parsed = safety._parse_test_config(valid_env)
    assert parsed[0] == valid_env["TEST_POSTGRES_DSN"]
    assert parsed[2]["dbname"] == "aigcnews_test"

    with pytest.raises(safety.PostgresTestSafetyError):
        safety._parse_test_config({"POSTGRES_DATABASE": "aigcnews_test"})


def test_database_name_policy_rejects_misleading_names(valid_env):
    for database in ("production_test", "aigcnews_testing", "aigcnews_test;drop", "aigcnews_test_"):
        invalid = {**valid_env, "TEST_POSTGRES_DSN": valid_env["TEST_POSTGRES_DSN"].replace("dbname=aigcnews_test", f"dbname={database}")}
        with pytest.raises(safety.PostgresTestSafetyError):
            safety._parse_test_config(invalid)


def test_verify_live_target_requires_exact_database_user_server_and_marker(monkeypatch, valid_env):
    monkeypatch.setattr(safety, "_expected_addresses", lambda host, port: {"127.0.0.1"})
    _, run_id, params = safety._parse_test_config(valid_env)
    connection = FakeConnection(
        {
            "database": "aigcnews_test",
            "username": "aigcnews_test",
            "server_addr": "127.0.0.1",
            "server_port": 5433,
            "marker_run_id": run_id,
        }
    )
    safety.verify_live_test_target(connection, params, run_id)

    for field, value in (("database", "aigcnews_test_backup"), ("username", "postgres"), ("marker_run_id", "other-run")):
        row = dict(connection.row)
        row[field] = value
        with pytest.raises(safety.PostgresTestSafetyError):
            safety.verify_live_test_target(FakeConnection(row), params, run_id)


def test_redaction_never_leaks_password():
    message = safety.redact_postgres_secrets(
        "postgresql://user:super-secret@db.example/aigcnews_test password=another-secret"
    )
    assert "super-secret" not in message
    assert "another-secret" not in message
    assert "***" in message


def test_legacy_opt_in_is_not_a_connection_authority(valid_env):
    assert safety.legacy_bootstrap_error({"POSTGRES_INTEGRATION": "1"}) is not None
    assert safety.legacy_bootstrap_error({**valid_env, "POSTGRES_INTEGRATION": "1"}) is None


def test_missing_dsn_skips_only_when_helper_is_invoked():
    with pytest.raises(pytest.skip.Exception):
        with safety.postgres_test_sandbox(environ={}):
            pass
