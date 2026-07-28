from __future__ import annotations

from datetime import datetime, timezone

from backend.app.services.project_catalog_evidence import (
    build_project_catalog_evidence,
    sanitize_evidence_input,
    verify_project_catalog_evidence,
)


def test_evidence_binds_release_target_barrier_and_expiry() -> None:
    artifact = build_project_catalog_evidence(
        release_id="release-7",
        revision="abc123",
        target_database="catalog_test",
        target_schema="public",
        consistency={"status": "match", "stable": True, "readiness_status": "ready"},
        barrier={"barrier_id": 42, "barrier_proven": True},
        sequences={"status": "ready"},
        smoke={"status": "passed", "suite": "contract-v1"},
        now=datetime(2026, 7, 24, tzinfo=timezone.utc),
        validity_seconds=1800,
    )

    assert artifact["ready"] is True
    assert artifact["release_id"] == "release-7"
    assert artifact["target"] == {"database": "catalog_test", "schema": "public"}
    assert artifact["barrier"]["barrier_id"] == 42
    assert artifact["expires_at"] == "2026-07-24T00:30:00+00:00"
    assert len(artifact["artifact_sha256"]) == 64


def test_evidence_reports_each_failed_gate_without_secret_values() -> None:
    artifact = build_project_catalog_evidence(
        release_id="release-safe",
        revision="rev-safe",
        target_database="catalog",
        target_schema="public",
        consistency={"status": "mismatch", "stable": False},
        barrier={"barrier_id": 3, "barrier_proven": False},
        sequences={"status": "not_ready"},
        smoke={"status": "failed"},
        capture_enabled=False,
        sync_enabled=False,
    )

    assert artifact["ready"] is False
    assert set(artifact["failed_gates"]) == {
        "consistency",
        "barrier",
        "sequences",
        "capture_enabled",
        "sync_enabled",
        "smoke",
    }


def test_v2_evidence_binds_image_topology_shadow_smoke_and_rollback() -> None:
    digest = "a" * 64
    artifact = build_project_catalog_evidence(
        release_id="release-8",
        revision="def456",
        image_digest=f"registry/backend@sha256:{digest}",
        topology_sha256="b" * 64,
        target_database="catalog",
        target_schema="public",
        consistency={"status": "match", "stable": True, "readiness_status": "ready"},
        barrier={"barrier_id": 9, "barrier_proven": True},
        sequences={"status": "ready"},
        shadow={"status": "match"},
        smoke={"status": "passed"},
        rollback={"status": "passed"},
        now=datetime(2026, 7, 24, tzinfo=timezone.utc),
    )

    assert artifact["artifact_version"] == 2
    assert artifact["release"]["image_sha256"] == digest
    assert artifact["ready"] is True
    assert verify_project_catalog_evidence(
        artifact,
        release_id="release-8",
        revision="def456",
        image_digest=digest,
        topology_sha256="b" * 64,
        now=datetime(2026, 7, 24, 0, 1, tzinfo=timezone.utc),
    )["valid"] is True


def test_v2_evidence_fails_closed_when_extended_gate_is_missing() -> None:
    import pytest

    with pytest.raises(ValueError, match="required together"):
        build_project_catalog_evidence(
            release_id="release-incomplete",
            revision="abc",
            image_digest="a" * 64,
            target_database="catalog",
            target_schema="public",
            consistency={"status": "match", "stable": True},
            barrier={"barrier_proven": True},
            smoke={"status": "passed"},
        )


def test_verifier_rejects_tampering_expiry_and_wrong_release() -> None:
    artifact = build_project_catalog_evidence(
        release_id="release-9",
        revision="abc",
        target_database="catalog",
        target_schema="public",
        consistency={"status": "match", "stable": True, "readiness_status": "ready"},
        barrier={"barrier_proven": True},
        smoke={"status": "passed"},
        now=datetime(2026, 7, 24, tzinfo=timezone.utc),
    )
    artifact["target"]["schema"] = "tampered"

    result = verify_project_catalog_evidence(
        artifact,
        release_id="wrong",
        now=datetime(2026, 7, 25, tzinfo=timezone.utc),
    )

    assert result["valid"] is False
    assert set(result["failed_checks"]) >= {"artifact_sha256", "expiry", "release_id"}


def test_versioned_input_is_digest_checked_and_sanitized() -> None:
    import hashlib
    import json

    evidence = {
        "evidence_version": 1,
        "kind": "shadow",
        "status": "match",
        "release_id": "release-10",
        "revision": "abc",
        "image_sha256": "a" * 64,
        "topology_sha256": "b" * 64,
        "suite": "shadow-v1",
        "sample_count": 12,
        "secret": "postgres://user:password@db/catalog",
    }
    evidence["result_sha256"] = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    sanitized = sanitize_evidence_input(
        evidence,
        kind="shadow",
        release_id="release-10",
        revision="abc",
        image_sha256="a" * 64,
        topology_sha256="b" * 64,
    )

    assert sanitized["sample_count"] == 12
    assert "secret" not in sanitized
    assert "password" not in str(sanitized)
