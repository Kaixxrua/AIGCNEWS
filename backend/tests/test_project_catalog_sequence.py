from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator
from unittest.mock import MagicMock, patch

from backend.app.services.project_catalog_sequence import (
    IdentitySequenceStatus,
    ProjectCatalogSequenceService,
)
from backend.app.services.project_catalog_transfer import TABLE_TRANSFER_SPEC_BY_NAME


class TransactionalDatabase:
    def __init__(self, connection: MagicMock) -> None:
        self.connection = connection

    @contextmanager
    def transaction(self) -> Iterator[MagicMock]:
        yield self.connection


def _service(connection: MagicMock) -> ProjectCatalogSequenceService:
    return ProjectCatalogSequenceService(
        mysql=object(),  # type: ignore[arg-type]
        postgres=TransactionalDatabase(connection),  # type: ignore[arg-type]
        config=type("Config", (), {"env": "development"})(),
    )


def test_inspection_reports_behind_without_consuming_sequence() -> None:
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [
        {"maximum_id": 12},
        {"sequence_name": "public.tool_websites_id_seq"},
        {"last_value": 10, "is_called": True},
    ]
    service = _service(connection)

    result = service._inspect_spec(
        TABLE_TRANSFER_SPEC_BY_NAME["tool_websites"],
        target_schema="public",
    )

    assert result.status == "behind"
    assert result.maximum_id == 12
    assert result.next_value == 11
    sql = " ".join(str(call.args[0]) for call in cursor.execute.call_args_list)
    assert "nextval" not in sql.lower()


def test_empty_or_ahead_sequence_is_healthy() -> None:
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [
        {"maximum_id": None},
        {"sequence_name": "public.tool_websites_id_seq"},
        {"last_value": 50, "is_called": True},
    ]

    result = _service(connection)._inspect_spec(
        TABLE_TRANSFER_SPEC_BY_NAME["tool_websites"],
        target_schema="public",
    )

    assert result.status == "healthy"
    assert result.next_value == 51


def test_dry_run_never_locks_or_sets_sequence() -> None:
    connection = MagicMock()
    service = _service(connection)
    target = type(
        "Target",
        (),
        {"database": "catalog_test", "schema": "public", "schema_version": 4},
    )()
    behind = IdentitySequenceStatus(
        "tool_websites",
        "id",
        "public.tool_websites_id_seq",
        12,
        10,
        True,
        11,
        "behind",
    )
    with (
        patch.object(service._transfer, "_inspect_target", return_value=target),
        patch.object(service, "_inspect_spec", return_value=behind),
        patch.object(service, "_repair_spec") as repair,
    ):
        result = service.repair(
            target_database="catalog_test",
            target_schema="public",
        )

    assert result["status"] == "not_ready"
    assert all(item["action"] == "planned" for item in result["tables"])
    repair.assert_not_called()


def test_apply_repairs_only_after_table_lock_and_reinspection() -> None:
    connection = MagicMock()
    service = _service(connection)
    spec = TABLE_TRANSFER_SPEC_BY_NAME["tool_websites"]
    behind = IdentitySequenceStatus(
        spec.name,
        "id",
        "public.tool_websites_id_seq",
        12,
        10,
        True,
        11,
        "behind",
    )
    healthy = IdentitySequenceStatus(
        spec.name,
        "id",
        "public.tool_websites_id_seq",
        12,
        12,
        True,
        13,
        "healthy",
    )
    with patch.object(service, "_inspect_spec", side_effect=[behind, healthy]) as inspect:
        result = service._repair_spec(spec, target_schema="public")

    assert result == healthy
    cursor = connection.cursor.return_value.__enter__.return_value
    calls = cursor.execute.call_args_list
    assert "LOCK TABLE" in str(calls[0].args[0])
    assert "setval" in str(calls[1].args[0])
    assert calls[1].args[1] == ("public.tool_websites_id_seq", 12)
    assert inspect.call_count == 2
