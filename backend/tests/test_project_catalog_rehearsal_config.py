from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = ROOT / "docker" / "docker-compose.project-catalog-rehearsal.yml"
SCRIPT_PATH = ROOT / "scripts" / "rehearse_project_catalog_cutover.sh"


def test_rehearsal_compose_is_self_contained_persistent_and_healthy() -> None:
    text = COMPOSE_PATH.read_text(encoding="utf-8")

    assert "name: aigcnews-project-catalog-rehearsal" in text
    for image in ("mysql:8.0", "postgres:16-alpine", "redis:7-alpine", "etcd:v3.5.5", "minio/minio:", "milvusdb/milvus:v2.4.6"):
        assert re.search(rf"image: .*{re.escape(image)}.*@sha256:[0-9a-f]{{64}}", text)
    for service in ("mysql-aigc:", "project-catalog-postgres:", "redis:", "etcd:", "minio:", "milvus:", "project-catalog-backend:"):
        assert service in text
    assert "project_catalog_rehearsal_mysql:/var/lib/mysql" in text
    assert "project_catalog_rehearsal_postgres:/var/lib/postgresql/data" in text
    assert text.count("healthcheck:") == 7
    assert "build:" not in text
    assert "/src" not in text
    assert "external: true" not in text
    assert "internal: true" in text
    assert "REHEARSAL_DEPENDENCY_NETWORK" not in text
    assert "MYSQL_HOST: mysql-aigc" in text
    assert "MILVUS_HOST: milvus" in text


def test_rehearsal_compose_has_dedicated_ephemeral_dependencies() -> None:
    text = COMPOSE_PATH.read_text(encoding="utf-8")

    assert "tmpfs: [/data]" in text
    assert "tmpfs: [/etcd]" in text
    assert "tmpfs: [/minio_data]" in text
    assert "tmpfs: [/var/lib/milvus]" in text
    assert "ports:" not in text
    assert "container_name:" not in text
    assert "x-rehearsal-labels: &rehearsal-labels" in text
    assert "labels: *rehearsal-labels" in text


def test_rehearsal_compose_has_safe_parameterized_defaults() -> None:
    text = COMPOSE_PATH.read_text(encoding="utf-8")

    assert "${REHEARSAL_CATALOG_BACKEND:-mysql}" in text
    assert "${REHEARSAL_CATALOG_CAPTURE:-true}" in text
    assert "${REHEARSAL_CATALOG_SYNC:-false}" in text
    assert "${REHEARSAL_CATALOG_SHADOW:-false}" in text
    assert "${REHEARSAL_SEARCH_STRATEGY:-legacy}" in text
    assert 'PROJECT_CATALOG_SHADOW_SAMPLE_RATE: "1.0"' in text
    assert 'PROJECT_SEARCH_SHADOW_SAMPLE_RATE: "1.0"' in text
    assert text.count("${REHEARSAL_RELEASE_ID:?set REHEARSAL_RELEASE_ID}") == 2
    assert 'SCHEDULER_ENABLED: "false"' in text
    for credential in ("MYSQL_ROOT_PASSWORD", "MYSQL_PASSWORD", "POSTGRES_PASSWORD", "MINIO_ROOT_PASSWORD"):
        assert f"REHEARSAL_{credential}:?" in text
    assert not re.search(r"(?:MYSQL|POSTGRES|MINIO).*PASSWORD:\s+(?!\$\{)", text)


def test_orchestrator_has_static_safety_guards() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "set -Eeuo pipefail" in text
    assert "@sha256:" in text
    assert "--project-name" in text
    assert "--no-build --pull never --wait" in text
    assert "--force-recreate project-catalog-backend" in text
    assert "REHEARSAL_CONFIRM" in text
    assert "require_env REHEARSAL_RELEASE_ID" in text
    assert "REHEARSAL_DEPENDENCY_NETWORK" not in text
    assert "postgres mode requires REHEARSAL_CATALOG_SYNC=true" in text
    assert "compose down --remove-orphans" in text
    assert "compose down --volumes" not in text
    assert "compose config --quiet" in text


def test_orchestrator_shell_syntax() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT_PATH)], check=True)
