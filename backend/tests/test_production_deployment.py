from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

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
    monkeypatch.setattr(deploy, "checkout", lambda root, sha: observed.append(f"checkout:{sha}"))
    monkeypatch.setattr(
        deploy,
        "reconcile",
        lambda root, candidate: observed.append(f"reconcile:{candidate.source_sha}"),
    )

    assert deploy.deploy(tmp_path, release(SHA_A), lock_timeout=0) == "deployed"
    state = deploy.read_state(tmp_path / ".aigcnews-deploy/state.json")
    assert state["active_release"] == SHA_A
    assert state["in_progress"] is None
    assert observed == [f"checkout:{SHA_A}", f"reconcile:{SHA_A}"]
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
    assert '--match-head-commit "$HEAD_SHA"' in auto_merge
    assert '--head "$HEAD_BRANCH"' in auto_merge
    assert "--auto" not in auto_merge
    assert "startsWith(github.event.workflow_run.head_branch, 'session/')" in auto_merge
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

    assert all(legacy_ci_runner not in text for text in workflows.values())
    assert workflows["contract-baseline.yml"].count(ephemeral_runner) == 5
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
