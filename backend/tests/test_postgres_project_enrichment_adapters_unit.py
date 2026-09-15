from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

from backend.app.repositories.postgres_project_enrichment_repository import (
    PostgresGitHubProjectEnrichmentRepository,
    PostgresToolWebsiteEnrichmentRepository,
)
from backend.app.repositories.project_write_repository import (
    GitHubProjectEnrichmentRepository,
    ToolWebsiteEnrichmentRepository,
)


class FakeDatabase:
    def __init__(self, cursor: MagicMock) -> None:
        self.cursor = cursor
        self.connection = MagicMock()
        context = MagicMock()
        context.__enter__.return_value = cursor
        self.connection.cursor.return_value = context
        self.transaction_count = 0

    @contextmanager
    def transaction(self):
        self.transaction_count += 1
        yield self.connection


def test_github_candidate_query_pushes_eligibility_and_limit_into_sql() -> None:
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    repository = PostgresGitHubProjectEnrichmentRepository(FakeDatabase(cursor))  # type: ignore[arg-type]

    repository.get_github_projects_needing_enrichment(limit=25, min_stars=600)
    sql, params = cursor.execute.call_args.args
    assert "LIMIT %s" in sql
    assert "e.repo_id IS NULL" in sql
    assert "e.status IS DISTINCT FROM 'succeeded'" in sql
    # 可富化输入 = 非空原始 description，或 succeeded 且非空的 README 快照；
    # 仅 README 行/pending/failed/限流/404 都不能解锁模型调用
    assert "BTRIM(COALESCE(c.description, '')) <> ''" in sql
    assert "readme_status = 'succeeded'" in sql
    assert "BTRIM(COALESCE(ss.readme_text, '')) <> ''" in sql
    assert "LEFT JOIN github_project_semantic_sources ss ON ss.repo_id = c.repo_id" in sql
    assert "DISTINCT ON (repo_id)" in sql
    # 改名墓碑行（旧名候选行）必须排除：富化写入归一到新名行，
    # 旧名行若入选会永远重复富化、待处理计数清不零
    assert "github_repo_aliases ga" in sql
    assert "ga.alias_repo_id = c.repo_id" in sql
    assert "ga.canonical_repo_id <> c.repo_id" in sql
    assert params == (600, 25)

    repository.get_github_projects_needing_enrichment(
        refresh_changed=True, prompt_version="v9", limit=10,
    )
    sql, params = cursor.execute.call_args.args
    assert "e.prompt_version IS DISTINCT FROM %s" in sql
    assert "sha256" in sql
    assert "e.source_fingerprint IS DISTINCT FROM" in sql
    assert params == (500, "v9", 10)

    repository.get_github_projects_needing_enrichment(force=True, limit=5)
    sql, params = cursor.execute.call_args.args
    assert "AND TRUE" in sql
    assert "IS DISTINCT FROM" not in sql
    assert params == (500, 5)

    repository.get_github_projects_needing_enrichment(retry_failed=False, limit=7)
    sql, params = cursor.execute.call_args.args
    assert "e.repo_id IS NULL" in sql
    assert "e.status IS DISTINCT FROM 'succeeded'" not in sql
    assert params == (500, 7)


def test_github_enrichment_status_query_excludes_alias_tombstones() -> None:
    cursor = MagicMock()
    cursor.fetchone.return_value = {"eligible": 0, "succeeded": 0, "failed": 0}
    cursor.fetchall.return_value = []
    repository = PostgresGitHubProjectEnrichmentRepository(FakeDatabase(cursor))  # type: ignore[arg-type]

    status = repository.get_github_project_enrichment_status(min_stars=600)

    assert status["pending"] == 0
    for call in cursor.execute.call_args_list:
        sql = call.args[0]
        assert "github_repo_aliases ga" in sql
        assert "ga.alias_repo_id = c.repo_id" in sql
    # The canonical catalog CTE is reused by all status projections.
    assert cursor.execute.call_args_list[0].args[1] == (600,) * 5


