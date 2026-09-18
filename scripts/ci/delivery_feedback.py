"""Durable exact-SHA feedback and fail-closed wakeups through Codex app-server."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path


class BridgeError(RuntimeError):
    pass


class CodexBridge:
    def __enter__(self):
        from websockets.sync.client import unix_connect

        self.connection = unix_connect(
            str(Path.home() / ".codex/app-server-control/app-server-control.sock"),
            uri="ws://localhost", proxy=None, compression=None, open_timeout=5,
        )
        self.sequence = 0
        try:
            self.call("initialize", {"clientInfo": {"name": "delivery-feedback", "version": "1"}})
            self.send({"method": "initialized"})
        except Exception:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_):
        self.connection.close()

    def send(self, message):
        self.connection.send(json.dumps(message))

    def call(self, method, params):
        self.sequence += 1
        self.send({"id": self.sequence, "method": method, "params": params})
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            line = self.connection.recv(timeout=max(.01, deadline - time.monotonic()))
            response = json.loads(line)
            if response.get("id") == self.sequence:
                if "error" in response:
                    raise BridgeError(f"{method} rejected")
                return response["result"]
        raise BridgeError(f"{method} response unavailable")

    def idle(self, thread_id):
        thread = self.call("thread/read", {"threadId": thread_id, "includeTurns": False})["thread"]
        return thread.get("id") == thread_id and thread.get("status", {}).get("type") == "idle"

    def wake(self, thread_id, prompt):
        # Inherit the existing thread's model, permissions and workspace.
        if not self.idle(thread_id):
            raise BridgeError("thread is no longer idle")
        return self.call("turn/start", {"threadId": thread_id, "input": [
            {"type": "text", "text": prompt, "text_elements": []}
        ]})


def enqueue(db, *, thread_id, pr, sha, kind, url):
    uuid.UUID(thread_id)
    if kind not in {"conflict", "test_failure", "base_update"} or len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
        raise ValueError("invalid feedback identity")
    if not url.startswith("https://github.com/Kaixxrua/AIGCNEWS/"):
        raise ValueError("feedback evidence must belong to this repository")
    key = hashlib.sha256(f"{thread_id}:{pr}:{sha}:{kind}".encode()).hexdigest()
    payload = json.dumps({"thread_id": thread_id, "pr": pr, "sha": sha, "kind": kind, "url": url})
    db.execute("INSERT OR IGNORE INTO feedback VALUES (?, ?, 'pending', NULL)", (key, payload))
    db.commit()
    return key


def open_db(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    path.chmod(0o600)
    db.execute("CREATE TABLE IF NOT EXISTS feedback (id TEXT PRIMARY KEY, payload TEXT, status TEXT, detail TEXT)")
    return db


def dispatch(db, key, bridge, *, current_sha, paused):
    row = db.execute("SELECT payload,status FROM feedback WHERE id=?", (key,)).fetchone()
    if not row or row[1] != "pending":
        return "unchanged"
    event = json.loads(row[0])
    if current_sha != event["sha"]:
        db.execute("UPDATE feedback SET status='obsolete' WHERE id=?", (key,))
        db.commit()
        return "obsolete"
    if paused or not bridge.idle(event["thread_id"]):
        return "waiting"
    # Commit before side effect. Ambiguous transport failures never trigger a
    # duplicate turn; the receipt must be reconciled before retrying.
    cursor = db.execute("UPDATE feedback SET status='dispatching' WHERE id=? AND status='pending'", (key,))
    db.commit()
    if cursor.rowcount != 1:
        return "unchanged"
    prompt = (
        f"Delivery feedback {key}: PR #{event['pr']} at exact SHA {event['sha']} "
        f"has {event['kind']}. Evidence: {event['url']}. Return this PR to development. "
        "Verify the failure and current branch first; preserve other tasks. Stay in your own "
        "worktree and session branch, fetch the latest origin/main and merge it into your branch. "
        "Do not switch to main to develop. Coalesce intervening main updates into that latest fetch. "
        "Resolve conflicts or repair failing tests, then rerun local validation and submit a new SHA "
        "through the established pipeline. Do not bypass checks, force-push, or deploy manually."
    )
    try:
        receipt = bridge.wake(event["thread_id"], prompt)
        turn_id = receipt["turn"]["id"]
    except Exception:
        db.execute("UPDATE feedback SET status='unconfirmed',detail='wake receipt unavailable' WHERE id=?", (key,))
        db.commit()
        raise
    db.execute("UPDATE feedback SET status='sent',detail=? WHERE id=?", (turn_id, key))
    db.commit()
    return "sent"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", required=True, metavar="THREAD_ID")
    args = parser.parse_args()
    uuid.UUID(args.probe)
    try:
        with CodexBridge() as bridge:
            print(json.dumps({"available": True, "idle": bridge.idle(args.probe)}))
    except (BridgeError, OSError, ValueError) as exc:
        print(json.dumps({"available": False, "error": str(exc)}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
