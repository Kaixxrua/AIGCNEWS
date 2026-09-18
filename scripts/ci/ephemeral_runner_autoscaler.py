#!/usr/bin/env python3
"""Scale clean LXD GitHub Actions JIT runners for queued AIGCNEWS CI jobs."""

from __future__ import annotations

import argparse
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


class AutoscalerError(RuntimeError):
    pass


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


class GitHub(Protocol):
    def queued_jobs(self, label: str) -> list[int]: ...

    def generate_jit(self, name: str, label: str) -> tuple[int, str]: ...

    def delete_runner(self, runner_id: int) -> None: ...


class Runtime(Protocol):
    def instances(self) -> list[Instance]: ...

    def reap(self, *, idle_timeout: timedelta) -> list[str]: ...

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
                detail = exc.read().decode(errors="replace")[:1000]
                if method != "GET" or exc.code not in {429, 500, 502, 503, 504}:
                    raise AutoscalerError(
                        f"GitHub API {method} {path} failed ({exc.code}): {detail}"
                    ) from None
            except OSError as exc:
                if method != "GET":
                    raise AutoscalerError(
                        f"GitHub API {method} {path} failed: {exc}"
                    ) from None
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
        raise AutoscalerError(f"GitHub API {method} {path} exhausted retries")

    def queued_jobs(self, label: str) -> list[int]:
        runs: dict[int, dict[str, Any]] = {}
        for status in ("queued", "in_progress"):
            document = self.request(
                "GET", f"/actions/runs?status={status}&per_page=100"
            )
            for run in document.get("workflow_runs", []):
                runs[int(run["id"])] = run
        jobs: list[int] = []
        for run_id in sorted(runs):
            document = self.request(
                "GET", f"/actions/runs/{run_id}/jobs?filter=latest&per_page=100"
            )
            for job in document.get("jobs", []):
                labels = {str(item).lower() for item in job.get("labels", [])}
                if job.get("status") == "queued" and label.lower() in labels:
                    jobs.append(int(job["id"]))
        return jobs

    def generate_jit(self, name: str, label: str) -> tuple[int, str]:
        result = self.request(
            "POST",
            "/actions/runners/generate-jitconfig",
            {
                "name": name,
                "runner_group_id": self.runner_group_id,
                "labels": [label],
                "work_folder": "_work",
            },
        )
        return int(result["runner"]["id"]), str(result["encoded_jit_config"])

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
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            detail = getattr(exc, "stderr", b"").decode(errors="replace")[:1000]
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
        )

    def destroy(self, name: str) -> None:
        self.archive_logs(name)
        self.command(["delete", "--force", name])

    def reap(self, *, idle_timeout: timedelta) -> list[str]:
        removed: list[str] = []
        now = datetime.now(UTC)
        for instance in self.instances():
            stale_idle = (
                instance.status == "RUNNING"
                and instance.created_at is not None
                and now - instance.created_at > idle_timeout
                and not self.has_worker(instance.name)
            )
            if instance.status == "STOPPED" or stale_idle:
                self.destroy(instance.name)
                removed.append(instance.name)
        return removed

    def launch(
        self, name: str, jit_config: str, runner_id: int, *, cpu: str, memory: str
    ) -> None:
        created_at = datetime.now(UTC).isoformat()
        self.command(["copy", self.template, name])
        try:
            for key, value in (
                ("limits.cpu", cpu),
                ("limits.memory", memory),
                ("user.aigcnews.created_at", created_at),
                ("user.aigcnews.runner_id", str(runner_id)),
            ):
                self.command(["config", "set", name, key, value])
            self.command(["start", name])
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
            self.command(
                [
                    "exec",
                    name,
                    "--",
                    "systemctl",
                    "start",
                    "aigcnews-ephemeral-runner.service",
                ]
            )
        except AutoscalerError:
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
    ):
        self.github = github
        self.runtime = runtime
        self.label = label
        self.prefix = prefix
        self.maximum = maximum
        self.cpu = cpu
        self.memory = memory
        self.idle_timeout = idle_timeout

    def reconcile(self, *, apply: bool) -> Plan:
        if apply:
            self.runtime.reap(idle_timeout=self.idle_timeout)
        instances = self.runtime.instances()
        jobs = self.github.queued_jobs(self.label)
        plan = make_plan(len(jobs), len(instances), self.maximum)
        if not apply:
            return plan
        for _ in range(plan.spawn):
            name = f"{self.prefix}{int(time.time())}-{secrets.token_hex(3)}"
            runner_id, jit_config = self.github.generate_jit(name, self.label)
            try:
                self.runtime.launch(
                    name,
                    jit_config,
                    runner_id,
                    cpu=self.cpu,
                    memory=self.memory,
                )
            except AutoscalerError:
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
    return Autoscaler(
        github,
        runtime,
        label=label,
        prefix=prefix,
        maximum=maximum,
        cpu=os.environ.get("AIGCNEWS_RUNNER_CPU", "4"),
        memory=os.environ.get("AIGCNEWS_RUNNER_MEMORY", "8GiB"),
        idle_timeout=timedelta(
            minutes=int(os.environ.get("AIGCNEWS_RUNNER_IDLE_MINUTES", "20"))
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=int(os.environ.get("AIGCNEWS_RUNNER_POLL_SECONDS", "20")),
    )
    args = parser.parse_args(argv)
    if args.poll_seconds < 5:
        parser.error("--poll-seconds must be at least 5")
    try:
        autoscaler = build_autoscaler()
        while True:
            plan = autoscaler.reconcile(apply=args.apply)
            print(json.dumps(asdict(plan)), flush=True)
            if not args.loop:
                return 0
            time.sleep(args.poll_seconds)
    except (AutoscalerError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
