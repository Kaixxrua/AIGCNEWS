"""Conservative aggregate CI admission; frozen containers retain reservations."""
from __future__ import annotations

import json
import math
import re
import subprocess
import time
from dataclasses import dataclass

GIB = 1024**3
CPU_LIMIT = 6.0
MEMORY_LIMIT = 12 * GIB
ADMISSION = 0.9


@dataclass(frozen=True)
class Usage:
    cpu: float
    memory: int
    reserved_cpu: float
    reserved_memory: int


@dataclass(frozen=True)
class Allocation:
    count: int
    cpu: float = 0
    memory: int = 0
    reason: str = ""


def allocate(queued: int, usage: Usage, *, min_memory: int = 3 * GIB) -> Allocation:
    values = (usage.cpu, usage.memory, usage.reserved_cpu, usage.reserved_memory)
    if queued < 0 or min_memory <= 0 or any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("invalid resource evidence")
    if queued == 0:
        return Allocation(0, reason="no queued runnable jobs")
    if usage.cpu >= CPU_LIMIT * ADMISSION or usage.memory >= MEMORY_LIMIT * ADMISSION:
        return Allocation(0, reason="measured usage reached 90 percent")
    cpu = CPU_LIMIT * ADMISSION - usage.reserved_cpu
    memory = math.floor(MEMORY_LIMIT * ADMISSION) - usage.reserved_memory
    count = max(0, min(queued, math.floor(cpu), memory // min_memory))
    if not count:
        return Allocation(0, reason="insufficient unreserved capacity")
    # Round down: individual hard quotas must never sum above the pool budget.
    return Allocation(count, math.floor(cpu / count * 100) / 100, memory // count)


def lxc(*args):
    result = subprocess.run(["lxc", *args], capture_output=True, text=True, check=True, timeout=15)
    return json.loads(result.stdout)


def memory_bytes(value: str) -> int:
    match = re.fullmatch(r"(\d+)(GiB|MiB|B)?", value)
    if not match:
        raise ValueError("CI container lacks an explicit byte memory limit")
    return int(match[1]) * {None: 1, "B": 1, "MiB": 1024**2, "GiB": GIB}[match[2]]


def reservations(items):
    total_cpu = 0.0
    total_memory = 0
    names = []
    for item in items:
        name = item["name"]
        if not (name == "aigcnews-ci" or name.startswith("aigcnews-ci-")):
            continue
        if item["status"].upper() == "STOPPED":
            continue
        if item["status"].upper() not in {"RUNNING", "FROZEN"}:
            raise ValueError("unknown CI container state")
        config = item["expanded_config"]
        allowance = config.get("limits.cpu.allowance", "")
        if allowance:
            match = re.fullmatch(r"(\d+)ms/100ms", allowance)
            if not match:
                raise ValueError("unsupported CPU quota")
            cpu = int(match[1]) / 100
        else:
            cpu = int(config["limits.cpu"])
        if cpu <= 0:
            raise ValueError("missing CPU reservation")
        total_cpu += cpu
        total_memory += memory_bytes(config["limits.memory"])
        names.append(name)
    return names, total_cpu, total_memory


def sample() -> Usage:
    before = lxc("list", "--format=json")
    names, reserved_cpu, reserved_memory = reservations(before)
    first = {name: lxc("query", f"/1.0/instances/{name}/state") for name in names}
    started = time.monotonic()
    time.sleep(1)
    elapsed = time.monotonic() - started
    second = {name: lxc("query", f"/1.0/instances/{name}/state") for name in names}
    if reservations(lxc("list", "--format=json")) != (names, reserved_cpu, reserved_memory):
        raise ValueError("CI inventory changed during measurement")
    delta = sum(second[n]["cpu"]["usage"] - first[n]["cpu"]["usage"] for n in names)
    memory = sum(second[n]["memory"]["usage"] for n in names)
    if delta < 0 or any(second[n]["memory"].get("swap_usage", 0) for n in names):
        raise ValueError("CPU counter reset or CI swapping; expansion denied")
    return Usage(delta / 1e9 / elapsed, memory, reserved_cpu, reserved_memory)
