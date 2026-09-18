import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location(
    "delivery_feedback", Path(__file__).parents[2] / "scripts/ci/delivery_feedback.py")
feedback = importlib.util.module_from_spec(spec)
spec.loader.exec_module(feedback)
THREAD = "01a0a9b2-7db0-78a2-a960-cfc652157d21"


def event(db):
    return feedback.enqueue(db, thread_id=THREAD, pr=66, sha="a"*40,
                            kind="conflict", url="https://github.com/Kaixxrua/AIGCNEWS/pull/66")


def test_duplicate_fault_creates_only_one_event(tmp_path):
    with feedback.open_db(tmp_path / "events.db") as db:
        assert event(db) == event(db)
        assert db.execute("SELECT count(*) FROM feedback").fetchone()[0] == 1


@pytest.mark.parametrize("paused,idle", [(True, True), (False, False)])
def test_pause_or_busy_never_wakes(tmp_path, paused, idle):
    with feedback.open_db(tmp_path / "events.db") as db:
        key = event(db)
        bridge = Mock()
        bridge.idle.return_value = idle
        assert feedback.dispatch(db, key, bridge, current_sha="a"*40, paused=paused) == "waiting"
        bridge.wake.assert_not_called()


def test_old_sha_is_obsolete_not_delivered(tmp_path):
    with feedback.open_db(tmp_path / "events.db") as db:
        bridge = Mock()
        assert feedback.dispatch(db, event(db), bridge, current_sha="b"*40, paused=False) == "obsolete"
        bridge.wake.assert_not_called()


def test_acknowledged_wakeup_is_not_repeated(tmp_path):
    with feedback.open_db(tmp_path / "events.db") as db:
        key = event(db)
        bridge = Mock()
        bridge.idle.return_value = True
        bridge.wake.return_value = {"turn": {"id": "turn-one"}}
        assert feedback.dispatch(db, key, bridge, current_sha="a"*40, paused=False) == "sent"
        assert feedback.dispatch(db, key, bridge, current_sha="a"*40, paused=False) == "unchanged"
        bridge.wake.assert_called_once()


def test_timeout_does_not_cause_duplicate_turn(tmp_path):
    with feedback.open_db(tmp_path / "events.db") as db:
        key = event(db)
        bridge = Mock()
        bridge.idle.return_value = True
        bridge.wake.side_effect = TimeoutError()
        with pytest.raises(TimeoutError):
            feedback.dispatch(db, key, bridge, current_sha="a"*40, paused=False)
        assert feedback.dispatch(db, key, bridge, current_sha="a"*40, paused=False) == "unchanged"


def test_bridge_protocol_and_inherited_configuration(monkeypatch):
    connection = Mock()
    connection.recv.side_effect = [
        json.dumps({"id": 1, "result": {}}),
        json.dumps({"method": "notification"}),
        json.dumps({"id": 2, "result": {"thread": {"status": {"type": "idle"}}}}),
        json.dumps({"id": 3, "result": {"turn": {"id": "receipt"}}}),
    ]
    connect = Mock(return_value=connection)
    monkeypatch.setattr("websockets.sync.client.unix_connect", connect)
    with feedback.CodexBridge() as bridge:
        assert bridge.wake(THREAD, "test")["turn"]["id"] == "receipt"
    messages = [json.loads(call.args[0]) for call in connection.send.call_args_list]
    assert [m["method"] for m in messages] == ["initialize", "initialized", "thread/read", "turn/start"]
    assert messages[-1]["params"] == {"threadId": THREAD, "input": [
        {"type": "text", "text": "test", "text_elements": []}]}
    assert connect.call_args.kwargs["proxy"] is None
    connection.close.assert_called_once()


def test_bridge_rechecks_busy_before_start():
    bridge = feedback.CodexBridge()
    bridge.call = Mock(return_value={"thread": {"status": {"type": "active"}}})
    with pytest.raises(feedback.BridgeError):
        bridge.wake(THREAD, "test")
    bridge.call.assert_called_once_with("thread/read", {"threadId": THREAD, "includeTurns": False})