def test_github_enrichment_pages_use_independent_stable_offsets() -> None:
    cursor = MagicMock()
    cursor.fetchone.return_value = {
        "unprocessable_total": 121,
        "unprocessable_items": [{
            "repo_id": 7,
            "full_name": "acme/missing",
            "url": "https://github.com/acme/missing",
            "stars": "700",
            "reason": "",
        }],
        "retained_total": 44,
        "retained_items": [{
            "repo_id": "retained-1",
            "full_name": "acme/retained",
            "url": "https://github.com/acme/retained",
            "stars": 650,
            "reason": "not_found",
        }],
    }
    database = FakeDatabase(cursor)
    repository = PostgresGitHubProjectEnrichmentRepository(database)  # type: ignore[arg-type]

    result = repository.list_github_project_enrichment_pages(
        unprocessable_page=2,
        retained_page=3,
        page_size=15,
        min_stars=600,
    )

    sql, params = cursor.execute.call_args.args
    assert database.transaction_count == 1
    assert cursor.execute.call_count == 1
    assert sql.count("LIMIT %s OFFSET %s") == 2
    assert "FROM unprocessable" in sql
    assert "FROM retained" in sql
    assert sql.count('ORDER BY stars DESC, full_name COLLATE "C" ASC') == 2
    assert params == (600, 600, 600, 600, 600, 15, 15, 15, 30)
    assert result == {
        "unprocessable": {
            "items": [{
                "repo_id": "7",
                "full_name": "acme/missing",
                "url": "https://github.com/acme/missing",
                "stars": 700,
                "reason": "missing_description",
            }],
            "total": 121,
            "page": 2,
            "page_size": 15,
        },
        "retained": {
            "items": [{
                "repo_id": "retained-1",
                "full_name": "acme/retained",
                "url": "https://github.com/acme/retained",
                "stars": 650,
                "reason": "not_found",
            }],
            "total": 44,
            "page": 3,
            "page_size": 15,
        },
    }


def test_github_enrichment_pages_normalize_empty_out_of_range_input() -> None:
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    repository = PostgresGitHubProjectEnrichmentRepository(FakeDatabase(cursor))  # type: ignore[arg-type]

    result = repository.list_github_project_enrichment_pages(
        unprocessable_page=0,
        retained_page=-2,
        page_size=0,
    )

    _, params = cursor.execute.call_args.args
    assert params[-4:] == (1, 0, 1, 0)
    assert result == {
        "unprocessable": {"items": [], "total": 0, "page": 1, "page_size": 1},
        "retained": {"items": [], "total": 0, "page": 1, "page_size": 1},
    }


def test_github_fingerprint_sql_matches_python_fingerprint() -> None:
    # _FINGERPRINT_SQL 与 _github_fingerprint 必须同构：拼接顺序、分隔符、编码一致
    import hashlib

    from backend.app.repositories.postgres_project_enrichment_repository import (
        _FINGERPRINT_SQL,
        _github_fingerprint,
    )

    row = {
        "full_name": "acme/agent",
        "description": "Agent 描述",
        "language": "Python",
        "topics_json": '["rag"]',
        "readme_status": "succeeded",
        "readme_sha256": "readme-hash",
    }
    expected = hashlib.sha256(
        "acme/agent\nAgent 描述\nPython\n[\"rag\"]\nreadme-hash".encode("utf-8")
    ).hexdigest()
    assert _github_fingerprint(row) == expected
    assert "COALESCE(c.full_name, '')" in _FINGERPRINT_SQL
    assert "COALESCE(c.description, '')" in _FINGERPRINT_SQL
    assert "COALESCE(c.language, '')" in _FINGERPRINT_SQL
    assert "COALESCE(c.topics_json, '')" in _FINGERPRINT_SQL
    assert "E'\\n'" in _FINGERPRINT_SQL
    assert "sha256" in _FINGERPRINT_SQL
    assert "UTF8" in _FINGERPRINT_SQL


def test_postgres_enrichment_adapters_expose_protocols_and_provider_reader() -> None:
    database = FakeDatabase(MagicMock())
    github: GitHubProjectEnrichmentRepository = PostgresGitHubProjectEnrichmentRepository(database)  # type: ignore[arg-type]
    websites: ToolWebsiteEnrichmentRepository = PostgresToolWebsiteEnrichmentRepository(database)  # type: ignore[arg-type]

    assert github.runtime_provider_settings is github.runtime_provider_settings
    assert websites.runtime_provider_settings is websites.runtime_provider_settings
    assert callable(github.get_github_projects_needing_enrichment)
    assert callable(websites.upsert_tool_website)


