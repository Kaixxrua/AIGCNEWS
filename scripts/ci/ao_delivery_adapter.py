"""Explicit AO handoff registry. Never infer owners or mutate GitHub state."""
from __future__ import annotations

import argparse
import fcntl
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


def send(db, branch, identity, message, repository, *, read=ao_read, deliver=None):
    row = db.execute("SELECT session,worktree,stage FROM tasks WHERE branch=?", (branch,)).fetchone()
    if not row:
        return "unowned"
    session, path, stage = row
    if stage != "active":
        return "held"
    verify_workspace(path, branch, repository)
    info = read(session)["session"]
    if info.get("id") != session or info.get("isTerminated") or info.get("activity", {}).get("state") != "idle":
        return "waiting"
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


def reconcile(db, github, repository):
    results = []
    for branch, session, number in db.execute("SELECT branch,session,pr FROM tasks WHERE stage='active' AND pr IS NOT NULL").fetchall():
        pr = github.request("GET", f"/pulls/{number}")
        if pr["head"]["ref"] != branch or pr["state"] != "open" or pr.get("draft"):
            continue
        if (pr["head"].get("repo") or {}).get("full_name") != "Kaixxrua/AIGCNEWS":
            continue
        # Let the agent finish its just-pushed update before observing remote CI.
        path = db.execute("SELECT worktree FROM tasks WHERE branch=?", (branch,)).fetchone()[0]
        if git(path, "rev-parse", "HEAD") != pr["head"]["sha"] or git(path, "status", "--porcelain"):
            continue
        head = pr["head"]["sha"]
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
    args = parser.parse_args()
    with database(args.state) as db:
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
