from __future__ import annotations

from backend.app.repositories.postgres_github_logo_repository import PostgresGitHubLogoRepository
from backend.app.repositories.postgres_project_catalog import PostgresProjectCatalogRepository
from backend.tests.postgres_test_safety import postgres_test_sandbox


def test_hot_dates_skip_scan_lists_each_metric_date_once_newest_first():
    with postgres_test_sandbox() as sandbox:
        db = sandbox.database
        catalog = PostgresProjectCatalogRepository(db)
        assert catalog.list_github_hot_dates(limit=5) == []
        with db.transaction() as connection:
            connection.execute("""
                INSERT INTO github_repo_candidates (repo_id, full_name, title, stars)
                VALUES ('a/one', 'a/one', 'One', 900),
                       ('a/two', 'a/two', 'Two', 800),
                       ('a/three', 'a/three', 'Three', 700);
                INSERT INTO github_repo_daily_metrics (repo_id, metric_date)
                VALUES ('a/one', '2026-10-01'), ('a/two', '2026-10-01'), ('a/three', '2026-10-01'),
                       ('a/one', '2026-10-03'), ('a/two', '2026-10-03'),
                       ('a/three', '2026-09-28'),
                       ('a/one', '2026-10-04');
            """)
        assert catalog.list_github_hot_dates(limit=10) == [
            "2026-10-04", "2026-10-03", "2026-10-01", "2026-09-28",
        ]
        assert catalog.list_github_hot_dates(limit=2) == ["2026-10-04", "2026-10-03"]
        assert catalog.list_github_hot_dates(limit=1) == ["2026-10-04"]


def test_logo_url_is_listed_only_for_repositories_the_logo_endpoint_serves():
    # logo 接口只发 active 仓库的图；已下架仓库仍在项目库置灰展示，但不再给 logo 地址。
    with postgres_test_sandbox() as sandbox:
        db = sandbox.database
        with db.transaction() as connection:
            connection.execute("""
                INSERT INTO github_repo_candidates (repo_id, full_name, title, stars, availability_status)
                VALUES ('acme/live', 'acme/live', 'Live', 2000, 'active'),
                       ('acme/gone', 'acme/gone', 'Gone', 1500, 'not_found');
                INSERT INTO github_repo_enrichments
                  (repo_id, category_slug, category_name, description_zh,
                   tags_json, source_fingerprint, prompt_version, status)
                VALUES ('acme/live', 'other', 'Other', '在线', '[]', 'test', 'v1', 'succeeded'),
                       ('acme/gone', 'other', 'Other', '下架', '[]', 'test', 'v1', 'succeeded');
            """)
        logos = PostgresGitHubLogoRepository(db)
        for repo_id in ("acme/live", "acme/gone"):
            logos.save(repo_id, {"status": "found", "content": b"artwork",
                                 "content_type": "image/webp", "sha256": repo_id})
        items = {
            item["repo_id"]: item
            for item in PostgresProjectCatalogRepository(db).list_projects(source="github")["items"]
        }
        assert items["acme/live"]["image_url"] == "/api/projects/github/logo/acme/live"
        assert logos.get("acme/live") is not None
        assert items["acme/gone"]["availability_status"] == "not_found"
        assert items["acme/gone"]["image_url"] is None
        assert logos.get("acme/gone") is None