def test_github_candidate_selection_preserves_fingerprint_and_refresh_semantics() -> None:
    from backend.app.repositories.postgres_project_enrichment_repository import _github_fingerprint

    cursor = MagicMock()
    cursor.fetchall.return_value = [
        {
            "repo_id": "1", "full_name": "acme/agent", "description": "Agent",
            "language": "Python", "topics_json": '["rag"]', "stars": 800,
            "existing_status": "succeeded", "existing_prompt_version": "v1",
            "existing_source_fingerprint": _github_fingerprint({
                "full_name": "acme/agent", "description": "Agent",
                "language": "Python", "topics_json": '["rag"]',
            }),
            "existing_description_zh": "中文描述",
            "existing_description_en": "English description",
        },
        {
            "repo_id": "2", "full_name": "acme/new", "description": "New",
            "language": "Go", "topics_json": "[]", "stars": 700,
            "existing_status": None, "existing_prompt_version": None,
            "existing_source_fingerprint": None,
        },
    ]
    repository = PostgresGitHubProjectEnrichmentRepository(FakeDatabase(cursor))  # type: ignore[arg-type]

    normal = repository.get_github_projects_needing_enrichment(refresh_changed=False)
    refreshed = repository.get_github_projects_needing_enrichment(refresh_changed=True)

    assert [row["repo_id"] for row in normal] == ["2"]
    # refresh_changed no longer forces complete bilingual records; raw changes
    # and missing fields are detected by the unified eligibility predicate.
    assert [row["repo_id"] for row in refreshed] == ["2"]
    assert refreshed[0]["topics"] == []
    assert len(refreshed[0]["source_fingerprint"]) == 64
    assert "DISTINCT ON (repo_id)" in cursor.execute.call_args_list[0].args[0]


def test_bilingual_tag_backfill_queries_are_cursor_ordered_and_system_only() -> None:
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    github = PostgresGitHubProjectEnrichmentRepository(FakeDatabase(cursor))  # type: ignore[arg-type]
    github.list_github_projects_needing_bilingual_tags(
        after_repo_id="10", limit=25, min_stars=500,
    )
    sql, params = cursor.execute.call_args.args
    assert "c.repo_id > %s" in sql
    assert "e.status = 'succeeded'" in sql
    assert "COALESCE(e.tags_en_json, '') = ''" in sql
    assert "LEFT JOIN github_repo_aliases a ON a.alias_repo_id = c.repo_id" in sql
    assert "a.alias_repo_id IS NULL" in sql
    assert 'ORDER BY c.repo_id COLLATE "C" ASC' in sql
    assert params == ("10", 500, 25)

    website = PostgresToolWebsiteEnrichmentRepository(FakeDatabase(cursor))  # type: ignore[arg-type]
    website.list_tool_websites_needing_bilingual_tags(after_website_id=4, limit=20)
    sql, params = cursor.execute.call_args.args
    assert "w.id > %s" in sql
    assert "e.status = 'succeeded'" in sql
    assert "COALESCE(e.tags_en_json, '') = ''" in sql
    assert "prompt_version NOT LIKE '%%-manual'" in sql
    assert "user_tool_website_overrides" not in sql
    assert params == (4, 20)


def test_targeted_bilingual_tag_updates_do_not_mark_or_rewrite_user_data() -> None:
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    github = PostgresGitHubProjectEnrichmentRepository(FakeDatabase(cursor))  # type: ignore[arg-type]
    github.update_github_repo_system_tags(
        repo_id="1", tags_zh_json='["中文"]', tags_en_json='["English"]',
        prompt_version="v5",
    )
    sql = cursor.execute.call_args_list[-1].args[0]
    assert "UPDATE github_repo_enrichments" in sql
    assert "status='succeeded'" in sql
    assert "user_tool_website_overrides" not in sql

    website = PostgresToolWebsiteEnrichmentRepository(FakeDatabase(cursor))  # type: ignore[arg-type]
    website.update_tool_website_system_tags(
        website_id=2, tags_zh_json='["中文"]', tags_en_json='["English"]',
        prompt_version="v5",
    )
    sql = cursor.execute.call_args.args[0]
    assert "UPDATE tool_website_enrichments" in sql
    assert "prompt_version NOT LIKE '%%-manual'" in sql
    assert "user_tool_website_overrides" not in sql


