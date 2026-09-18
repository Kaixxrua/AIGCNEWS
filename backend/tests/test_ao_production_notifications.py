import importlib.util
import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location("ao_production", Path(__file__).parents[2] / "scripts/ci/ao_delivery_adapter.py")
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


@pytest.fixture
def delivery(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter.Path, "home", lambda: tmp_path)
    repo = tmp_path / "repository"
    repo.mkdir()

    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args], text=True, stderr=subprocess.DEVNULL).strip()

    git("init")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")

    def commit(name):
        git("-c", "core.hooksPath=/dev/null", "commit", "--allow-empty", "-m", name)
        return git("rev-parse", "HEAD")

    base = commit("base")
    landing = commit("task landing")
    carrier = commit("carrier landing")
    head = "a" * 40
    pr = {"number": 68, "state": "closed", "merged_at": "2026-09-18T12:00:00Z", "merge_commit_sha": landing,
          "head": {"ref": "session/task", "sha": head, "repo": {"full_name": "Kaixxrua/AIGCNEWS"}},
          "base": {"ref": "main", "repo": {"full_name": "Kaixxrua/AIGCNEWS"}}}
    state = {"schema": "aigcnews.production-state.v1", "active_release": base, "in_progress": None}
    runs = []
    owners = []
    client = Mock()

    def request(method, endpoint):
        assert method == "GET"
        if endpoint == "/pulls/68":
            return pr.copy()
        if endpoint.startswith("/actions/workflows/"):
            return {"workflow_runs": runs}
        if endpoint == f"/commits/{carrier}/pulls":
            return owners
        raise AssertionError(endpoint)

    client.request.side_effect = request
    monkeypatch.setattr(adapter, "production_state", lambda _: state.copy())
    monkeypatch.setattr(adapter, "verify_workspace", Mock())
    monkeypatch.setattr(adapter, "git", lambda _, *args: head if args[0] == "rev-parse" else "")
    read = Mock(side_effect=lambda session: {"session": {"id": session, "activity": {"state": "idle"}}})
    deliver = Mock(return_value={"delivery": "accepted_by_cli"})
    original_send = adapter.send
    monkeypatch.setattr(adapter, "send", lambda *a, **kw: original_send(*a, **kw, read=read, deliver=deliver))
    with adapter.database(tmp_path / "events.sqlite") as db:
        db.execute("INSERT INTO tasks(branch,session,worktree,source,stage,pr) VALUES(?,?,?,?,?,?)",
                   ("session/task", "original-owner", str(repo), "explicit handoff", "active", 68))
        db.commit()
        yield {"db": db, "repo": repo, "base": base, "landing": landing, "carrier": carrier,
               "head": head, "pr": pr, "state": state, "runs": runs, "owners": owners,
               "client": client, "read": read, "deliver": deliver, "home": tmp_path}


def reconcile(d):
    return adapter.reconcile(d["db"], d["client"], d["repo"])


def run(d, **overrides):
    return {"id": 100, "run_attempt": 1, "event": "workflow_run", "status": "queued",
            "display_title": "production-source:" + d["carrier"],
            "html_url": "https://github.com/Kaixxrua/AIGCNEWS/actions/runs/100", **overrides}


def test_active_completion_is_exact_owner_terminal_and_durable(delivery):
    d = delivery
    d["state"].update(active_release=d["landing"], in_progress=d["carrier"])
    assert reconcile(d)[0]["result"] == "accepted"
    session, message = d["deliver"].call_args.args
    assert session == "original-owner"
    assert "active" in message and d["landing"] in message
    assert "Do not edit files, commit, push, merge, retry deployments or deploy" in message
    d["state"].update(active_release=d["carrier"], in_progress=None)
    assert reconcile(d)[0]["result"] == "duplicate"
    with adapter.database(d["home"] / "events.sqlite") as reopened:
        assert adapter.reconcile(reopened, d["client"], d["repo"])[0]["result"] == "duplicate"
    d["deliver"].assert_called_once()


def test_carrier_failure_retry_and_replacement_have_distinct_events(delivery):
    d = delivery
    d["runs"].append(run(d))
    assert reconcile(d)[0]["result"] == "accepted"
    assert "superseded_waiting" in d["deliver"].call_args.args[1]
    assert '"owners": []' in d["deliver"].call_args.args[1]
    assert reconcile(d)[0]["result"] == "duplicate"
    d["runs"][0].update(status="completed", conclusion="failure")
    assert reconcile(d)[0]["result"] == "accepted"
    assert "replacement_failed" in d["deliver"].call_args.args[1]
    assert "wait for coordinator instructions" in d["deliver"].call_args.args[1]
    d["runs"][0].update(status="queued", conclusion=None, run_attempt=2)
    assert reconcile(d)[0]["result"] == "accepted"
    d["runs"][0].update(id=101)
    assert reconcile(d)[0]["result"] == "accepted"
    assert d["db"].execute("SELECT count(*) FROM events").fetchone()[0] == 4


def test_carrier_identity_requires_explicit_verified_binding(delivery):
    d = delivery
    d["runs"].append(run(d))
    owner = {**d["pr"], "number": 71, "merge_commit_sha": d["carrier"],
             "head": {**d["pr"]["head"], "ref": "session/carrier"}, "title": "Never infer this title"}
    d["owners"].append(owner)
    evidence = adapter.production_evidence(d["db"], d["client"], d["repo"], d["pr"])
    assert evidence["replacement"]["owners"] == []
    d["db"].execute("INSERT INTO tasks(branch,session,worktree,source,stage,pr) VALUES(?,?,?,?,?,?)",
                    ("session/carrier", "carrier-owner", str(d["repo"]), "independent receipt", "active", 71))
    evidence = adapter.production_evidence(d["db"], d["client"], d["repo"], d["pr"])
    assert evidence["replacement"]["owners"] == [
        {"pr": 71, "branch": "session/carrier", "ao_session": "carrier-owner"}]
    owner["head"] = {**owner["head"], "sha": "b" * 40}
    assert adapter.production_evidence(d["db"], d["client"], d["repo"], d["pr"])["replacement"]["owners"] == []


