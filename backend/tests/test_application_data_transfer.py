from __future__ import annotations

import json
from pathlib import Path

from backend.app.services.application_data_transfer import (
    APPLICATION_TABLE_TRANSFER_BY_NAME,
    APPLICATION_TABLE_TRANSFER_SPECS,
    validate_application_transfer_specs,
)

MANIFEST = Path(__file__).resolve().parents[1] / "migrations" / "mysql_to_postgres_manifest.json"


def test_application_transfer_specs_cover_every_manifest_migrate_table() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    migrate_tables = {
        name
        for name, entry in manifest["tables"].items()
        if entry["disposition"] == "migrate"
    }

    assert set(APPLICATION_TABLE_TRANSFER_BY_NAME) == migrate_tables
    assert len(APPLICATION_TABLE_TRANSFER_SPECS) == 13


def test_application_transfer_specs_follow_foreign_key_dependency_order() -> None:
    validate_application_transfer_specs()
    positions = {
        spec.name: index for index, spec in enumerate(APPLICATION_TABLE_TRANSFER_SPECS)
    }

    for spec in APPLICATION_TABLE_TRANSFER_SPECS:
        for dependency in spec.dependencies:
            assert positions[dependency] < positions[spec.name]


def test_application_transfer_specs_preserve_sensitive_and_typed_fields() -> None:
    users = APPLICATION_TABLE_TRANSFER_BY_NAME["users"]
    mcp_servers = APPLICATION_TABLE_TRANSFER_BY_NAME["mcp_server_configs"]
    tokens = APPLICATION_TABLE_TRANSFER_BY_NAME["user_mcp_tokens"]
    messages = APPLICATION_TABLE_TRANSFER_BY_NAME["chat_messages"]
    attachments = APPLICATION_TABLE_TRANSFER_BY_NAME["chat_attachments"]

    assert "hashed_password" in users.columns
    assert "api_key" in APPLICATION_TABLE_TRANSFER_BY_NAME[
        "runtime_provider_settings"
    ].columns
    assert "auth_token" in mcp_servers.columns
    assert "token_hash" in tokens.columns
    assert set(messages.json_columns) == {"sources_json", "attachments_json"}
    assert attachments.json_columns == ("meta_json",)
    assert messages.dependencies == ("conversations",)
    assert attachments.dependencies == ("users", "conversations")


def test_postgres_only_runtime_credentials_are_not_mysql_transfer_input() -> None:
    assert "x_credentials" not in APPLICATION_TABLE_TRANSFER_BY_NAME
    assert all(spec.name != "x_credentials" for spec in APPLICATION_TABLE_TRANSFER_SPECS)


def test_all_generated_ids_have_identity_repair_metadata() -> None:
    identity_tables = {
        "users",
        "ingestion_tasks",
        "briefings",
        "rag_evaluations",
        "mcp_server_configs",
        "document_rank_snapshots",
        "conversations",
        "user_mcp_tokens",
        "briefing_subscriptions",
        "chat_messages",
        "chat_attachments",
    }

    assert {
        spec.name
        for spec in APPLICATION_TABLE_TRANSFER_SPECS
        if spec.identity_column == "id"
    } == identity_tables
