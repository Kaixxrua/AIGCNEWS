#!/usr/bin/env python3
"""Scale clean LXD GitHub Actions JIT runners for queued AIGCNEWS CI jobs."""

from __future__ import annotations

import argparse
import fcntl
import http.client
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

DEFAULT_LABEL = "aigcnews-ci-ephemeral"
DEFAULT_PREFIX = "aigcnews-ci-job-"
DEFAULT_RUNNER_LABELS = ("self-hosted", "linux", "x64")


class AutoscalerError(RuntimeError):
    pass


class TransientGitHubError(AutoscalerError):
    """Read-only request exhausted bounded retries; safe to poll again."""


class LaunchUncertain(AutoscalerError):
    """A dispatched runner may own a job; preserve it for reconciliation."""


@dataclass(frozen=True)
class Instance:
    name: str
    status: str
    created_at: datetime | None = None
    runner_id: int | None = None


@dataclass(frozen=True)
class Plan:
    queued_jobs: int
    active_instances: int
    spawn: int
    reason: str = ""
    metrics: dict[str, Any] | None = None


class GitHub(Protocol):
    def queued_jobs(self, label: str, compat_labels: tuple[str, ...] = ()) -> list[int]: ...

    def generate_jit(self, name: str, label: str, compat_labels: tuple[str, ...] = ()) -> tuple[int, str]: ...

    def runners(self) -> list[dict[str, Any]]: ...

    def delete_runner(self, runner_id: int) -> None: ...


class Runtime(Protocol):
    def instances(self) -> list[Instance]: ...

    def reap(self, *, idle_timeout: timedelta, github: GitHub) -> list[str]: ...

    def launch(
        self, name: str, jit_config: str, runner_id: int, *, cpu: str, memory: str
    ) -> None: ...

    def destroy(self, name: str) -> None: ...