@pytest.mark.parametrize("fault", ["head", "fork", "base", "base_repo", "unmerged", "held", "dirty", "wrong_target", "busy"])
def test_unverified_or_unavailable_target_never_receives(delivery, monkeypatch, fault):
    d = delivery
    d["state"]["active_release"] = d["carrier"]
    if fault == "head":
        d["pr"]["head"]["sha"] = "b" * 40
    elif fault == "fork":
        d["pr"]["head"]["repo"]["full_name"] = "someone/fork"
    elif fault == "base":
        d["pr"]["base"]["ref"] = "other"
    elif fault == "base_repo":
        d["pr"]["base"]["repo"]["full_name"] = "someone/fork"
    elif fault == "unmerged":
        d["pr"]["merged_at"] = None
    elif fault == "held":
        d["db"].execute("UPDATE tasks SET stage='audit'")
    elif fault == "dirty":
        monkeypatch.setattr(adapter, "git", lambda _, *args: d["head"] if args[0] == "rev-parse" else " M file")
    elif fault == "wrong_target":
        d["read"].side_effect = lambda _: {"session": {"id": "wrong", "activity": {"state": "idle"}}}
    else:
        d["read"].side_effect = lambda s: {"session": {"id": s, "activity": {"state": "working"}}}
    reconcile(d)
    d["deliver"].assert_not_called()
    assert d["db"].execute("SELECT count(*) FROM events").fetchone()[0] == 0


def test_busy_then_idle_retries_without_consuming_event(delivery):
    d = delivery
    d["state"]["active_release"] = d["carrier"]
    d["read"].side_effect = lambda s: {"session": {"id": s, "activity": {"state": "working"}}}
    assert reconcile(d)[0]["result"] == "waiting"
    d["read"].side_effect = lambda s: {"session": {"id": s, "activity": {"state": "idle"}}}
    assert reconcile(d)[0]["result"] == "accepted"


@pytest.mark.parametrize("change", ["pause", "owner", "binding_pr", "provenance", "busy", "production", "pr", "worktree"])
def test_changes_during_verification_prevent_dispatch(delivery, monkeypatch, change):
    d = delivery
    d["state"]["active_release"] = d["carrier"]
    original = d["client"].request.side_effect
    calls = 0

    def request(method, endpoint):
        nonlocal calls
        calls += 1
        if calls == 2:
            if change == "pause":
                marker = d["home"] / ".config/aigcnews/ci-paused"
                marker.parent.mkdir(parents=True)
                marker.touch()
            elif change == "owner":
                d["db"].execute("UPDATE tasks SET session='another-owner'")
            elif change == "binding_pr":
                d["db"].execute("UPDATE tasks SET pr=999")
            elif change == "provenance":
                d["db"].execute("UPDATE tasks SET source=''")
            elif change == "busy":
                d["read"].side_effect = lambda s: {"session": {"id": s, "activity": {"state": "working"}}}
            elif change == "production":
                d["state"]["active_release"] = d["base"]
            elif change == "pr":
                d["pr"]["merge_commit_sha"] = d["base"]
            else:
                monkeypatch.setattr(adapter, "git", lambda _, *args: d["head"] if args[0] == "rev-parse" else " M file")
        return original(method, endpoint)

    d["client"].request.side_effect = request
    assert reconcile(d)[0]["result"] in {"paused", "ownership_changed", "waiting", "obsolete"}
    d["deliver"].assert_not_called()
    assert d["db"].execute("SELECT count(*) FROM events").fetchone()[0] == 0


def test_unrelated_and_unknown_commit_cannot_claim_completion(delivery):
    d = delivery
    d["state"]["in_progress"] = d["base"]
    assert reconcile(d)[0]["result"] == "waiting"
    d["state"]["active_release"] = "f" * 40
    with pytest.raises(ValueError, match="cannot be verified"):
        reconcile(d)
    d["deliver"].assert_not_called()


def test_failed_transport_is_durable_and_not_replayed(delivery):
    d = delivery
    d["state"]["active_release"] = d["carrier"]
    d["deliver"].side_effect = TimeoutError()
    with pytest.raises(TimeoutError):
        reconcile(d)
    assert reconcile(d)[0]["result"] == "duplicate"
    assert d["db"].execute("SELECT status FROM events").fetchone()[0] == "unconfirmed"
    d["deliver"].assert_called_once()


def test_in_progress_state_carrier_needs_ancestry_but_not_guessed_owner(delivery):
    d = delivery
    d["state"]["in_progress"] = d["carrier"]
    assert reconcile(d)[0]["result"] == "accepted"
    message = d["deliver"].call_args.args[1]
    assert '"status": "in_progress"' in message
    assert '"owners": []' in message


def test_configured_production_state_read(tmp_path, monkeypatch):
    root = tmp_path / "production"
    (root / ".aigcnews-deploy").mkdir(parents=True)
    state = {"schema": "aigcnews.production-state.v1", "active_release": "a" * 40}
    (root / ".aigcnews-deploy/state.json").write_text(json.dumps(state))
    monkeypatch.setattr(adapter.subprocess, "run", lambda *a, **kw: Mock(returncode=0, stdout=str(root)))
    monkeypatch.setattr(adapter, "git", lambda *a: str(tmp_path / "repo/.git"))
    assert adapter.production_state(tmp_path / "repo") == state
