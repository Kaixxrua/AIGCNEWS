from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "release" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


build = load("build_candidate")
verify = load("verify_candidate")
gate = load("classify_gate")


def manifest(risk="green"):
    return build.build_manifest(
        source_sha="a" * 40,
        candidate_id="candidate-1",
        ci_run_id="run-1",
        dependency_lock_hashes={"backend": "b" * 64},
        migration_set_digest="c" * 64,
        migration_latest_version="0042",
        image_digests=["registry.example/app@sha256:" + "d" * 64],
        frontend_artifact_digest="e" * 64,
        risk=risk,
        actor="ci",
        evidence_digests={"tests": "f" * 64},
        created_at="2026-09-01T00:00:00Z",
    )


def test_manifest_has_exact_contract_and_immutable_image():
    value = manifest()
    verify.validate_manifest(value)
    assert gate.classify_gate(value) == "automatic"
    with pytest.raises(ValueError, match="immutable"):
        value["image_digests"] = ["registry.example/app:latest"]
        verify.validate_manifest(value)


def test_verification_rejects_dirty_tree_and_protected_sha_mismatch():
    value = manifest()
    with pytest.raises(ValueError, match="dirty"):
        verify.verify_candidate(manifest=value, root=ROOT, protected_sha="a" * 40, dirty=True)
    with pytest.raises(ValueError, match="protected-main"):
        verify.verify_candidate(manifest=value, root=ROOT, protected_sha="b" * 40, dirty=False)


def test_verification_rejects_digest_substitution():
    value = manifest()
    with pytest.raises(ValueError, match="exactly match"):
        verify.verify_candidate(
            manifest=value,
            root=ROOT,
            protected_sha="a" * 40,
            dirty=False,
            expected_images=["registry.example/app@sha256:" + "1" * 64],
        )
    with pytest.raises(ValueError, match="frontend artifact"):
        verify.verify_candidate(
            manifest=value, root=ROOT, protected_sha="a" * 40, dirty=False, expected_frontend_digest="1" * 64
        )


@pytest.mark.parametrize(("risk", "expected"), [("green", "automatic"), ("yellow", "manual"), ("red", "blocked")])
def test_gate_classification(risk, expected):
    assert gate.classify_gate(manifest(risk)) == expected
    assert gate.classify_gate(manifest(risk), source_dirty=True) == "reject"
