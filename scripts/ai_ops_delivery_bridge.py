#!/usr/bin/env python3
"""Copy a credential-free delivery projection into the backend's metrics volume."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def install(source: Path, destination: Path):
    """Install only the read-only bridge, never change the delivery controller."""
    runtime = Path.home() / ".local/lib/aigcnews-ai-ops/bridge.py"
    runtime.parent.mkdir(parents=True, exist_ok=True)
    runtime.write_bytes(Path(__file__).read_bytes())
    units = Path.home() / ".config/systemd/user"
    units.mkdir(parents=True, exist_ok=True)
    # systemd quoting is not shell quoting. Reject characters with expansion semantics.
    args = [sys.executable, str(runtime), "--source", str(source.resolve()),
            "--destination", str(destination.resolve())]
    if any(any(c in a for c in '\n\r%$"\\') for a in args):
        raise ValueError("unsupported unit path")
    command = " ".join('"' + a + '"' for a in args)
    (units / "aigcnews-ai-ops-bridge.service").write_text(
        "[Unit]\nDescription=AIGCNEWS read-only AI operations delivery projection\n"
        "[Service]\nType=oneshot\nNoNewPrivileges=true\nExecStart=" + command + "\n")
    (units / "aigcnews-ai-ops-bridge.timer").write_text(
        "[Unit]\nDescription=Refresh AI operations delivery evidence\n"
        "[Timer]\nOnBootSec=15\nOnUnitActiveSec=30\nAccuracySec=5\n"
        "[Install]\nWantedBy=timers.target\n")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", "aigcnews-ai-ops-bridge.timer"], check=True)


def publish(source: Path, destination: Path):
    snapshot = json.loads(source.read_text())
    if snapshot.get("schema") != "aigcnews.local-delivery.v1":
        raise ValueError("unexpected delivery snapshot")
    active = snapshot.get("active_release") or {}
    release = snapshot.get("release") or {}
    projection = {
        "generated_at": snapshot["generated_at"],
        "main_sha": snapshot.get("main_sha"),
        "active_sha": active.get("sha") if isinstance(active, dict) else active,
        "release_status": release.get("status") if isinstance(release, dict) else None,
        "tasks": [{key: row.get(key) for key in ("sha", "status", "created_at", "updated_at")}
                  for row in snapshot.get("tasks", [])[-10:]],
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=destination.parent, prefix=".ai-ops-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(projection, stream)
        os.chmod(temp, 0o644)
        os.replace(temp, destination)
    finally:
        Path(temp).unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    publish(args.source, args.destination)
    if args.install:
        install(args.source, args.destination)
