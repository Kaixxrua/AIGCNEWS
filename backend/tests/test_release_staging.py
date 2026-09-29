from __future__ import annotations

import re
from pathlib import Path

COMPOSE = Path(__file__).parents[2] / "deploy" / "staging" / "docker-compose.yml"


_APPLICATION_SERVICES = {
    "backend-api-staging",
    "mcp-api-go-staging",
    "frontend-web-staging",
}


def test_staging_compose_uses_manifest_digest_inputs_without_build_or_source_mounts() -> None:
    text = COMPOSE.read_text(encoding="utf-8")

    assert "build:" not in text
    assert not re.search(r"\n\s*-\s*[^\n:]+/(?:backend|frontend|src)(?::[^\n]*)?\s*$", text, re.MULTILINE)
    assert "../backend" not in text
    assert "../frontend" not in text
    assert "source-code mounts" in text

    for variable in (
        "AIGCNEWS_STAGING_BACKEND_IMAGE_DIGEST",
        "AIGCNEWS_STAGING_MCP_IMAGE_DIGEST",
        "AIGCNEWS_STAGING_FRONTEND_IMAGE_DIGEST",
    ):
        assert f"${{{variable}:?" in text


def test_staging_application_images_are_immutable_and_services_are_isolated() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    service_blocks = re.split(r"(?=^  [a-z][a-z0-9-]+:\s*$)", text, flags=re.MULTILINE)

    for service in _APPLICATION_SERVICES:
        block = next(part for part in service_blocks if part.startswith(f"  {service}:"))
        assert re.search(r"image:\s*\$\{AIGCNEWS_STAGING_[A-Z]+_IMAGE_DIGEST:\?", block)
        assert "container_name: aigcnews-staging-" in block
        assert "build:" not in block

    assert '"127.0.0.1:18000:8000"' in text
    assert '"127.0.0.1:18002:8000"' in text
    assert '"127.0.0.1:18080:80"' in text
    assert '"127.0.0.1:18443:443"' in text
    assert '"127.0.0.1:8000:8000"' not in text
    assert '"80:80"' not in text
    assert '"443:443"' not in text


def test_staging_defaults_disable_side_effects() -> None:
    text = COMPOSE.read_text(encoding="utf-8")

    for setting in (
        "SCHEDULER_ENABLED",
        "PAYMENTS_ENABLED",
        "TELEGRAM_PUSH_ENABLED",
        "X_SOURCE_ENABLED",
        "PROJECT_SEMANTIC_SEARCH_ENABLED",
        "PROJECT_SEMANTIC_INDEXING_ENABLED",
        "X_MEDIA_WARMUP_ENABLED",
    ):
        assert f'${{STAGING_{setting}:-false}}' in text
    assert '${AIGCNEWS_OPS_ALERT_DISABLED:-1}' in text


def test_contract_baseline_validates_staging_compose() -> None:
    workflow = (COMPOSE.parents[2] / ".github" / "workflows" / "contract-baseline.yml").read_text(
        encoding="utf-8"
    )
    assert "Validate digest-only staging compose file" in workflow
    assert "docker compose --file deploy/staging/docker-compose.yml config --quiet" in workflow
