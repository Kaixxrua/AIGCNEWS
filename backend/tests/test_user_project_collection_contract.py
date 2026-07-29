from __future__ import annotations

import ast
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.app.repositories import mysql_user_project_collection_repository
from backend.app.repositories.mysql_user_project_collection_repository import (
    MySQLUserProjectCollectionRepository,
)
from backend.app.services.mcp.inbound import tools as mcp_tools
from backend.app.services.mcp.inbound.tools import McpToolContext


def _repository_with_connection() -> tuple[
    MySQLUserProjectCollectionRepository, MagicMock, MagicMock
]:
    database = MagicMock()
    project_catalog = MagicMock()
    connection = MagicMock()
    cursor = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    database.connect.return_value = connection
    repository = MySQLUserProjectCollectionRepository(
        database,
        project_catalog=project_catalog,
    )
    return repository, connection, cursor


def _normalized_sql(value: str) -> str:
    return " ".join(value.split())


def test_personal_collection_sql_is_owned_by_dedicated_adapter() -> None:
    repository_path = Path(__file__).parents[1] / "app/repositories/mysql_repo.py"
    adapter_path = (
        Path(__file__).parents[1]
        / "app/repositories/mysql_user_project_collection_repository.py"
    )
    facade_tree = ast.parse(repository_path.read_text(encoding="utf-8"))
    adapter_tree = ast.parse(adapter_path.read_text(encoding="utf-8"))
    personal_methods = {
        "add_project_favorite",
        "remove_project_favorite",
        "link_user_tool_website",
        "unlink_user_tool_website",
        "get_tool_website_item_for_user",
        "upsert_user_tool_website_override",
        "list_user_project_collection",
        "get_user_project_categories",
        "get_user_project_tags",
    }

    facade_class = next(
        node
        for node in facade_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "MySQLRepository"
    )
    facade_methods = {
        node.name for node in facade_class.body if isinstance(node, ast.FunctionDef)
    }
    adapter_class = next(
        node
        for node in adapter_tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "MySQLUserProjectCollectionRepository"
    )
    adapter_methods = {
        node.name for node in adapter_class.body if isinstance(node, ast.FunctionDef)
    }
    adapter_imports = {
        alias.name
        for node in adapter_tree.body
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }

    assert personal_methods.isdisjoint(facade_methods)
    assert personal_methods.issubset(adapter_methods)
    assert "MySQLRepository" not in adapter_imports
    assert "backend.app.repositories.mysql_repo" not in adapter_path.read_text(
        encoding="utf-8"
    )


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


def test_personal_collection_delegates_only_catalog_read_to_narrow_port() -> None:
    repository, connection, _ = _repository_with_connection()
    repository._project_catalog.list_projects.return_value = {
        "items": [],
        "total": 0,
        "page": 1,
        "page_size": 24,
    }

    result = repository.list_user_project_collection(
        user_id=7,
        source="website",
        enriched_only=True,
    )

    assert result["items"] == []
    repository._project_catalog.list_projects.assert_called_once_with(
        user_id=7,
        favorites_only=True,
        source="website",
        enriched_only=True,
    )
    connection.commit.assert_not_called()
    connection.close.assert_not_called()


def test_collection_outbox_preserves_canonical_event_shape() -> None:
    cursor = MagicMock()

    with patch.object(
        mysql_user_project_collection_repository.settings,
        "project_catalog_outbox_capture_enabled",
        True,
    ):
        MySQLUserProjectCollectionRepository._record_project_catalog_change_cur(
            cursor,
            aggregate_type="project_favorites",
            aggregate_key={"user_id": 7, "project_source": "github", "project_id": "42"},
            operation="delete",
            source_method="remove_project_favorite",
        )

    sql, params = cursor.execute.call_args.args
    assert "INSERT INTO project_catalog_outbox" in sql
    assert params[1:] == (
        "project_favorites",
        '{"project_id":"42","project_source":"github","user_id":7}',
        "delete",
        "remove_project_favorite",
    )


def test_unlink_atomically_cleans_only_owner_scoped_collection_rows() -> None:
    repository, connection, cursor = _repository_with_connection()
    cursor.rowcount = 1

    with patch.object(
        mysql_user_project_collection_repository.settings,
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
        mysql_user_project_collection_repository.settings,
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
