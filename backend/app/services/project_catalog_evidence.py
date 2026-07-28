from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

ARTIFACT_VERSION = 2
LEGACY_ARTIFACT_VERSION = 1
EVIDENCE_INPUT_VERSION = 1
_SHA256_LENGTH = 64


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _json_digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sha256(value: Any, *, field: str) -> str:
    digest = str(value or "").strip().lower()
    if digest.startswith("sha256:"):
        digest = digest[7:]
    elif "@sha256:" in digest:
        digest = digest.rsplit("@sha256:", 1)[1]
    if len(digest) != _SHA256_LENGTH or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ValueError(f"{field} must contain an immutable sha256 digest")
    return digest


def _copy_fields(value: Mapping[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    """Copy only documented, non-secret evidence fields into the release artifact."""
    return {field: value[field] for field in fields if field in value}


def sanitize_evidence_input(
    value: Mapping[str, Any],
    *,
    kind: str,
    release_id: str,
    revision: str,
    image_sha256: str,
    topology_sha256: str,
) -> dict[str, Any]:
    if int(value.get("evidence_version") or 0) != EVIDENCE_INPUT_VERSION:
        raise ValueError(f"{kind} evidence version is unsupported")
    if value.get("kind") != kind:
        raise ValueError(f"{kind} evidence kind does not match")
    bindings = {
        "release_id": release_id,
        "revision": revision,
        "image_sha256": _sha256(image_sha256, field="image_sha256"),
        "topology_sha256": _sha256(topology_sha256, field="topology_sha256"),
    }
    for field, expected in bindings.items():
        supplied = str(value.get(field) or "").strip()
        if field.endswith("sha256"):
            supplied = _sha256(supplied, field=field)
        if supplied != expected:
            raise ValueError(f"{kind} evidence {field} does not match")
    supplied_digest = _sha256(value.get("result_sha256"), field=f"{kind} result_sha256")
    digest_payload = dict(value)
    digest_payload.pop("result_sha256", None)
    if supplied_digest != _json_digest(digest_payload):
        raise ValueError(f"{kind} evidence digest does not match")
    allowed = (
        "evidence_version",
        "kind",
        "status",
        "release_id",
        "revision",
        "image_sha256",
        "topology_sha256",
        "suite",
        "environment",
        "sample_count",
        "mismatch_count",
        "checked_at",
        "result_sha256",
    )
    sanitized = _copy_fields(value, allowed)
    if not str(sanitized.get("suite") or "").strip():
        raise ValueError(f"{kind} evidence suite is required")
    accepted_statuses = {
        "shadow": {"match", "passed"},
        "smoke": {"passed"},
        "rollback": {"passed"},
    }
    if sanitized.get("status") not in accepted_statuses[kind] | {"failed", "mismatch"}:
        raise ValueError(f"{kind} evidence status is invalid")
    return sanitized


def evaluate_project_catalog_gates(
    *,
    consistency: Mapping[str, Any],
    barrier: Mapping[str, Any],
    sequences: Mapping[str, Any] | None = None,
    shadow: Mapping[str, Any] | None = None,
    smoke: Mapping[str, Any] | None = None,
    rollback: Mapping[str, Any] | None = None,
    expected_backend: str = "postgres",
    capture_enabled: bool = True,
    sync_enabled: bool = True,
    require_extended: bool = False,
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
    if require_extended:
        gates["shadow"] = bool(shadow) and shadow.get("status") in {"match", "passed"}
        gates["rollback"] = bool(rollback) and rollback.get("status") == "passed"
    failed = [name for name, passed in gates.items() if not passed]
    result = {
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
    if require_extended:
        result["shadow"] = dict(shadow or {})
        result["rollback"] = dict(rollback or {})
    return result


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
    image_digest: str | None = None,
    topology_sha256: str | None = None,
    shadow: Mapping[str, Any] | None = None,
    rollback: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    release_id = release_id.strip()
    revision = revision.strip()
    if not release_id or not revision:
        raise ValueError("release_id and revision are required")
    if validity_seconds <= 0:
        raise ValueError("validity_seconds must be positive")
    extended_values = (image_digest, topology_sha256, shadow, rollback)
    extended = any(value is not None for value in extended_values)
    if extended and not all(value is not None for value in extended_values):
        raise ValueError(
            "image_digest, topology_sha256, shadow, and rollback are required together"
        )
    image_sha256 = _sha256(image_digest, field="image_digest") if extended else None
    topology_digest = (
        _sha256(topology_sha256, field="topology_sha256") if extended else None
    )
    generated_at = (now or _utc_now()).astimezone(timezone.utc)
    gates = evaluate_project_catalog_gates(
        consistency=consistency,
        barrier=barrier,
        sequences=sequences,
        shadow=shadow,
        smoke=smoke,
        rollback=rollback,
        expected_backend=expected_backend,
        capture_enabled=capture_enabled,
        sync_enabled=sync_enabled,
        require_extended=extended,
    )
    artifact = {
        "artifact_version": ARTIFACT_VERSION if extended else LEGACY_ARTIFACT_VERSION,
        "release_id": release_id,
        "revision": revision,
        "target": {"database": target_database, "schema": target_schema},
        "source_identity_sha256": source_identity_sha256,
        "generated_at": generated_at.isoformat(),
        "expires_at": (generated_at + timedelta(seconds=validity_seconds)).isoformat(),
        **gates,
    }
    if extended:
        artifact["release"] = {
            "id": release_id,
            "revision": revision,
            "image_sha256": image_sha256,
            "topology_sha256": topology_digest,
        }
    artifact["artifact_sha256"] = _json_digest(artifact)
    return artifact


def verify_project_catalog_evidence(
    artifact: Mapping[str, Any],
    *,
    release_id: str | None = None,
    revision: str | None = None,
    image_digest: str | None = None,
    topology_sha256: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Verify an artifact without databases, network calls, or state changes."""
    failures: list[str] = []
    version = artifact.get("artifact_version")
    if version not in {LEGACY_ARTIFACT_VERSION, ARTIFACT_VERSION}:
        failures.append("artifact_version")
    supplied_digest = str(artifact.get("artifact_sha256") or "").strip().lower()
    digest_payload = dict(artifact)
    digest_payload.pop("artifact_sha256", None)
    if supplied_digest != _json_digest(digest_payload):
        failures.append("artifact_sha256")
    try:
        expires_at = datetime.fromisoformat(str(artifact.get("expires_at") or ""))
        if expires_at.tzinfo is None or expires_at <= (now or _utc_now()).astimezone(timezone.utc):
            failures.append("expiry")
    except ValueError:
        failures.append("expiry")
    gates = artifact.get("gates")
    if (
        artifact.get("ready") is not True
        or artifact.get("failed_gates") != []
        or not isinstance(gates, Mapping)
        or not gates
        or not all(value is True for value in gates.values())
    ):
        failures.append("gates")
    expected = {"release_id": release_id, "revision": revision}
    for field, value in expected.items():
        if value is not None and artifact.get(field) != value:
            failures.append(field)
    if image_digest is not None or topology_sha256 is not None:
        release = artifact.get("release")
        if version != ARTIFACT_VERSION or not isinstance(release, Mapping):
            failures.append("release_identity")
        else:
            try:
                if image_digest is not None and release.get("image_sha256") != _sha256(
                    image_digest, field="image_digest"
                ):
                    failures.append("image_sha256")
                if topology_sha256 is not None and release.get(
                    "topology_sha256"
                ) != _sha256(topology_sha256, field="topology_sha256"):
                    failures.append("topology_sha256")
            except ValueError:
                failures.append("release_identity")
    return {
        "status": "valid" if not failures else "invalid",
        "valid": not failures,
        "artifact_version": version,
        "artifact_sha256": supplied_digest if len(supplied_digest) == 64 else None,
        "release_id": artifact.get("release_id"),
        "revision": artifact.get("revision"),
        "failed_checks": failures,
    }


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