def test_failure_writes_defaults_truncates_error_and_resolves_alias() -> None:
    cursor = MagicMock()
    cursor.fetchone.return_value = {"canonical_repo_id": "canonical"}
    repository = PostgresGitHubProjectEnrichmentRepository(FakeDatabase(cursor))  # type: ignore[arg-type]

    repository.mark_github_repo_enrichment_failed(
        "alias", source_fingerprint="f" * 64, prompt_version="v2", error_msg="x" * 2100
    )

    _, upsert = cursor.execute.call_args_list
    params = upsert.args[1]
    assert params["repo_id"] == "canonical"
    assert params["status"] == "failed"
    assert params["subcategory_slug"] == "other_uncategorized"
    assert len(params["error_msg"]) == 2000
    assert "ON CONFLICT (repo_id) DO UPDATE" in upsert.args[0]


def test_website_upsert_preserves_canonical_merge_policy() -> None:
    cursor = MagicMock()
    cursor.fetchone.return_value = {"id": 4, "normalized_url_hash": "hash"}
    repository = PostgresToolWebsiteEnrichmentRepository(FakeDatabase(cursor))  # type: ignore[arg-type]

    result = repository.upsert_tool_website({
        "canonical_url": "https://tool.test/docs", "normalized_url_hash": "hash",
        "domain": "tool.test", "source_fingerprint": "f" * 64, "visibility": "INVALID",
    })

    sql, params = cursor.execute.call_args.args
    assert result["id"] == 4
    assert params["visibility"] == "public"
    assert params["raw_metadata_json"] == "{}"
    assert "COALESCE(NULLIF(EXCLUDED.title,''),tool_websites.title)" in sql
    assert "tool_websites.visibility='public' OR EXCLUDED.visibility='public'" in sql


def test_website_failure_uses_same_enrichment_upsert_defaults() -> None:
    cursor = MagicMock()
    repository = PostgresToolWebsiteEnrichmentRepository(FakeDatabase(cursor))  # type: ignore[arg-type]

    repository.mark_tool_website_enrichment_failed(
        9, source_fingerprint="f" * 64, prompt_version="v1", error_msg="bad"
    )

    params = cursor.execute.call_args.args[1]
    assert params["website_id"] == 9
    assert params["status"] == "failed"
    assert params["category_slug"] == "other"
    assert params["tags_json"] == "[]"
    assert params["tags_zh_json"] == "[]"
    assert params["tags_en_json"] is None


def test_website_blocked_uses_same_enrichment_upsert_defaults() -> None:
    cursor = MagicMock()
    repository = PostgresToolWebsiteEnrichmentRepository(FakeDatabase(cursor))  # type: ignore[arg-type]

    repository.mark_tool_website_enrichment_blocked(
        9,
        source_fingerprint="f" * 64,
        prompt_version="v5-blocked",
        reason="x" * 2100,
    )

    params = cursor.execute.call_args.args[1]
    assert params["website_id"] == 9
    assert params["status"] == "blocked"
    assert params["category_slug"] == "other"
    assert params["tags_json"] == "[]"
    assert len(params["error_msg"]) == 2000


def test_bilingual_enrichment_backfill_query_excludes_blocked_rows() -> None:
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    repository = PostgresToolWebsiteEnrichmentRepository(FakeDatabase(cursor))  # type: ignore[arg-type]

    repository.list_tool_websites_needing_bilingual_enrichment(
        after_website_id=4, limit=20, prompt_version="v5"
    )

    sql, params = cursor.execute.call_args.args
    assert "e.status != 'blocked'" in sql
    assert params == (4, "v5%", 20)
