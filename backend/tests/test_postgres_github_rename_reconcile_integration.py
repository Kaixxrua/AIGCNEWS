"""改名归一化与僵尸项目防御的 PostgreSQL 集成测试。

覆盖：
- renamed_from 观测触发的改名归一（node 型 PK 就地改名 / name 型 PK 克隆并入）
- 新旧两名重复行合并（子表随迁、收藏软引用改指、别名长期可解析）
- 名称重用防御（陌生 node id 观测被拒 + 累计不可用观测）
- 热榜读取侧过滤（not_found / 别名隐藏行不再出现）
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from backend.tests.postgres_test_safety import postgres_test_sandbox

_TESTS_DIR = Path(__file__).resolve().parent
_IMPORT_CWD = Path.cwd()
os.chdir(_TESTS_DIR)
try:
    psycopg = pytest.importorskip("psycopg")
    pytest.importorskip("psycopg_pool")

    from backend.app.repositories.postgres_project_ingestion_repository import (
        PostgresGitHubProjectIngestionRepository,
    )
finally:
    os.chdir(_IMPORT_CWD)

_CHECKED_AT = "2026-08-14T01:00:00+00:00"
_SNAPSHOT_DATE = "2026-08-14"


@pytest.fixture(scope="module")
def postgres_ingestion() -> Iterator[tuple[Any, Any]]:
    with postgres_test_sandbox() as sandbox:
        database = sandbox.database
        yield PostgresGitHubProjectIngestionRepository(database), database


def _seed_candidate(
    repository: Any,
    *,
    repo_id: str,
    full_name: str,
    stars: int = 500,
    source_channels: str = "trending_daily",
    first_seen_at: str = "2026-01-01T00:00:00+00:00",
    title: str | None = None,
) -> None:
    repository.upsert_github_repo_candidate(
        {
            "repo_id": repo_id,
            "full_name": full_name,
            "title": title or full_name,
            "url": f"https://github.com/{full_name}",
            "stars": stars,
            "forks": 10,
            "watchers": 20,
            "source_channels": source_channels,
            "first_seen_at": first_seen_at,
            "last_seen_at": first_seen_at,
            "last_snapshot_at": first_seen_at,
        }
    )


def _seed_node_candidate(
    database: Any,
    *,
    repo_id: str,
    full_name: str,
    stars: int = 500,
) -> None:
    """直插 node 型 PK 行（生产存量形态；upsert 路径对新行一律归一为 name 型 PK）。"""
    _execute(
        database,
        "INSERT INTO github_repo_candidates (repo_id, full_name, title, url, stars, forks, watchers, "
        "source_channels, first_seen_at, last_seen_at, last_snapshot_at) VALUES "
        "(%s, %s, %s, %s, %s, 10, 20, 'trending_daily', '2026-01-01T00:00:00+00:00', "
        "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')",
        (repo_id, full_name, full_name, f"https://github.com/{full_name}", stars),
    )


def _observation(
    *,
    node_id: str,
    requested_name: str,
    api_name: str,
    stars: int,
) -> dict[str, Any]:
    renamed_from = requested_name if api_name != requested_name else ""
    return {
        "candidate": {
            "repo_id": node_id,
            "full_name": api_name,
            "title": api_name,
            "url": f"https://github.com/{api_name}",
            "stars": stars,
            "forks": 11,
            "watchers": 22,
            "community_metrics_complete": True,
            "source_channels": "daily_metrics",
            "last_snapshot_at": _CHECKED_AT,
        },
        "available_full_name": requested_name,
        "renamed_from": renamed_from,
        "snapshot": {
            "repo_id": node_id,
            "full_name": api_name,
            "snapshot_date": _SNAPSHOT_DATE,
            "captured_at": _CHECKED_AT,
            "stars": stars,
            "forks": 11,
            "watchers": 22,
            "community_metrics_complete": True,
        },
    }


def _fetchone(database: Any, sql: str, params: tuple = ()) -> dict[str, Any] | None:
    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()


def _fetchall(database: Any, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return list(cursor.fetchall())


def _execute(database: Any, sql: str, params: tuple = ()) -> None:
    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)


def test_node_based_row_renamed_in_place(
    postgres_ingestion: tuple[Any, Any],
) -> None:
    repository, database = postgres_ingestion
    _seed_node_candidate(database, repo_id="R_node_a", full_name="acme/it-old", stars=700)

    written = repository.upsert_github_repo_metric_observations(
        [
            _observation(
                node_id="R_node_a",
                requested_name="acme/it-old",
                api_name="acme/it-new",
                stars=800,
            )
        ],
        checked_at=_CHECKED_AT,
    )

    assert written == 1
    row = _fetchone(
        database,
        "SELECT repo_id, full_name, title, url, stars, availability_status, not_found_count "
        "FROM github_repo_candidates WHERE repo_id='R_node_a'",
    )
    assert row is not None
    assert row["full_name"] == "acme/it-new"
    assert row["title"] == "acme/it-new"
    assert row["url"] == "https://github.com/acme/it-new"
    assert row["stars"] == 800
    assert row["availability_status"] == "active"
    assert row["not_found_count"] == 0
    # 旧名不再占据候选行，只作为别名长期可解析
    assert (
        _fetchone(
            database,
            "SELECT repo_id FROM github_repo_candidates WHERE LOWER(full_name)='acme/it-old'",
        )
        is None
    )
    alias = _fetchone(
        database,
        "SELECT canonical_repo_id FROM github_repo_aliases WHERE alias_repo_id='acme/it-old'",
    )
    assert alias is not None and alias["canonical_repo_id"] == "R_node_a"
    snapshot = _fetchone(
        database,
        "SELECT stars FROM github_repo_snapshots WHERE repo_id='R_node_a' AND snapshot_date=%s",
        (_SNAPSHOT_DATE,),
    )
    assert snapshot is not None and snapshot["stars"] == 800


def test_name_based_row_renamed_via_clone_and_merge(
    postgres_ingestion: tuple[Any, Any],
) -> None:
    repository, database = postgres_ingestion
    _seed_candidate(repository, repo_id="acme/legacy", full_name="acme/legacy", stars=600)
    # 旧行已绑定 node 别名（此前日刷链接过）
    _seed_candidate(repository, repo_id="R_node_b", full_name="acme/legacy", stars=610)
    _execute(
        database,
        "INSERT INTO github_repo_snapshots (repo_id, snapshot_date, captured_at, stars) "
        "VALUES ('acme/legacy', '2026-08-13', '2026-08-13T01:00:00+00:00', 590)",
    )

    written = repository.upsert_github_repo_metric_observations(
        [
            _observation(
                node_id="R_node_b",
                requested_name="acme/legacy",
                api_name="acme/renamed",
                stars=650,
            )
        ],
        checked_at=_CHECKED_AT,
    )

    assert written == 1
    # PK 迁移：旧 name 型 PK 行被删除，新身份行承载全部历史
    assert (
        _fetchone(
            database,
            "SELECT repo_id FROM github_repo_candidates WHERE repo_id='acme/legacy'",
        )
        is None
    )
    row = _fetchone(
        database,
        "SELECT repo_id, full_name, stars FROM github_repo_candidates WHERE repo_id='acme/renamed'",
    )
    assert row is not None
    assert row["full_name"] == "acme/renamed"
    assert row["stars"] == 650
    old_snapshot = _fetchone(
        database,
        "SELECT stars FROM github_repo_snapshots WHERE repo_id='acme/renamed' AND snapshot_date='2026-08-13'",
    )
    assert old_snapshot is not None and old_snapshot["stars"] == 590
    aliases = {
        item["alias_repo_id"]: item["canonical_repo_id"]
        for item in _fetchall(
            database,
            "SELECT alias_repo_id, canonical_repo_id FROM github_repo_aliases WHERE canonical_repo_id='acme/renamed'",
        )
    }
    assert aliases.get("R_node_b") == "acme/renamed"
    assert aliases.get("acme/legacy") == "acme/renamed"


def test_duplicate_rows_merged_keeping_new_name(
    postgres_ingestion: tuple[Any, Any],
) -> None:
    repository, database = postgres_ingestion
    _seed_candidate(
        repository,
        repo_id="acme/dup-old",
        full_name="acme/dup-old",
        stars=500,
        source_channels="trending_daily",
        first_seen_at="2026-01-01T00:00:00+00:00",
    )
    _seed_candidate(repository, repo_id="R_node_c", full_name="acme/dup-old", stars=510)
    _seed_candidate(
        repository,
        repo_id="acme/dup-new",
        full_name="acme/dup-new",
        stars=900,
        source_channels="search_candidates",
        first_seen_at="2026-06-01T00:00:00+00:00",
    )
    # 旧行历史：同日快照比新行旧（冲突时让位），另有一天独有历史（随迁）
    _execute(
        database,
        "INSERT INTO github_repo_snapshots (repo_id, snapshot_date, captured_at, stars) VALUES "
        "('acme/dup-old', '2026-08-12', '2026-08-12T01:00:00+00:00', 480),"
        "('acme/dup-old', '2026-08-13', '2026-08-13T00:30:00+00:00', 495),"
        "('acme/dup-new', '2026-08-13', '2026-08-13T01:30:00+00:00', 900)",
    )
    _execute(
        database,
        "INSERT INTO github_trending_hits (repo_id, full_name, period, rank, observed_date, captured_at) "
        "VALUES ('acme/dup-old', 'acme/dup-old', 'daily', 3, '2026-08-13', '2026-08-13T01:00:00+00:00')",
    )
    _execute(
        database,
        "INSERT INTO github_repo_star_observations (repo_id, observed_at, stars) VALUES "
        "('acme/dup-old', '2026-08-13T00:30:00+00:00', 495),"
        "('acme/dup-old', '2026-08-13T01:30:00+00:00', 494),"
        "('acme/dup-new', '2026-08-13T01:30:00+00:00', 900)",
    )
    _execute(
        database,
        "INSERT INTO github_repo_enrichments (repo_id, category_slug, category_name, "
        "subcategory_slug, description_zh, source_fingerprint, prompt_version, status) "
        "VALUES ('acme/dup-old', 'agent', 'Agent', 'general', '旧行画像', 'fp_old', 'v1', 'succeeded')",
    )
    _execute(
        database,
        "INSERT INTO users (id, hashed_password) VALUES (91, 'test-hash')",
    )
    _execute(
        database,
        "INSERT INTO project_favorites (user_id, project_source, project_id) VALUES (91, 'github', 'acme/dup-old')",
    )

    written = repository.upsert_github_repo_metric_observations(
        [
            _observation(
                node_id="R_node_c",
                requested_name="acme/dup-old",
                api_name="acme/dup-new",
                stars=950,
            )
        ],
        checked_at=_CHECKED_AT,
    )

    assert written == 1
    assert (
        _fetchone(
            database,
            "SELECT repo_id FROM github_repo_candidates WHERE repo_id='acme/dup-old'",
        )
        is None
    )
    row = _fetchone(
        database,
        "SELECT stars, first_seen_at, source_channels FROM github_repo_candidates WHERE repo_id='acme/dup-new'",
    )
    assert row is not None
    assert row["stars"] == 950
    assert row["first_seen_at"] == "2026-01-01T00:00:00+00:00"
    channels = set(str(row["source_channels"]).split(","))
    assert {"trending_daily", "search_candidates", "daily_metrics"} <= channels
    # 同日冲突保留较新一侧；独有历史随迁
    snapshots = {
        item["snapshot_date"]: item["stars"]
        for item in _fetchall(
            database,
            "SELECT snapshot_date, stars FROM github_repo_snapshots WHERE repo_id='acme/dup-new'",
        )
    }
    assert snapshots.get("2026-08-12") == 480
    assert snapshots.get("2026-08-13") == 900
    assert snapshots.get(_SNAPSHOT_DATE) == 950
    # 星数观测同样随迁：同一时刻保留新行，独有时刻迁入，含本次写入的观测
    observations = {
        item["observed_at"].isoformat(): item["stars"]
        for item in _fetchall(
            database,
            "SELECT observed_at, stars FROM github_repo_star_observations WHERE repo_id='acme/dup-new'",
        )
    }
    assert observations == {
        "2026-08-13T00:30:00+00:00": 495,
        "2026-08-13T01:30:00+00:00": 900,
        _CHECKED_AT: 950,
    }
    assert not _fetchall(
        database,
        "SELECT 1 FROM github_repo_star_observations WHERE repo_id='acme/dup-old'",
    )
    hit = _fetchone(
        database,
        "SELECT rank FROM github_trending_hits "
        "WHERE repo_id='acme/dup-new' AND period='daily' AND observed_date='2026-08-13'",
    )
    assert hit is not None and hit["rank"] == 3
    enrichment = _fetchone(
        database,
        "SELECT status FROM github_repo_enrichments WHERE repo_id='acme/dup-new'",
    )
    assert enrichment is not None and enrichment["status"] == "succeeded"
    favorite = _fetchone(
        database,
        "SELECT project_id FROM project_favorites WHERE user_id=91 AND project_source='github'",
    )
    assert favorite is not None and favorite["project_id"] == "acme/dup-new"
    aliases = {
        item["alias_repo_id"]: item["canonical_repo_id"]
        for item in _fetchall(
            database,
            "SELECT alias_repo_id, canonical_repo_id FROM github_repo_aliases WHERE canonical_repo_id='acme/dup-new'",
        )
    }
    assert aliases.get("R_node_c") == "acme/dup-new"
    assert aliases.get("acme/dup-old") == "acme/dup-new"


def test_casing_only_difference_normalized(postgres_ingestion: tuple[Any, Any]) -> None:
    repository, database = postgres_ingestion
    _seed_node_candidate(database, repo_id="R_node_d", full_name="ACME/Cased", stars=500)

    written = repository.upsert_github_repo_metric_observations(
        [
            _observation(
                node_id="R_node_d",
                requested_name="ACME/Cased",
                api_name="acme/cased",
                stars=520,
            )
        ],
        checked_at=_CHECKED_AT,
    )

    assert written == 1
    row = _fetchone(
        database,
        "SELECT full_name, stars FROM github_repo_candidates WHERE repo_id='R_node_d'",
    )
    assert row is not None
    assert row["full_name"] == "acme/cased"
    assert row["stars"] == 520


def test_name_reuse_guard_rejects_foreign_node_observation(
    postgres_ingestion: tuple[Any, Any],
) -> None:
    repository, database = postgres_ingestion
    # name 型行 + 已链接 node R_keep：同名观测带回陌生 node R_stranger 时拒绝覆盖
    _seed_candidate(repository, repo_id="acme/stay", full_name="acme/stay", stars=700)
    _seed_candidate(repository, repo_id="R_keep", full_name="acme/stay", stars=710)

    written = repository.upsert_github_repo_metric_observations(
        [
            _observation(
                node_id="R_stranger",
                requested_name="acme/stay",
                api_name="acme/stay",
                stars=9999,
            )
        ],
        checked_at=_CHECKED_AT,
    )

    assert written == 0
    row = _fetchone(
        database,
        "SELECT stars, not_found_count, availability_status FROM github_repo_candidates WHERE repo_id='acme/stay'",
    )
    assert row is not None
    assert row["stars"] == 710  # 未被陌生 node 的数据覆盖
    assert row["not_found_count"] == 1
    assert row["availability_status"] == "active"  # 第一次观测仅累计，未下架
    assert (
        _fetchone(
            database,
            "SELECT repo_id FROM github_repo_snapshots WHERE repo_id='acme/stay' AND snapshot_date=%s",
            (_SNAPSHOT_DATE,),
        )
        is None
    )


def test_rename_rejected_when_node_belongs_to_other_repo(
    postgres_ingestion: tuple[Any, Any],
) -> None:
    repository, database = postgres_ingestion
    _seed_candidate(repository, repo_id="acme/victim", full_name="acme/victim", stars=600)
    _seed_candidate(repository, repo_id="acme/other", full_name="acme/other", stars=600)
    _seed_candidate(repository, repo_id="R_other", full_name="acme/other", stars=610)

    written = repository.upsert_github_repo_metric_observations(
        [
            _observation(
                node_id="R_other",
                requested_name="acme/victim",
                api_name="acme/brand-new",
                stars=5000,
            )
        ],
        checked_at=_CHECKED_AT,
    )

    assert written == 0
    victim = _fetchone(
        database,
        "SELECT stars, not_found_count FROM github_repo_candidates WHERE repo_id='acme/victim'",
    )
    assert victim is not None
    assert victim["stars"] == 600  # 观测被拒，既有数据未被吞并
    assert victim["not_found_count"] == 1
    assert (
        _fetchone(
            database,
            "SELECT repo_id FROM github_repo_candidates WHERE LOWER(full_name)='acme/brand-new'",
        )
        is None
    )


def test_hot_repos_exclude_not_found_and_alias_hidden(
    postgres_ingestion: tuple[Any, Any],
) -> None:
    repository, database = postgres_ingestion
    _seed_candidate(repository, repo_id="acme/hot-active", full_name="acme/hot-active", stars=900)
    _seed_candidate(repository, repo_id="acme/hot-dead", full_name="acme/hot-dead", stars=900)
    _seed_candidate(repository, repo_id="acme/hot-hidden", full_name="acme/hot-hidden", stars=900)
    _seed_candidate(repository, repo_id="acme/hot-keep", full_name="acme/hot-keep", stars=900)
    assert repository.record_github_repo_not_found("acme/hot-dead", checked_at=_CHECKED_AT) is False
    assert repository.record_github_repo_not_found("acme/hot-dead", checked_at=_CHECKED_AT) is True
    _execute(
        database,
        "INSERT INTO github_repo_aliases (alias_repo_id, canonical_repo_id, full_name) "
        "VALUES ('acme/hot-hidden', 'acme/hot-keep', 'acme/hot-hidden')",
    )
    _execute(
        database,
        "INSERT INTO github_repo_snapshots (repo_id, snapshot_date, captured_at, stars) VALUES "
        "('acme/hot-active', '2026-08-14', '2026-08-14T00:30:00+00:00', 900),"
        "('acme/hot-dead', '2026-08-14', '2026-08-14T00:30:00+00:00', 900),"
        "('acme/hot-hidden', '2026-08-14', '2026-08-14T00:30:00+00:00', 900),"
        "('acme/hot-keep', '2026-08-14', '2026-08-14T00:30:00+00:00', 900)",
    )

    items = repository.get_github_hot_repos("weekly", limit=20)
    names = {str(item.get("full_name")) for item in items}

    assert "acme/hot-active" in names
    assert "acme/hot-keep" in names
    assert "acme/hot-dead" not in names
    assert "acme/hot-hidden" not in names


@pytest.mark.parametrize("observed_node", ["R_conflict_old", "R_conflict_new"])
def test_rename_never_merges_distinct_known_nodes(postgres_ingestion, observed_node):
    repository, database = postgres_ingestion
    suffix = observed_node.rsplit("_", 1)[-1]
    old, new = f"acme/conflict-{suffix}-old", f"acme/conflict-{suffix}-new"
    _seed_candidate(repository, repo_id="R_conflict_old_" + suffix, full_name=old, stars=31000)
    _seed_candidate(repository, repo_id="R_conflict_new_" + suffix, full_name=new, stars=2600)
    _execute(database, "INSERT INTO github_repo_snapshots (repo_id,snapshot_date,captured_at,stars) VALUES (%s,'2026-08-13',%s,31000),(%s,'2026-08-13',%s,2600)", (old, _CHECKED_AT, new, _CHECKED_AT))

    written = repository.upsert_github_repo_metric_observations(
        [_observation(node_id=observed_node + "_" + suffix, requested_name=old, api_name=new, stars=32000)],
        checked_at=_CHECKED_AT,
    )

    assert written == 0
    rows = _fetchall(database, "SELECT repo_id,stars FROM github_repo_snapshots WHERE repo_id=ANY(%s) ORDER BY repo_id", ([old, new],))
    assert {r["repo_id"]: r["stars"] for r in rows} == {old: 31000, new: 2600}
    assert _fetchone(database, "SELECT COUNT(*) AS n FROM github_repo_candidates WHERE repo_id=ANY(%s)", ([old, new],))["n"] == 2


@pytest.mark.parametrize("writer", ["candidate", "ensure", "snapshot"])
def test_all_single_writers_reject_reused_name(postgres_ingestion, writer):
    repository, database = postgres_ingestion
    name = f"acme/reused-{writer}"
    _seed_candidate(repository, repo_id="R_original_" + writer, full_name=name, stars=31000)
    observation = _observation(node_id="R_impostor_" + writer, requested_name=name, api_name=name, stars=2600)
    method, payload = {
        "candidate": (repository.upsert_github_repo_candidate, observation["candidate"]),
        "ensure": (repository.ensure_github_repo_candidate, observation["candidate"]),
        "snapshot": (repository.insert_github_repo_snapshot, observation["snapshot"]),
    }[writer]

    with pytest.raises(ValueError, match="identity conflict"):
        method(payload)

    assert _fetchone(database, "SELECT stars FROM github_repo_candidates WHERE repo_id=%s", (name,))["stars"] == 31000
    assert _fetchone(database, "SELECT alias_repo_id FROM github_repo_aliases WHERE alias_repo_id=%s", ("R_impostor_" + writer,)) is None
    assert _fetchone(database, "SELECT repo_id FROM github_repo_snapshots WHERE repo_id=%s", (name,)) is None


def test_name_write_cannot_follow_alias_over_different_live_identity(postgres_ingestion):
    repository, database = postgres_ingestion
    old, new = "acme/reclaimed-name", "acme/other-project"
    _seed_candidate(repository, repo_id="R_reclaimed", full_name=old, stars=2600)
    _seed_candidate(repository, repo_id="R_other", full_name=new, stars=31000)
    _execute(database, "INSERT INTO github_repo_aliases (alias_repo_id,canonical_repo_id,full_name) VALUES (%s,%s,%s)", (old, new, old))

    repository.insert_github_repo_snapshot(_observation(node_id=old, requested_name=old, api_name=old, stars=2700)["snapshot"])

    assert _fetchone(database, "SELECT stars FROM github_repo_snapshots WHERE repo_id=%s", (old,))["stars"] == 2700
    assert _fetchone(database, "SELECT repo_id FROM github_repo_snapshots WHERE repo_id=%s", (new,)) is None


def test_batch_rejects_two_new_identities_claiming_the_same_name(postgres_ingestion):
    repository, database = postgres_ingestion
    name = "acme/conflicting-new-batch"
    observations = [_observation(node_id=node, requested_name=name, api_name=name, stars=stars)
                    for node, stars in (("R_batch_a", 31000), ("R_batch_b", 2600))]
    assert repository.upsert_github_repo_metric_observations(observations, checked_at=_CHECKED_AT) == 0
    assert _fetchone(database, "SELECT repo_id FROM github_repo_candidates WHERE full_name=%s", (name,)) is None


def test_concurrent_new_identities_cannot_bind_to_one_name(postgres_ingestion):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    repository, database = postgres_ingestion
    barrier = Barrier(2)
    name = "acme/concurrent-identities"

    def write(node):
        barrier.wait(timeout=5)
        try:
            _seed_candidate(repository, repo_id=node, full_name=name)
            return True
        except ValueError as exc:
            assert "identity conflict" in str(exc)
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(write, ["R_concurrent_a", "R_concurrent_b"])) == [False, True]
    assert _fetchone(database, "SELECT COUNT(*) AS n FROM github_repo_aliases WHERE canonical_repo_id=%s", (name,))["n"] == 1


def test_authoritative_observation_can_correct_stale_candidate_maxima(postgres_ingestion):
    repository, database = postgres_ingestion
    name = "acme/current-counts"
    _seed_candidate(repository, repo_id="R_counts", full_name=name, stars=31000)
    observation = _observation(node_id="R_counts", requested_name=name, api_name=name, stars=2600)
    repository.upsert_github_repo_metric_observations([observation], checked_at=_CHECKED_AT)
    assert _fetchone(database, "SELECT stars FROM github_repo_candidates WHERE repo_id=%s", (name,))["stars"] == 2600
    before = _fetchone(database, "SELECT stars,forks,watchers FROM github_repo_candidates WHERE repo_id=%s", (name,))
    repository.upsert_github_repo_candidate({
        **observation["candidate"], "stars": 40000, "forks": 4000, "watchers": 4000,
        "last_snapshot_at": "2026-08-01T00:00:00+00:00",
    })
    assert _fetchone(database, "SELECT stars,forks,watchers FROM github_repo_candidates WHERE repo_id=%s", (name,)) == before


def test_snapshot_corrects_creation_date_without_losing_precision(postgres_ingestion):
    repository, database = postgres_ingestion
    name = "acme/creation-correction"
    _seed_candidate(repository, repo_id="R_created", full_name=name)
    snapshot = _observation(node_id="R_created", requested_name=name, api_name=name, stars=500)["snapshot"]
    repository.insert_github_repo_snapshot({**snapshot, "repo_created_at": "2026-08-13"})
    repository.insert_github_repo_snapshot({**snapshot, "repo_created_at": "2024-08-04T12:15:06Z"})
    repository.insert_github_repo_snapshot({**snapshot, "repo_created_at": "2024-08-04"})
    assert _fetchone(database, "SELECT repo_created_at FROM github_repo_snapshots WHERE repo_id=%s", (name,))["repo_created_at"] == "2024-08-04T12:15:06Z"


def test_legacy_node_primary_key_rejects_a_different_node_without_aliases(postgres_ingestion):
    repository, database = postgres_ingestion
    name = "acme/legacy-node-identity"
    _seed_node_candidate(database, repo_id="R_legacy_primary", full_name=name, stars=31000)
    observation = _observation(node_id="R_legacy_replacement", requested_name=name, api_name=name, stars=2600)

    assert repository.upsert_github_repo_metric_observations([observation], checked_at=_CHECKED_AT) == 0
    assert _fetchone(database, "SELECT stars FROM github_repo_candidates WHERE repo_id='R_legacy_primary'")["stars"] == 31000
    assert _fetchone(database, "SELECT alias_repo_id FROM github_repo_aliases WHERE alias_repo_id='R_legacy_replacement'") is None


def test_legacy_numeric_alias_can_be_augmented_with_a_graphql_node(postgres_ingestion):
    repository, database = postgres_ingestion
    name = "acme/numeric-identity"
    _seed_candidate(repository, repo_id="123456789", full_name=name)
    observation = _observation(node_id="R_numeric_equivalent", requested_name=name, api_name=name, stars=600)

    assert repository.upsert_github_repo_metric_observations([observation], checked_at=_CHECKED_AT) == 1
    assert _fetchone(database, "SELECT stars FROM github_repo_candidates WHERE repo_id=%s", (name,))["stars"] == 600


def test_unverified_historical_name_cannot_write_into_another_repo(postgres_ingestion):
    repository, database = postgres_ingestion
    name = "acme/alias-target"
    _seed_candidate(repository, repo_id="R_alias_target", full_name=name)
    _execute(database, "INSERT INTO github_repo_aliases (alias_repo_id,canonical_repo_id,full_name) VALUES ('acme/alias-reused',%s,'acme/alias-reused')", (name,))
    with pytest.raises(ValueError, match="unverified name alias"):
        _seed_candidate(repository, repo_id="acme/alias-reused", full_name="acme/alias-reused", stars=9000)
    assert _fetchone(database, "SELECT stars FROM github_repo_candidates WHERE repo_id=%s", (name,))["stars"] == 500


def test_identity_repair_dry_run_backup_and_stale_plan(postgres_ingestion, tmp_path):
    from scripts.apply_github_identity_repair import apply_plan

    repository, database = postgres_ingestion
    name = "acme/repair-manifest"
    _seed_candidate(repository, repo_id="R_manifest", full_name=name, stars=31000)
    target = _fetchone(database, "SELECT current_database() AS database,current_schema() AS schema")
    plan = {"target": target, "operations": [{
        "table": "github_repo_candidates", "key": {"repo_id": name},
        "before": {"stars": 31000}, "after": {"stars": 2600},
    }]}
    backup = tmp_path / "before.json"
    assert not apply_plan(database, plan, backup=backup)["applied"]
    assert not backup.exists()
    assert _fetchone(database, "SELECT stars FROM github_repo_candidates WHERE repo_id=%s", (name,))["stars"] == 31000
    assert apply_plan(database, plan, apply=True, backup=backup)["applied"]
    import json
    assert json.loads(backup.read_text())["preimages"][0]["row"]["stars"] == 31000
    with pytest.raises(ValueError, match="preimage changed"):
        apply_plan(database, plan, apply=True, backup=tmp_path / "stale.json")
    assert not (tmp_path / "stale.json").exists()
    assert _fetchone(database, "SELECT stars FROM github_repo_candidates WHERE repo_id=%s", (name,))["stars"] == 2600


def test_identity_repair_rolls_back_and_refuses_wrong_database(postgres_ingestion, tmp_path):
    from scripts.apply_github_identity_repair import apply_plan

    repository, database = postgres_ingestion
    name = "acme/repair-rollback"
    _seed_candidate(repository, repo_id="R_rollback", full_name=name)
    target = _fetchone(database, "SELECT current_database() AS database,current_schema() AS schema")
    operations = [
        {"table": "github_repo_candidates", "key": {"repo_id": name}, "before": {"stars": 500}, "after": {"stars": 400}},
        {"table": "github_repo_aliases", "key": {"alias_repo_id": "R_missing_parent"}, "before": None,
         "after": {"canonical_repo_id": "acme/not-a-parent", "full_name": "acme/not-a-parent"}},
    ]
    with pytest.raises(ValueError, match="target"):
        apply_plan(database, {"target": {**target, "database": "wrong"}, "operations": operations}, apply=True, backup=tmp_path / "wrong.json")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        apply_plan(database, {"target": target, "operations": operations}, apply=True, backup=tmp_path / "rollback.json")
    assert _fetchone(database, "SELECT stars FROM github_repo_candidates WHERE repo_id=%s", (name,))["stars"] == 500


def test_identity_audit_finds_conflicting_aliases_without_writing(postgres_ingestion):
    from scripts.audit_github_identity_pollution import audit

    repository, database = postgres_ingestion
    source, target = "acme/audit-source", "acme/audit-target"
    _seed_candidate(repository, repo_id="R_audit_source", full_name=source)
    _seed_candidate(repository, repo_id="R_audit_target", full_name=target)
    _execute(database, "INSERT INTO github_repo_aliases (alias_repo_id,canonical_repo_id,full_name) VALUES (%s,%s,%s)", (source, target, source))
    report = audit(database, since="2026-01-01")
    assert any(row["alias_repo_id"] == source and row["canonical_repo_id"] == target for row in report["name_collisions"])
    assert _fetchone(database, "SELECT canonical_repo_id FROM github_repo_aliases WHERE alias_repo_id=%s", (source,))["canonical_repo_id"] == target
