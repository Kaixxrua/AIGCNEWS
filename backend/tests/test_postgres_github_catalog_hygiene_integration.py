from __future__ import annotations

from typing import Any

from backend.app.repositories.postgres_github_logo_repository import PostgresGitHubLogoRepository
from backend.app.repositories.postgres_github_project_peek import PostgresGitHubProjectPeekRepository
from backend.app.repositories.postgres_project_catalog import PostgresProjectCatalogRepository
from backend.app.repositories.postgres_project_ingestion_repository import (
    PostgresGitHubProjectIngestionRepository,
)
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


# 疑似诱饵隔离名单夹具：(repo_id, created_at, availability_status, 是否富化成功)。
_QUARANTINE_CANDIDATES = [
    ("surge/lure", "2026-10-02T12:04:01Z", "active", True),
    ("surge/other-signals", "2026-01-05T00:00:00Z", "active", True),
    ("surge/coordinated-mild", "2026-10-02T12:06:00Z", "active", True),
    # 同名批次：早年原版保留；第一个被删副本建仓当天起的那一批整体隔离
    ("orig/camtasia-studio", "2025-01-01T00:00:00Z", "active", True),
    ("w1/camtasia-studio", "2026-09-20T08:00:00Z", "not_found", True),
    ("w2/Camtasia-Studio", "2026-09-21T08:00:00Z", "not_found", False),
    ("w3/camtasia-studio", "2026-09-22T08:00:00Z", "active", True),
    # 改名留下的别名行（指向原版）：不算进同名批次
    ("z/camtasia-studio", "2026-09-23T08:00:00Z", "not_found", False),
    # 合法同名：被删的不到一半 / 只删了一个 / 账号不足三个
    ("a/mcp", "2024-01-01T00:00:00Z", "active", True),
    ("b/mcp", "2025-05-01T00:00:00Z", "not_found", False),
    ("c/mcp", "2025-06-01T00:00:00Z", "active", True),
    ("d/mcp", "2025-07-01T00:00:00Z", "active", False),
    ("e/mcp", "2025-08-01T00:00:00Z", "active", False),
    ("f/mcp", "2025-09-01T00:00:00Z", "not_found", False),
    ("x1/tool", "2026-01-01T00:00:00Z", "not_found", False),
    ("x2/tool", "2026-02-01T00:00:00Z", "active", True),
    ("x3/tool", "2026-03-01T00:00:00Z", "active", False),
    ("y1/dup", "2026-01-01T00:00:00Z", "not_found", False),
    ("y2/dup", "2026-02-01T00:00:00Z", "not_found", False),
]

# (repo_id, 刷星嫌疑分, 信号)：指标日 2026-10-02，均为正增长、可上热榜。
_QUARANTINE_METRICS = [
    ("surge/lure", 0.9, '["coordinated_creation", "low_fork_follow"]'),
    ("surge/other-signals", 0.9, '["low_fork_follow", "spike_from_zero_baseline"]'),
    ("surge/coordinated-mild", 0.6, '["coordinated_creation"]'),
    # 同时命中两条规则时只记刷星
    ("w3/camtasia-studio", 0.85, '["coordinated_creation", "spike_from_zero_baseline"]'),
    ("orig/camtasia-studio", 0.0, "[]"),
]


def seed_quarantine_catalog(db: Any) -> None:
    """写入隔离名单规则夹具（Go 侧真库核对也复用这份夹具）。"""
    with db.transaction() as connection:
        for repo_id, created_at, availability, enriched in _QUARANTINE_CANDIDATES:
            connection.execute(
                "INSERT INTO github_repo_candidates"
                " (repo_id, full_name, title, url, stars, created_at, availability_status)"
                " VALUES (%s, %s, %s, %s, 2000, %s, %s)",
                (repo_id, repo_id, repo_id.split("/")[1], f"https://github.com/{repo_id}",
                 created_at, availability),
            )
            if enriched:
                connection.execute(
                    "INSERT INTO github_repo_enrichments"
                    " (repo_id, category_slug, category_name, description_zh,"
                    "  tags_json, source_fingerprint, prompt_version, status)"
                    " VALUES (%s, 'other', 'Other', '夹具', '[]', 'test', 'v1', 'succeeded')",
                    (repo_id,),
                )
        connection.execute(
            "INSERT INTO github_repo_aliases (alias_repo_id, canonical_repo_id, full_name)"
            " VALUES ('z/camtasia-studio', 'orig/camtasia-studio', 'z/camtasia-studio')"
        )
        for repo_id, score, signals in _QUARANTINE_METRICS:
            connection.execute(
                "INSERT INTO github_repo_daily_metrics"
                " (repo_id, metric_date, stars, daily_star_growth, daily_growth_available,"
                "  hot_score, growth_suspicion_score, growth_suspicion_signals)"
                " VALUES (%s, '2026-10-02', 2000, 300, TRUE, 50, %s, %s)",
                (repo_id, score, signals),
            )


