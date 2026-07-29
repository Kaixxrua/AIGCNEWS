from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from backend.app.repositories import mysql_repo
from backend.app.repositories.mysql_repo import MySQLRepository
from backend.app.services.mcp.inbound import tools as mcp_tools
from backend.app.services.mcp.inbound.tools import McpToolContext


def _repository_with_connection() -> tuple[MySQLRepository, MagicMock, MagicMock]:
    repository = object.__new__(MySQLRepository)
    connection = MagicMock()
    cursor = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    repository._connect = MagicMock(return_value=connection)
    return repository, connection, cursor


def _normalized_sql(value: str) -> str:
    return " ".join(value.split())


def test_website_favorite_rejects_cross_owner_access() -> None:
    repository, connection, cursor = _repository_with_connection()
    cursor.fetchone.return_value = None

    with pytest.raises(LookupError, match="不存在或不可收藏"):
        repository.add_project_favorite(
            user_id=7,
            source="website",
            website_id=42,
        )

    access_sql, access_params = cursor.execute.call_args.args
    normalized = _normalized_sql(access_sql)
    assert "utw.website_id = w.id AND utw.user_id = %s" in normalized
    assert "w.added_by_user_id = %s OR utw.id IS NOT NULL" in normalized
    assert access_params == (7, 42, 7)
    assert not any(
        "INSERT INTO project_favorites" in call.args[0]
        for call in cursor.execute.call_args_list
    )
    connection.commit.assert_not_called()
    connection.close.assert_called_once_with()


def test_website_override_requires_same_owner_link() -> None:
    repository, connection, cursor = _repository_with_connection()
    cursor.fetchone.return_value = None

    with pytest.raises(LookupError, match="不在你的收藏夹"):
        repository.upsert_user_tool_website_override(
            {"user_id": 7, "website_id": 42, "title": "Private title"}
        )

    lookup_sql, lookup_params = cursor.execute.call_args.args
    assert _normalized_sql(lookup_sql) == (
        "SELECT id FROM user_tool_websites "
        "WHERE user_id = %s AND website_id = %s LIMIT 1"
    )
    assert lookup_params == (7, 42)
    assert not any(
        "INSERT INTO user_tool_website_overrides" in call.args[0]
        for call in cursor.execute.call_args_list
    )
    connection.commit.assert_not_called()
    connection.close.assert_called_once_with()


def test_user_website_item_uses_owner_scoped_overlay_and_coalesce() -> None:
    repository, connection, cursor = _repository_with_connection()
    cursor.fetchone.return_value = None

    assert repository.get_tool_website_item_for_user(user_id=7, website_id=42) is None

    sql, params = cursor.execute.call_args.args
    normalized = _normalized_sql(sql)
    for expression in (
        "COALESCE(NULLIF(uo.title, ''), w.title) AS title",
        "COALESCE(NULLIF(uo.description, ''), w.description) AS description",
        "COALESCE(NULLIF(uo.description_zh, ''), e.description_zh) AS description_zh",
        "COALESCE(NULLIF(uo.category_slug, ''), e.category_slug) AS category_slug",
        "COALESCE(NULLIF(uo.tags_json, ''), e.tags_json) AS tags_json",
    ):
        assert expression in normalized
    assert "utw.user_id = %s AND utw.website_id = w.id" in normalized
    assert "pf.user_id = %s AND pf.project_source = 'website'" in normalized
    assert "uo.user_id = %s AND uo.website_id = w.id" in normalized
    assert params == (7, 7, 7, 42)
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_personal_collection_uses_link_or_favorite_visibility_unlike_public() -> None:
    personal, personal_connection, personal_cursor = _repository_with_connection()
    personal_cursor.fetchone.return_value = {"cnt": 0}
    personal_cursor.fetchall.return_value = []

    personal.list_user_project_collection(
        user_id=7,
        source="website",
        enriched_only=True,
    )

    personal_count_sql = _normalized_sql(personal_cursor.execute.call_args_list[0].args[0])
    personal_params = personal_cursor.execute.call_args_list[0].args[1]
    assert "LEFT JOIN project_favorites pf ON pf.user_id = %s" in personal_count_sql
    assert "LEFT JOIN user_tool_websites utw ON utw.user_id = %s" in personal_count_sql
    assert "LEFT JOIN user_tool_website_overrides uo ON uo.user_id = %s" in personal_count_sql
    assert "(pf.id IS NOT NULL OR utw.id IS NOT NULL)" in personal_count_sql
    assert "w.visibility" not in personal_count_sql
    assert personal_params == (7, 7, 7)
    personal_connection.commit.assert_called_once_with()

    public, public_connection, public_cursor = _repository_with_connection()
    public_cursor.fetchone.return_value = {"cnt": 0}
    public_cursor.fetchall.return_value = []

    public.list_projects(source="website", enriched_only=True)

    public_count_sql = _normalized_sql(public_cursor.execute.call_args_list[0].args[0])
    public_params = public_cursor.execute.call_args_list[0].args[1]
    assert "w.visibility" in public_count_sql
    assert "= _utf8mb4'public'" in public_count_sql
    assert "project_favorites" not in public_count_sql
    assert "user_tool_websites" not in public_count_sql
    assert "user_tool_website_overrides" not in public_count_sql
    assert public_params == ()
    public_connection.commit.assert_called_once_with()


