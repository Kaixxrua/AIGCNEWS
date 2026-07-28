from __future__ import annotations

import hashlib
import json
from unittest.mock import MagicMock, patch

from scripts import project_catalog_preflight


def smoke_evidence(revision: str) -> dict[str, str]:
    evidence = {
        "status": "passed",
        "revision": revision,
        "suite": "project-catalog-contract-v1",
    }
    digest = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {**evidence, "result_sha256": digest}


def versioned_evidence(
    kind: str, *, release_id: str, revision: str, image: str, topology: str
) -> dict[str, object]:
    evidence = {
        "evidence_version": 1,
        "kind": kind,
        "status": "match" if kind == "shadow" else "passed",
        "release_id": release_id,
        "revision": revision,
        "image_sha256": image,
        "topology_sha256": topology,
        "suite": f"{kind}-v1",
    }
    digest = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {**evidence, "result_sha256": digest}


def test_parser_has_no_database_credentials() -> None:
    parser = project_catalog_preflight.build_parser()
    options = {
        option for action in parser._actions for option in action.option_strings
    }
    assert "--password" not in options
    assert "--dsn" not in options
    assert "--apply" not in options


def test_preflight_writes_sanitized_ready_artifact(tmp_path, capsys) -> None:
    output = tmp_path / "evidence.json"
    smoke = tmp_path / "smoke.json"
    smoke.write_text(json.dumps(smoke_evidence("abc123")), encoding="utf-8")
    worker = MagicMock()
    worker.prove_barrier.return_value = {"barrier_id": 7, "barrier_proven": True}
    consistency = MagicMock()
    consistency.verify.return_value = {
        "status": "match",
        "stable": True,
        "readiness_status": "ready",
    }
    sequences = MagicMock()
    sequences.inspect.return_value = {"status": "ready"}
    with (
        patch.object(project_catalog_preflight, "ProjectCatalogSyncWorker", return_value=worker),
        patch.object(project_catalog_preflight, "ProjectCatalogConsistencyService", return_value=consistency),
        patch.object(project_catalog_preflight, "ProjectCatalogSequenceService", return_value=sequences),
        patch.object(project_catalog_preflight.settings, "project_catalog_outbox_capture_enabled", True),
        patch.object(project_catalog_preflight.settings, "project_catalog_sync_worker_enabled", True),
        patch.object(project_catalog_preflight.mysql_database, "close"),
        patch.object(project_catalog_preflight.postgres_database, "close"),
    ):
        code = project_catalog_preflight.main(
            [
                "--release-id",
                "release-1",
                "--revision",
                "abc123",
                "--target-database",
                "catalog_test",
                "--target-schema",
                "public",
                "--barrier-id",
                "7",
                "--smoke-evidence",
                str(smoke),
                "--output",
                str(output),
            ]
        )

    assert code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ready"
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["ready"] is True
    assert artifact["revision"] == "abc123"


def test_preflight_v2_requires_bound_versioned_inputs(tmp_path, capsys) -> None:
    output = tmp_path / "evidence.json"
    topology = tmp_path / "compose.yml"
    topology.write_text("services: {}\n", encoding="utf-8")
    topology_digest = hashlib.sha256(topology.read_bytes()).hexdigest()
    image = "a" * 64
    paths = {}
    for kind in ("shadow", "smoke", "rollback"):
        path = tmp_path / f"{kind}.json"
        path.write_text(
            json.dumps(
                versioned_evidence(
                    kind,
                    release_id="release-v2",
                    revision="abc123",
                    image=image,
                    topology=topology_digest,
                )
            ),
            encoding="utf-8",
        )
        paths[kind] = path
    worker = MagicMock()
    worker.prove_barrier.return_value = {"barrier_id": 7, "barrier_proven": True}
    consistency = MagicMock()
    consistency.verify.return_value = {
        "status": "match",
        "stable": True,
        "readiness_status": "ready",
    }
    sequences = MagicMock()
    sequences.inspect.return_value = {"status": "ready"}
    with (
        patch.object(project_catalog_preflight, "ProjectCatalogSyncWorker", return_value=worker),
        patch.object(project_catalog_preflight, "ProjectCatalogConsistencyService", return_value=consistency),
        patch.object(project_catalog_preflight, "ProjectCatalogSequenceService", return_value=sequences),
        patch.object(project_catalog_preflight.settings, "project_catalog_outbox_capture_enabled", True),
        patch.object(project_catalog_preflight.settings, "project_catalog_sync_worker_enabled", True),
        patch.object(project_catalog_preflight, "source_identity_sha256", return_value="c" * 64),
        patch.object(project_catalog_preflight.mysql_database, "close"),
        patch.object(project_catalog_preflight.postgres_database, "close"),
    ):
        code = project_catalog_preflight.main(
            [
                "--release-id", "release-v2", "--revision", "abc123",
                "--target-database", "catalog", "--target-schema", "public",
                "--barrier-id", "7", "--image-digest", image,
                "--topology-file", str(topology),
                "--shadow-evidence", str(paths["shadow"]),
                "--smoke-evidence", str(paths["smoke"]),
                "--rollback-evidence", str(paths["rollback"]),
                "--output", str(output),
            ]
        )

    assert code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ready"
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["artifact_version"] == 2
    assert artifact["release"]["topology_sha256"] == topology_digest


def test_preflight_rejects_partial_v2_inputs_before_database_calls(tmp_path, capsys) -> None:
    smoke = tmp_path / "smoke.json"
    smoke.write_text(json.dumps(smoke_evidence("abc123")), encoding="utf-8")
    with (
        patch.object(project_catalog_preflight, "ProjectCatalogSyncWorker") as worker,
        patch.object(project_catalog_preflight.mysql_database, "close"),
        patch.object(project_catalog_preflight.postgres_database, "close"),
    ):
        code = project_catalog_preflight.main(
            [
                "--release-id", "release-1", "--revision", "abc123",
                "--target-database", "catalog", "--target-schema", "public",
                "--barrier-id", "7", "--image-digest", "a" * 64,
                "--smoke-evidence", str(smoke), "--output", "unused.json",
            ]
        )

    assert code == 1
    worker.assert_not_called()
    assert "ValueError" in capsys.readouterr().err


def test_preflight_failure_does_not_print_secret(tmp_path, capsys) -> None:
    smoke = tmp_path / "smoke.json"
    smoke.write_text(json.dumps(smoke_evidence("abc123")), encoding="utf-8")
    with (
        patch.object(
            project_catalog_preflight,
            "ProjectCatalogSyncWorker",
            side_effect=RuntimeError("postgres://user:secret@db/catalog"),
        ),
        patch.object(project_catalog_preflight.mysql_database, "close"),
        patch.object(project_catalog_preflight.postgres_database, "close"),
    ):
        code = project_catalog_preflight.main(
            [
                "--release-id",
                "release-1",
                "--revision",
                "abc123",
                "--target-database",
                "catalog_test",
                "--target-schema",
                "public",
                "--barrier-id",
                "7",
                "--smoke-evidence",
                str(smoke),
                "--output",
                "unused.json",
            ]
        )

    captured = capsys.readouterr()
    assert code == 1
    assert "RuntimeError" in captured.err
    assert "secret" not in captured.err
