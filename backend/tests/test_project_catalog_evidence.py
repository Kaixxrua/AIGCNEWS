from __future__ import annotations

from datetime import datetime, timezone

from backend.app.services.project_catalog_evidence import build_project_catalog_evidence


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
