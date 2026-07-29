from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from backend.app.repositories import mysql_repo
from backend.app.repositories.mysql_project_write_repository import (
    MySQLProjectWriteRepository,
)
from backend.app.repositories.mysql_repo import MySQLRepository
from backend.app.repositories.project_write_repository import (
    GitHubProjectEnrichmentRepository,
    GitHubProjectIngestionRepository,
    GitHubProjectRecommendationRepository,
    GitHubProjectSemanticSourceRepository,
)


def _repository_with_connection() -> tuple[MySQLRepository, MagicMock, MagicMock]:
    repository = object.__new__(MySQLRepository)
    connection = MagicMock()
    cursor = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    repository._connect = MagicMock(return_value=connection)
    return repository, connection, cursor


def _normalized_sql(sql: str) -> str:
    return " ".join(sql.split())


def test_four_project_write_protocols_have_exact_capabilities() -> None:
    assert {
        name for name in GitHubProjectIngestionRepository.__dict__ if not name.startswith("_")
    } == {
        "upsert_github_repo_candidate",
        "mark_github_repo_available",
        "record_github_repo_not_found",
        "ensure_github_repo_candidate",
        "insert_github_repo_snapshot",
        "upsert_github_trending_hit",
        "get_github_hot_repos",
        "get_github_snapshot_count",
        "list_github_project_metric_targets",
        "get_github_metric_refresh_status",
        "get_github_daily_metric_inputs",
        "upsert_github_daily_metrics",
    }
    assert {
        name for name in GitHubProjectEnrichmentRepository.__dict__ if not name.startswith("_")
    } == {
        "runtime_provider_settings",
        "get_github_projects_needing_enrichment",
        "upsert_github_repo_enrichment",
        "mark_github_repo_enrichment_failed",
        "get_github_project_enrichment_status",
    }
    assert {
        name for name in GitHubProjectRecommendationRepository.__dict__ if not name.startswith("_")
    } == {"recommend_github_project", "unrecommend_github_project"}
    assert {
        name for name in GitHubProjectSemanticSourceRepository.__dict__ if not name.startswith("_")
    } == {
        "list_github_projects_for_semantic_sync",
        "upsert_github_project_semantic_source",
        "get_github_project_semantic_status",
    }


def test_extracted_adapter_owns_only_ingestion_and_recommendation_capabilities() -> None:
    ingestion_methods = {
        name
        for name in GitHubProjectIngestionRepository.__dict__
        if not name.startswith("_")
    }
    recommendation_methods = {
        name
        for name in GitHubProjectRecommendationRepository.__dict__
        if not name.startswith("_")
    }

    assert ingestion_methods | recommendation_methods <= set(
        MySQLProjectWriteRepository.__dict__
    )
    assert not hasattr(MySQLProjectWriteRepository, "upsert_github_repo_enrichment")
    assert not hasattr(MySQLProjectWriteRepository, "upsert_github_project_semantic_source")


def test_four_project_write_protocol_signatures_match_mysql_implementation() -> None:
    protocols = (
        GitHubProjectIngestionRepository,
        GitHubProjectEnrichmentRepository,
        GitHubProjectRecommendationRepository,
        GitHubProjectSemanticSourceRepository,
    )

    def call_shape(capability: Any) -> inspect.Signature:
        signature = inspect.signature(capability)
        return signature.replace(
            parameters=[
                parameter.replace(annotation=inspect.Signature.empty)
                for parameter in signature.parameters.values()
            ],
            return_annotation=inspect.Signature.empty,
        )

    for protocol in protocols:
        for name, capability in protocol.__dict__.items():
            if name.startswith("_") or isinstance(capability, property):
                continue
            assert call_shape(getattr(MySQLRepository, name)) == call_shape(capability)

    assert str(inspect.signature(GitHubProjectIngestionRepository.get_github_daily_metric_inputs)) == (
        "(self, *, metric_date: 'str', previous_date: 'str', "
        "baseline_start_date: 'str', min_stars: 'int' = 500, "
        "repo_ids: 'list[str] | None' = None) -> 'list[dict[str, Any]]'"
    )
    assert str(inspect.signature(GitHubProjectEnrichmentRepository.get_github_projects_needing_enrichment)) == (
        "(self, *, limit: 'int' = 50, min_stars: 'int' = 500, "
        "prompt_version: 'str' = 'v1', force: 'bool' = False, "
        "retry_failed: 'bool' = True, refresh_changed: 'bool' = False) "
        "-> 'list[dict[str, Any]]'"
    )
    assert str(inspect.signature(GitHubProjectRecommendationRepository.recommend_github_project)) == (
        "(self, *, repo_id: 'Any' = None, full_name: 'str' = '', "
        "recommended_by_user_id: 'int | None' = None) -> 'dict[str, Any]'"
    )
    assert str(inspect.signature(GitHubProjectSemanticSourceRepository.list_github_projects_for_semantic_sync)) == (
        "(self, *, limit: 'int' = 100, min_stars: 'int' = 500, "
        "after_repo_id: 'str' = '', retry_failed: 'bool' = True) "
        "-> 'list[dict[str, Any]]'"
    )


