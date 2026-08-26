from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Iterator

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_IMPORT_CWD = Path.cwd()
os.chdir(_TESTS_DIR)
try:
    psycopg = pytest.importorskip("psycopg")
    pytest.importorskip("psycopg_pool")
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    from psycopg_pool import ConnectionPool

    from backend.app.core.postgres_database import PostgresDatabaseLifecycle
    from backend.app.core.postgres_migrations import PostgresMigrationRunner
    from backend.app.repositories.postgres_project_enrichment_repository import (
        PostgresGitHubProjectEnrichmentRepository,
        PostgresToolWebsiteEnrichmentRepository,
    )
finally:
    os.chdir(_IMPORT_CWD)


def _test_dsn() -> str:
    dsn = os.environ.get("TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("TEST_POSTGRES_DSN is required for PostgreSQL integration tests")
    database = str(conninfo_to_dict(dsn).get("dbname") or "")
    if "test" not in database.lower():
        pytest.skip("TEST_POSTGRES_DSN dbname must contain 'test'")
    return dsn


@pytest.fixture(scope="module")
def repositories() -> Iterator[tuple[Any, Any, Any]]:
    dsn = _test_dsn()
    schema = f"enrichment_pg16_{uuid.uuid4().hex}"
    with psycopg.connect(dsn, autocommit=True) as admin:
        version = int(admin.execute("SHOW server_version_num").fetchone()[0])
        if version < 160000 or version >= 170000:
            pytest.skip("this integration suite requires PostgreSQL 16")
        admin.execute(f'CREATE SCHEMA "{schema}"')
    scoped_dsn = make_conninfo(dsn, options=f"-c search_path={schema}")
    database = PostgresDatabaseLifecycle(lambda: ConnectionPool(
        conninfo=scoped_dsn, min_size=1, max_size=4, timeout=10,
        kwargs={"autocommit": False, "row_factory": psycopg.rows.dict_row}, open=False,
    ))
    try:
        PostgresMigrationRunner(database).apply()
        yield database, PostgresGitHubProjectEnrichmentRepository(database), PostgresToolWebsiteEnrichmentRepository(database)
    finally:
        database.close()
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def test_pg16_github_candidates_fingerprint_status_and_alias_upsert(repositories) -> None:
    database, github, _ = repositories
    with database.transaction() as connection:
        with connection.cursor() as cursor:
            # renamed_old：改名墓碑行（旧名候选行保留 + alias 指向新名），
            # stars 最高也必须被候选圈选与状态计数同时排除——否则富化写入
            # 归一到新名行后旧名行永远 pending，队列清不零。
            cursor.execute("""INSERT INTO github_repo_candidates
                (repo_id,full_name,description,language,topics_json,stars,forks,watchers)
                VALUES ('canonical','acme/agent','Agent','Python','[\"rag\"]',600,2,3),
                       ('new','acme/new','New','Go','[]',550,1,1),
                       ('renamed_old','acme/old-name','Old','Rust','[]',900,9,9)""")
            cursor.execute("""INSERT INTO github_repo_aliases
                (alias_repo_id,canonical_repo_id,full_name) VALUES ('alias','canonical','old/agent'),
                ('renamed_old','canonical','acme/old-name')""")
            cursor.execute("""INSERT INTO github_repo_snapshots
                (repo_id,snapshot_date,captured_at,stars,forks,watchers,open_issues)
                VALUES ('canonical','2026-07-27','now',700,4,5,6),
                       ('canonical','2026-07-28','now',800,7,8,9)""")
    candidates = github.get_github_projects_needing_enrichment(limit=10)
    assert [row["repo_id"] for row in candidates] == ["canonical", "new"]
    assert candidates[0]["stars"] == 800
    assert candidates[0]["topics"] == ["rag"]
    fingerprint = candidates[0]["source_fingerprint"]

    github.upsert_github_repo_enrichment({
        "repo_id": "alias", "category_slug": "agent", "category_name": "Agent",
        "description_zh": "智能体", "tags": ["RAG"], "source_fingerprint": fingerprint,
        "prompt_version": "v1",
    })
    assert [row["repo_id"] for row in github.get_github_projects_needing_enrichment()] == ["new"]
    github.mark_github_repo_enrichment_failed(
        "new", source_fingerprint=candidates[1]["source_fingerprint"],
        prompt_version="v1", error_msg="boom"
    )
    # 完整状态投影（真实 PG）：活动统计 = canonical 有效项目（alias/墓碑排除，
    # 4 行候选只算 canonical+new），四状态守恒 total = s/f/u/p；队列计数与
    # catalog 展示口径分离；retained 桶全零但结构齐全。
    assert github.get_github_project_enrichment_status() == {
        "eligible": 2, "succeeded": 1, "failed": 1, "pending": 0,
        "queue_pending": 0, "queue_failed": 1, "content_total": 1,
        "catalog_total": 2, "catalog_succeeded": 1, "catalog_failed": 1,
        "catalog_pending": 0, "catalog_unprocessable": 0,
        "catalog_progress": {
            "total": 2, "succeeded": 1, "failed": 1,
            "unprocessable": 0, "pending": 0,
        },
        "retained_total": 0,
        "retained_buckets": {
            "tombstone": 0, "not_found": 0,
            "snapshot_below_threshold": 0, "lost_input": 0,
        },
        "retained_projects": [],
        "by_category": [{"slug": "agent", "name": "Agent", "count": 1}],
        "unprocessable": 0, "unprocessable_projects": [],
    }
    assert [row["repo_id"] for row in github.get_github_projects_needing_enrichment(retry_failed=True)] == ["new"]


def test_pg16_readme_only_repos_enter_enrichment_and_no_input_unifies_unprocessable(
    repositories,
) -> None:
    """description 空 + 成功 README 的仓库进入标准队列；无富化输入的项目
    （含 404 下架形态）统一计入无法富化名单。"""
    database, github, _ = repositories
    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("""INSERT INTO github_repo_candidates
                (repo_id,full_name,description,language,topics_json,stars,forks,watchers,availability_status)
                VALUES
                ('readme_only','acme/readme-only','','Python','[]',800,1,1,'active'),
                ('readme_failed','acme/readme-failed','','Go','[]',700,1,1,'active'),
                ('both_empty','acme/both-empty','','Rust','[]',650,1,1,'active'),
                ('gone','QAI-brain/awesome-QAI-Papers-QDiffusion','','','[]',900,1,1,'not_found')""")
            cursor.execute("""INSERT INTO github_project_semantic_sources
                (repo_id,readme_text,readme_sha256,readme_status,updated_at)
                VALUES
                ('readme_only','Awesome QAI papers README body','h1','succeeded','now'),
                ('readme_failed','stale text','h2','failed','now'),
                ('gone','','','not_found','now')""")

    queue = {row["repo_id"] for row in github.get_github_projects_needing_enrichment(limit=100)}
    # README-only 首次可富化；failed/空 README 与 404 仓库都不是可富化输入
    assert "readme_only" in queue
    assert "readme_failed" not in queue
    assert "both_empty" not in queue
    assert "gone" not in queue

    status = github.get_github_project_enrichment_status(min_stars=500)
    unprocessable_ids = {row["repo_id"] for row in status["unprocessable_projects"]}
    # 无输入即无法富化：404 下架（QDiffusion 形态）、README 抓取失败与双空
    # 统一计入；仅有有效 README 输入的不进名单，且计数与详情列表一致
    assert "gone" in unprocessable_ids
    assert "readme_only" not in unprocessable_ids
    assert "readme_failed" in unprocessable_ids
    assert "both_empty" in unprocessable_ids
    assert status["unprocessable"] == len(unprocessable_ids)


def test_pg16_no_input_failed_and_pending_rows_unify_into_unprocessable(repositories) -> None:
    """无富化输入的 failed/pending 残渣统一归 unprocessable（生产 QAI-brain 形态）：
    404 下架不再豁免、留有 failed 行也不再挂失败数；有输入 failed 仍可重试；
    succeeded 丢输入仍计成功并退到 retained lost_input 桶。模块共享 schema，
    断言一律用 before/after 差值，不锁全局绝对数。"""
    database, github, _ = repositories
    before = github.get_github_project_enrichment_status(min_stars=500)
    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("""INSERT INTO github_repo_candidates
                (repo_id,full_name,description,language,topics_json,stars,forks,watchers,availability_status)
                VALUES
                ('uc_failed_gone','QAI-brain/uc-failed-gone','','','[]',800,1,1,'not_found'),
                ('uc_pending_gone','QAI-brain/uc-pending-gone','','','[]',700,1,1,'not_found'),
                ('uc_pending_active','acme/uc-pending-active',NULL,'','[]',650,1,1,'active'),
                ('uc_failed_input','acme/uc-failed-input','Has desc','','[]',900,1,1,'active'),
                ('uc_ok_pending','acme/uc-ok-pending','Ok desc','','[]',600,1,1,'active'),
                ('uc_succeeded_lost','acme/uc-succeeded-lost','','','[]',550,1,1,'active')""")
    github.mark_github_repo_enrichment_failed(
        "uc_failed_gone", source_fingerprint="f" * 64,
        prompt_version="v1", error_msg="boom",
    )
    github.mark_github_repo_enrichment_failed(
        "uc_failed_input", source_fingerprint="f" * 64,
        prompt_version="v1", error_msg="boom",
    )
    github.upsert_github_repo_enrichment({
        "repo_id": "uc_succeeded_lost", "category_slug": "agent",
        "category_name": "Agent", "description_zh": "智能体",
        "description_en": "Agent", "tags": [], "source_fingerprint": "s" * 64,
        "prompt_version": "v1",
    })
    after = github.get_github_project_enrichment_status(min_stars=500)

    def delta(key: str) -> int:
        return int(after[key]) - int(before[key])

    # 三个无输入项目统一计入无法富化（不论 404 下架还是留有 failed 行）
    assert delta("catalog_unprocessable") == 3
    assert delta("unprocessable") == 3
    listed = {row["repo_id"] for row in after["unprocessable_projects"]}
    assert {"uc_failed_gone", "uc_pending_gone", "uc_pending_active"} <= listed
    # 有输入 failed 留在可重试桶；有输入无行仍待处理；队列口径只数有输入项目
    assert delta("catalog_failed") == 1
    assert delta("catalog_pending") == 1
    assert delta("queue_failed") == 1
    assert delta("queue_pending") == 1
    assert delta("eligible") == 2
    # succeeded 丢输入仍计成功，退到 retained lost_input 桶而非 unprocessable
    assert delta("catalog_succeeded") == 1
    assert delta("retained_total") == 1
    assert (
        int(after["retained_buckets"]["lost_input"])
        - int(before["retained_buckets"]["lost_input"])
    ) == 1
    # catalog 投影四状态互斥守恒
    progress = after["catalog_progress"]
    assert progress["total"] == (
        progress["succeeded"] + progress["failed"]
        + progress["unprocessable"] + progress["pending"]
    )
    assert (
        progress["unprocessable"] - before["catalog_progress"]["unprocessable"]
    ) == 3


def test_pg16_readme_hash_change_triggers_refresh(repositories) -> None:
    """README 快照 hash 变化改变源指纹，refresh_changed 重新圈选已富化项目。"""
    database, github, _ = repositories
    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("""INSERT INTO github_repo_candidates
                (repo_id,full_name,description,language,topics_json,stars,forks,watchers)
                VALUES ('readme_fp','acme/readme-fp','','Python','[]',800,1,1)""")
            cursor.execute("""INSERT INTO github_project_semantic_sources
                (repo_id,readme_text,readme_sha256,readme_status,updated_at)
                VALUES ('readme_fp','README v1 body','hash-v1','succeeded','now')""")

    row = next(
        item
        for item in github.get_github_projects_needing_enrichment(limit=100)
        if item["repo_id"] == "readme_fp"
    )
    github.upsert_github_repo_enrichment({
        "repo_id": "readme_fp", "category_slug": "agent", "category_name": "Agent",
        "description_zh": "智能体", "description_en": "Agent",
        "tags": [], "source_fingerprint": row["source_fingerprint"],
        "prompt_version": "v1",
    })
    assert "readme_fp" not in {
        item["repo_id"]
        for item in github.get_github_projects_needing_enrichment(
            refresh_changed=True, prompt_version="v1", limit=100,
        )
    }

    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE github_project_semantic_sources "
                "SET readme_text='README v2 body', readme_sha256='hash-v2' "
                "WHERE repo_id='readme_fp'"
            )
    assert "readme_fp" in {
        item["repo_id"]
        for item in github.get_github_projects_needing_enrichment(
            refresh_changed=True, prompt_version="v1", limit=100,
        )
    }


