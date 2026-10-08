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


def test_missing_logos_prioritize_rolling_only_growth_like_the_ranking():
    """只有滚动 24h 增长（无前日快照）的新仓同样按热度优先补 logo；

    滚动窗口明确为 0 的仓库即使日增量为正也不再插队，退回按星数排序。
    """
    with postgres_test_sandbox() as sandbox:
        db = sandbox.database
        with db.transaction() as connection:
            connection.execute("""
                INSERT INTO github_repo_candidates (repo_id, full_name, title, stars, first_seen_at)
                VALUES ('a/old', 'a/old', 'Old', 100000, '2020-01-01'),
                       ('a/born', 'a/born', 'Born', 1765, '2020-01-01'),
                       ('a/flat', 'a/flat', 'Flat', 3000, '2020-01-01');
                INSERT INTO github_repo_daily_metrics
                    (repo_id, metric_date, hot_score, daily_growth_available, daily_star_growth,
                     rolling_24h_star_growth, rolling_24h_growth_source)
                VALUES ('a/born', (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Shanghai')::date,
                        84, FALSE, 0, 1765, 'since_creation'),
                       ('a/flat', (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Shanghai')::date,
                        90, TRUE, 30, 0, 'rolling_window');
            """)
        assert [r['repo_id'] for r in PostgresGitHubLogoRepository(db).pending()] == [
            'a/born', 'a/old', 'a/flat',
        ]


def test_cached_default_avatars_retry_before_thirty_days_without_busy_loop():
    from backend.app.core.github_artwork import GITHUB_DEFAULT_AVATAR_SHA256

    with postgres_test_sandbox() as sandbox:
        db = sandbox.database
        with db.transaction() as connection:
            connection.execute("""
                INSERT INTO github_repo_candidates (repo_id, full_name, title, stars)
                VALUES ('a/bad', 'a/bad', 'Bad', 2000), ('a/good', 'a/good', 'Good', 2000)
            """)
        repo = PostgresGitHubLogoRepository(db)
        repo.save('a/bad', {'status': 'found', 'content': b'placeholder',
                          'sha256': GITHUB_DEFAULT_AVATAR_SHA256, 'content_type': 'image/webp'})
        repo.save('a/good', {'status': 'found', 'content': b'artwork',
                           'sha256': 'good', 'content_type': 'image/webp'})
        assert [r['repo_id'] for r in repo.pending()] == ['a/bad']
        repo.save('a/bad', {'status': 'failed'})
        assert repo.pending() == []
        with db.transaction() as connection:
            connection.execute("UPDATE github_project_logos SET next_check_at = CURRENT_TIMESTAMP WHERE repo_id = 'a/bad'")
        assert [r['repo_id'] for r in repo.pending()] == ['a/bad']
        repo.save('a/bad', {'status': 'found', 'content': b'correct',
                          'sha256': 'correct', 'content_type': 'image/webp'})
        assert repo.pending() == []
        assert bytes(repo.get('a/bad')['content']) == b'correct'
        assert bytes(repo.get('a/good')['content']) == b'artwork'


def test_recovery_requeues_only_missing_artwork_and_failures_retry_in_one_hour():
    with postgres_test_sandbox() as sandbox:
        db = sandbox.database
        with db.transaction() as connection:
            connection.execute("""
                INSERT INTO github_repo_candidates (repo_id, full_name, title, stars)
                VALUES ('a/missing', 'a/missing', 'Missing', 2000),
                       ('a/good', 'a/good', 'Good', 3000)
            """)
        repo = PostgresGitHubLogoRepository(db)
        repo.save('a/missing', {'status': 'failed'})
        repo.save('a/good', {'status': 'found', 'content': b'good', 'sha256': 'good',
                           'content_type': 'image/webp'})
        with db.transaction() as connection:
            row = connection.execute("""
                SELECT EXTRACT(EPOCH FROM (next_check_at - checked_at)) AS delay
                FROM github_project_logos WHERE repo_id = 'a/missing'
            """).fetchone()
        assert 3590 <= float(row['delay']) <= 3610
        assert repo.pending() == []
        assert repo.enqueue_missing() == 1
        assert [r['repo_id'] for r in repo.pending()] == ['a/missing']
        assert repo.get('a/good')['sha256'] == 'good'


def test_hot_placeholder_is_repaired_before_cold_missing_artwork():
    from backend.app.core.github_artwork import GITHUB_DEFAULT_AVATAR_SHA256

    with postgres_test_sandbox() as sandbox:
        db = sandbox.database
        with db.transaction() as connection:
            connection.execute("""
                INSERT INTO github_repo_candidates (repo_id, full_name, title, stars)
                VALUES ('a/hot', 'a/hot', 'Hot', 2000), ('a/cold', 'a/cold', 'Cold', 5000);
                INSERT INTO github_repo_daily_metrics
                    (repo_id, metric_date, hot_score, daily_growth_available, daily_star_growth)
                VALUES ('a/hot', (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Shanghai')::date, 99, TRUE, 500)
            """)
        repo = PostgresGitHubLogoRepository(db)
        repo.save('a/hot', {'status': 'found', 'content': b'placeholder',
                          'sha256': GITHUB_DEFAULT_AVATAR_SHA256, 'content_type': 'image/webp'})
        assert [r['repo_id'] for r in repo.pending()] == ['a/hot', 'a/cold']