def test_unlink_atomically_cleans_only_owner_scoped_collection_rows() -> None:
    repository, connection, cursor = _repository_with_connection()
    cursor.rowcount = 1

    with patch.object(
        mysql_repo.settings,
        "project_catalog_outbox_capture_enabled",
        False,
    ):
        assert repository.unlink_user_tool_website(user_id=7, website_id=42) is True

    statements = [
        (_normalized_sql(call.args[0]), call.args[1])
        for call in cursor.execute.call_args_list
    ]
    assert statements == [
        (
            "DELETE FROM user_tool_websites WHERE user_id = %s AND website_id = %s",
            (7, 42),
        ),
        (
            "DELETE FROM user_tool_website_overrides WHERE user_id = %s AND website_id = %s",
            (7, 42),
        ),
        (
            "DELETE FROM project_favorites WHERE user_id = %s "
            "AND project_source = 'website' AND project_id = %s",
            (7, "42"),
        ),
    ]
    assert not any("DELETE FROM tool_websites" in sql for sql, _ in statements)
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_github_favorite_uses_canonical_id_owner_key_and_idempotent_insert() -> None:
    repository, connection, cursor = _repository_with_connection()
    repository._resolve_github_repo_id_cur = MagicMock(return_value="canonical-42")
    created_at = datetime(2026, 7, 29, tzinfo=timezone.utc)
    cursor.fetchone.side_effect = [
        {"repo_id": "canonical-42"},
        {"created_at": created_at},
    ]

    with patch.object(
        mysql_repo.settings,
        "project_catalog_outbox_capture_enabled",
        False,
    ):
        result = repository.add_project_favorite(
            user_id=7,
            source="github",
            repo_id="Owner/Repo",
        )

    repository._resolve_github_repo_id_cur.assert_called_once_with(
        cursor, "Owner/Repo", "Owner/Repo"
    )
    candidate_sql, candidate_params = cursor.execute.call_args_list[0].args
    insert_sql, insert_params = cursor.execute.call_args_list[1].args
    select_sql, select_params = cursor.execute.call_args_list[2].args
    assert "repo_id = %s OR LOWER(TRIM(full_name)) = LOWER(TRIM(%s))" in _normalized_sql(candidate_sql)
    assert candidate_params == ("canonical-42", "Owner/Repo")
    assert "ON DUPLICATE KEY UPDATE created_at = created_at" in _normalized_sql(insert_sql)
    assert insert_params == (7, "github", "canonical-42")
    assert "WHERE user_id = %s AND project_source = %s AND project_id = %s" in _normalized_sql(select_sql)
    assert select_params == (7, "github", "canonical-42")
    assert result == {
        "source": "github",
        "project_id": "canonical-42",
        "repo_id": "canonical-42",
        "is_favorited": True,
        "favorited_at": "2026-07-29T00:00:00Z",
    }
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_mcp_favorites_owner_comes_from_token_not_tool_arguments() -> None:
    collection = MagicMock()
    collection.list_user_project_collection.return_value = {
        "items": [],
        "total": 0,
    }
    context = McpToolContext(
        user={
            "user_id": 42,
            "scopes": frozenset({"projects:favorites:read"}),
        },
        documents=MagicMock(),
        papers=MagicMock(),
        rank_snapshots=MagicMock(),
        project_collection=collection,
        request=MagicMock(),
    )

    override_attempt = asyncio.run(
        mcp_tools._call_tool(
            context,
            "search_my_project_favorites",
            {"user_id": 999, "limit": 5},
        )
    )

    assert override_attempt["isError"] is True
    collection.list_user_project_collection.assert_not_called()

    response = asyncio.run(
        mcp_tools._call_tool(
            context,
            "search_my_project_favorites",
            {"limit": 5},
        )
    )

    assert response["isError"] is False
    collection.list_user_project_collection.assert_called_once()
    assert collection.list_user_project_collection.call_args.kwargs["user_id"] == 42