def test_pg16_retained_breakdown_buckets_and_projects(repositories) -> None:
    """在库但已退出可执行队列的项目按互斥原因分桶，且可逐仓库溯源。

    播种忠实复刻生产生命周期：先富化成功（当时仍符合口径），
    随后各自发生退出事件——改名、404 下架、快照星数回落、简介被删。
    """
    database, github, _ = repositories
    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("""INSERT INTO github_repo_candidates
                (repo_id,full_name,description,language,topics_json,stars,forks,watchers,availability_status)
                VALUES
                ('ret_tomb','acme/before-rename','Was great','Python','[]',950,1,1,'active'),
                ('ret_gone404','acme/taken-down','','Go','[]',900,1,1,'active'),
                ('ret_dropped','acme/lost-stars','Still described','Rust','[]',600,1,1,'active'),
                ('ret_lost','acme/desc-deleted','Had a description','C++','[]',850,1,1,'active')""")

    # 1) 四个仓库都在“还符合口径”时完成富化
    for repo_id in ("ret_tomb", "ret_gone404", "ret_dropped", "ret_lost"):
        github.upsert_github_repo_enrichment({
            "repo_id": repo_id, "category_slug": "agent", "category_name": "Agent",
            "description_zh": "智能体", "tags": [],
            "source_fingerprint": f"fp-{repo_id}", "prompt_version": "v1",
        })

    with database.transaction() as connection:
        with connection.cursor() as cursor:
            # 2) 各自发生退出事件
            # ret_tomb：改名为 canonical，旧行变墓碑（成果归一到新名）
            cursor.execute("""INSERT INTO github_repo_aliases
                (alias_repo_id,canonical_repo_id,full_name)
                VALUES ('ret_tomb','canonical','acme/before-rename')""")
            # ret_gone404：两次 404 观测后下架
            cursor.execute("UPDATE github_repo_candidates SET availability_status='not_found' "
                           "WHERE repo_id='ret_gone404'")
            # ret_dropped：最新快照星数回落到门槛以下（candidates 仍 600）
            cursor.execute("""INSERT INTO github_repo_snapshots
                (repo_id,snapshot_date,captured_at,stars,forks,watchers,open_issues)
                VALUES ('ret_dropped','2026-08-20','now',450,1,1,1)""")
            # ret_lost：作者删掉简介，README 抓取也失败
            cursor.execute("UPDATE github_repo_candidates SET description='' "
                           "WHERE repo_id='ret_lost'")
            cursor.execute("""INSERT INTO github_project_semantic_sources
                (repo_id,readme_text,readme_sha256,readme_status,updated_at)
                VALUES ('ret_lost','','','failed','now')""")

    status = github.get_github_project_enrichment_status(min_stars=500)

    # 逐仓库溯源：列表必须给出具体项目与互斥原因（模块共享 schema，按 repo 断言）
    retained = {row["repo_id"]: row for row in status["retained_projects"]}
    assert retained["ret_tomb"]["reason"] == "tombstone"
    assert retained["ret_gone404"]["reason"] == "not_found"
    assert retained["ret_dropped"]["reason"] == "snapshot_below_threshold"
    assert retained["ret_lost"]["reason"] == "lost_input"
    # 列表展示用星数为最新快照优先（ret_dropped 显示 450 而非 600）
    assert retained["ret_dropped"]["stars"] == 450
    for row in retained.values():
        assert {"repo_id", "full_name", "url", "stars", "reason"} <= set(row)

    # 分桶计数与列表自洽：每个桶至少覆盖我播种的这一行
    buckets = status["retained_buckets"]
    assert buckets["tombstone"] >= 1
    assert buckets["not_found"] >= 1
    assert buckets["snapshot_below_threshold"] >= 1
    assert buckets["lost_input"] >= 1
    assert status["retained_total"] == sum(buckets.values())
    assert status["retained_total"] == len(status["retained_projects"]) or \
        status["retained_total"] > len(status["retained_projects"])  # 列表有 100 条上限

    # 四行都富化成功过：绝不进入无法富化名单
    unprocessable_ids = {row["repo_id"] for row in status["unprocessable_projects"]}
    assert not {"ret_tomb", "ret_gone404", "ret_dropped", "ret_lost"} & unprocessable_ids

    # 队列侧同步退出：四行都不再被圈选
    queue = {row["repo_id"] for row in github.get_github_projects_needing_enrichment(limit=500)}
    assert not {"ret_tomb", "ret_gone404", "ret_dropped", "ret_lost"} & queue

    # 反向 sanity：前序用例的 404 仓库（无富化记录）不进 retained（无成功成果），
    # 但因无富化输入统一计入无法富化名单
    assert "gone" not in retained
    assert "gone" in unprocessable_ids


