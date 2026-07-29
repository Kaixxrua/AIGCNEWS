from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from backend.app.repositories import mysql_repo
from backend.app.repositories.mysql_repo import MySQLRepository


def _adapter_with_connection() -> tuple[MySQLRepository, MagicMock, MagicMock]:
    """Keep construction isolated so a dedicated adapter can replace the repository."""
    adapter = object.__new__(MySQLRepository)
    connection = MagicMock()
    cursor = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    adapter._connect = MagicMock(return_value=connection)
    return adapter, connection, cursor


def _github_enrichment_payload(repo_id: str = "alias-1") -> dict[str, object]:
    return {
        "repo_id": repo_id,
        "category_slug": "other",
        "category_name": "其他",
        "subcategory_slug": "other_uncategorized",
        "subcategory_name": "未分类",
        "description_zh": "描述",
        "tags_json": "[]",
        "source_fingerprint": "fingerprint",
        "prompt_version": "v1",
    }


@pytest.mark.parametrize(
    ("options", "required_fragments", "forbidden_fragments", "expected_params"),
    [
        (
            {},
            ["e.repo_id IS NULL", "e.status != 'succeeded'"],
            ["e.prompt_version != %s", "1 = 1"],
            (500, 50),
        ),
        (
            {"retry_failed": False},
            ["e.repo_id IS NULL"],
            ["e.status != 'succeeded'", "e.prompt_version != %s", "1 = 1"],
            (500, 50),
        ),
        (
            {"refresh_changed": True, "prompt_version": "v3"},
            ["e.repo_id IS NULL", "e.status != 'succeeded'", "e.prompt_version != %s", "e.source_fingerprint != SHA2"],
            ["1 = 1"],
            (500, "v3", 50),
        ),
        (
            {"force": True},
            ["1 = 1"],
            ["e.repo_id IS NULL", "e.status != 'succeeded'", "e.prompt_version != %s"],
            (500, 50),
        ),
    ],
)
def test_github_enrichment_selection_modes(
    options: dict[str, object],
    required_fragments: list[str],
    forbidden_fragments: list[str],
    expected_params: tuple[object, ...],
) -> None:
    adapter, connection, cursor = _adapter_with_connection()
    cursor.fetchall.return_value = []

    assert adapter.get_github_projects_needing_enrichment(**options) == []

    sql, params = cursor.execute.call_args.args
    for fragment in required_fragments:
        assert fragment in sql
    for fragment in forbidden_fragments:
        assert fragment not in sql
    assert params == expected_params
    assert "ORDER BY COALESCE(ls.stars, c.stars, 0) DESC, c.full_name ASC" in sql
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


@pytest.mark.parametrize(("requested", "expected"), [(0, 50), (-2, 1), (999, 500)])
def test_github_enrichment_selection_clamps_limit(requested: int, expected: int) -> None:
    adapter, _, cursor = _adapter_with_connection()
    cursor.fetchall.return_value = []

    adapter.get_github_projects_needing_enrichment(limit=requested)

    assert cursor.execute.call_args.args[1][-1] == expected


def test_github_enrichment_upsert_resolves_canonical_id_and_captures_same_transaction() -> None:
    adapter, connection, cursor = _adapter_with_connection()
    adapter._resolve_github_repo_id_cur = MagicMock(return_value="canonical-1")

    with patch.object(mysql_repo.settings, "project_catalog_outbox_capture_enabled", True):
        adapter.upsert_github_repo_enrichment(_github_enrichment_payload())

    assert cursor.execute.call_count == 2
    write_sql, write_payload = cursor.execute.call_args_list[0].args
    assert "INSERT INTO github_repo_enrichments" in write_sql
    assert write_payload["repo_id"] == "canonical-1"
    outbox_sql, outbox_params = cursor.execute.call_args_list[1].args
    assert "INSERT INTO project_catalog_outbox" in outbox_sql
    assert outbox_params[1] == "github_repo_enrichments"
    assert json.loads(outbox_params[2]) == {"repo_id": "canonical-1"}
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_github_enrichment_outbox_failure_prevents_commit() -> None:
    adapter, connection, cursor = _adapter_with_connection()
    adapter._resolve_github_repo_id_cur = MagicMock(return_value="canonical-1")
    cursor.execute.side_effect = [None, RuntimeError("outbox unavailable")]

    with (
        patch.object(mysql_repo.settings, "project_catalog_outbox_capture_enabled", True),
        pytest.raises(RuntimeError, match="outbox unavailable"),
    ):
        adapter.upsert_github_repo_enrichment(_github_enrichment_payload())

    connection.commit.assert_not_called()
    connection.close.assert_called_once_with()


