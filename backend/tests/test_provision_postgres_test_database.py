from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "provision_postgres_test_database", ROOT / "scripts" / "provision_postgres_test_database.py"
)
assert _SPEC and _SPEC.loader
_module = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_module)


ADMIN_DSN = "host=127.0.0.1 port=5432 user=test_admin dbname=postgres password=secret"


def test_database_name_is_test_prefixed_and_bounded(monkeypatch) -> None:
    monkeypatch.setattr(_module.secrets, "token_hex", lambda size: "a" * (size * 2))
    name = _module.database_name("ci/run-1")
    assert name == "aigcnews_test_ci_run_1_" + "a" * 20
    assert len(name) <= 63


def test_admin_dsn_requires_explicit_connection_identity() -> None:
    with pytest.raises(ValueError, match="explicitly set dbname"):
        _module._admin_params("host=127.0.0.1 user=admin port=5432")


def test_drop_rejects_non_test_database_before_connect(monkeypatch) -> None:
    monkeypatch.setattr(_module, "connect", lambda *args, **kwargs: pytest.fail("must not connect"))
    with pytest.raises(ValueError, match="outside the test prefix"):
        _module.drop_database(ADMIN_DSN, "aigcnews_production")


def test_provision_bootstrap_failure_reports_exact_orphan(monkeypatch) -> None:
    class Admin:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, statement, *args):
            return None

    calls = []

    def fake_connect(dsn, **kwargs):
        calls.append(dsn)
        if len(calls) == 1:
            return Admin()
        raise RuntimeError("bootstrap unavailable")

    monkeypatch.setattr(_module, "connect", fake_connect)
    monkeypatch.setattr(_module.secrets, "token_hex", lambda size: "b" * (size * 2))
    monkeypatch.setattr(_module, "drop_database", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("drop failed")))
    with pytest.raises(RuntimeError, match="orphaned PostgreSQL test database: aigcnews_test_ci_"):
        _module.provision(ADMIN_DSN, "ci")
    assert calls[0] == ADMIN_DSN
    assert _module.conninfo_to_dict(calls[1])["dbname"] == (
        "aigcnews_test_ci_bbbbbbbbbbbbbbbbbbbb"
    )