def test_repo_identity_prefers_alias_before_full_name_candidate() -> None:
    repository = object.__new__(MySQLRepository)
    cursor = MagicMock()
    cursor.fetchone.return_value = {"canonical_repo_id": "canonical-7"}

    resolved = repository._resolve_github_repo_id_cur(
        cursor, "legacy-7", "owner/project"
    )

    assert resolved == "canonical-7"
    assert cursor.execute.call_count == 1
    assert "FROM github_repo_aliases" in cursor.execute.call_args.args[0]
    assert cursor.execute.call_args.args[1] == ("legacy-7",)


def test_repo_identity_falls_back_to_ranked_full_name_candidate() -> None:
    repository = object.__new__(MySQLRepository)
    cursor = MagicMock()
    cursor.fetchone.side_effect = [None, {"repo_id": "canonical-8"}]

    resolved = repository._resolve_github_repo_id_cur(
        cursor, "legacy-8", "Owner/Project"
    )

    assert resolved == "canonical-8"
    candidate_sql, params = cursor.execute.call_args.args
    assert "FROM github_repo_candidates" in candidate_sql
    assert "ORDER BY (repo_id = full_name) DESC" in candidate_sql
    assert "COALESCE(stars, 0) DESC" in candidate_sql
    assert params == ("Owner/Project",)


def test_candidate_write_orders_alias_before_candidate_and_outbox() -> None:
    repository, connection, cursor = _repository_with_connection()
    repository._resolve_github_repo_id_cur = MagicMock(return_value="canonical-1")

    with patch.object(
        mysql_repo.settings, "project_catalog_outbox_capture_enabled", True
    ):
        repository.upsert_github_repo_candidate(
            {"repo_id": "legacy-1", "full_name": "owner/repo"}
        )

    sql_calls = [_normalized_sql(call.args[0]) for call in cursor.execute.call_args_list]
    assert "INSERT INTO github_repo_aliases" in sql_calls[0]
    assert "INSERT INTO project_catalog_outbox" in sql_calls[1]
    assert "INSERT INTO github_repo_candidates" in sql_calls[2]
    assert "INSERT INTO project_catalog_outbox" in sql_calls[3]
    assert cursor.execute.call_args_list[1].args[1][1] == "github_repo_aliases"
    assert cursor.execute.call_args_list[3].args[1][1] == "github_repo_candidates"
    connection.commit.assert_called_once_with()


def test_snapshot_merge_protects_complete_community_metrics_and_monotonic_counts() -> None:
    repository, _, cursor = _repository_with_connection()
    repository._resolve_github_repo_id_cur = MagicMock(return_value="canonical-1")

    repository.insert_github_repo_snapshot(
        {"repo_id": "legacy-1", "snapshot_date": "2026-07-28"}
    )

    sql = _normalized_sql(cursor.execute.call_args_list[0].args[0])
    assert "stars=GREATEST" in sql
    assert "WHEN community_metrics_complete = 1 THEN forks" in sql
    assert "WHEN community_metrics_complete = 1 THEN watchers" in sql
    assert "community_metrics_complete=CASE" in sql
    assert "OR VALUES(community_metrics_complete) = 1 THEN 1" in sql