def test_pg16_website_metadata_merge_item_and_enrichment_failure(repositories) -> None:
    _, _, websites = repositories
    created = websites.upsert_tool_website({
        "canonical_url": "https://tool.test/docs", "normalized_url_hash": "h" * 64,
        "domain": "tool.test", "title": "Tool", "description": "Useful",
        "image_url": "https://tool.test/logo.png", "raw_metadata_json": '{"a":1}',
        "source_fingerprint": "a" * 64, "visibility": "private",
    })
    merged = websites.upsert_tool_website({
        "canonical_url": "https://tool.test", "normalized_url_hash": "h" * 64,
        "domain": "tool.test", "title": "", "description": "", "image_url": "",
        "source_fingerprint": "b" * 64, "visibility": "public",
    })
    assert merged["id"] == created["id"]
    assert merged["title"] == "Tool"
    assert merged["description"] == "Useful"
    assert merged["visibility"] == "public"

    websites.upsert_tool_website_enrichment({
        "website_id": created["id"], "category_slug": "ai_tools",
        "category_name": "AI 工具", "description_zh": "工具", "tags": ["AI"],
        "source_fingerprint": "b" * 64, "prompt_version": "v1",
    })
    item = websites.get_tool_website_item(created["id"])
    assert item is not None
    assert item["id"] == f"website:{created['id']}"
    assert item["tags"] == ["AI"]
    assert item["image_url"] == "https://tool.test/logo.png"

    websites.mark_tool_website_enrichment_failed(
        created["id"], source_fingerprint="c" * 64,
        prompt_version="v2", error_msg="x" * 2100,
    )
    failed = websites.get_tool_website_enrichment(created["id"])
    assert failed is not None
    assert failed["status"] == "failed"
    assert len(failed["error_msg"]) == 2000


