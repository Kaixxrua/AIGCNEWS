from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = ROOT / "docker" / "docker-compose.yml"
SCRIPT_PATH = ROOT / "scripts" / "manage_main_stack.sh"
UNIT_PATH = ROOT / "deploy" / "systemd" / "aigcnews-compose@.service"


def test_main_compose_has_health_gated_boot_contract() -> None:
    text = COMPOSE_PATH.read_text(encoding="utf-8")

    assert text.startswith("name: docker\n")
    for service in ("etcd", "minio", "milvus", "attu", "neo4j"):
        assert re.search(
            rf"^  {service}:\n(?:(?:    |$).*\n)*?    restart: unless-stopped$",
            text,
            re.MULTILINE,
        )
    assert "http://127.0.0.1:9091/healthz" in text
    assert "http://127.0.0.1:8000/api/ready" in text
    for mysql_runtime_marker in (
        "mysql-aigc",
        "mysqladmin",
        '"3306:3306"',
        "mysql_data",
    ):
        assert mysql_runtime_marker not in text
    assert '["CMD", "redis-cli", "ping"]' in text
    assert text.count("condition: service_healthy") == 8
    backend_dependencies = text.split("  backend-api:", 1)[1].split(
        "\n  project-catalog-postgres:\n", 1
    )[0]
    for dependency in ("redis", "milvus", "project-catalog-postgres"):
        assert f"      {dependency}:\n        condition: service_healthy" in backend_dependencies
    assert "./volumes/etcd:/etcd" in text
    assert "./volumes/minio:/minio_data" in text
    assert "./volumes/milvus:/var/lib/milvus" in text
    assert "${NEXT_PUBLIC_SUPABASE_URL:?set NEXT_PUBLIC_SUPABASE_URL}" in text
    assert "${NEXT_PUBLIC_SUPABASE_ANON_KEY:?set NEXT_PUBLIC_SUPABASE_ANON_KEY}" in text


def test_main_stack_orchestrator_has_static_safety_guards() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "set -Eeuo pipefail" in text
    assert '--project-name "${EXPECTED_PROJECT}"' in text
    assert "compose config --quiet" in text
    assert "--remove-orphans --no-build --pull never --wait --wait-timeout 300" in text
    assert '--env-file "${APP_ENV_FILE}"' in text
    assert '--env-file "${PRICEAI_ENV_FILE}"' in text
    assert "sudo" not in text
    assert "down --volumes" not in text
    assert "down -v" not in text
    assert "volume rm" not in text
    assert "volume prune" not in text


def test_main_stack_systemd_unit_is_non_destructive() -> None:
    text = UNIT_PATH.read_text(encoding="utf-8")

    assert "Requires=docker.service" in text
    assert "After=docker.service network-online.target" in text
    assert "Type=oneshot" in text
    assert "RemainAfterExit=yes" in text
    assert "User=%i" in text
    assert "EnvironmentFile=/home/%i/AIGCNEWS/.env" in text
    assert "EnvironmentFile=/home/%i/.priceai-node.env" in text
    assert "scripts/manage_main_stack.sh up" in text
    assert "WantedBy=multi-user.target" in text
    assert "ExecStop=" not in text


def test_main_stack_orchestrator_shell_syntax() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT_PATH)], check=True)
