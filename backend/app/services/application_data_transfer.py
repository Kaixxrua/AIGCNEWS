from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ApplicationTableTransferSpec:
    name: str
    columns: tuple[str, ...]
    cursor_columns: tuple[str, ...]
    conflict_columns: tuple[str, ...]
    dependencies: tuple[str, ...] = ()
    boolean_columns: tuple[str, ...] = ()
    datetime_columns: tuple[str, ...] = ()
    non_null_default_columns: tuple[str, ...] = ()
    fixed_char_columns: tuple[str, ...] = ()
    identity_column: str | None = None
    natural_key_columns: tuple[str, ...] = ()
    text_cursor_columns: tuple[str, ...] = ()
    json_columns: tuple[str, ...] = ()


def _spec(
    name: str,
    columns: tuple[str, ...],
    cursor_columns: tuple[str, ...],
    *,
    conflict_columns: tuple[str, ...] | None = None,
    dependencies: tuple[str, ...] = (),
    boolean_columns: tuple[str, ...] = (),
    datetime_columns: tuple[str, ...] = (),
    non_null_default_columns: tuple[str, ...] = (),
    fixed_char_columns: tuple[str, ...] = (),
    identity_column: str | None = None,
    natural_key_columns: tuple[str, ...] = (),
    text_cursor_columns: tuple[str, ...] = (),
    json_columns: tuple[str, ...] = (),
) -> ApplicationTableTransferSpec:
    return ApplicationTableTransferSpec(
        name=name,
        columns=columns,
        cursor_columns=cursor_columns,
        conflict_columns=conflict_columns or cursor_columns,
        dependencies=dependencies,
        boolean_columns=boolean_columns,
        datetime_columns=datetime_columns,
        non_null_default_columns=non_null_default_columns,
        fixed_char_columns=fixed_char_columns,
        identity_column=identity_column,
        natural_key_columns=natural_key_columns,
        text_cursor_columns=text_cursor_columns,
        json_columns=json_columns,
    )


