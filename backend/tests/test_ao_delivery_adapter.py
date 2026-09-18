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


def test_reconcile_detects_new_main_and_rechecks_head(db, monkeypatch):
    db.execute("UPDATE tasks SET stage='active'")
    monkeypatch.setattr(adapter, "git", lambda _, *args: "a" * 40 if args[0] == "rev-parse" else "")
    pr = {"state": "open", "head": {"ref": "session/example", "sha": "a" * 40,
          "repo": {"full_name": "Kaixxrua/AIGCNEWS"}}, "html_url": "https://github.com/Kaixxrua/AIGCNEWS/pull/69"}
    client = Mock()
    client.request.side_effect = [pr, {"object": {"sha": "b" * 40}}, {"status": "diverged"}, pr]
    sender = Mock(return_value="accepted")
    monkeypatch.setattr(adapter, "send", sender)
    assert adapter.reconcile(db, client, ".")[0]["result"] == "accepted"
    assert sender.call_args.args[2] == "69:" + "a" * 40 + ":base_update"
    client.contract_runs.assert_not_called()


def test_reconcile_does_not_interrupt_dirty_task(db, monkeypatch):
    db.execute("UPDATE tasks SET stage='active'")
    monkeypatch.setattr(adapter, "git", lambda _, *args: "a" * 40 if args[0] == "rev-parse" else " M file")
    client = Mock()
    client.request.return_value = {"state": "open", "head": {"ref": "session/example", "sha": "a" * 40,
        "repo": {"full_name": "Kaixxrua/AIGCNEWS"}}}
    assert adapter.reconcile(db, client, ".") == []
    assert client.request.call_count == 1
