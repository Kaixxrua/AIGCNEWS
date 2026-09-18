import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location("ao_adapter", Path(__file__).parents[2] / "scripts/ci/ao_delivery_adapter.py")
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "verify_workspace", Mock())
    monkeypatch.setattr(adapter, "ao_read", lambda _: {"session": {"id": "standalone-2"}})
    with adapter.database(tmp_path / "state.sqlite") as conn:
        adapter.bind(conn, "session/example", "standalone-2", tmp_path, "original task receipt", tmp_path, 69)
        yield conn


def ready(session):
    return {"session": {"id": session, "activity": {"state": "idle"}}}


def test_migrated_task_is_initially_held(db):
    deliver = Mock()
    assert adapter.send(db, "session/example", "event", "message", ".", read=ready, deliver=deliver) == "held"
    deliver.assert_not_called()


def test_exact_target_and_idempotency(db):
    db.execute("UPDATE tasks SET stage='active'")
    deliver = Mock(return_value={"accepted": True})
    assert adapter.send(db, "session/example", "event", "message", ".", read=ready, deliver=deliver) == "accepted"
    assert adapter.send(db, "session/example", "event", "message", ".", read=ready, deliver=deliver) == "duplicate"
    deliver.assert_called_once()
    assert deliver.call_args.args[0] == "standalone-2"


@pytest.mark.parametrize("info", [
    {"id": "another-task", "activity": {"state": "idle"}},
    {"id": "standalone-2", "activity": {"state": "working"}},
    {"id": "standalone-2", "activity": {"state": "idle"}, "isTerminated": True},
])
def test_busy_or_wrong_target_waits(db, info):
    db.execute("UPDATE tasks SET stage='active'")
    deliver = Mock()
    assert adapter.send(db, "session/example", "event", "message", ".", read=lambda _: {"session": info}, deliver=deliver) == "waiting"
    deliver.assert_not_called()


def test_ambiguous_delivery_never_replays(db):
    db.execute("UPDATE tasks SET stage='active'")
    deliver = Mock(side_effect=TimeoutError())
    with pytest.raises(TimeoutError):
        adapter.send(db, "session/example", "event", "message", ".", read=ready, deliver=deliver)
    assert adapter.send(db, "session/example", "event", "message", ".", read=ready, deliver=deliver) == "duplicate"
    assert db.execute("SELECT status FROM events").fetchone()[0] == "unconfirmed"


def test_branch_change_prevents_send(db, monkeypatch):
    db.execute("UPDATE tasks SET stage='active'")
    monkeypatch.setattr(adapter, "verify_workspace", Mock(side_effect=ValueError("changed")))
    deliver = Mock()
    with pytest.raises(ValueError):
        adapter.send(db, "session/example", "event", "message", ".", read=ready, deliver=deliver)
    deliver.assert_not_called()
