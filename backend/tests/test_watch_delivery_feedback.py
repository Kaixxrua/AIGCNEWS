import copy
import importlib
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest


@pytest.fixture
def watcher(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[2] / "scripts/ci"))
    sys.modules.pop("watch_delivery_feedback", None)
    module = importlib.import_module("watch_delivery_feedback")
    monkeypatch.setattr(module, "resolve_owner", Mock(return_value="01a0a9b2-7db0-78a2-a960-cfc652157d21"))
    return module


@pytest.fixture
def inputs():
    snapshot = {"generated_at": datetime.now(UTC).isoformat(), "sessions": [{
        "association": "verified", "thread_id": "01a0a9b2-7db0-78a2-a960-cfc652157d21",
        "deliveries": [{"pr": 66, "sha": "a" * 40, "branch": "session/example"}],
    }]}
    pr = {"state": "open", "draft": False, "base": {"ref": "main"},
          "head": {"sha": "a" * 40, "ref": "session/example", "repo": {"full_name": "Kaixxrua/AIGCNEWS"}},
          "mergeable": False, "mergeable_state": "dirty", "html_url": "https://github.com/Kaixxrua/AIGCNEWS/pull/66"}
    client = Mock()
    client.request.return_value = pr
    bridge = Mock()
    bridge.idle.return_value = True
    bridge.wake.return_value = {"turn": {"id": "receipt"}}
    return snapshot, pr, client, bridge


def test_conflict_wakes_once(watcher, inputs, tmp_path):
    snapshot, _, client, bridge = inputs
    with watcher.open_db(tmp_path / "events.db") as db:
        assert watcher.tick(db, snapshot, client, bridge, paused=False) == [{"pr": 66, "status": "sent"}]
        watcher.tick(db, snapshot, client, bridge, paused=False)
    bridge.wake.assert_called_once()
    assert all(call.args[0] == "GET" for call in client.request.call_args_list)


@pytest.mark.parametrize("case", ["paused", "stale", "errors", "ambiguous", "missing_owner", "fork",
                                       "draft", "closed", "unknown", "sha", "branch", "base", "busy", "late_pause"])
def test_unsafe_events_never_wake(watcher, inputs, tmp_path, case):
    snapshot, pr, client, bridge = inputs
    if case == "stale":
        snapshot["generated_at"] = (datetime.now(UTC) - timedelta(minutes=4)).isoformat()
    elif case == "errors":
        snapshot["errors"] = ["unavailable"]
    elif case == "ambiguous":
        other = copy.deepcopy(snapshot["sessions"][0])
        other["thread_id"] = "01a0a9b2-7db0-78a2-a960-cfc652157d22"
        other["deliveries"][0]["branch"] = "session/another"
        snapshot["sessions"].append(other)
    elif case == "missing_owner":
        watcher.resolve_owner.return_value = None
    elif case == "fork":
        pr["head"]["repo"]["full_name"] = "other/AIGCNEWS"
    elif case == "draft":
        pr["draft"] = True
    elif case == "closed":
        pr["state"] = "closed"
    elif case == "unknown":
        pr["mergeable"] = None
    elif case == "sha":
        pr["head"]["sha"] = "b" * 40
    elif case == "branch":
        pr["head"]["ref"] = "session/another"
    elif case == "base":
        pr["base"]["ref"] = "other"
    elif case == "busy":
        bridge.idle.return_value = False
    with watcher.open_db(tmp_path / "events.db") as db:
        watcher.tick(db, snapshot, client, bridge, paused=case == "paused", pause_check=lambda: case == "late_pause")
    bridge.wake.assert_not_called()


def test_manual_dashboard_owner_cannot_redirect(watcher, inputs, tmp_path):
    snapshot, _, client, bridge = inputs
    snapshot["sessions"][0]["thread_id"] = "01a0a9b2-7db0-78a2-a960-cfc652157d22"
    with watcher.open_db(tmp_path / "events.db") as db:
        watcher.tick(db, snapshot, client, bridge, paused=False)
    assert bridge.wake.call_args.args[0] == "01a0a9b2-7db0-78a2-a960-cfc652157d21"


def test_changed_owner_blocks_dispatch(watcher, inputs, tmp_path):
    snapshot, _, client, bridge = inputs
    watcher.resolve_owner.side_effect = ["01a0a9b2-7db0-78a2-a960-cfc652157d21", None]
    with watcher.open_db(tmp_path / "events.db") as db:
        assert watcher.tick(db, snapshot, client, bridge, paused=False) == [{"pr": 66, "status": "ownership_changed"}]
    bridge.wake.assert_not_called()


@pytest.mark.parametrize("change", ["sha", "draft", "mergeable_state"])
def test_live_recheck_prevents_obsolete_wake(watcher, inputs, tmp_path, change):
    snapshot, pr, client, bridge = inputs
    latest = copy.deepcopy(pr)
    if change == "sha":
        latest["head"]["sha"] = "b" * 40
    elif change == "draft":
        latest["draft"] = True
    else:
        latest["mergeable_state"] = "unknown"
    client.request.side_effect = [pr, latest, {}]
    with watcher.open_db(tmp_path / "events.db") as db:
        watcher.tick(db, snapshot, client, bridge, paused=False)
    bridge.wake.assert_not_called()


def test_api_failure_never_wakes(watcher, inputs, tmp_path):
    snapshot, _, client, bridge = inputs
    client.request.side_effect = OSError("offline")
    with watcher.open_db(tmp_path / "events.db") as db, pytest.raises(OSError):
        watcher.tick(db, snapshot, client, bridge, paused=False)
    bridge.wake.assert_not_called()


def test_behind_main_wakes_owner_and_coalesces_updates(watcher, inputs, tmp_path):
    snapshot, pr, client, bridge = inputs
    pr["mergeable"] = True
    pr["mergeable_state"] = "behind"
    main = ["b" * 40]

    def request(method, path):
        assert method == "GET"
        if path == "/git/ref/heads/main":
            return {"object": {"sha": main[0]}}
        if path.startswith("/compare/"):
            return {"status": "diverged"}
        return pr

    client.request.side_effect = request
    with watcher.open_db(tmp_path / "events.db") as db:
        assert watcher.tick(db, snapshot, client, bridge, paused=False)[0]["status"] == "sent"
        main[0] = "c" * 40
        assert watcher.tick(db, snapshot, client, bridge, paused=False)[0]["status"] == "unchanged"
    bridge.wake.assert_called_once()
    assert "base_update" in bridge.wake.call_args.args[1]
    assert "own worktree" in bridge.wake.call_args.args[1]