def parse_timestamp(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def make_plan(queued_jobs: int, active_instances: int, maximum: int) -> Plan:
    if minimum := min(queued_jobs, max(0, maximum - active_instances)):
        spawn = minimum
    else:
        spawn = 0
    return Plan(queued_jobs, active_instances, spawn)


class ApiClient:
    def __init__(self, repository: str, token: str, runner_group_id: int = 1):
        if repository.count("/") != 1:
            raise AutoscalerError("repository must use owner/name format")
        if not token:
            raise AutoscalerError("GH_TOKEN is unavailable")
        self.base = f"https://api.github.com/repos/{repository}"
        self.runner_group_id = runner_group_id
        self.completed_jobs = {}
        self.previous_active_runs = {}
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "aigcnews-ephemeral-runner-autoscaler",
        }

    def request(
        self, method: str, path: str, document: dict[str, object] | None = None
    ) -> Any:
        payload = json.dumps(document).encode() if document is not None else None
        attempts = 4 if method == "GET" else 1
        for attempt in range(attempts):
            request = urllib.request.Request(
                self.base + path,
                data=payload,
                headers=self.headers,
                method=method,
            )
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    body = response.read()
                return json.loads(body) if body else None
            except urllib.error.HTTPError as exc:
                # Do not read or print error bodies: they can contain payloads.
                code = exc.code
                exc.close()
                if method != "GET" or code not in {429, 500, 502, 503, 504}:
                    raise AutoscalerError(f"GitHub API {method} failed ({code})") from None
            except (OSError, http.client.IncompleteRead, http.client.RemoteDisconnected,
                    http.client.BadStatusLine, json.JSONDecodeError, UnicodeDecodeError) as exc:
                if method != "GET":
                    raise AutoscalerError(
                        f"GitHub API {method} transport failed ({type(exc).__name__}); not replayed"
                    ) from None
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
        raise TransientGitHubError("GitHub API GET exhausted 4 attempts; admission deferred")

    def queued_jobs(self, label: str, compat_labels: tuple[str, ...] = ()) -> list[int]:
        runs: dict[int, dict[str, Any]] = dict(self.previous_active_runs)
        active_runs = {}
        for status in ("queued", "in_progress", "completed"):
            # Small pages avoid megabyte bodies. Only recent completions are
            # needed for fast jobs; previously active runs are followed exactly.
            size = 10 if status == "completed" else 20
            page = 1
            while True:
                document = self.request(
                    "GET", f"/actions/runs?status={status}&per_page={size}&page={page}&exclude_pull_requests=true"
                )
                batch = document.get("workflow_runs", [])
                for run in batch:
                    runs[int(run["id"])] = run
                    if status != "completed":
                        active_runs[int(run["id"])] = run
                if status == "completed" or len(batch) < size:
                    break
                page += 1
        supported = {item.strip().lower() for item in (label, *compat_labels) if item.strip()}
        jobs: dict[int, dict[str, Any]] = {}
        # Terminal run jobs are immutable within an attempt. Cache them so a
        # steady-state poll does not issue 100 historical jobs requests again.
        current_keys = set()
        for run_id in sorted(runs):
            run = runs[run_id]
            key = (run_id, run.get("run_attempt", 1))
            current_keys.add(key)
            document = self.completed_jobs.get(key)
            if document is None:
                document = self.request(
                    "GET", f"/actions/runs/{run_id}/jobs?filter=latest&per_page=100"
                )
                if run.get("status") == "completed":
                    self.completed_jobs[key] = document
            for job in document.get("jobs", []):
                labels = {str(item).lower() for item in job.get("labels", [])}
                if job.get("status") in {"queued", "in_progress", "completed"} and supported.intersection(labels):
                    jobs[int(job["id"])] = {**job, "workflow_name": runs[run_id].get("name", ""), "run_id": run_id}
        self.completed_jobs = {key: value for key, value in self.completed_jobs.items() if key in current_keys}
        self.previous_active_runs = active_runs
        self.job_metadata = list(jobs.values())
        return sorted(key for key, job in jobs.items() if job["status"] == "queued")

    def generate_jit(self, name: str, label: str, compat_labels: tuple[str, ...] = ()) -> tuple[int, str]:
        result = self.request(
            "POST",
            "/actions/runners/generate-jitconfig",
            {
                "name": name,
                "runner_group_id": self.runner_group_id,
                "labels": list(dict.fromkeys(
                    item.strip().lower()
                    for item in (*DEFAULT_RUNNER_LABELS, label, *compat_labels)
                    if item.strip()
                )),
                "work_folder": "_work",
            },
        )
        return int(result["runner"]["id"]), str(result["encoded_jit_config"])

    def runners(self) -> list[dict[str, Any]]:
        result = []
        page = 1
        while True:
            batch = self.request("GET", f"/actions/runners?per_page=100&page={page}")["runners"]
            result.extend(batch)
            if len(batch) < 100:
                return result
            page += 1

    def delete_runner(self, runner_id: int) -> None:
        try:
            self.request("DELETE", f"/actions/runners/{runner_id}")
        except AutoscalerError as exc:
            if "(404)" not in str(exc):
                raise