def test_trending_merge_keeps_best_rank_and_rejects_older_growth() -> None:
    repository, _, cursor = _repository_with_connection()
    repository._resolve_github_repo_id_cur = MagicMock(return_value="canonical-1")
    cursor.fetchone.return_value = {"id": 9}

    result = repository.upsert_github_trending_hit(
        {
            "repo_id": "legacy-1",
            "period": "daily",
            "observed_date": "2026-07-28",
            "rank": 4,
            "period_star_growth": 12,
            "period_growth_observed_at": "2026-07-28T12:00:00Z",
        }
    )

    sql = _normalized_sql(cursor.execute.call_args_list[0].args[0])
    assert result == "canonical-1"
    assert "`rank`=LEAST" in sql
    assert "VALUES(period_growth_observed_at) >= period_growth_observed_at" in sql
    assert "ELSE period_star_growth" in sql
    assert "captured_at=GREATEST" in sql


def test_metric_targets_have_stable_order_and_bounded_limit() -> None:
    repository, _, cursor = _repository_with_connection()
    cursor.fetchall.return_value = [{"repo_id": "r1"}]

    assert repository.list_github_project_metric_targets(
        min_stars=750, limit=50_000
    ) == [{"repo_id": "r1"}]

    sql, params = cursor.execute.call_args.args
    assert "ORDER BY COALESCE(stars, 0) DESC, full_name ASC" in sql
    assert "LIMIT %s" in sql
    assert params == (750, 20_000)


def test_metric_inputs_preserve_requested_batch_order_and_stable_result_order() -> None:
    repository, _, cursor = _repository_with_connection()
    cursor.fetchall.return_value = []

    repository.get_github_daily_metric_inputs(
        metric_date="2026-07-28",
        previous_date="2026-07-27",
        baseline_start_date="2026-07-21",
        min_stars=900,
        repo_ids=[" repo-b ", "", "repo-a"],
    )

    sql, params = cursor.execute.call_args.args
    assert "AND s.repo_id IN (%s, %s)" in sql
    assert "ORDER BY COALESCE(s.stars, 0) DESC, COALESCE(c.full_name, s.repo_id) ASC" in sql
    assert params[-2:] == ("repo-b", "repo-a")
    assert params[:8] == (
        "2026-07-21",
        "2026-07-28",
        "2026-07-21",
        "2026-07-28",
        "2026-07-27",
        "2026-07-28",
        "2026-07-28",
        900,
    )


def test_daily_metric_batch_is_noop_when_empty_and_normalizes_rows() -> None:
    repository, connection, cursor = _repository_with_connection()
    assert repository.upsert_github_daily_metrics([]) == 0
    repository._connect.assert_not_called()

    cursor.rowcount = 2
    affected = repository.upsert_github_daily_metrics(
        [
            {"repo_id": "r2", "metric_date": "2026-07-28"},
            {
                "repo_id": "r1",
                "metric_date": "2026-07-28",
                "daily_growth_available": True,
            },
        ]
    )

    assert affected == 2
    rows = cursor.executemany.call_args.args[1]
    assert [row["repo_id"] for row in rows] == ["r2", "r1"]
    assert [row["daily_growth_available"] for row in rows] == [0, 1]
    assert all(row["score_version"] == "daily_hot_v4" for row in rows)
    connection.commit.assert_called_once_with()


@pytest.mark.parametrize(
    ("kwargs", "required_sql", "forbidden_sql", "params"),
    [
        ({}, "e.status != 'succeeded'", "e.prompt_version != %s", (500, 50)),
        (
            {"retry_failed": False},
            "e.repo_id IS NULL",
            "e.status != 'succeeded'",
            (500, 50),
        ),
        (
            {"refresh_changed": True, "prompt_version": "v3"},
            "e.prompt_version != %s",
            "1 = 1",
            (500, "v3", 50),
        ),
        ({"force": True}, "AND 1 = 1", "e.repo_id IS NULL", (500, 50)),
    ],
)
def test_enrichment_selection_modes(
    kwargs: dict[str, Any], required_sql: str, forbidden_sql: str, params: tuple[Any, ...]
) -> None:
    repository, _, cursor = _repository_with_connection()
    cursor.fetchall.return_value = []

    repository.get_github_projects_needing_enrichment(**kwargs)

    sql, actual_params = cursor.execute.call_args.args
    assert required_sql in sql
    assert forbidden_sql not in sql
    assert actual_params == params
    assert "ORDER BY COALESCE(ls.stars, c.stars, 0) DESC, c.full_name ASC" in sql


