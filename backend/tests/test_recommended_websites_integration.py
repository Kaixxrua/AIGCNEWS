from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from backend.app.repositories.postgres_recommended_website_repository import PostgresRecommendedWebsiteRepository
from backend.app.repositories.recommended_website_repository import DuplicateRecommendedWebsiteError


def test_curated_directory_roundtrip_and_private_collection_isolation() -> None:
    dsn = os.getenv("TEST_POSTGRES_DSN", "").strip()
    run_id = os.getenv("TEST_POSTGRES_RUN_ID", "").strip()
    if not dsn:
        pytest.skip("Explicitly provisioned TEST_POSTGRES_DSN required")
    assert conninfo_to_dict(dsn).get("dbname", "").startswith("aigcnews_test_")
    assert run_id, "TEST_POSTGRES_RUN_ID is required"
    schema = "recommended_websites_" + uuid.uuid4().hex
    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as connection:
        marker = connection.execute("SELECT run_id FROM public.aigcnews_test_run_guard WHERE run_id=%s", (run_id,)).fetchone()
        assert marker and marker["run_id"] == run_id
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            connection.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema)))
            connection.execute("CREATE TABLE tool_websites (id integer PRIMARY KEY, private_note text)")
            connection.execute("INSERT INTO tool_websites VALUES (1, 'private-only')")
            connection.execute("CREATE TABLE user_tool_websites (user_id integer, website_id integer)")
            connection.execute("INSERT INTO user_tool_websites VALUES (7, 1)")
            for name in ("0066_recommended_websites.sql", "0081_recommended_website_icons.sql"):
                migration = Path(__file__).parents[1] / "migrations/postgres" / name
                with connection.transaction():
                    connection.execute(migration.read_text(encoding="utf-8"))

            class Database:
                @contextmanager
                def transaction(self) -> Iterator[Any]:
                    with connection.transaction():
                        yield connection

            repository = PostgresRecommendedWebsiteRepository(Database())  # type: ignore[arg-type]
            assert repository.list_websites() == []
            payload = {"title": "Example", "url": "https://example.com/", "description": "Public reason", "category": "Tools", "sort_order": 0}
            first = repository.create_website(**payload)
            with pytest.raises(DuplicateRecommendedWebsiteError):
                repository.create_website(**payload)
            second = repository.create_website(**{**payload, "title": "Another", "url": "https://example.org/", "sort_order": -1})
            assert [row["id"] for row in repository.list_websites()] == [second["id"], first["id"]]
            edited = repository.update_website(first["id"], **{**payload, "description": "Edited", "sort_order": -2})
            assert edited and edited["description"] == "Edited"
            assert repository.list_websites()[0]["id"] == first["id"]
            assert repository.delete_website(first["id"])
            assert not repository.delete_website(first["id"])
            assert repository.update_website(first["id"], **payload) is None
            icon = "/api/media/site/" + "c" * 32 + ".webp"
            third = repository.create_website(**{**payload, "url": "https://example.net/"}, icon_url=icon)
            assert third["icon_url"] == icon and second["icon_url"] == ""
            # An edit whose icon fetch failed keeps the stored icon; a new URL drops it.
            kept = repository.update_website(third["id"], **{**payload, "url": "https://example.net/", "title": "Kept"})
            assert kept and kept["icon_url"] == icon
            refreshed = "/api/media/site/" + "d" * 32 + ".webp"
            kept = repository.update_website(third["id"], **{**payload, "url": "https://example.net/"}, icon_url=refreshed)
            assert kept and kept["icon_url"] == refreshed
            moved = repository.update_website(third["id"], **{**payload, "url": "https://example.io/"})
            assert moved and moved["icon_url"] == ""
            # Only re-encoded local site assets can be stored.
            for foreign in ("https://tracker.example/pixel.png", "/api/media/site/../secret.webp", "/api/media/site/" + "e" * 32 + ".svg"):
                with pytest.raises(psycopg.errors.CheckViolation):
                    repository.create_website(**{**payload, "url": "https://foreign.example/"}, icon_url=foreign)
            assert connection.execute("SELECT * FROM tool_websites").fetchall() == [{"id": 1, "private_note": "private-only"}]
            assert connection.execute("SELECT * FROM user_tool_websites").fetchall() == [{"user_id": 7, "website_id": 1}]
        finally:
            connection.execute("SET search_path TO public")
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
