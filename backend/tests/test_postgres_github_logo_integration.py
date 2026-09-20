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



def test_missing_logos_prioritize_daily_ranking_then_new_projects_and_retry_legacy_misses():
    with postgres_test_sandbox() as sandbox:
        db = sandbox.database
        with db.transaction() as connection:
            connection.execute("""
                INSERT INTO github_repo_candidates (repo_id, full_name, title, stars, first_seen_at)
                VALUES ('a/old', 'a/old', 'Old', 100000, '2020-01-01'),
                       ('a/new', 'a/new', 'New', 1000, CURRENT_TIMESTAMP::text),
                       ('a/hot', 'a/hot', 'Hot', 2000, '2020-01-01');
                INSERT INTO github_repo_daily_metrics
                    (repo_id, metric_date, hot_score, daily_growth_available, daily_star_growth)
                VALUES ('a/hot', (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Shanghai')::date, 99, TRUE, 500);
            """)
        repo = PostgresGitHubLogoRepository(db)
        repo.save('a/hot', {"status": "not_found"})
        assert [r['repo_id'] for r in repo.pending()] == ['a/hot', 'a/new', 'a/old']
        repo.save('a/hot', {"status": "found", "content": b'avatar', "content_type": 'image/webp'})
        assert [r['repo_id'] for r in repo.pending()] == ['a/new', 'a/old']
        repo.save('a/new', {"status": "failed"})
        assert [r['repo_id'] for r in repo.pending()] == ['a/old']
        assert repo.enqueue_all() == 2
        assert {r['repo_id'] for r in repo.pending()} == {'a/hot', 'a/new', 'a/old'}
        assert bytes(repo.get('a/hot')['content']) == b'avatar'
