"""Poll verified delivery ownership; wake idle owners of exact-head conflicts."""
from __future__ import annotations

import fcntl
import json
import os
import time
from datetime import datetime
from pathlib import Path

from delivery_feedback import CodexBridge, dispatch, enqueue, open_db
from delivery_ownership import resolve_owner
from delivery_sweeper import ApiClient


def fresh(snapshot):
    try:
        generated = datetime.fromisoformat(snapshot["generated_at"].replace("Z", "+00:00"))
        return generated.tzinfo is not None and 0 <= time.time() - generated.timestamp() <= 180
    except (KeyError, ValueError, TypeError):
        return False


def eligible(pr):
    return (pr.get("state") == "open" and not pr.get("draft")
            and pr.get("base", {}).get("ref") == "main"
            and (pr.get("head", {}).get("repo") or {}).get("full_name") == "Kaixxrua/AIGCNEWS")


def reason(pr, client):
    if not eligible(pr):
        return None
    if pr.get("mergeable") is False and pr.get("mergeable_state") == "dirty":
        return "conflict"
    main = client.request("GET", "/git/ref/heads/main").get("object", {}).get("sha")
    if not main:
        return None
    comparison = client.request("GET", f"/compare/{main}...{pr['head']['sha']}")
    return "base_update" if comparison.get("status") in {"behind", "diverged"} else None


def tick(db, snapshot, client, bridge, *, paused, pause_check=lambda: False):
    if paused or snapshot.get("errors") or not fresh(snapshot):
        return []
    owners = {}
    for session in snapshot.get("sessions", []):
        for item in session.get("deliveries", []):
            owners.setdefault(item["pr"], set()).add((item["sha"], item["branch"]))
    results = []
    for number, threads in owners.items():
        if len(threads) != 1:
            continue
        expected_sha, branch = next(iter(threads))
        thread = resolve_owner(branch)
        if thread is None:
            results.append({"pr": number, "status": "ownership_unverified"})
            continue
        pr = client.request("GET", f"/pulls/{number}")
        if not eligible(pr) or pr["head"]["sha"] != expected_sha or pr["head"]["ref"] != branch:
            continue
        # Conflict is authoritative. Test failure classification requires logs;
        # don't wake developers to repair transient network failures.
        kind = reason(pr, client)
        if kind is None:
            continue
        sha = pr["head"]["sha"]
        key = enqueue(db, thread_id=thread, pr=number, sha=sha,
                      kind=kind, url=pr["html_url"])
        latest = client.request("GET", f"/pulls/{number}")
        if not eligible(latest) or latest["head"]["ref"] != branch or reason(latest, client) != kind:
            continue
        if resolve_owner(branch) != thread:
            results.append({"pr": number, "status": "ownership_changed"})
            continue
        result = dispatch(db, key, bridge, current_sha=latest["head"]["sha"], paused=pause_check())
        results.append({"pr": number, "status": result})
    return results


def main():
    root = Path.home() / ".local/state/aigcnews-delivery-feedback"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = (root / "watcher.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    token_path = Path.home() / ".config/aigcnews/delivery-read-token"
    if token_path.stat().st_mode & 0o077:
        raise ValueError("credential file must be private")
    client = ApiClient("Kaixxrua/AIGCNEWS", token_path.read_text().strip())
    snapshot_path = Path.home() / ".local/share/delivery-observatory/data/snapshot.json"
    with open_db(root / "outbox.sqlite") as db:
        while True:
            try:
                paused = (Path.home() / ".config/aigcnews/ci-paused").exists()
                if paused:
                    print(json.dumps({"status": "paused"}), flush=True)
                elif time.time() - snapshot_path.stat().st_mtime > 180:
                    print(json.dumps({"status": "stale_snapshot"}), flush=True)
                else:
                    with CodexBridge() as bridge:
                        results = tick(db, json.loads(snapshot_path.read_text()), client, bridge, paused=False,
                                       pause_check=lambda: (Path.home() / ".config/aigcnews/ci-paused").exists())
                    print(json.dumps({"results": results}), flush=True)
            except Exception as exc:  # noqa: BLE001 - daemon boundary: fail closed, never replay a wake
                print(json.dumps({"status": "unavailable", "error_type": type(exc).__name__}), flush=True)
            time.sleep(int(os.environ.get("DELIVERY_FEEDBACK_POLL_SECONDS", "60")))


if __name__ == "__main__":
    main()