def _quarantine(db: Any) -> dict[str, str]:
    with db.transaction() as connection:
        rows = connection.execute("SELECT repo_id, reason FROM github_repo_quarantine").fetchall()
    return {row["repo_id"]: row["reason"] for row in rows}


def test_quarantine_refresh_applies_both_rules_and_keeps_originals():
    with postgres_test_sandbox() as sandbox:
        db = sandbox.database
        seed_quarantine_catalog(db)
        ingestion = PostgresGitHubProjectIngestionRepository(db)

        assert ingestion.refresh_github_quarantine() == {"quarantined": 4, "added": 4, "released": 0}
        assert _quarantine(db) == {
            "surge/lure": "coordinated_surge",
            "w3/camtasia-studio": "coordinated_surge",
            "w1/camtasia-studio": "name_reuse",
            "w2/Camtasia-Studio": "name_reuse",
        }
        # 名单不变时重算是空操作
        assert ingestion.refresh_github_quarantine() == {"quarantined": 4, "added": 0, "released": 0}

        catalog = PostgresProjectCatalogRepository(db)
        listed = {item["repo_id"] for item in catalog.list_projects(source="github", page_size=100)["items"]}
        assert listed == {
            "surge/other-signals", "surge/coordinated-mild", "orig/camtasia-studio",
            "a/mcp", "c/mcp", "x2/tool",
        }
        assert catalog.count_github_catalog_candidates() == 6
        hot = [row["repo_id"] for row in catalog.list_github_hot_for_date(metric_date="2026-10-02", limit=10)]
        assert sorted(hot) == ["orig/camtasia-studio", "surge/coordinated-mild", "surge/other-signals"]
        assert catalog.find_lexical_candidate_repo_ids(q="camtasia") == ["orig/camtasia-studio"]
        assert catalog.find_repo_ids_by_name_segment(name="camtasia-studio") == ["orig/camtasia-studio"]
        peek = PostgresGitHubProjectPeekRepository(db)
        assert peek.peek_source("w3/camtasia-studio") is None
        assert peek.peek_source("orig/camtasia-studio") is not None

        # 刷星信号消失 → 放出；同名批次仍成立 → 理由改记同名
        with db.transaction() as connection:
            connection.execute(
                "UPDATE github_repo_daily_metrics SET growth_suspicion_signals = '[\"low_fork_follow\"]'"
                " WHERE repo_id = 'surge/lure'"
            )
            connection.execute("DELETE FROM github_repo_daily_metrics WHERE repo_id = 'w3/camtasia-studio'")
        assert ingestion.refresh_github_quarantine() == {"quarantined": 3, "added": 0, "released": 1}
        assert _quarantine(db) == {
            "w1/camtasia-studio": "name_reuse",
            "w2/Camtasia-Studio": "name_reuse",
            "w3/camtasia-studio": "name_reuse",
        }

        # 被删副本恢复到只剩一个：同名规则不再成立，整批放出、重新公开
        # （别名行 z/camtasia-studio 也是 not_found，若被算进来批次会仍然成立）
        with db.transaction() as connection:
            connection.execute(
                "UPDATE github_repo_candidates SET availability_status = 'active'"
                " WHERE repo_id = 'w2/Camtasia-Studio'"
            )
        assert ingestion.refresh_github_quarantine() == {"quarantined": 0, "added": 0, "released": 3}
        assert _quarantine(db) == {}
        assert catalog.find_repo_ids_by_name_segment(name="camtasia-studio", limit=10) == [
            "orig/camtasia-studio", "w2/Camtasia-Studio", "w3/camtasia-studio",
        ]
        listed = {item["repo_id"] for item in catalog.list_projects(source="github", page_size=100)["items"]}
        assert {"w1/camtasia-studio", "w3/camtasia-studio"} <= listed
