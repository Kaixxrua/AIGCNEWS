from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from backend.app.services.project_catalog_consistency import (
    ProjectCatalogConsistencyService,
    TableDigest,
    canonical_row_bytes,
    digest_rows,
)
from backend.app.services.project_catalog_transfer import TABLE_TRANSFER_SPEC_BY_NAME


def test_canonical_encoding_is_typed_and_distinguishes_null_empty_and_false() -> None:
    spec = TABLE_TRANSFER_SPEC_BY_NAME["github_repo_recommendations"]
    base = {
        "repo_id": "owner/repo",
        "active": False,
        "recommended_by_user_id": None,
        "recommended_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
    }
    encoded = canonical_row_bytes(spec, base)
    assert b'"boolean",false' in encoded
    assert b'"null"' in encoded
    assert b'"datetime_utc"' in encoded
    assert encoded != canonical_row_bytes(spec, dict(base, recommended_by_user_id=0))


def test_canonical_datetime_requires_timezone() -> None:
    spec = TABLE_TRANSFER_SPEC_BY_NAME["github_repo_recommendations"]
    row = {
        "repo_id": "owner/repo",
        "active": True,
        "recommended_by_user_id": None,
        "recommended_at": datetime(2026, 1, 1),
        "updated_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
    }
    with pytest.raises(ValueError, match="timezone-aware"):
        canonical_row_bytes(spec, row)


def test_digest_rows_reports_count_key_range_and_portable_hashes() -> None:
    spec = TABLE_TRANSFER_SPEC_BY_NAME["github_repo_aliases"]
    rows = [
        {
            "alias_repo_id": "a/repo",
            "canonical_repo_id": "owner/repo",
            "full_name": "A/Repo",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": None,
        },
        {
            "alias_repo_id": "b/repo",
            "canonical_repo_id": "owner/repo",
            "full_name": "B/Repo",
            "created_at": "2026-01-02T00:00:00Z",
            "updated_at": None,
        },
    ]
    first = digest_rows(spec, rows)
    second = digest_rows(spec, [dict(row) for row in rows])
    changed = digest_rows(spec, [rows[0], dict(rows[1], full_name="Changed")])
    assert first == second
    assert first.count == 2
    assert first.minimum_key == {"alias_repo_id": "a/repo"}
    assert first.maximum_key == {"alias_repo_id": "b/repo"}
    assert first.primary_key_sha256 == changed.primary_key_sha256
    assert first.full_row_sha256 != changed.full_row_sha256


def test_unstable_source_is_never_reported_as_match() -> None:
    service = ProjectCatalogConsistencyService(mysql=object(), postgres=object())  # type: ignore[arg-type]
    first = TableDigest(1, "a" * 64, "b" * 64, {"id": 1}, {"id": 1})
    second = TableDigest(1, "a" * 64, "c" * 64, {"id": 1}, {"id": 1})
    first_report = {
        spec.name: first for spec in TABLE_TRANSFER_SPEC_BY_NAME.values()
    }
    second_report = {
        spec.name: second for spec in TABLE_TRANSFER_SPEC_BY_NAME.values()
    }
    with (
        patch.object(
            service._transfer,
            "_inspect_target",
            return_value=type("Target", (), {"database": "test", "schema": "public", "schema_version": 2})(),
        ),
        patch.object(
            service,
            "_digest_source_catalog",
            side_effect=[first_report, second_report, first_report, second_report],
        ),
        patch.object(service, "_digest_target_catalog", return_value=second_report),
        patch.object(service, "_reference_checks", return_value={"orphans": 0}),
        patch.object(
            service,
            "_sequence_checks",
            return_value={"status": "ready", "tables": []},
        ),
    ):
        result = service.verify(
            target_database="test",
            target_schema="public",
            stability_passes=2,
        )
    assert result["stable"] is False
    assert result["status"] == "mismatch"
    assert result["attempts_completed"] == 2
    assert all(not attempt["stable"] for attempt in result["attempts"])


def test_bracket_retries_and_accepts_first_stable_attempt() -> None:
    service = ProjectCatalogConsistencyService(mysql=object(), postgres=object())  # type: ignore[arg-type]
    first = TableDigest(1, "a" * 64, "b" * 64, {"id": 1}, {"id": 1})
    changed = TableDigest(1, "a" * 64, "c" * 64, {"id": 1}, {"id": 1})
    first_report = {spec.name: first for spec in TABLE_TRANSFER_SPEC_BY_NAME.values()}
    changed_report = {spec.name: changed for spec in TABLE_TRANSFER_SPEC_BY_NAME.values()}
    target = type("Target", (), {"database": "test", "schema": "public", "schema_version": 2})()
    with (
        patch.object(service._transfer, "_inspect_target", return_value=target),
        patch.object(
            service,
            "_digest_source_catalog",
            side_effect=[first_report, changed_report, changed_report, changed_report],
        ),
        patch.object(service, "_digest_target_catalog", side_effect=[first_report, changed_report]),
        patch.object(service, "_reference_checks", return_value={"orphans": 0}),
        patch.object(service, "_sequence_checks", return_value={"status": "ready", "tables": []}),
    ):
        result = service.verify(
            target_database="test", target_schema="public", stability_passes=2
        )
    assert result["status"] == "match"
    assert result["attempts_completed"] == 2
    assert [attempt["stable"] for attempt in result["attempts"]] == [False, True]


def test_digest_order_is_explicit_not_database_collation_dependent() -> None:
    spec = TABLE_TRANSFER_SPEC_BY_NAME["github_repo_aliases"]
    upper = {
        "alias_repo_id": "A/repo",
        "canonical_repo_id": "owner/repo",
        "full_name": "A/Repo",
        "created_at": None,
        "updated_at": None,
    }
    lower = dict(upper, alias_repo_id="a/repo", full_name="a/Repo")
    assert digest_rows(spec, [upper, lower]) != digest_rows(spec, [lower, upper])
