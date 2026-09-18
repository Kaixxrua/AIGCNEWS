from __future__ import annotations

import importlib.util
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "ci" / "ephemeral_runner_autoscaler.py"
PREPARE_SCRIPT = ROOT / "scripts" / "ci" / "prepare_ephemeral_runner_template.sh"


def load_module():
    spec = importlib.util.spec_from_file_location("ephemeral_runner_autoscaler", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


autoscaler = load_module()


class FakeGitHub:
    def __init__(self, jobs: list[int]):
        self.jobs = jobs
        self.generated: list[str] = []
        self.deleted: list[int] = []

    def queued_jobs(self, label: str):
        assert label == "aigcnews-ci-ephemeral"
        return self.jobs

    def generate_jit(self, name: str, label: str):
        self.generated.append(name)
        return 100 + len(self.generated), f"jit-{name}"

    def delete_runner(self, runner_id: int):
        self.deleted.append(runner_id)


class FakeRuntime:
    def __init__(self, instances=None, fail=False):
        self.data = list(instances or [])
        self.fail = fail
        self.reaped = 0
        self.launched: list[tuple[str, str, int, str, str]] = []

    def instances(self):
        return self.data

    def reap(self, *, idle_timeout):
        assert idle_timeout == timedelta(minutes=5)
        self.reaped += 1
        return []

    def launch(self, name, jit_config, runner_id, *, cpu, memory):
        if self.fail:
            raise autoscaler.AutoscalerError("launch failed")
        self.launched.append((name, jit_config, runner_id, cpu, memory))
        self.data.append(autoscaler.Instance(name, "RUNNING"))

    def destroy(self, name: str):
        self.data = [item for item in self.data if item.name != name]


def build(github, runtime, maximum=2):
    return autoscaler.Autoscaler(
        github,
        runtime,
        label="aigcnews-ci-ephemeral",
        prefix="aigcnews-ci-job-",
        maximum=maximum,
        cpu="4",
        memory="8GiB",
        idle_timeout=timedelta(minutes=5),
    )


def test_plan_respects_capacity_and_never_overprovisions():
    assert autoscaler.make_plan(5, 0, 2).spawn == 2
    assert autoscaler.make_plan(5, 1, 2).spawn == 1
    assert autoscaler.make_plan(5, 2, 2).spawn == 0
    assert autoscaler.make_plan(0, 0, 2).spawn == 0


def test_dry_run_has_no_runtime_or_github_side_effects():
    github = FakeGitHub([1, 2, 3])
    runtime = FakeRuntime([autoscaler.Instance("aigcnews-ci-job-existing", "RUNNING")])

    plan = build(github, runtime).reconcile(apply=False)

    assert plan.spawn == 1
    assert runtime.reaped == 0
    assert not runtime.launched
    assert not github.generated


def test_apply_reaps_then_starts_only_available_jit_runners():
    github = FakeGitHub([1, 2, 3])
    runtime = FakeRuntime()

    plan = build(github, runtime).reconcile(apply=True)

    assert plan.spawn == 2
    assert runtime.reaped == 1
    assert len(runtime.launched) == 2
    assert all(item[3:] == ("4", "8GiB") for item in runtime.launched)


def test_failed_launch_removes_registered_runner():
    github = FakeGitHub([1])
    runtime = FakeRuntime(fail=True)

    try:
        build(github, runtime).reconcile(apply=True)
    except autoscaler.AutoscalerError as exc:
        assert str(exc) == "launch failed"
    else:
        raise AssertionError("expected launch failure")

    assert github.deleted == [101]


def test_lxd_launch_starts_runner_without_blocking_autoscaler(tmp_path):
    runtime = autoscaler.LxdRuntime("template", "job-", tmp_path)
    commands: list[list[str]] = []

    def command(arguments, **_kwargs):
        commands.append(arguments)
        return autoscaler.subprocess.CompletedProcess(arguments, 0, b"", b"")

    runtime.command = command
    runtime.launch("job-one", "jit", 7, cpu="4", memory="8GiB")

    assert [
        "exec",
        "job-one",
        "--",
        "systemctl",
        "start",
        "--no-block",
        "aigcnews-ephemeral-runner.service",
    ] in commands


def test_jit_registration_includes_labels_required_by_workflows():
    client = autoscaler.ApiClient("owner/repository", "token")
    documents = []

    def request(method, path, document=None):
        documents.append((method, path, document))
        return {"runner": {"id": 7}, "encoded_jit_config": "jit"}

    client.request = request

    assert client.generate_jit("job-one", "aigcnews-ci-ephemeral") == (7, "jit")
    assert documents[0][2]["labels"] == [
        "self-hosted",
        "linux",
        "x64",
        "aigcnews-ci-ephemeral",
    ]


def test_template_keeps_only_the_isolated_public_registry_cache():
    source = PREPARE_SCRIPT.read_text(encoding="utf-8")

    assert "docker inspect --format '{{.Id}}' ci-registry" in source
    assert '[[ "$container" == "$registry_id" ]]' in source
    assert "docker ps --all --quiet --no-trunc" in source
    assert '[[ "$volume" == "$registry_volume" ]]' in source
    assert "systemctl start docker.service" in source
    assert "docker info >/dev/null" in source
    assert "docker builder prune --all --force" in source
    assert "rm -rf /var/lib/docker" not in source
