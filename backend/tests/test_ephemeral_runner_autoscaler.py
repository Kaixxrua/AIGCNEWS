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

    def queued_jobs(self, label: str, compat_labels=()):
        assert label == "aigcnews-ci-ephemeral"
        return self.jobs

    def generate_jit(self, name: str, label: str, compat_labels=()):
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

    def reap(self, *, idle_timeout, github):
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
    runtime.launch("job-one", "jit", 7, cpu="1.8", memory="3865470566")

    assert ["config", "set", "job-one", "limits.cpu.allowance", "180ms/100ms"] in commands
    assert ["config", "set", "job-one", "limits.memory", "3865470566"] in commands
    assert ["config", "set", "job-one", "limits.memory.swap", "false"] in commands

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


def test_worker_probe_error_never_means_idle(tmp_path):
    import pytest

    runtime = autoscaler.LxdRuntime("template", "job-", tmp_path)
    runtime.command = lambda *args, **kwargs: autoscaler.subprocess.CompletedProcess(
        [], 2, b"", b"unavailable"
    )
    with pytest.raises(autoscaler.AutoscalerError, match="worker state"):
        runtime.has_worker("job-one")


def test_template_preserves_pinned_public_bases_without_business_images():
    source = PREPARE_SCRIPT.read_text()
    assert "node:22-alpine@sha256:c610" in source
    assert "nginx:alpine@sha256:4a730" in source
    assert 'docker create "$base"' in source
    assert 'docker rm --volumes "${keepers[@]}"' in source
    assert source.index('docker create "$base"') < source.index("docker image prune")


def test_reap_deregisters_before_destroy_and_fails_closed(tmp_path):
    import pytest

    runtime = autoscaler.LxdRuntime("template", "job-", tmp_path)
    runtime.instances = lambda: [autoscaler.Instance("job-one", "STOPPED", runner_id=7)]
    events = []
    runtime.destroy = lambda name: events.append(("destroy", name))
    github = FakeGitHub([])
    github.delete_runner = lambda runner_id: events.append(("unregister", runner_id))
    assert runtime.reap(idle_timeout=timedelta(minutes=5), github=github) == ["job-one"]
    assert events == [("unregister", 7), ("destroy", "job-one")]
    events.clear()

    def busy(_runner_id):
        raise autoscaler.AutoscalerError("busy or unreachable")

    github.delete_runner = busy
    with pytest.raises(autoscaler.AutoscalerError):
        runtime.reap(idle_timeout=timedelta(minutes=5), github=github)
    assert not events


def test_smoke_build_uses_isolated_runner_proxy():
    workflow = (ROOT / ".github/workflows/contract-baseline.yml").read_text()
    assert "--add-host host.docker.internal:host-gateway" in workflow
    assert "--build-arg HTTPS_PROXY=http://host.docker.internal:7895" in workflow


def test_resource_gate_overrides_fixed_runner_count(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts/ci"))
    import runner_resource_budget as budget

    monkeypatch.setattr(budget, "sample", lambda: budget.Usage(0, 0, 0, 0))
    runtime = FakeRuntime()
    scaler = build(FakeGitHub([1, 2, 3, 4]), runtime)
    scaler.resource_budget = True
    assert scaler.reconcile(apply=True).spawn == 3
    assert len(runtime.launched) == 3
    assert sum(float(item[3]) for item in runtime.launched) <= 5.4
    assert sum(int(item[4]) for item in runtime.launched) <= 12 * budget.GIB * .9


def test_resource_measurement_failure_never_launches(monkeypatch):
    import pytest
    monkeypatch.syspath_prepend(str(ROOT / "scripts/ci"))
    import runner_resource_budget as budget

    def failed():
        raise ValueError("unknown memory")

    monkeypatch.setattr(budget, "sample", failed)
    runtime = FakeRuntime()
    scaler = build(FakeGitHub([1]), runtime)
    scaler.resource_budget = True
    with pytest.raises(ValueError):
        scaler.reconcile(apply=True)
    assert not runtime.launched


def test_compatibility_queue_matches_alias_and_deduplicates_jobs():
    client = autoscaler.ApiClient("owner/repository", "token")
    jobs = [
        {"id": 1, "status": "queued", "labels": ["aigcnews-ci-ephemeral"]},
        {"id": 2, "status": "queued", "labels": ["AIGCNEWS-CI"]},
        {"id": 3, "status": "queued", "labels": ["aigcnews-ci", "aigcnews-ci-ephemeral"]},
        {"id": 2, "status": "queued", "labels": ["aigcnews-ci"]},
        {"id": 4, "status": "in_progress", "labels": ["aigcnews-ci"]},
        {"id": 5, "status": "queued", "labels": ["aigcnews-control"]},
    ]
    client.request = lambda method, path: (
        {"jobs": jobs} if "/jobs?" in path else {"workflow_runs": [{"id": 10}]}
    )
    assert client.queued_jobs(autoscaler.DEFAULT_LABEL) == [1, 3]
    assert client.queued_jobs(autoscaler.DEFAULT_LABEL, ("aigcnews-ci",)) == [1, 2, 3]


def test_configured_alias_reaches_queue_and_jit_registration(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "unused-test-token")
    monkeypatch.setenv("AIGCNEWS_RUNNER_LABEL", autoscaler.DEFAULT_LABEL)
    monkeypatch.setenv("AIGCNEWS_RUNNER_COMPAT_LABELS", " aigcnews-ci, AIGCNEWS-CI, ,aigcnews-ci-ephemeral")
    monkeypatch.setattr(autoscaler.Path, "home", lambda: Path("/nonexistent-test-home"))
    monkeypatch.syspath_prepend(str(ROOT / "scripts/ci"))
    import runner_resource_budget as budget

    monkeypatch.setattr(budget, "sample", lambda: budget.Usage(0, 0, 0, 0))
    scaler = autoscaler.build_autoscaler()
    scaler.runtime = FakeRuntime()
    registrations = []

    def request(method, path, document=None):
        if method == "POST":
            registrations.append(document)
            return {"runner": {"id": 7}, "encoded_jit_config": "jit"}
        if "/jobs?" in path:
            return {"jobs": [{"id": 1, "status": "queued", "labels": ["aigcnews-ci"]}]}
        return {"workflow_runs": [{"id": 10}]}

    scaler.github.request = request
    plan = scaler.reconcile(apply=True)
    assert plan.queued_jobs == plan.spawn == 1
    assert registrations[0]["labels"] == [
        "self-hosted", "linux", "x64", "aigcnews-ci-ephemeral", "aigcnews-ci"
    ]
    assert len(scaler.runtime.launched) == 1
    assert float(scaler.runtime.launched[0][3]) <= 5.4
    assert int(scaler.runtime.launched[0][4]) <= 12 * budget.GIB * .9

    monkeypatch.delenv("AIGCNEWS_RUNNER_COMPAT_LABELS")
    assert autoscaler.build_autoscaler().compat_labels == ()