def test_enrichment_success_uses_canonical_identity_and_success_defaults() -> None:
    repository, connection, cursor = _repository_with_connection()
    repository._resolve_github_repo_id_cur = MagicMock(return_value="canonical-1")

    repository.upsert_github_repo_enrichment(
        {
            "repo_id": "legacy-1",
            "category_slug": "agents",
            "category_name": "Agents",
            "description_zh": "描述",
            "source_fingerprint": "fingerprint",
            "prompt_version": "v2",
            "tags": ["agent", "tools"],
        }
    )

    payload = cursor.execute.call_args_list[0].args[1]
    assert payload["repo_id"] == "canonical-1"
    assert payload["status"] == "succeeded"
    assert payload["tags_json"] == '["agent", "tools"]'
    connection.commit.assert_called_once_with()


def test_enrichment_failure_delegates_stable_failed_projection() -> None:
    repository = object.__new__(MySQLRepository)
    repository.upsert_github_repo_enrichment = MagicMock()

    repository.mark_github_repo_enrichment_failed(
        "repo-1",
        source_fingerprint="fingerprint",
        prompt_version="v2",
        error_msg="x" * 2100,
        model_provider="provider",
        model_name="model",
    )

    payload = repository.upsert_github_repo_enrichment.call_args.args[0]
    assert payload["repo_id"] == "repo-1"
    assert payload["status"] == "failed"
    assert payload["category_slug"] == "other"
    assert payload["subcategory_slug"] == "other_uncategorized"
    assert len(payload["error_msg"]) == 2000


def test_recommendation_resolves_canonical_identity() -> None:
    repository, _, cursor = _repository_with_connection()
    repository._resolve_github_repo_id_cur = MagicMock(return_value="canonical-1")
    cursor.fetchone.side_effect = [
        {"repo_id": "canonical-1", "full_name": "owner/repo"},
        {"recommended_at": "2026-07-28T12:00:00Z"},
    ]

    result = repository.recommend_github_project(
        repo_id="legacy-1", recommended_by_user_id=7
    )

    assert result["repo_id"] == "canonical-1"
    assert result["is_recommended"] is True
    assert cursor.execute.call_args_list[1].args[1] == ("canonical-1", 7)


def test_unrecommendation_is_idempotent_noop_without_outbox() -> None:
    repository, connection, cursor = _repository_with_connection()
    repository._resolve_github_repo_id_cur = MagicMock(return_value="canonical-1")
    cursor.fetchone.return_value = {
        "repo_id": "canonical-1",
        "full_name": "owner/repo",
    }
    cursor.rowcount = 0

    with patch.object(
        mysql_repo.settings, "project_catalog_outbox_capture_enabled", True
    ):
        result = repository.unrecommend_github_project(repo_id="legacy-1")

    assert result == {
        "repo_id": "canonical-1",
        "full_name": "owner/repo",
        "is_recommended": False,
        "recommended_at": None,
        "removed": False,
    }
    assert cursor.execute.call_count == 2
    assert all(
        "project_catalog_outbox" not in call.args[0]
        for call in cursor.execute.call_args_list
    )
    connection.commit.assert_called_once_with()


def test_semantic_source_cursor_and_retry_policy_are_stable() -> None:
    repository, _, cursor = _repository_with_connection()
    cursor.fetchall.return_value = []

    repository.list_github_projects_for_semantic_sync(
        limit=5000,
        min_stars=800,
        after_repo_id="repo-100",
        retry_failed=False,
    )

    sql, params = cursor.execute.call_args.args
    assert "c.repo_id > %s" in sql
    assert "ORDER BY c.repo_id ASC" in sql
    assert "ss.index_status IN (%s)" in sql
    assert params[0:3] == (800, "repo-100", "pending")
    assert params[-1] == 1000


def test_semantic_status_derives_non_negative_pending_count() -> None:
    repository, _, cursor = _repository_with_connection()
    cursor.fetchone.return_value = {
        "eligible": 2,
        "indexed": 2,
        "failed": 1,
        "readme_succeeded": 2,
        "chunk_count": 8,
        "last_indexed_at": "2026-07-28T12:00:00Z",
    }

    status = repository.get_github_project_semantic_status(min_stars=700)

    assert status == {
        "eligible": 2,
        "indexed": 2,
        "failed": 1,
        "pending": 0,
        "readme_succeeded": 2,
        "chunk_count": 8,
        "last_indexed_at": "2026-07-28T12:00:00Z",
    }
    assert cursor.execute.call_args.args[1] == (700,)
