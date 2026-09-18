from __future__ import annotations

import pytest

from backend.app.repositories.postgres_github_logo_repository import PostgresGitHubLogoRepository
from backend.app.repositories.postgres_project_catalog import PostgresProjectCatalogRepository
from backend.tests.postgres_test_safety import postgres_test_sandbox


def test_persistent_logo_queue_cache_catalog_and_size_constraint():
    with postgres_test_sandbox() as sandbox:
        db = sandbox.database
        with db.transaction() as connection:
            connection.execute("""
                INSERT INTO github_repo_candidates (repo_id, full_name, title, stars)
                VALUES ('acme/demo', 'acme/demo', 'Demo', 2000),
                       ('acme/other', 'acme/other', 'Other', 1000);
                INSERT INTO github_repo_enrichments
                  (repo_id, category_slug, category_name, description_zh,
                   tags_json, source_fingerprint, prompt_version, status)
                VALUES ('acme/demo', 'other', 'Other', '演示', '[]', 'test', 'v1', 'succeeded');
            """)
        repo = PostgresGitHubLogoRepository(db)
        assert [r["repo_id"] for r in repo.pending()] == ["acme/demo", "acme/other"]
        repo.save("acme/demo", {"status": "found", "content": b"artwork",
                  "content_type": "image/webp", "sha256": "abc", "source_url": "https://example.com/logo"})
        assert bytes(repo.get("acme/demo")["content"]) == b"artwork"
        repo.save("acme/demo", {"status": "failed"})
        assert repo.get("acme/demo")["sha256"] == "abc"
        assert [r["repo_id"] for r in repo.pending()] == ["acme/other"]
        catalog = PostgresProjectCatalogRepository(db)
        result = catalog.list_projects(source="github", min_stars=500)
        assert next(row for row in result["items"] if row["repo_id"] == "acme/demo")["image_url"] == "/api/projects/github/logo/acme/demo"
        with pytest.raises(Exception, match="check constraint"):
            repo.save("acme/other", {"status": "found", "content": b"x" * 262145, "content_type": "image/webp"})
        with db.transaction() as connection:
            connection.execute("DELETE FROM github_repo_candidates WHERE repo_id='acme/demo'")
        assert repo.get("acme/demo") is None
