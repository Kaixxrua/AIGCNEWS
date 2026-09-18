"""Read-only cgroup-v2 proof and conservative adaptive CI admission.

The coordinator provisions the parent and template; this module never writes
cgroups. Memory predictions permit overcommit: unexpected spikes can OOM.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from runner_resource_budget import CPU_LIMIT, GIB, MEMORY_LIMIT, lxc, memory_bytes


@dataclass(frozen=True)
class Evidence:
    identity: tuple
    cpu: float
    memory: int
    memory_ceiling: int
    committed_memory: int
    pressure: bool
    predicted_growth: int = 0
    startup_prediction: int = 3 * GIB
    bootstraps: int = 0
    oom: bool = False


def inventory():
    return lxc("list", "--format=json")


def active(items):
    result = []
    for item in items:
        config = item["expanded_config"]
        if not (item["name"] == "aigcnews-ci" or item["name"].startswith("aigcnews-ci-")
                or config.get("user.aigcnews.ci") == "true"):
            continue
        if item["status"].upper() == "STOPPED":
            continue
        if item["status"].upper() not in {"RUNNING", "FROZEN"}:
            raise ValueError("unknown CI state")
        result.append(item)
    return sorted(result, key=lambda item: item["name"])


def fingerprint(items):
    keys = ("name", "status", "expanded_config", "expanded_devices", "project", "location")
    return json.dumps([{key: item.get(key) for key in keys} for item in active(items)], sort_keys=True)


def counters(path):
    return dict(line.split() for line in path.read_text().splitlines())


def limits(parent):
    quota, period = (parent / "cpu.max").read_text().split()
    memory = int((parent / "memory.max").read_text())
    expected_high = int(MEMORY_LIMIT * .9)
    actual_high = int((parent / "memory.high").read_text())
    if not expected_high - os.sysconf("SC_PAGE_SIZE") < actual_high <= expected_high:
        raise ValueError("parent memory.high must be 90 percent")
    if quota == "max" or int(period) <= 0 or not 0 < int(quota) / int(period) <= CPU_LIMIT:
        raise ValueError("shared CPU ceiling is missing or excessive")
    if not 0 < memory <= MEMORY_LIMIT or int((parent / "memory.swap.max").read_text()) != 0:
        raise ValueError("shared memory/swap ceiling is missing or excessive")
    # Require the designed ceiling, rather than admitting against a smaller pool.
    if int(quota) / int(period) != CPU_LIMIT or memory != MEMORY_LIMIT:
        raise ValueError("pool does not match 6 CPU / 12 GiB design")
    return parent.stat().st_ino, quota, period, memory


def registered_coverage(items, runners, labels):
    ids = [int(item["expanded_config"]["user.aigcnews.runner_id"]) for item in active(items)]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate runner ownership")
    for runner in runners:
        runner_labels = {v["name"].lower() for v in runner["labels"]}
        if runner_labels.intersection({*labels, "aigcnews-ci", "aigcnews-control"}):
            if (runner["status"] == "online" or runner["busy"]) and runner["id"] not in ids:
                raise ValueError("registered CI/control runner is not accounted")


def parent_config(parent, name, existing):
    root = Path("/sys/fs/cgroup")
    parent = parent.resolve()
    if parent == root or not parent.is_relative_to(root) or any(c in str(parent) for c in "\n\r ="):
        raise ValueError("invalid shared parent path")
    if "lxc.cgroup.dir" in existing or "lxc.cgroup.relative" in existing:
        raise ValueError("template already overrides cgroup placement")
    relative = parent.relative_to(root)
    return (existing.rstrip() + "\n" +
            f"lxc.cgroup.dir.container = {relative}/{name}\n" +
            f"lxc.cgroup.dir.monitor = {relative}/monitors/{name}\n" +
            "lxc.cgroup.dir.container.inner = payload\n")


def owner(parent, unit, *, cgroup_root=Path("/sys/fs/cgroup"), proc=Path("/proc")):
    if not unit or not unit.endswith(".service") or "/" in unit:
        raise ValueError("explicit parent user service required")
    output = subprocess.run(
        ["systemctl", "--user", "show", unit, "--property=ActiveState,ControlGroup,MainPID,InvocationID,Delegate"],
        check=True, capture_output=True, text=True, timeout=10,
    ).stdout
    properties = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
    parent = Path(parent).resolve()
    if (properties["ActiveState"] != "active" or properties["Delegate"] != "yes"
            or not properties["InvocationID"]
            or (cgroup_root / properties["ControlGroup"].lstrip("/")).resolve() != parent
            or parent.stat().st_uid != os.getuid()):
        raise ValueError("unverified pool owner service")
    pid = int(properties["MainPID"])
    supervisor = parent / "supervisor"
    expected = "0::/" + str(supervisor.relative_to(cgroup_root))
    if pid <= 0 or (proc / str(pid) / "cgroup").read_text().strip() != expected:
        raise ValueError("pool MainPID is outside supervisor")
    if set((supervisor / "cgroup.procs").read_text().split()) != {str(pid)}:
        raise ValueError("unexpected supervisor processes")
    if any(path.is_dir() for path in supervisor.iterdir()):
        raise ValueError("unexpected supervisor descendants")
    overhead = 0
    for name in ("supervisor", "monitors"):
        group = parent / name
        bound = int((group / "memory.max").read_text())
        if not 0 < bound <= 64 * 1024**2 or int((group / "memory.swap.max").read_text()) != 0:
            raise ValueError("unbounded supervisor/monitor overhead")
        overhead += bound
    return (properties["InvocationID"], pid, parent.stat().st_ino), overhead


def membership(items, runners, labels, parent, *, cgroup_root=Path("/sys/fs/cgroup"), proc=Path("/proc"), owner_unit=None):
    parent = parent.resolve()
    if parent == cgroup_root.resolve() or not parent.is_relative_to(cgroup_root.resolve()):
        raise ValueError("pool must be a dedicated cgroup-v2 descendant")
    covered = set()
    allowed_children = set()
    committed = 0
    identities = []
    if owner_unit:
        ownership, committed = owner(parent, owner_unit, cgroup_root=cgroup_root, proc=proc)
        identities.append(("owner", ownership))
        allowed_children.update(("supervisor", "monitors"))
        if (parent / "monitors/cgroup.procs").read_text().strip():
            raise ValueError("unexpected monitor parent processes")
    for item in active(items):
        state = lxc("query", f"/1.0/instances/{item['name']}/state")
        pid = int(state["pid"])
        if pid <= 0:
            raise ValueError("missing CI init PID")
        raw = (proc / str(pid) / "cgroup").read_text().strip()
        if not raw.startswith("0::/") or "\n" in raw:
            raise ValueError("unified cgroup membership unavailable")
        path = (cgroup_root / raw[4:]).resolve()
        if path == parent or not path.is_relative_to(parent):
            raise ValueError("CI/control payload outside shared parent")
        config = item["expanded_config"]
        reservation = memory_bytes(config["limits.memory"])
        child = parent / path.relative_to(parent).parts[0]
        # Check the kernel bound, not just mutable LXD configuration evidence.
        if int((child / "memory.max").read_text()) > reservation:
            raise ValueError("kernel child memory bound exceeds reservation")
        allowed_children.add(child.name)
        if owner_unit:
            monitor = parent / "monitors" / item["name"]
            pids = (monitor / "cgroup.procs").read_text().split()
            if len(pids) != 1 or any(path.is_dir() for path in monitor.iterdir()):
                raise ValueError("unexpected monitor process tree")
            command = (proc / pids[0] / "cmdline").read_bytes().replace(b"\0", b" ").decode()
            if "lxc monitor" not in command or item["name"] not in command.split():
                raise ValueError("monitor PID is not bound to container")
            expected = "0::/" + str(monitor.relative_to(cgroup_root))
            if (proc / pids[0] / "cgroup").read_text().strip() != expected:
                raise ValueError("monitor PID membership changed")
            identities.append(("monitor", item["name"], pids[0]))
        else:
            allowed_children.add(item["name"] + "-monitor")
        committed += reservation
        if config.get("limits.memory.swap") != "false":
            raise ValueError("CI swap must remain disabled")
        runner_id = int(config["user.aigcnews.runner_id"])
        if runner_id in covered:
            raise ValueError("duplicate runner ownership")
        covered.add(runner_id)
        identities.append((item["name"], pid, raw))
    for runner in runners:
        runner_labels = {v["name"].lower() for v in runner["labels"]}
        if runner_labels.intersection({*labels, "aigcnews-ci", "aigcnews-control"}):
            if (runner["status"] == "online" or runner["busy"]) and runner["id"] not in covered:
                raise ValueError("registered CI/control runner is not accounted")
    if (parent / "cgroup.procs").read_text().strip():
        raise ValueError("unaccounted processes in parent")
    for child in parent.iterdir():
        if child.is_dir() and child.name not in allowed_children:
            raise ValueError("unaccounted subtree in shared parent")
    if owner_unit:
        expected_monitors = {item["name"] for item in active(items)}
        if {p.name for p in (parent / "monitors").iterdir() if p.is_dir()} != expected_monitors:
            raise ValueError("unexpected monitor subgroups")
    return tuple(identities), committed


def sample(parent, runners, labels, *, interval=1, owner_unit=None, history=None, jobs=()):
    parent = Path(parent)
    before = inventory()
    bound = limits(parent)
    identities, committed = membership(before, runners, labels, parent, owner_unit=owner_unit)
    first = counters(parent / "cpu.stat")
    events = counters(parent / "memory.events")
    started = time.monotonic()
    time.sleep(interval)
    second = counters(parent / "cpu.stat")
    elapsed = time.monotonic() - started
    memory = int((parent / "memory.current").read_text())
    swap = int((parent / "memory.swap.current").read_text())
    after = inventory()
    if fingerprint(before) != fingerprint(after) or bound != limits(parent):
        raise ValueError("pool or inventory changed during sample")
    if (identities, committed) != membership(after, runners, labels, parent, owner_unit=owner_unit):
        raise ValueError("CI membership changed during sample")
    delta = int(second["usage_usec"]) - int(first["usage_usec"])
    if delta < 0 or elapsed <= 0 or memory < 0 or swap:
        raise ValueError("invalid pool measurement")
    pressure = events != counters(parent / "memory.events")
    psi = (parent / "memory.pressure").read_text().splitlines()
    for line in psi:
        fields = dict(part.split("=", 1) for part in line.split()[1:])
        if float(fields["avg10"]) > 0:
            pressure = True
    growth, startup, bootstraps, oom = workload_evidence(after, jobs, parent, history, runners)
    return Evidence((bound, identities, fingerprint(after)), delta / 1e6 / elapsed,
                    memory, bound[3], committed, pressure, growth, startup, bootstraps,
                    oom or int(counters(parent / "memory.events").get("oom_kill", 0)) > 0)


def workload_evidence(items, jobs, parent, history, runners=()):
    from runner_workloads import category
    if history is None:
        return 0, 3 * GIB, 0, False
    queued = [job for job in jobs if job["status"] == "queued"]
    # Generic GitHub JIT labels cannot bind a runner to one job. Until category
    # labels exist, reserve prediction for the largest eligible queued category.
    startup = max((history.predict(category(job)) for job in queued), default=0)
    running = {job.get("runner_id"): job for job in jobs if job["status"] == "in_progress"}
    controls = {r['id'] for r in runners if 'aigcnews-control' in
                {label['name'].lower() for label in r['labels']}}
    growth = 0
    bootstraps = 0
    oom = False
    for item in active(items):
        runner_id = int(item["expanded_config"]["user.aigcnews.runner_id"])
        job = running.get(runner_id)
        kind = category(job) if job else ('control' if runner_id in controls else 'unknown')
        child = parent / item["name"]
        current = int((child / "memory.current").read_text())
        peak = int((child / "memory.peak").read_text())
        events = counters(child / "memory.events")
        identity = str(job['id']) if job else item['name']
        if job or runner_id in controls:
            history.observe(identity, kind, peak)
            prediction = history.predict(kind)
        else:
            bootstraps += 1
            prediction = max(startup, history.predict('unknown'))
        kills = int(events.get('oom_kill', 0))
        history.oom(identity, kills)
        oom = oom or kills > 0
        growth += max(0, prediction - current)
    # Persisted OOM evidence requires explicit coordinator reconciliation;
    # restarting the controller must never erase the circuit breaker.
    return growth, startup, bootstraps, oom or bool(history.data['oom'])


class AdaptiveAdmission:
    """One launch per settling period, with restart warmup and hysteresis.

    CPU shares can expand; memory uses measured category growth predictions.
    Overcommit can OOM; pressure and OOM evidence stop admission. Never resize running jobs. Inventory changes restart the settling window.
    """
    def __init__(self, *, settling_seconds=60, startup_memory=3 * GIB, startup_cpu=1.0):
        if settling_seconds < 30 or startup_memory < 3 * GIB or startup_cpu < 1:
            raise ValueError("unsafe startup headroom")
        self.settling = settling_seconds
        self.startup_memory = startup_memory
        self.startup_cpu = startup_cpu
        self.identity = None
        self.until = 0.0
        self.cpu = self.memory = None
        self.blocked = True

    def decide(self, queued, evidence, now):
        import math
        if queued < 0 or any(not math.isfinite(x) or x < 0 for x in
                            (evidence.cpu, evidence.memory, evidence.committed_memory,
                             evidence.predicted_growth, evidence.startup_prediction,
                             evidence.bootstraps, evidence.memory_ceiling, now)):
            raise ValueError("invalid admission evidence")
        if evidence.memory_ceiling != MEMORY_LIMIT:
            raise ValueError("unexpected shared memory ceiling")
        if self.identity != evidence.identity:
            self.identity = evidence.identity
            self.until = now + self.settling
            self.cpu, self.memory = evidence.cpu, evidence.memory
            self.blocked = True
        self.cpu = .5 * evidence.cpu + .5 * self.cpu
        self.memory = .5 * evidence.memory + .5 * self.memory
        cpu = max(evidence.cpu, self.cpu)
        memory = max(evidence.memory, self.memory)
        if evidence.pressure or evidence.oom or cpu >= CPU_LIMIT * .9 or memory >= evidence.memory_ceiling * .9:
            self.blocked = True
            self.until = now + self.settling
        if cpu < CPU_LIMIT * .8 and memory < evidence.memory_ceiling * .8 and not evidence.pressure and not evidence.oom:
            self.blocked = False
        if not queued or self.blocked or now < self.until:
            return 0
        if cpu + self.startup_cpu >= CPU_LIMIT * .9:
            return 0
        if evidence.bootstraps >= 2:
            return 0
        if memory + evidence.predicted_growth + evidence.startup_prediction >= evidence.memory_ceiling * .9:
            return 0
        return 1

    def launched(self, now):
        self.until = now + self.settling