def test_repair_snapshot_includes_deferred_failures_but_not_good_or_unavailable_artwork():
    from backend.app.core.github_artwork import GITHUB_DEFAULT_AVATAR_SHA256

    with postgres_test_sandbox() as sandbox:
        db = sandbox.database
        with db.transaction() as connection:
            connection.execute("""
                INSERT INTO github_repo_candidates (repo_id, full_name, title, stars)
                VALUES ('a/new', 'a/new', 'New', 500), ('a/failed', 'a/failed', 'Failed', 1000),
                       ('a/default', 'a/default', 'Default', 2000), ('a/good', 'a/good', 'Good', 3000)
            """)
        repo = PostgresGitHubLogoRepository(db)
        repo.save('a/failed', {'status': 'failed'})
        repo.save('a/default', {'status': 'found', 'content': b'default',
                              'sha256': GITHUB_DEFAULT_AVATAR_SHA256, 'content_type': 'image/webp'})
        repo.save('a/good', {'status': 'found', 'content': b'good', 'sha256': 'good',
                           'content_type': 'image/webp'})
        assert [row['repo_id'] for row in repo.repair_targets()] == ['a/default', 'a/failed', 'a/new']


def test_logo_route_name_resolves_artwork_stored_under_github_node_id():
    with postgres_test_sandbox() as sandbox:
        db = sandbox.database
        with db.transaction() as connection:
            connection.execute("""
                INSERT INTO github_repo_candidates (repo_id, full_name, title, stars)
                VALUES ('R_kgDOexample', 'acme/demo', 'Demo', 1000)
            """)
        repo = PostgresGitHubLogoRepository(db)
        repo.save('R_kgDOexample', {'status': 'found', 'content': b'artwork',
                                  'sha256': 'good', 'content_type': 'image/webp'})
        assert bytes(repo.get('acme/demo')['content']) == b'artwork'
        assert repo.get('R_kgDOexample')['sha256'] == 'good'
        assert repo.get('acme/missing') is None
        assert repo.avatar_owner('acme/demo') == 'acme'
        assert repo.avatar_owner('acme/missing') is None
        with db.transaction() as connection:
            connection.execute("""
                INSERT INTO github_repo_aliases (alias_repo_id, canonical_repo_id, full_name)
                VALUES ('old-owner/demo', 'R_kgDOexample', 'old-owner/demo')
            """)
        assert repo.avatar_owner('old-owner/demo') == 'acme'
        with db.transaction() as connection:
            connection.execute("UPDATE github_repo_candidates SET availability_status='not_found' WHERE repo_id='R_kgDOexample'")
        assert repo.avatar_owner('acme/demo') is None
        assert repo.avatar_owner('old-owner/demo') is None


def test_avatar_upgrade_snapshot_excludes_project_logos_and_inactive_rows():
    with postgres_test_sandbox() as sandbox:
        db = sandbox.database
        with db.transaction() as connection:
            connection.execute("""
                INSERT INTO github_repo_candidates (repo_id, full_name, title, stars)
                VALUES ('a/avatar', 'a/avatar', 'Avatar', 1000),
                       ('a/logo', 'a/logo', 'Logo', 1000),
                       ('a/gone', 'a/gone', 'Gone', 1000)
            """)
        repo = PostgresGitHubLogoRepository(db)
        for name, source in [('a/avatar', 'https://avatars.githubusercontent.com/u/123'),
                             ('a/logo', 'https://raw.githubusercontent.com/a/logo/main/logo.svg'),
                             ('a/gone', 'https://github.com/a.png?size=128')]:
            repo.save(name, {'status': 'found', 'content': b'image', 'sha256': name,
                             'content_type': 'image/webp', 'source_url': source})
        assert {r['repo_id'] for r in repo.avatar_targets()} == {'a/avatar', 'a/gone'}
        with db.transaction() as connection:
            connection.execute("UPDATE github_repo_candidates SET availability_status='not_found' WHERE repo_id='a/gone'")
        assert [r['repo_id'] for r in repo.avatar_targets()] == ['a/avatar']


def test_avatar_fallback_cannot_overwrite_cached_project_artwork():
    with postgres_test_sandbox() as sandbox:
        with sandbox.database.transaction() as connection:
            connection.execute("INSERT INTO github_repo_candidates (repo_id, full_name, title) VALUES ('a/demo', 'a/demo', 'Demo')")
        repo = PostgresGitHubLogoRepository(sandbox.database)
        repo.save('a/demo', {'status': 'found', 'content': b'logo', 'sha256': 'logo',
                             'content_type': 'image/svg+xml', 'source_url': 'https://raw.githubusercontent.com/a/demo/main/logo.svg'})
        repo.save('a/demo', {'status': 'found', 'content': b'avatar', 'sha256': 'avatar',
                             'content_type': 'image/webp', 'source_url': 'https://avatars.githubusercontent.com/u/123'})
        assert repo.get('a/demo')['sha256'] == 'logo'
        assert repo.pending() == []
        repo.save('a/demo', {'status': 'found', 'content': b'new logo', 'sha256': 'new',
                             'content_type': 'image/svg+xml', 'source_url': 'https://raw.githubusercontent.com/a/demo/new/logo.svg'})
        assert repo.get('a/demo')['sha256'] == 'new'
