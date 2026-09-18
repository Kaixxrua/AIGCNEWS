#!/usr/bin/env python3
"""Unprivileged delegated-user-service owner; never changes host permissions.

Only initializes new empty subgroups. Coordinator installs/starts the unit after
review. SIGTERM waits for payload and monitor subgroups to drain.
"""
from __future__ import annotations

import os
import signal
import socket
import time
from pathlib import Path

OVERHEAD = 64 * 1024**2


def prepare(parent):
    supervisor = parent / "supervisor"
    if any(p.is_dir() and p.name != "supervisor" for p in parent.iterdir()):
        raise ValueError("parent must start empty; reconcile old payloads first")
    (parent / "cgroup.subtree_control").write_text("+cpu +memory +pids")
    if (supervisor / "memory.max").read_text().strip() != "max":
        raise ValueError("refusing to resize existing supervisor")
    if int((supervisor / "memory.current").read_text()) >= OVERHEAD // 2:
        raise ValueError("supervisor lacks startup headroom")
    (supervisor / "memory.max").write_text(str(OVERHEAD))
    (supervisor / "memory.swap.max").write_text("0")
    monitors = parent / "monitors"
    monitors.mkdir()
    (monitors / "memory.max").write_text(str(OVERHEAD))
    (monitors / "memory.swap.max").write_text("0")
    (monitors / "cgroup.subtree_control").write_text("+cpu +memory +pids")


def drained(parent):
    # LXD removes container/monitor cgroups only after termination. Unknown
    # subgroups keep the service alive for coordinator reconciliation.
    return (not any(p.is_dir() and p.name not in {"supervisor", "monitors"} for p in parent.iterdir())
            and not any(p.is_dir() for p in (parent / "monitors").iterdir())
            and not (parent / "monitors/cgroup.procs").read_text().strip())


def main():
    membership = Path("/proc/self/cgroup").read_text().strip()
    if not membership.startswith("0::/") or not membership.endswith("/supervisor"):
        raise ValueError("must run in delegated user-service supervisor")
    parent = (Path("/sys/fs/cgroup") / membership[4:]).parent
    prepare(parent)
    address = os.environ.get("NOTIFY_SOCKET")
    if address:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as channel:
            channel.connect("\0" + address[1:] if address.startswith("@") else address)
            channel.sendall(b"READY=1")
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping or not drained(parent):
        time.sleep(1)


if __name__ == "__main__":
    main()
