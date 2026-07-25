from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

ARTIFACT_VERSION = 1


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _json_digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def evaluate_project_catalog_gates(
    *,
    consistency: Mapping[str, Any],
    barrier: Mapping[str, Any],
    sequences: Mapping[str, Any] | None = None,
    smoke: Mapping[str, Any] | None = None,
    expected_backend: str = "postgres",
    capture_enabled: bool = True,
    sync_enabled: bool = True,
) -> dict[str, Any]:
    sequences = sequences or {
        "status": "ready"
        if consistency.get("readiness_status") == "ready"
        else "not_ready"
    }
    smoke = smoke or {"status": "not_run"}
    gates = {
        "consistency": consistency.get("status") == "match"
        and consistency.get("stable") is True
        and consistency.get("readiness_status", "ready") == "ready",
        "barrier": barrier.get("barrier_proven") is True,
        "sequences": sequences.get("status") == "ready",
        "capture_enabled": bool(capture_enabled),
        "sync_enabled": bool(sync_enabled),
        "smoke": smoke.get("status") in {"match", "passed"},
    }
    failed = [name for name, passed in gates.items() if not passed]
    return {
        "ready": not failed,
        "expected_backend": expected_backend,
        "scope": "public_catalog_reads_only",
        "gates": gates,
        "failed_gates": failed,
        "consistency": dict(consistency),
        "barrier": dict(barrier),
        "sequences": dict(sequences),
        "smoke": dict(smoke),
    }


def build_project_catalog_evidence(
    *,
    release_id: str,
    revision: str,
    target_database: str,
    target_schema: str,
    consistency: Mapping[str, Any],
    barrier: Mapping[str, Any],
    sequences: Mapping[str, Any] | None = None,
    smoke: Mapping[str, Any] | None = None,
    expected_backend: str = "postgres",
    capture_enabled: bool = True,
    sync_enabled: bool = True,
    validity_seconds: int = 1800,
    source_identity_sha256: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not release_id.strip() or not revision.strip():
        raise ValueError("release_id and revision are required")
    if validity_seconds <= 0:
        raise ValueError("validity_seconds must be positive")
    generated_at = (now or _utc_now()).astimezone(timezone.utc)
    gates = evaluate_project_catalog_gates(
        consistency=consistency,
        barrier=barrier,
        sequences=sequences,
        smoke=smoke,
        expected_backend=expected_backend,
        capture_enabled=capture_enabled,
        sync_enabled=sync_enabled,
    )
    artifact = {
        "artifact_version": ARTIFACT_VERSION,
        "release_id": release_id,
        "revision": revision,
        "target": {"database": target_database, "schema": target_schema},
        "source_identity_sha256": source_identity_sha256,
        "generated_at": generated_at.isoformat(),
        "expires_at": (generated_at + timedelta(seconds=validity_seconds)).isoformat(),
        **gates,
    }
    artifact["artifact_sha256"] = _json_digest(artifact)
    return artifact


def write_project_catalog_evidence(path: str | Path, artifact: Mapping[str, Any]) -> None:
    target = Path(path)
    payload = (
        json.dumps(dict(artifact), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    descriptor, temporary = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
