"""Explicit AO handoff registry. Never infer owners or mutate GitHub state."""
from __future__ import annotations

import argparse
import fcntl
import importlib.util
import json
import re
import sqlite3
import subprocess
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path.home() / ".local/state/aigcnews-ao"
AO = Path.home() / ".local/lib/aigcnews-ao/ao"


def peer(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ao_read(session, resource=""):
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", session):
        raise ValueError("invalid AO session")
    with urllib.request.urlopen(f"http://127.0.0.1:8792/api/v1/sessions/{session}{resource}", timeout=10) as response:
        return json.load(response)


def git(path, *args):
    import os

    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.check_output(["git", "-C", str(path), *args], env=env, text=True, timeout=15).strip()


def verify_workspace(path, branch, repository):
    if not re.fullmatch(r"session/[a-z0-9-]+", branch):
        raise ValueError("not a session branch")
    common = git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if common != git(repository, "rev-parse", "--path-format=absolute", "--git-common-dir"):
        raise ValueError("workspace belongs to a different repository")
    if git(path, "symbolic-ref", "--short", "HEAD") != branch:
        raise ValueError("workspace branch changed")
    if Path(path).resolve() == Path(repository).resolve():
        raise ValueError("primary checkout cannot be a task workspace")


def database(path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(path)
    path.chmod(0o600)
    db.executescript("""
      CREATE TABLE IF NOT EXISTS recovery_lineage (
        old_branch TEXT PRIMARY KEY, new_branch TEXT UNIQUE, event TEXT, binding TEXT);
      CREATE TABLE IF NOT EXISTS tasks (
        branch TEXT PRIMARY KEY, session TEXT UNIQUE NOT NULL, worktree TEXT NOT NULL,
        source TEXT NOT NULL, stage TEXT NOT NULL DEFAULT 'audit', pr INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP);
      CREATE TABLE IF NOT EXISTS events (
        branch TEXT, identity TEXT, status TEXT, receipt TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(branch,identity));
    """)
    return db


def bind(db, branch, session, worktree, source, repository, pr=None):
    verify_workspace(worktree, branch, repository)
    info = ao_read(session)["session"]
    if info["id"] != session or info.get("isTerminated"):
        raise ValueError("AO target unavailable")
    if not source.strip():
        raise ValueError("handoff provenance required")
    db.execute("INSERT INTO tasks(branch,session,worktree,source,pr) VALUES(?,?,?,?,?)",
               (branch, session, str(Path(worktree).resolve()), source, pr))
    db.commit()


def send(db, branch, identity, message, repository, *, read=ao_read, deliver=None,
         expected_owner=None, validate=None):
    if (Path.home() / ".config/aigcnews/ci-paused").exists():
        return "paused"
    row = db.execute("SELECT session,worktree,stage,source,pr FROM tasks WHERE branch=?", (branch,)).fetchone()
    if not row:
        return "unowned"
    session, path, stage = row[:3]
    if expected_owner is not None and row[:3] != expected_owner:
        return "ownership_changed"
    if stage != "active":
        return "held"
    verify_workspace(path, branch, repository)
    info = read(session)["session"]
    if info.get("id") != session or info.get("isTerminated") or info.get("activity", {}).get("state") != "idle":
        return "waiting"
    if validate is not None and not validate():
        return "obsolete"
    # Recheck after remote evidence reads; neither a changed owner nor a pause
    # or a newly busy target may consume the event or receive a notification.
    if db.execute("SELECT session,worktree,stage,source,pr FROM tasks WHERE branch=?", (branch,)).fetchone() != row:
        return "ownership_changed"
    verify_workspace(path, branch, repository)
    info = read(session)["session"]
    if info.get("id") != session or info.get("isTerminated") or info.get("activity", {}).get("state") != "idle":
        return "waiting"
    if (Path.home() / ".config/aigcnews/ci-paused").exists():
        return "paused"
    cursor = db.execute("INSERT OR IGNORE INTO events(branch,identity,status) VALUES(?,?,'dispatching')", (branch, identity))
    db.commit()
    if not cursor.rowcount:
        return "duplicate"
    # Persist intent first. An ambiguous timeout cannot cause a blind replay.
    if deliver is None:
        deliver = deliver_message
    try:
        receipt = deliver(session, f"[delivery:{identity}] Workspace {path}, branch {branch}.\n{message}")
    except Exception:
        db.execute("UPDATE events SET status='unconfirmed' WHERE branch=? AND identity=?", (branch, identity))
        db.commit()
        raise
    db.execute("UPDATE events SET status='accepted',receipt=? WHERE branch=? AND identity=?",
               (json.dumps(receipt), branch, identity))
    db.commit()
    return "accepted"


def deliver_message(session, message):
    # Use AO's documented controller rather than writing its database or sending
    # input directly to a Codex app-server owned by another client.
    import os

    env = dict(os.environ, AO_DATA_DIR=str(ROOT / "data"), AO_RUN_FILE=str(ROOT / "running.json"))
    subprocess.run([str(AO), "send", "--session", session, "--message", message],
                   env=env, check=True, capture_output=True, timeout=30)
    return {"ao_session": session, "delivery": "accepted_by_cli"}


def observe(db, github, repository):
    """Persist timing facts. No PR merges, deployments or CI reruns here."""
    now = datetime.now(UTC).isoformat()
    facts = []
    for branch, session, pr in db.execute("SELECT branch,session,pr FROM tasks WHERE pr IS NOT NULL"):
        data = github.request("GET", f"/pulls/{pr}")
        if data["head"]["ref"] != branch:
            raise ValueError("PR branch does not match migration binding")
        facts.append({"observed_at": now, "pr": pr, "ao_session": session,
                      "head": data["head"]["sha"], "merged_at": data.get("merged_at"),
                      "merge_sha": data.get("merge_commit_sha"), "state": data["state"]})
    return facts


def lineage_probe():
    spec = importlib.util.spec_from_file_location(
        "delivery_probe", Path(__file__).resolve().parents[1] / "release/delivery_probe.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def production_state(repository):
    configured = subprocess.run(
        ["git", "-C", str(repository), "config", "--get", "aigcnews.productionRoot"],
        capture_output=True, text=True, check=False, timeout=15,
    )
    if configured.returncode not in (0, 1):
        raise ValueError("production root unavailable")
    common = Path(git(repository, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    root = Path(configured.stdout.strip()).expanduser() if configured.stdout.strip() else common.parent.with_name(
        common.parent.name + "-production"
    )
    return json.loads((root / ".aigcnews-deploy/state.json").read_text())


def merged_task(pr, branch, head, number):
    return (pr.get("number") == number and pr.get("state") == "closed" and bool(pr.get("merged_at"))
            and pr.get("base", {}).get("ref") == "main"
            and (pr.get("base", {}).get("repo") or {}).get("full_name") == "Kaixxrua/AIGCNEWS"
            and pr.get("head", {}).get("ref") == branch and pr["head"].get("sha") == head
            and (pr["head"].get("repo") or {}).get("full_name") == "Kaixxrua/AIGCNEWS")


def production_evidence(db, github, repository, pr):
    probe = lineage_probe()
    landing = pr["merge_commit_sha"]
    state = production_state(repository)
    result = probe.evaluate(Path(repository), landing, state)
    if result["status"] == "active":
        return result
    runs = github.request("GET", "/actions/workflows/deploy-production.yml/runs?event=workflow_run&per_page=100")
    replacement = probe.queued_replacement(Path(repository), landing, runs.get("workflow_runs", []))
    candidate = replacement["source_sha"] if replacement else state.get("in_progress")
    if not candidate or candidate == landing:
        return result
    # Establish containment before associating any task with a carrier.
    if not probe.contains(Path(repository), landing, candidate):
        return result
    replacement = dict(replacement or {"source_sha": candidate, "status": "in_progress"})
    owners = []
    for owner in github.request("GET", f"/commits/{candidate}/pulls"):
        branch = owner.get("head", {}).get("ref")
        head = owner.get("head", {}).get("sha")
        number = owner.get("number")
        if not merged_task(owner, branch, head, number) or owner.get("merge_commit_sha") != candidate:
            continue
        row = db.execute(
            "SELECT session,worktree,source FROM tasks WHERE branch=? AND pr=? AND stage='active'",
            (branch, number),
        ).fetchone()
        if not row or not row[2].strip():
            continue
        session, path, _ = row
        try:
            verify_workspace(path, branch, repository)
            if git(path, "rev-parse", "HEAD") != head:
                continue
        except (ValueError, OSError, subprocess.SubprocessError):
            continue
        owners.append({"pr": number, "branch": branch, "ao_session": session})
    replacement["owners"] = sorted(owners, key=lambda item: (item["pr"], item["ao_session"]))
    return probe.evaluate(Path(repository), landing, state, replacement)


def production_notification(db, github, repository, pr, branch, session, path):
    head, number = pr["head"]["sha"], pr["number"]
    binding = db.execute("SELECT session,worktree,stage,source,pr FROM tasks WHERE branch=?", (branch,)).fetchone()
    if not binding or binding[:3] != (session, path, "active") or not binding[3].strip() or binding[4] != number:
        return "ownership_unverified"
    if not merged_task(pr, branch, head, number):
        return "unverified"
    evidence = production_evidence(db, github, repository, pr)
    status = evidence["status"]
    if status not in {"active", "superseded_waiting", "replacement_failed"}:
        return "waiting"
    # Active is terminal for this task landing, regardless of later releases.
    identity = f"{number}:{head}:production:{pr['merge_commit_sha']}:{status}"
    if status != "active":
        carrier = evidence["replacement"]
        identity += f":{carrier['source_sha']}:{carrier.get('run_id', 'state')}:{carrier.get('run_attempt', 1)}"
        identity += f":{carrier['status']}"
    message = (
        f"Verified production notification for PR #{number} at {head}: {status}. "
        f"Evidence: {json.dumps(evidence, sort_keys=True)}. "
        "Notify only. Do not edit files, commit, push, merge, retry deployments or deploy in response. "
        "If active, this task is delivered; report completion and stop. If superseded, stop development and "
        "duplicate publishing; await a verified completion notification. If the carrier failed, report "
        "the failure and wait for coordinator instructions. Never infer an owner from a title or branch name."
    )

    def current():
        if db.execute("SELECT session,worktree,stage,source,pr FROM tasks WHERE branch=?", (branch,)).fetchone() != binding:
            return False
        latest = github.request("GET", f"/pulls/{number}")
        if not merged_task(latest, branch, head, number) or latest.get("merge_commit_sha") != pr["merge_commit_sha"]:
            return False
        if git(path, "rev-parse", "HEAD") != head or git(path, "status", "--porcelain"):
            return False
        return production_evidence(db, github, repository, latest) == evidence

    return send(db, branch, identity, message, repository,
                expected_owner=(session, path, "active"), validate=current)


def reconcile(db, github, repository):
    results = []
    # Newly created tasks bind before their PR exists. Attach only one exact
    # same-repository branch match, never a title or an inferred conversation.
    unlinked = db.execute("SELECT branch FROM tasks WHERE stage='active' AND pr IS NULL").fetchall()
    if unlinked:
        pulls = github.open_pulls()
        for (branch,) in unlinked:
            matches = [p for p in pulls if p["head"]["ref"] == branch
                       and (p["head"].get("repo") or {}).get("full_name") == "Kaixxrua/AIGCNEWS"]
            if len(matches) == 1:
                db.execute("UPDATE tasks SET pr=? WHERE branch=? AND pr IS NULL", (matches[0]["number"], branch))
        db.commit()
    for branch, session, number in db.execute("SELECT branch,session,pr FROM tasks WHERE stage='active' AND pr IS NOT NULL").fetchall():
        pr = github.request("GET", f"/pulls/{number}")
        if pr["head"]["ref"] != branch or pr.get("draft"):
            continue
        if pr["state"] != "open" and not pr.get("merged_at"):
            continue
        if (pr["head"].get("repo") or {}).get("full_name") != "Kaixxrua/AIGCNEWS":
            continue
        # Let the agent finish its just-pushed update before observing remote CI.
        path = db.execute("SELECT worktree FROM tasks WHERE branch=?", (branch,)).fetchone()[0]
        if git(path, "rev-parse", "HEAD") != pr["head"]["sha"] or git(path, "status", "--porcelain"):
            continue
        head = pr["head"]["sha"]
        if pr.get("merged_at"):
            if pr.get("number") != number:
                continue
            result = production_notification(db, github, repository, pr, branch, session, path)
            if result == "waiting":
                from types import SimpleNamespace
                ao_recovery = peer("ao_recovery")
                result = ao_recovery.notify(SimpleNamespace(**globals()), db, github, repository,
                                            pr, branch, session, path)
            results.append({"pr": number, "session": session, "result": result})
            continue
        kind = None
        evidence = pr["html_url"]
        main = github.request("GET", "/git/ref/heads/main")["object"]["sha"]
        comparison = github.request("GET", f"/compare/{main}...{head}")
        if comparison.get("status") in {"diverged", "behind"}:
            kind = "base_update"
        else:
            runs = [r for r in github.contract_runs(branch) if r.get("head_sha") == head
                    and r.get("event") == "pull_request"
                    and any(p.get("number") == number for p in r.get("pull_requests", []))]
            latest = max(runs, key=lambda r: (r["id"], r.get("run_attempt", 1)), default=None)
            if latest and latest.get("conclusion") == "failure":
                kind = "ci_failure"
                evidence = latest["html_url"]
        if kind is None:
            continue
        latest_pr = github.request("GET", f"/pulls/{number}")
        if latest_pr["head"]["sha"] != head or latest_pr["state"] != "open":
            continue
        message = (f"PR #{number} at {head} requires {kind}. Evidence: {evidence}. "
                   "Verify live evidence first. Work only in the bound existing session worktree; preserve other tasks. "
                   "Fetch latest origin/main and merge it into your branch if needed; never rebase or force-push. "
                   "Inspect failure logs before fixing, distinguish infrastructure failures from code failures. "
                   "Run relevant checks and dev_session check; commit only the scoped validated change and normal push. "
                   "Do not weaken gates, change credentials, manually merge or deploy. Report exact SHA and UTC completion time.")
        results.append({"pr": number, "session": session,
                        "result": send(db, branch, f"{number}:{head}:{kind}", message, repository)})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=ROOT / "delivery.sqlite")
    parser.add_argument("--repository", type=Path, default=Path.home() / "AIGCNEWS")
    sub = parser.add_subparsers(dest="command", required=True)
    register = sub.add_parser("bind")
    for field in ("branch", "session", "worktree", "source"):
        register.add_argument("--" + field, required=True)
    register.add_argument("--pr", type=int)
    sub.add_parser("list")
    sub.add_parser("observe")
    sub.add_parser("watch")
    recovery = sub.add_parser("recover")
    for field in ("old-branch", "branch", "worktree", "event"):
        recovery.add_argument("--" + field, required=True)
    new = sub.add_parser("new")
    new.add_argument("--name", required=True)
    new.add_argument("--prompt-file", type=Path, required=True)
    activate = sub.add_parser("activate")
    activate.add_argument("--branch", required=True)
    activate.add_argument("--expect-head", required=True)
    activate.add_argument("--handoff-evidence", required=True)
    args = parser.parse_args()
    if args.command == "new":
        import os

        prompt = args.prompt_file.read_text()
        instructions = (
            "You are an authorized AIGCNEWS development task controlled by AO. "
            f"First read {args.repository}/AGENTS.md and docs/git-workflow.md. "
            "Before editing any project file, run scripts/dev_session.py start with a unique task slug "
            "from the repository, preserving your own CODEX_THREAD_ID. Work exclusively in its returned worktree. "
            f"Immediately register that branch using python3 {Path(__file__).resolve()} bind "
            "--branch <returned branch> --worktree <returned worktree> --session $AO_SESSION_ID "
            "--source 'new AO task: dev_session creation receipt'. "
            "Registration starts held; report the exact creation receipt and wait for coordinator activation "
            "before implementing. Do not write to main, force push, rebase, or change production/private Godot artifacts. "
            "Requested task for after activation:\n" + prompt)
        env = dict(os.environ, AO_DATA_DIR=str(ROOT / "data"), AO_RUN_FILE=str(ROOT / "running.json"))
        subprocess.run([str(AO), "spawn", "--standalone", "--name", args.name, "--agent", "codex",
                        "--mode", "chat", "--prompt", instructions], env=env, check=True)
        return
    with database(args.state) as db:
        if args.command == "recover":
            from types import SimpleNamespace
            ao_recovery = peer("ao_recovery")
            from delivery_sweeper import ApiClient
            token = (Path.home() / ".config/aigcnews/delivery-read-token").read_text().strip()
            client = ApiClient("Kaixxrua/AIGCNEWS", token)
            print(json.dumps(ao_recovery.recover(SimpleNamespace(**globals()), db, client, args.repository,
                                                args.old_branch, args.branch, args.worktree, args.event)))
            return
        if args.command == "activate":
            row = db.execute("SELECT session,worktree FROM tasks WHERE branch=?", (args.branch,)).fetchone()
            if not row or not args.handoff_evidence.strip():
                raise ValueError("task binding and writer handoff evidence required")
            session, path = row
            verify_workspace(path, args.branch, args.repository)
            if git(path, "rev-parse", "HEAD") != args.expect_head or git(path, "status", "--porcelain"):
                raise ValueError("task changed since handoff audit")
            info = ao_read(session)["session"]
            if info.get("id") != session or info.get("isTerminated") or info.get("activity", {}).get("state") != "idle":
                raise ValueError("AO task must be idle before ownership activation")
            db.execute("UPDATE tasks SET stage='active',source=source || ? WHERE branch=?",
                       (" ; handoff: " + args.handoff_evidence, args.branch))
            db.commit()
        if args.command == "watch":
            from delivery_sweeper import ApiClient

            lock = (args.state.parent / "adapter.lock").open("a")
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            token = (Path.home() / ".config/aigcnews/delivery-read-token").read_text().strip()
            client = ApiClient("Kaixxrua/AIGCNEWS", token)
            while True:
                try:
                    if (Path.home() / ".config/aigcnews/ci-paused").exists():
                        print(json.dumps({"status": "paused"}), flush=True)
                    else:
                        from types import SimpleNamespace
                        ao_recovery = peer("ao_recovery")
                        receipt_errors = ao_recovery.receipts(SimpleNamespace(**globals()), db)
                        if receipt_errors:
                            print(json.dumps({"receipt_errors": receipt_errors}), flush=True)
                        print(json.dumps({"results": reconcile(db, client, args.repository)}), flush=True)
                except Exception as exc:  # noqa: BLE001 - daemon boundary fails closed without replay
                    print(json.dumps({"error_type": type(exc).__name__}), flush=True)
                time.sleep(30)
        if args.command == "bind":
            bind(db, args.branch, args.session, args.worktree, args.source, args.repository, args.pr)
        if args.command == "observe":
            from delivery_sweeper import ApiClient

            token = (Path.home() / ".config/aigcnews/delivery-read-token").read_text().strip()
            facts = observe(db, ApiClient("Kaixxrua/AIGCNEWS", token), args.repository)
            print(json.dumps(facts, ensure_ascii=False))
            with (args.state.parent / "delivery-timeline.jsonl").open("a") as stream:
                stream.write(json.dumps(facts) + "\n")
            return
        print(json.dumps([dict(zip(("branch", "session", "worktree", "source", "stage", "pr", "created_at"), r, strict=True))
                          for r in db.execute("SELECT * FROM tasks")], ensure_ascii=False))


if __name__ == "__main__":
    main()