def test_pg16_run_scope_excludes_alias_tombstones(repositories) -> None:
    """单次爬取运行范围（count/list 共用 _RUN_SCOPE_WHERE）同样排除改名墓碑行：
    旧名行的富化写入会归一到新名，留在范围内会被反复圈选、白烧模型调用。"""
    database, github, _ = repositories
    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("""INSERT INTO github_repo_candidates
                (repo_id,full_name,description,language,topics_json,stars,forks,watchers,
                 source_channels,first_seen_at)
                VALUES ('run_canonical','acme/run-new','Desc','Python','[]',900,2,3,
                        'it-chan','2026-08-20T00:00:00Z'),
                       ('run_old','acme/run-old','Desc','Python','[]',950,2,3,
                        'it-chan','2026-08-20T00:00:00Z')""")
            cursor.execute("""INSERT INTO github_repo_aliases
                (alias_repo_id,canonical_repo_id,full_name)
                VALUES ('run_old','run_canonical','acme/run-old')""")

    assert github.count_github_run_enrichment_candidates(
        channel="it-chan", first_seen_after="2026-08-01T00:00:00Z", min_stars=500
    ) == 1
    rows = github.list_github_run_enrichment_candidates(
        channel="it-chan", first_seen_after="2026-08-01T00:00:00Z", min_stars=500
    )
    assert [row["repo_id"] for row in rows] == ["run_canonical"]