class LxdRuntime:
    def __init__(self, template: str, prefix: str, logs_dir: Path):
        self.template = template
        self.prefix = prefix
        self.logs_dir = logs_dir
        self.receipts = None
        self.history = None
        self.expected_proxy_connect = None
        self.shared_parent = None
        self.shared_unit = None

    @staticmethod
    def command(
        arguments: list[str], *, input_data: bytes | None = None, check: bool = True
    ) -> subprocess.CompletedProcess[bytes]:
        try:
            return subprocess.run(
                ["lxc", *arguments],
                input=input_data,
                capture_output=True,
                check=check,
                timeout=60,
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            detail = (getattr(exc, "stderr", b"") or b"").decode(errors="replace")[:1000]
            raise AutoscalerError(
                f"lxc {' '.join(arguments)} failed: {detail}"
            ) from None

    def instances(self) -> list[Instance]:
        output = self.command(["list", "--format=json"]).stdout
        instances: list[Instance] = []
        for item in json.loads(output or b"[]"):
            name = str(item.get("name", ""))
            if not name.startswith(self.prefix):
                continue
            config = item.get("expanded_config", {})
            runner_id = config.get("user.aigcnews.runner_id")
            instances.append(
                Instance(
                    name=name,
                    status=str(item.get("status", "UNKNOWN")).upper(),
                    created_at=parse_timestamp(config.get("user.aigcnews.created_at")),
                    runner_id=int(runner_id) if runner_id else None,
                )
            )
        return instances

    def has_worker(self, name: str) -> bool:
        result = self.command(
            [
                "exec",
                name,
                "--",
                "pgrep",
                "-f",
                "/opt/actions-runner/bin/Runner.Worker",
            ],
            check=False,
        )
        if result.returncode not in (0, 1):
            raise AutoscalerError(f"Cannot establish worker state for {name}")
        return result.returncode == 0

    def archive_logs(self, name: str) -> None:
        destination = self.logs_dir / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "lxc",
                "file",
                "pull",
                "-r",
                f"{name}/opt/actions-runner/_diag",
                str(destination),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=60,
        )

    def destroy(self, name: str) -> None:
        self.archive_logs(name)
        self.command(["delete", "--force", name])

    def reap(self, *, idle_timeout: timedelta, github: GitHub) -> list[str]:
        removed: list[str] = []
        now = datetime.now(UTC)
        for instance in self.instances():
            if self.shared_parent and instance.status == "RUNNING":
                if self.has_worker(instance.name):
                    continue
                service = self.command(["exec", instance.name, "--", "systemctl", "show",
                                        "aigcnews-ephemeral-runner.service", "--property=ActiveState", "--value"])
                if service.stdout.strip() not in (b"inactive", b"failed"):
                    continue
                if instance.runner_id is None:
                    continue
                if not self.capture_final(instance, github):
                    continue
                github.delete_runner(instance.runner_id)
                self.destroy(instance.name)
                removed.append(instance.name)
                continue
            stale_idle = (
                instance.status == "RUNNING"
                and instance.created_at is not None
                and now - instance.created_at > idle_timeout
                and not self.has_worker(instance.name)
            )
            if instance.status == "STOPPED" or stale_idle:
                # Unregister first: GitHub refuses removal of a busy runner.
                # A failed/ambiguous request must never lead to killing a job.
                if instance.runner_id is None:
                    continue
                if self.shared_parent:
                    self.capture_final(instance, github)
                github.delete_runner(instance.runner_id)
                self.destroy(instance.name)
                removed.append(instance.name)
        return removed

    def capture_final(self, instance, github):
        from shared_runner_pool import counters
        if instance.status != "RUNNING" or self.has_worker(instance.name):
            raise AutoscalerError("final peak unavailable; preserve container for reconciliation")
        service = self.command(["exec", instance.name, "--", "systemctl", "show",
                                "aigcnews-ephemeral-runner.service", "--property=ActiveState", "--value"])
        if service.stdout.strip() not in (b"inactive", b"failed"):
            raise AutoscalerError("JIT service is not finished; preserve final evidence")
        receipt = json.loads(self.receipts.path(instance.runner_id).read_text())
        if not receipt.get("job"):
            raise AutoscalerError("job identity unavailable; preserve container for reconciliation")
        job = github.request("GET", f"/actions/jobs/{receipt['job']['id']}")
        if job["status"] != "completed":
            return False
        child = Path(self.shared_parent) / instance.name
        self.receipts.finalize(instance.runner_id, job,
                               int((child / "memory.peak").read_text()),
                               int(counters(child / "memory.events").get("oom_kill", 0)), self.history)
        return True

    def verify_proxy(self, name: str) -> None:
        if not self.expected_proxy_connect:
            return
        instance = json.loads(self.command(["query", f"/1.0/instances/{name}"]).stdout)
        proxy = instance.get("expanded_devices", {}).get("egress-proxy", {})
        if (proxy.get("type") != "proxy" or proxy.get("bind") != "container"
                or proxy.get("connect") != self.expected_proxy_connect
                or proxy.get("listen") != "tcp:0.0.0.0:7895"):
            raise AutoscalerError("CI template/clone proxy does not match accepted endpoint")

    def launch(
        self, name: str, jit_config: str, runner_id: int, *, cpu: str, memory: str
    ) -> None:
        if self.shared_parent:
            from shared_runner_pool import limits, owner
            owner(Path(self.shared_parent), self.shared_unit)
            limits(Path(self.shared_parent))
        self.verify_proxy(self.template)
        created_at = datetime.now(UTC).isoformat()
        self.command(["copy", self.template, name])
        dispatched = False
        try:
            self.verify_proxy(name)
            for key, value in (
                ("boot.autostart", "false"),
                ("user.aigcnews.ci", "true"),
                ("limits.cpu", "6"),
                ("limits.cpu.allowance", "100%" if self.shared_parent else f"{int(float(cpu) * 100)}ms/100ms"),
                ("limits.cpu.priority", "5"),
                ("limits.memory", memory),
                ("limits.memory.swap", "false"),
                ("user.aigcnews.created_at", created_at),
                ("user.aigcnews.runner_id", str(runner_id)),
            ):
                self.command(["config", "set", name, key, value])
            if self.shared_parent:
                from shared_runner_pool import parent_config
                existing = self.command(["config", "get", name, "raw.lxc"]).stdout.decode()
                raw = parent_config(Path(self.shared_parent), name, existing)
                self.command(["config", "set", name, "raw.lxc", raw])
            if self.shared_parent:
                # Leave the one-job container alive until the host has durably
                # captured final cgroup counters. No second job can be accepted.
                self.command(["file", "push", "-p", "-",
                              f"{name}/etc/systemd/system/aigcnews-ephemeral-runner.service.d/final-peak.conf"],
                             input_data=b"[Service]\nExecStopPost=\n")
            self.command(["start", name])
            if self.shared_parent:
                from shared_runner_pool import inventory, limits, membership
                limits(Path(self.shared_parent))
                membership(inventory(), [], (), Path(self.shared_parent), owner_unit=self.shared_unit)
            self.command(
                ["file", "push", "-p", "-", f"{name}/run/aigcnews-jitconfig"],
                input_data=jit_config.encode(),
            )
            self.command(
                [
                    "exec",
                    name,
                    "--",
                    "chmod",
                    "600",
                    "/run/aigcnews-jitconfig",
                ]
            )
            dispatched = True
            self.command(
                [
                    "exec",
                    name,
                    "--",
                    "systemctl",
                    "start",
                    "--no-block",
                    "aigcnews-ephemeral-runner.service",
                ]
            )
        except (AutoscalerError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            if dispatched:
                raise LaunchUncertain(f"JIT start uncertain for {name}; preserve runner and payload") from exc
            self.destroy(name)
            raise


class Autoscaler:
    def __init__(
        self,
        github: GitHub,
        runtime: Runtime,
        *,
        label: str,
        prefix: str,
        maximum: int,
        cpu: str,
        memory: str,
        idle_timeout: timedelta,
        compat_labels: tuple[str, ...] = (),
    ):
        self.github = github
        self.runtime = runtime
        self.label = label
        self.compat_labels = compat_labels
        self.prefix = prefix
        self.maximum = maximum
        self.cpu = cpu
        self.memory = memory
        self.idle_timeout = idle_timeout
        self.resource_budget = False
        self.shared_parent = None
        self.shared_unit = None
        self.adaptive = None
        self.verify_accounting = False
        self.history = None

    def reconcile(self, *, apply: bool, drain: bool = False) -> Plan:
        if (Path.home() / ".config/aigcnews/ci-paused").exists() and not drain:
            return Plan(0, len(self.runtime.instances()), 0, "operator pause")
        jobs = self.github.queued_jobs(self.label, self.compat_labels)
        if self.shared_parent and apply:
            owned_ids = {instance.runner_id for instance in self.runtime.instances()}
            for job in getattr(self.github, "job_metadata", []):
                if job.get("runner_id") in owned_ids and job["status"] in {"in_progress", "completed"}:
                    self.runtime.receipts.bind(job["runner_id"], job)
        if apply:
            self.runtime.reap(idle_timeout=self.idle_timeout, github=self.github)
        instances = self.runtime.instances()
        if drain:
            return Plan(len(jobs), len(instances), 0, "draining; admission disabled")
        plan = make_plan(len(jobs), len(instances), self.maximum)
        if self.verify_accounting:
            from shared_runner_pool import inventory, registered_coverage
            registered_coverage(inventory(), self.github.runners(), (self.label, *self.compat_labels))
        if self.shared_parent:
            from shared_runner_pool import sample
            evidence = sample(self.shared_parent, self.github.runners(), (self.label, *self.compat_labels), owner_unit=self.shared_unit, history=self.history, jobs=getattr(self.github, "job_metadata", []))
            count = self.adaptive.decide(len(jobs), evidence, time.monotonic())
            plan = Plan(len(jobs), len(instances), count, "shared pool; predicted memory overcommit risk", {
                "cpu": evidence.cpu, "memory": evidence.memory,
                "predicted_growth": evidence.predicted_growth,
                "startup_prediction": evidence.startup_prediction,
                "bootstraps": evidence.bootstraps, "pressure": evidence.pressure,
                "oom_hold": evidence.oom, "memory_high": int(evidence.memory_ceiling * .9),
                "hard_limit_sum": evidence.committed_memory,
                "memory_overcommit": evidence.committed_memory > evidence.memory_ceiling,
            })
            self.cpu = "6"
            self.memory = str(12 * 1024**3)
            if apply and self.history:
                self.history.save()
        elif self.resource_budget:
            from runner_resource_budget import allocate, sample

            allocation = allocate(len(jobs), sample())
            plan = Plan(len(jobs), len(instances), allocation.count, allocation.reason)
            self.cpu = str(allocation.cpu)
            self.memory = str(allocation.memory)
        if not apply:
            return plan
        for _ in range(plan.spawn):
            if self.shared_parent:
                # Re-sample immediately before registration; a changed inventory
                # restarts settling instead of consuming stale capacity.
                evidence = sample(self.shared_parent, self.github.runners(), (self.label, *self.compat_labels), owner_unit=self.shared_unit, history=self.history, jobs=getattr(self.github, "job_metadata", []))
                if not self.adaptive.decide(len(jobs), evidence, time.monotonic()):
                    return Plan(len(jobs), len(instances), 0, "pool changed before launch")
                self.adaptive.launched(time.monotonic())
            name = f"{self.prefix}{int(time.time())}-{secrets.token_hex(3)}"
            runner_id, jit_config = self.github.generate_jit(name, self.label, self.compat_labels)
            try:
                if self.shared_parent:
                    self.runtime.receipts.register(runner_id, name)
                self.runtime.launch(
                    name,
                    jit_config,
                    runner_id,
                    cpu=self.cpu,
                    memory=self.memory,
                )
            except LaunchUncertain:
                raise
            except (AutoscalerError, OSError, ValueError, KeyError, subprocess.SubprocessError):
                self.github.delete_runner(runner_id)
                raise
        return plan


def build_autoscaler() -> Autoscaler:
    repository = os.environ.get("GITHUB_REPOSITORY", "Kaixxrua/AIGCNEWS")
    label = os.environ.get("AIGCNEWS_RUNNER_LABEL", DEFAULT_LABEL)
    prefix = os.environ.get("AIGCNEWS_RUNNER_PREFIX", DEFAULT_PREFIX)
    maximum = int(os.environ.get("AIGCNEWS_RUNNER_MAX", "2"))
    if maximum < 1:
        raise AutoscalerError("AIGCNEWS_RUNNER_MAX must be positive")
    github = ApiClient(
        repository,
        os.environ.get("GH_TOKEN", ""),
        int(os.environ.get("AIGCNEWS_RUNNER_GROUP_ID", "1")),
    )
    runtime = LxdRuntime(
        os.environ.get("AIGCNEWS_RUNNER_TEMPLATE", "aigcnews-ci-template"),
        prefix,
        Path(
            os.environ.get(
                "AIGCNEWS_RUNNER_LOGS",
                str(Path.home() / ".local/state/aigcnews-ci-runners"),
            )
        ),
    )
    runtime.expected_proxy_connect = os.environ.get("AIGCNEWS_RUNNER_EXPECTED_PROXY_CONNECT")
    scaler = Autoscaler(
        github,
        runtime,
        label=label,
        compat_labels=tuple(
            item.strip() for item in os.environ.get("AIGCNEWS_RUNNER_COMPAT_LABELS", "").split(",")
            if item.strip()
        ),
        prefix=prefix,
        maximum=maximum,
        cpu=os.environ.get("AIGCNEWS_RUNNER_CPU", "4"),
        memory=os.environ.get("AIGCNEWS_RUNNER_MEMORY", "8GiB"),
        idle_timeout=timedelta(
            minutes=int(os.environ.get("AIGCNEWS_RUNNER_IDLE_MINUTES", "5"))
        ),
    )
    scaler.resource_budget = True
    scaler.verify_accounting = True
    parent = os.environ.get("AIGCNEWS_RUNNER_SHARED_CGROUP", "")
    if parent:
        from runner_pool_receipts import Receipts
        from runner_workloads import History
        from shared_runner_pool import AdaptiveAdmission
        unit = os.environ.get("AIGCNEWS_RUNNER_SHARED_UNIT", "")
        if not unit:
            raise AutoscalerError("AIGCNEWS_RUNNER_SHARED_UNIT is required with shared parent")
        scaler.shared_unit = unit
        runtime.shared_unit = unit
        scaler.shared_parent = parent
        runtime.shared_parent = parent
        scaler.adaptive = AdaptiveAdmission()
        scaler.history = History(Path.home() / ".local/state/aigcnews-ci-runners/workload-history.json")
        runtime.history = scaler.history
        runtime.receipts = Receipts(Path.home() / ".local/state/aigcnews-ci-runners/job-receipts")
    return scaler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--drain", action="store_true", help="collect final receipts and reap; never admit")
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=int(os.environ.get("AIGCNEWS_RUNNER_POLL_SECONDS", "20")),
    )
    args = parser.parse_args(argv)
    if args.poll_seconds < 5:
        parser.error("--poll-seconds must be at least 5")
    try:
        lock_path = Path.home() / ".local/state/aigcnews-ci-runners/controller.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock = lock_path.open("a")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        autoscaler = build_autoscaler()
        while True:
            try:
                plan = autoscaler.reconcile(apply=args.apply, drain=args.drain)
                print(json.dumps(asdict(plan)), flush=True)
            except TransientGitHubError as exc:
                if not args.loop:
                    raise
                # No mutation is replayed. Next poll revalidates queue and live
                # cgroups; the singleton controller retains its settling state.
                print(json.dumps({"error": str(exc), "retry": "next_poll"}),
                      file=sys.stderr, flush=True)
            if not args.loop:
                return 0
            time.sleep(args.poll_seconds)
    except (AutoscalerError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