def test_failed_github_enrichment_caps_error_at_2000_characters() -> None:
    adapter = object.__new__(MySQLRepository)
    adapter.upsert_github_repo_enrichment = MagicMock()

    adapter.mark_github_repo_enrichment_failed(
        "repo-1",
        source_fingerprint="fingerprint",
        prompt_version="v1",
        error_msg="x" * 2001,
    )

    payload = adapter.upsert_github_repo_enrichment.call_args.args[0]
    assert payload["status"] == "failed"
    assert payload["error_msg"] == "x" * 2000


def test_tool_website_identity_lookup_uses_normalized_hash() -> None:
    adapter, connection, cursor = _adapter_with_connection()
    cursor.fetchone.return_value = {"id": 7, "normalized_url_hash": "hash-1"}

    result = adapter.get_tool_website_by_hash("hash-1")

    assert result == {"id": 7, "normalized_url_hash": "hash-1"}
    assert cursor.execute.call_args.args[1] == ("hash-1",)
    assert "normalized_url_hash = %s" in cursor.execute.call_args.args[0]
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


@pytest.mark.parametrize(
    ("visibility", "update_existing", "expected_visibility", "update_fragment", "forbidden_fragment"),
    [
        ("PRIVATE", True, "private", "visibility=IF(", None),
        ("invalid", True, "public", "visibility=IF(", None),
        ("private", False, "private", "last_seen_at=VALUES(last_seen_at)", "canonical_url=VALUES(canonical_url)"),
    ],
)
def test_tool_website_upsert_visibility_and_update_modes(
    visibility: str,
    update_existing: bool,
    expected_visibility: str,
    update_fragment: str,
    forbidden_fragment: str | None,
) -> None:
    adapter, connection, cursor = _adapter_with_connection()
    cursor.fetchone.return_value = {"id": 7}
    payload = {
        "canonical_url": "https://example.com/tool",
        "normalized_url_hash": "hash-1",
        "domain": "example.com",
        "source_fingerprint": "fingerprint",
        "visibility": visibility,
    }

    with patch.object(mysql_repo.settings, "project_catalog_outbox_capture_enabled", False):
        result = adapter.upsert_tool_website(payload, update_existing=update_existing)

    sql, data = cursor.execute.call_args_list[0].args
    assert result == {"id": 7}
    assert data["visibility"] == expected_visibility
    assert update_fragment in sql
    if forbidden_fragment:
        assert forbidden_fragment not in sql
    assert cursor.execute.call_args_list[1].args[1] == ("hash-1",)
    connection.commit.assert_called_once_with()


def test_tool_website_item_projects_normalized_website_shape() -> None:
    adapter, _, cursor = _adapter_with_connection()
    cursor.fetchone.return_value = {
        "id": "website:7",
        "source": "website",
        "website_id": 7,
        "full_name": "Example Tool",
        "title": "Example Tool",
        "url": "https://example.com/tool",
        "domain": "example.com",
        "image_url": "https://example.com/favicon.ico",
        "description": "Tool description",
        "description_zh": "工具描述",
        "category_slug": "other",
        "subcategory_slug": "",
        "topics_json": "[]",
        "tags_json": '["workflow"]',
        "stars": 0,
        "forks": 0,
        "watchers": 0,
        "open_issues": 0,
        "confidence": 0.75,
        "is_favorited": 0,
        "user_added": 0,
    }

    item = adapter.get_tool_website_item(7)

    assert item is not None
    assert item["id"] == "website:7"
    assert item["source"] == "website"
    assert item["website_id"] == 7
    assert item["url"] == "https://example.com/tool"
    assert item["tags"] == ["workflow"]
    assert item["topics"] == []
    assert item["stars"] == 0
    assert item["is_favorited"] is False
    assert cursor.execute.call_args.args[1] == (7,)


def test_tool_website_enrichment_upsert_captures_outbox_in_same_transaction() -> None:
    adapter, connection, cursor = _adapter_with_connection()
    payload = {
        "website_id": 7,
        "category_slug": "other",
        "category_name": "其他",
        "subcategory_slug": "other_uncategorized",
        "subcategory_name": "未分类",
        "description_zh": "描述",
        "tags_json": "[]",
        "source_fingerprint": "fingerprint",
        "prompt_version": "v1",
    }

    with patch.object(mysql_repo.settings, "project_catalog_outbox_capture_enabled", True):
        adapter.upsert_tool_website_enrichment(payload)

    assert "INSERT INTO tool_website_enrichments" in cursor.execute.call_args_list[0].args[0]
    outbox_sql, outbox_params = cursor.execute.call_args_list[1].args
    assert "INSERT INTO project_catalog_outbox" in outbox_sql
    assert outbox_params[1] == "tool_website_enrichments"
    assert json.loads(outbox_params[2]) == {"website_id": 7}
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()