def test_pg16_refresh_changed_uses_sql_fingerprint_equivalent_to_python(repositories) -> None:
    """refresh_changed 的 SQL 指纹下推与 Python 侧 _github_fingerprint 严格一致。"""
    database, github, _ = repositories
    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("""INSERT INTO github_repo_candidates
                (repo_id,full_name,description,language,topics_json,stars,forks,watchers)
                VALUES ('stable','acme/稳定','Agent 描述','Python','[\"rag\"]',900,2,3)""")

    # 模块共享 schema 内可能有前序用例的其他 repo，断言只锁定 stable 一行
    stable = next(
        row
        for row in github.get_github_projects_needing_enrichment(limit=50)
        if row["repo_id"] == "stable"
    )
    fingerprint = stable["source_fingerprint"]
    github.upsert_github_repo_enrichment({
        "repo_id": "stable", "category_slug": "agent", "category_name": "Agent",
        "description_zh": "智能体", "description_en": "Agent",
        "tags": ["RAG"], "source_fingerprint": fingerprint,
        "prompt_version": "v1",
    })

    # 指纹、双语字段与版本一致：SQL 下推必须排除该项目
    assert "stable" not in {
        row["repo_id"]
        for row in github.get_github_projects_needing_enrichment(
            refresh_changed=True, prompt_version="v1", limit=50,
        )
    }

    # prompt_version 变化触发重富化
    assert "stable" in {
        row["repo_id"]
        for row in github.get_github_projects_needing_enrichment(
            refresh_changed=True, prompt_version="v2", limit=50,
        )
    }

    # 内容变化（SQL 指纹随之变化）触发重富化
    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE github_repo_candidates SET description='New 描述' "
                "WHERE repo_id='stable'"
            )
    assert "stable" in {
        row["repo_id"]
        for row in github.get_github_projects_needing_enrichment(
            refresh_changed=True, prompt_version="v1", limit=50,
        )
    }