APPLICATION_TABLE_TRANSFER_SPECS = (
    _spec(
        "users",
        (
            "id",
            "phone",
            "email",
            "email_verified",
            "invite_code_used",
            "username",
            "hashed_password",
            "role",
            "created_at",
        ),
        ("id",),
        boolean_columns=("email_verified",),
        datetime_columns=("created_at",),
        identity_column="id",
    ),
    _spec(
        "documents",
        (
            "id",
            "source",
            "source_channel",
            "title",
            "url",
            "summary",
            "published_date",
            "tags",
            "score",
            "raw_score",
            "rank_in_period",
            "indexed",
            "created_at",
            "in_daily",
            "in_weekly",
            "in_monthly",
            "local_pdf_path",
            "stars",
            "forks",
            "language",
        ),
        ("id",),
        boolean_columns=("indexed", "in_daily", "in_weekly", "in_monthly"),
        text_cursor_columns=("id",),
    ),
    _spec(
        "ingestion_tasks",
        (
            "id",
            "task_name",
            "status",
            "started_at",
            "finished_at",
            "error_msg",
            "item_count",
        ),
        ("id",),
        identity_column="id",
    ),
    _spec(
        "briefings",
        ("id", "date", "content", "created_at"),
        ("id",),
        identity_column="id",
    ),
    _spec(
        "rag_evaluations",
        (
            "id",
            "query",
            "answer",
            "sources_json",
            "recall_score",
            "citation_score",
            "subjective_score",
            "evaluated_at",
        ),
        ("id",),
        identity_column="id",
    ),
    _spec(
        "runtime_provider_settings",
        ("provider", "base_url", "api_key", "updated_at", "model_name"),
        ("provider",),
        datetime_columns=("updated_at",),
        text_cursor_columns=("provider",),
    ),
    _spec(
        "mcp_server_configs",
        (
            "id",
            "server_key",
            "display_name",
            "description",
            "url",
            "transport",
            "auth_type",
            "auth_token",
            "enabled",
            "last_test_status",
            "last_test_message",
            "last_test_at",
            "last_tools_json",
            "created_at",
            "updated_at",
        ),
        ("id",),
        boolean_columns=("enabled",),
        datetime_columns=("last_test_at", "created_at", "updated_at"),
        identity_column="id",
    ),
    _spec(
        "document_rank_snapshots",
        (
            "id",
            "doc_id",
            "snapshot_date",
            "source_channel",
            "rank_in_period",
            "raw_score",
            "score",
            "created_at",
        ),
        ("id",),
        dependencies=("documents",),
        identity_column="id",
    ),
    _spec(
        "conversations",
        (
            "id",
            "user_id",
            "scope",
            "scope_key",
            "title",
            "last_message_preview",
            "message_count",
            "last_accessed_at",
            "updated_at",
            "created_at",
        ),
        ("id",),
        dependencies=("users",),
        datetime_columns=("last_accessed_at", "updated_at", "created_at"),
        identity_column="id",
    ),
    _spec(
        "user_mcp_tokens",
        (
            "id",
            "user_id",
            "token_hash",
            "token_hint",
            "scopes_json",
            "client_type",
            "client_label",
            "expires_at",
            "revoked_at",
            "deleted_at",
            "created_at",
            "last_used_at",
        ),
        ("id",),
        dependencies=("users",),
        datetime_columns=(
            "expires_at",
            "revoked_at",
            "deleted_at",
            "created_at",
            "last_used_at",
        ),
        identity_column="id",
    ),
    _spec(
        "briefing_subscriptions",
        (
            "id",
            "user_id",
            "email",
            "source",
            "period",
            "is_active",
            "created_at",
            "updated_at",
        ),
        ("id",),
        dependencies=("users",),
        boolean_columns=("is_active",),
        datetime_columns=("created_at", "updated_at"),
        identity_column="id",
    ),
    _spec(
        "chat_messages",
        (
            "id",
            "conversation_id",
            "role",
            "content",
            "thinking",
            "sources_json",
            "attachments_json",
            "status",
            "parent_message_id",
            "created_at",
            "updated_at",
        ),
        ("id",),
        dependencies=("conversations",),
        datetime_columns=("created_at", "updated_at"),
        json_columns=("sources_json", "attachments_json"),
        identity_column="id",
    ),
    _spec(
        "chat_attachments",
        (
            "id",
            "user_id",
            "conversation_id",
            "file_name",
            "mime_type",
            "modality",
            "storage_path",
            "file_size",
            "page_count",
            "parse_status",
            "extract_text",
            "meta_json",
            "created_at",
            "updated_at",
        ),
        ("id",),
        dependencies=("users", "conversations"),
        datetime_columns=("created_at", "updated_at"),
        json_columns=("meta_json",),
        identity_column="id",
    ),
)

APPLICATION_TABLE_TRANSFER_BY_NAME = {
    spec.name: spec for spec in APPLICATION_TABLE_TRANSFER_SPECS
}


def validate_application_transfer_specs() -> None:
    names = [spec.name for spec in APPLICATION_TABLE_TRANSFER_SPECS]
    if len(names) != len(set(names)):
        raise ValueError("duplicate application transfer table spec")
    seen: set[str] = set()
    for spec in APPLICATION_TABLE_TRANSFER_SPECS:
        if not spec.columns or not spec.cursor_columns:
            raise ValueError(f"incomplete application transfer spec: {spec.name}")
        if not set(spec.cursor_columns).issubset(spec.columns):
            raise ValueError(f"invalid cursor columns for {spec.name}")
        if not set(spec.conflict_columns).issubset(spec.columns):
            raise ValueError(f"invalid conflict columns for {spec.name}")
        if not set(spec.dependencies).issubset(seen):
            raise ValueError(f"application transfer dependency order invalid: {spec.name}")
        typed_columns = (
            set(spec.boolean_columns)
            | set(spec.datetime_columns)
            | set(spec.json_columns)
        )
        if not typed_columns.issubset(spec.columns):
            raise ValueError(f"unknown typed columns for {spec.name}")
        if spec.identity_column is not None and spec.identity_column not in spec.columns:
            raise ValueError(f"invalid identity column for {spec.name}")
        seen.add(spec.name)


validate_application_transfer_specs()
