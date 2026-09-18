from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "release" / "deploy_production.py"


def load_module():
    spec = importlib.util.spec_from_file_location("deploy_production", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


deploy = load_module()
SHA_A = "a" * 40
SHA_B = "b" * 40
DIGEST = "d" * 64


def release(sha: str = SHA_A):
    return deploy.Release(
        sha,
        f"ghcr.io/example/backend@sha256:{DIGEST}",
        f"ghcr.io/example/mcp@sha256:{DIGEST}",
        f"ghcr.io/example/frontend@sha256:{DIGEST}",
    )


def test_release_requires_immutable_images_and_round_trips_env():
    value = release()
    assert deploy.parse_release_env(value.env_text()) == value
    with pytest.raises(deploy.DeployError, match="immutable"):
        deploy.Release(SHA_A, "ghcr.io/example/backend:latest", value.mcp_image, value.frontend_image)


def test_state_is_atomic_and_fail_closed(tmp_path: Path):
    state_path = tmp_path / "control" / "state.json"
    expected = {"schema": deploy.SCHEMA, "active_release": SHA_A, "in_progress": None}
    deploy.write_state(state_path, expected)
    assert deploy.read_state(state_path) == expected

    state_path.write_text(json.dumps({"schema": "unknown"}), encoding="utf-8")
    with pytest.raises(deploy.DeployError, match="schema"):
        deploy.read_state(state_path)


def test_superseded_release_exits_before_checkout_or_reconcile(tmp_path: Path, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(deploy, "ensure_clean_tracked_tree", lambda root: calls.append("clean"))
    monkeypatch.setattr(deploy, "refresh_and_classify", lambda root, sha: "superseded")
    monkeypatch.setattr(deploy, "migrate_candidate", lambda *args: calls.append("migrate"))
    monkeypatch.setattr(deploy, "checkout", lambda *args: calls.append("checkout"))
    monkeypatch.setattr(deploy, "reconcile", lambda *args: calls.append("reconcile"))

    assert deploy.deploy(tmp_path, release(), lock_timeout=0) == "superseded"
    assert calls == ["clean"]


def test_failed_release_rolls_back_only_its_owned_attempt(tmp_path: Path, monkeypatch):
    root = tmp_path
    control = root / ".aigcnews-deploy"
    old_release = release(SHA_B)
    (root / ".release.env").write_text(old_release.env_text(), encoding="utf-8")
    deploy.write_state(
        control / "state.json",
        {"schema": deploy.SCHEMA, "active_release": SHA_B, "in_progress": None},
    )
    checkouts: list[str] = []
    reconciled: list[str] = []
    monkeypatch.setattr(deploy, "ensure_clean_tracked_tree", lambda root: None)
    monkeypatch.setattr(deploy, "refresh_and_classify", lambda root, sha: "current")
    monkeypatch.setattr(deploy, "run", lambda command, **kwargs: SHA_B)
    monkeypatch.setattr(deploy, "migrate_candidate", lambda *args: None)
    monkeypatch.setattr(deploy, "checkout", lambda root, sha: checkouts.append(sha))

    def fake_reconcile(root, candidate):
        reconciled.append(candidate.source_sha)
        if candidate.source_sha == SHA_A:
            raise deploy.DeployError("health check failed")

    monkeypatch.setattr(deploy, "reconcile", fake_reconcile)

    with pytest.raises(deploy.DeployError, match="previous runtime was restored"):
        deploy.deploy(root, release(SHA_A), lock_timeout=0)

    state = deploy.read_state(control / "state.json")
    assert state["active_release"] == SHA_B
    assert state["in_progress"] is None
    assert state["last_failed_release"] == SHA_A
    assert checkouts == [SHA_A, SHA_B]
    assert reconciled == [SHA_A, SHA_B]


def test_successful_release_commits_state_after_reconcile(tmp_path: Path, monkeypatch):
    observed: list[str] = []
    monkeypatch.setattr(deploy, "ensure_clean_tracked_tree", lambda root: None)
    monkeypatch.setattr(deploy, "refresh_and_classify", lambda root, sha: "current")
    monkeypatch.setattr(deploy, "run", lambda command, **kwargs: SHA_B)
    monkeypatch.setattr(deploy, "migrate_candidate", lambda *args: None)
    monkeypatch.setattr(deploy, "checkout", lambda root, sha: observed.append(f"checkout:{sha}"))
    monkeypatch.setattr(
        deploy,
        "reconcile",
        lambda root, candidate: observed.append(f"reconcile:{candidate.source_sha}"),
    )

    monkeypatch.setattr(deploy, "migrate_candidate", lambda *args: observed.append("migrate"))
    assert deploy.deploy(tmp_path, release(SHA_A), lock_timeout=0) == "deployed"
    state = deploy.read_state(tmp_path / ".aigcnews-deploy/state.json")
    assert state["active_release"] == SHA_A
    assert state["in_progress"] is None
    assert observed == [f"checkout:{SHA_A}", "migrate", f"reconcile:{SHA_A}"]
    assert deploy.parse_release_env((tmp_path / ".release.env").read_text(encoding="utf-8")) == release(SHA_A)


def test_workflows_serialize_only_production_and_merge_exact_validated_head():
    deployment = (ROOT / ".github/workflows/deploy-production.yml").read_text(encoding="utf-8")
    auto_merge = (ROOT / ".github/workflows/auto-merge.yml").read_text(encoding="utf-8")
    session_pr = (ROOT / ".github/workflows/session-pr.yml").read_text(encoding="utf-8")

    assert "'aigcnews-production-latest'" in deployment
    assert "format('aigcnews-production-skip-{0}', github.run_id)" in deployment
    assert "cancel-in-progress: false" in deployment
    assert deployment.index("concurrency:") < deployment.index("jobs:")
    assert deployment.count("concurrency:") == 1
    assert "AIGCNEWS_GODOT_RELEASE_ROOT" in deployment
    assert "AIGCNEWS_GODOT_RELEASE_ID" in deployment
    assert "AIGCNEWS_GODOT_RELEASE_DESCRIPTOR_SHA256" in deployment
    assert "stage_private_frontend.py" in deployment
    assert "--expected-release-id" in deployment
    assert "--expected-descriptor-sha256" in deployment
    assert "GodotContactScene.test.ts" in deployment
    assert "group: aigcnews-delivery-sweeper" in auto_merge
    assert "python3 scripts/ci/delivery_sweeper.py --apply" in auto_merge
    assert "--auto" not in auto_merge
    assert "startsWith(github.event.workflow_run.head_branch, 'session/')" in auto_merge
    assert "GH_TOKEN: ${{ secrets.AIGCNEWS_DELIVERY_TOKEN }}" in auto_merge
    assert "GH_TOKEN: ${{ github.token }}" not in auto_merge
    assert 'branches:\n      - "session/**"' in session_pr


def test_workflows_use_ephemeral_ci_and_isolated_production_runner():
    workflows = {
        path.name: path.read_text(encoding="utf-8")
        for path in (ROOT / ".github" / "workflows").glob("*.yml")
    }  # fmt: skip
    control_runner = "runs-on: [self-hosted, linux, aigcnews-control]"
    ephemeral_runner = "runs-on: [self-hosted, linux, aigcnews-ci-ephemeral]"
    legacy_ci_runner = "runs-on: [self-hosted, linux, aigcnews-ci]"
    production_runner = "runs-on: [self-hosted, linux, aigcnews-production]"

    assert all("runs-on: ubuntu-latest" not in text for text in workflows.values())
    baseline_jobs = yaml.safe_load(workflows["contract-baseline.yml"])["jobs"]
    test_jobs = {
        "backend-tests", "postgres-integration", "mcp-go", "compose-smoke", "frontend-build"
    }
    assert set(baseline_jobs) == test_jobs | {"pr-admission"}
    assert all(legacy_ci_runner not in text for text in workflows.values())
    assert workflows["contract-baseline.yml"].count(ephemeral_runner) == 6
    for job in baseline_jobs.values():
        assert job["runs-on"] == ["self-hosted", "linux", "aigcnews-ci-ephemeral"]
    admission = baseline_jobs["pr-admission"]
    assert any(step.get("uses") == "./.github/actions/check-pr-base" for step in admission["steps"])
    for name in test_jobs:
        assert baseline_jobs[name]["needs"] == "pr-admission"
        assert any(step.get("uses") == "./.github/actions/check-pr-base"
                   for step in baseline_jobs[name]["steps"])
    assert workflows["deploy-production.yml"].count(control_runner) == 1
    assert workflows["deploy-production.yml"].count(production_runner) == 4
    assert workflows["session-pr.yml"].count(control_runner) == 1
    assert workflows["auto-merge.yml"].count(control_runner) == 1
    assert workflows["delivery-sweeper.yml"].count(control_runner) == 1
    assert workflows["evals-contract.yml"].count(ephemeral_runner) == 2
    assert production_runner not in workflows["contract-baseline.yml"]
    assert "cache: pip" not in workflows["contract-baseline.yml"]
    assert "cache: npm" not in workflows["contract-baseline.yml"]
    assert "cache: false" in workflows["contract-baseline.yml"]


def test_main_compose_uses_digest_overrides_without_backend_source_mount():
    compose = (ROOT / "docker/docker-compose.yml").read_text(encoding="utf-8")
    assert "AIGCNEWS_BACKEND_IMAGE_DIGEST" in compose
    assert "AIGCNEWS_MCP_IMAGE_DIGEST" in compose
    assert "AIGCNEWS_FRONTEND_IMAGE_DIGEST" in compose
    assert "      - ../backend:/src/backend\n" not in compose


def test_deployment_entrypoint_can_execute_stack_controller():
    assert os.access(ROOT / "scripts/manage_main_stack.sh", os.X_OK)


def test_reconcile_reuses_exact_local_digests_without_registry(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(deploy, "run", lambda command, **kwargs: calls.append(command))
    monkeypatch.setattr(deploy, "probe_backend", lambda: calls.append(["probe"]))
    candidate = release()
    deploy.reconcile(tmp_path, candidate)
    assert calls[:3] == [["docker", "image", "inspect", image] for image in
                         (candidate.backend_image, candidate.mcp_image, candidate.frontend_image)]
    assert not any(command[:2] == ["docker", "pull"] for command in calls)
    assert calls[-1] == ["probe"]


def test_reconcile_pulls_only_missing_digest_before_switch(tmp_path, monkeypatch):
    calls = []
    candidate = release()

    def invoke(command, **kwargs):
        calls.append(command)
        if command == ["docker", "image", "inspect", candidate.backend_image]:
            raise deploy.DeployError("missing image")

    monkeypatch.setattr(deploy, "run", invoke)
    monkeypatch.setattr(deploy, "probe_backend", lambda: None)
    deploy.reconcile(tmp_path, candidate)
    assert [c for c in calls if c[:2] == ["docker", "pull"]] == [
        ["docker", "pull", candidate.backend_image]]
    assert calls.index(["docker", "pull", candidate.backend_image]) < len(calls) - 1


def test_trusted_builds_keep_images_and_cache_on_production_daemon():
    workflow = (ROOT / ".github/workflows/deploy-production.yml").read_text()
    assert workflow.count("builder: default") == 3
    assert workflow.count("load: true") == 3
    assert workflow.count("push: false") == 3
    assert "docker/setup-buildx-action" not in workflow
    assert "docker/login-action" not in workflow
    assert "packages: write" not in workflow


def test_failed_baseline_cannot_evict_pending_production_and_stale_builds_skip():
    workflow = (ROOT / ".github/workflows/deploy-production.yml").read_text()
    group = workflow.split("concurrency:", 1)[1].split("jobs:", 1)[0]
    assert "github.event.workflow_run.conclusion == 'success'" in group
    assert workflow.count("if: needs.metadata.outputs.eligible == 'true'") == 3
    assert 'git merge-base --is-ancestor "$SOURCE_SHA" "$latest"' in workflow
    assert workflow.index("Reject stale candidates") < workflow.index("build-backend:")


@pytest.mark.parametrize("previous_release", [False, True])
def test_migration_failure_never_switches_runtime(tmp_path, monkeypatch, previous_release):
    old = release(SHA_B)
    state_path = tmp_path / ".aigcnews-deploy/state.json"
    if previous_release:
        (tmp_path / ".release.env").write_text(old.env_text())
        deploy.write_state(state_path, {
            "schema": deploy.SCHEMA, "active_release": SHA_B, "in_progress": None,
        })
    calls = []
    monkeypatch.setattr(deploy, "ensure_clean_tracked_tree", lambda root: None)
    monkeypatch.setattr(deploy, "refresh_and_classify", lambda *args: "current")
    monkeypatch.setattr(deploy, "run", lambda *args, **kwargs: SHA_B)
    monkeypatch.setattr(deploy, "checkout", lambda root, sha: calls.append(sha))

    def failed_migration(root, candidate):
        assert deploy.parse_release_env((root / ".release.env").read_text()) == candidate
        assert deploy.read_state(state_path)["in_progress"] == SHA_A
        raise deploy.DeployError("migration failed")

    monkeypatch.setattr(deploy, "migrate_candidate", failed_migration)
    monkeypatch.setattr(deploy, "reconcile", lambda *args: pytest.fail("runtime switched"))
    monkeypatch.setattr(deploy, "reconcile_existing", lambda *args: pytest.fail("runtime restarted"))
    with pytest.raises(deploy.DeployError, match="previous runtime was not switched"):
        deploy.deploy(tmp_path, release(), lock_timeout=0)
    state = deploy.read_state(state_path)
    assert state.get("active_release") == (SHA_B if previous_release else None)
    assert state["in_progress"] is None
    assert state["last_failed_release"] == SHA_A
    assert calls == [SHA_A, SHA_B]
    if previous_release:
        assert (tmp_path / ".release.env").read_text() == old.env_text()
    else:
        assert not (tmp_path / ".release.env").exists()


@pytest.mark.parametrize("missing_image", [False, True])
def test_migration_uses_exact_candidate_image_and_release_environment(tmp_path, monkeypatch, missing_image):
    candidate = release()
    calls = []

    def invoke(command, **kwargs):
        calls.append((command, kwargs))
        if missing_image and command[:3] == ["docker", "image", "inspect"]:
            raise deploy.DeployError("missing image")

    monkeypatch.setattr(deploy, "run", invoke)
    monkeypatch.setenv("AIGCNEWS_BACKEND_IMAGE_DIGEST", "wrong:latest")
    deploy.migrate_candidate(tmp_path, candidate)
    assert calls[0][0] == ["docker", "image", "inspect", candidate.backend_image]
    assert [c for c, _ in calls if c[:2] == ["docker", "pull"]] == (
        [["docker", "pull", candidate.backend_image]] if missing_image else []
    )
    command, kwargs = calls[-1]
    assert command == [str(tmp_path / "scripts/manage_main_stack.sh"), "migrate"]
    assert kwargs["env"]["AIGCNEWS_RELEASE_ENV"] == str(tmp_path / ".release.env")
    assert kwargs["env"]["AIGCNEWS_BACKEND_IMAGE_DIGEST"] == candidate.backend_image


@pytest.mark.parametrize("migration_exit", [0, 17])
def test_stack_migration_entrypoint_preserves_compose_config_and_exit(tmp_path, migration_exit):
    import shutil
    import subprocess

    root = tmp_path / "checkout"
    (root / "scripts").mkdir(parents=True)
    (root / "docker").mkdir()
    script = root / "scripts/manage_main_stack.sh"
    shutil.copy2(ROOT / "scripts/manage_main_stack.sh", script)
    (root / ".env").write_text("")
    (root / ".release.env").write_text(release().env_text())
    (root / "docker/docker-compose.yml").write_text("services: {}")
    overlay = tmp_path / "private.yml"
    overlay.write_text("services: {}")
    (tmp_path / ".priceai-node.env").write_text("")
    binary = tmp_path / "bin"
    binary.mkdir()
    log = tmp_path / "calls.jsonl"
    docker = binary / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "with open(os.environ['CALL_LOG'], 'a') as f: f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "sys.exit(int(os.environ['MIGRATION_EXIT']) if 'run' in sys.argv else 0)\n"
    )
    docker.chmod(0o755)
    env = {**os.environ, "PATH": str(binary) + os.pathsep + os.environ["PATH"],
           "CALL_LOG": str(log), "MIGRATION_EXIT": str(migration_exit),
           "AIGCNEWS_PRIVATE_COMPOSE": str(overlay),
           "AIGCNEWS_RELEASE_ENV": str(root / ".release.env"), "COMPOSE_PROJECT_NAME": "docker"}
    result = subprocess.run([str(script), "migrate"], env=env, capture_output=True, text=True)
    assert result.returncode == migration_exit, result.stderr
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(calls) == 2
    assert calls[0][-2:] == ["config", "--quiet"]
    command = calls[1]
    assert command[:command.index("run")] == calls[0][:-2]
    for path in (root / ".env", root / ".release.env", overlay, tmp_path / ".priceai-node.env"):
        assert path.resolve() in [Path(arg).resolve() for arg in command if arg.startswith("/")]
    assert command[command.index("run"):-1] == [
        "run", "--rm", "--no-deps", "--pull", "never", "--entrypoint", "python", "backend-api", "-c",
    ]
    assert "PostgresMigrationRunner" in command[-1]
    assert "runner.apply()" in command[-1]
    assert "runner.status()" in command[-1]
    assert "postgres_database.close()" in command[-1]
    compile(command[-1], "migration-gate", "exec")
