from __future__ import annotations

import os
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo

import pytest

from backend.tests.postgres_test_safety import postgres_test_sandbox

_TESTS_DIR = Path(__file__).resolve().parent
_IMPORT_CWD = Path.cwd()
os.chdir(_TESTS_DIR)
try:
    psycopg = pytest.importorskip("psycopg")
    pytest.importorskip("psycopg_pool")

    from backend.app.core.config import settings
    from backend.app.repositories.postgres_document_repository import (
        PostgresDocumentRepository,
    )
    from backend.app.repositories.postgres_ingestion_task_repository import (
        PostgresIngestionTaskRepository,
    )
    from backend.app.repositories.postgres_project_enrichment_repository import (
        PostgresGitHubProjectEnrichmentRepository,
    )
    from backend.app.repositories.postgres_project_ingestion_repository import (
        PostgresGitHubProjectIngestionRepository,
    )
    from backend.app.repositories.postgres_rank_snapshot_repository import (
        PostgresRankSnapshotRepository,
    )
finally:
    os.chdir(_IMPORT_CWD)


@pytest.fixture(scope="module")
def database() -> Iterator[Any]:
    with postgres_test_sandbox() as sandbox:
        database = sandbox.database
        yield database


@pytest.fixture(scope="module")
def repositories(database: Any) -> Iterator[tuple[Any, Any, Any, Any]]:
    yield (
        PostgresDocumentRepository(database),
        PostgresIngestionTaskRepository(database),
        PostgresRankSnapshotRepository(database),
        PostgresGitHubProjectIngestionRepository(database),
    )


# get_today_document_count uses the UTC+8 calendar day of created_at; pin the
# fixture to UTC+8 noon so the assertion stays true regardless of the run date.
_CREATED_AT_TODAY = (
    datetime.now(timezone(timedelta(hours=8))).replace(hour=12, minute=0, second=0, microsecond=0).isoformat()
)


def _document(doc_id: str, **overrides: Any) -> dict[str, Any]:
    document = {
        "id": doc_id,
        "source": "arxiv",
        "source_channel": "huggingface_daily_html",
        "title": f"Agent paper {doc_id}",
        "url": f"https://example.test/{doc_id}",
        "summary": "Agent orchestration and RAG",
        "published_date": "2026-07-28",
        "tags": ["Agent", "RAG"],
        "score": 2.0,
        "raw_score": 3.0,
        "rank_in_period": 5,
        "indexed": 1,
        "in_daily": 1,
        "created_at": _CREATED_AT_TODAY,
    }
    document.update(overrides)
    return document


def test_real_postgres_document_upsert_search_feeds_and_stats(repositories) -> None:
    documents, _, _, _ = repositories
    documents.upsert_document(_document("doc-b", raw_score=4.0, rank_in_period=3))
    documents.upsert_document(_document("doc-a", raw_score=4.0, rank_in_period=2))
    documents.upsert_document(
        _document(
            "doc-a",
            published_date="",
            summary="Updated Agent summary",
            raw_score=1.0,
            rank_in_period=9,
            indexed=0,
            in_daily=0,
            in_weekly=1,
        )
    )

    detail = documents.get_paper_detail("doc-a")
    assert detail is not None
    assert detail["published_date"] == "2026-07-28"
    assert detail["raw_score"] == 4.0
    assert detail["rank_in_period"] == 2
    projected = {row["id"]: row for row in documents.get_latest_documents()}
    assert projected["doc-a"]["indexed"] is False
    assert projected["doc-a"]["in_daily"] is True
    assert projected["doc-a"]["in_weekly"] is True
    assert documents.search_document_page("agent", page=1, page_size=1) == {
        "items": [detail],
        "total": 2,
        "page": 1,
        "page_size": 1,
    }
    assert {row["id"] for row in documents.get_top_documents()} == {"doc-a", "doc-b"}
    assert documents.get_document_count() == 2
    assert documents.get_source_counts() == {"arxiv": 2}
    summaries = documents.get_existing_document_summaries(ids=["doc-a"], urls=["missing"])
    assert summaries["id:doc-a"] == "Updated Agent summary"
    assert documents.get_today_document_count() == 2


def test_real_postgres_tasks_preserve_order_pagination_and_clear(repositories) -> None:
    _, tasks, _, _ = repositories
    first = tasks.create_task("first")
    second = tasks.create_task("second")
    tasks.finish_task(first, status="failed", error_msg="boom", item_count=3)

    assert tasks.get_latest_task()["id"] == second
    assert [row["id"] for row in tasks.get_recent_tasks(2)] == [second, first]
    page = tasks.list_tasks(page=2, page_size=1)
    assert page["total"] == 2
    assert [row["id"] for row in page["items"]] == [first]
    assert page["items"][0]["error_msg"] == "boom"
    assert tasks.clear_all_tasks() == 2


def test_restart_reconciles_only_previous_running_tasks_and_terminal_rows_are_stable(repositories):
    _, tasks, _, _ = repositories
    old = tasks.create_task("interrupted-old")
    complete = tasks.create_task("already-complete")
    tasks.finish_task(complete, item_count=4)
    cutoff = datetime.now(timezone.utc).isoformat()
    current = tasks.create_task("new-process")
    try:
        assert tasks.interrupt_running_tasks(started_before=cutoff) == 1
        assert tasks.get_task(old)["status"] == "failed"
        assert "restarted" in tasks.get_task(old)["error_msg"]
        assert tasks.get_task(current)["status"] == "running"
        tasks.finish_task(complete, status="failed", error_msg="late cancellation")
        assert tasks.get_task(complete)["status"] == "success"
        assert tasks.get_task(complete)["item_count"] == 4
        assert tasks.interrupt_running_tasks(started_before=cutoff) == 0
    finally:
        with tasks._database.transaction() as connection:
            connection.execute("DELETE FROM ingestion_tasks WHERE id=ANY(%s)", ([old, complete, current],))


def test_real_postgres_snapshots_sync_filter_order_and_delete(repositories) -> None:
    documents, _, snapshots, _ = repositories
    documents.upsert_document(_document("github-one", source="github", rank_in_period=10))
    snapshots.upsert_rank_snapshot("doc-a", "2026-07-28", "huggingface_daily_html", 2, 3.0, 2.0)
    snapshots.upsert_rank_snapshot("doc-a", "2026-07-28", "huggingface_weekly_html", 1, 8.0, 7.0)
    snapshots.upsert_rank_snapshot("doc-a", "2026-07-28", "huggingface_daily_html", 5, 1.0, 1.0)
    snapshots.upsert_rank_snapshot("github-one", "2026-07-28", "github_trending_daily", 1, 4.0, 4.0)

    rows = snapshots.get_snapshot_documents("2026-07-28")
    assert [row["id"] for row in rows] == ["github-one", "doc-a", "doc-a"]
    arxiv_rows = [row for row in rows if row["id"] == "doc-a"]
    assert {(row["raw_score"], row["score"]) for row in arxiv_rows} == {(8.0, 7.0)}
    assert snapshots.get_snapshot_dates(source="arxiv", period="daily") == ["2026-07-28"]
    assert snapshots.get_snapshot_source_counts("2026-07-28") == {"arxiv": 1, "github": 1}
    assert snapshots.get_snapshot_doc_ids("2026-07-28", "huggingface_daily_html") == {"doc-a"}
    assert snapshots.delete_snapshots_by_channel("2026-07-28", "huggingface_weekly_html") == 1


def test_real_postgres_replace_channel_snapshots_is_atomic_and_syncs_scores(repositories) -> None:
    documents, _, snapshots, _ = repositories
    documents.upsert_document(_document("doc-r1"))
    documents.upsert_document(_document("doc-r2"))
    snapshots.upsert_rank_snapshot("doc-r1", "2026-08-08", "huggingface_daily_html", 5, 1.0, 1.0)
    snapshots.upsert_rank_snapshot("doc-stale", "2026-08-08", "huggingface_daily_html", 9, 0.5, 0.5)
    snapshots.upsert_rank_snapshot("doc-r2", "2026-08-08", "huggingface_weekly_html", 3, 6.0, 5.0)

    written = snapshots.replace_channel_snapshots(
        "2026-08-08",
        "huggingface_daily_html",
        [
            {"doc_id": "doc-r1", "rank_in_period": 1, "raw_score": 9.0, "score": 8.0},
            {"doc_id": "doc-r2", "rank_in_period": 2, "raw_score": 7.0, "score": 7.0},
        ],
    )

    assert written == 2
    daily_ids = snapshots.get_snapshot_doc_ids("2026-08-08", "huggingface_daily_html")
    assert daily_ids == {"doc-r1", "doc-r2"}
    rows = snapshots.get_snapshot_documents("2026-08-08")
    weekly = [row for row in rows if row["source_channel"] == "huggingface_weekly_html"]
    # 跨 channel 分数同步：doc-r2 的 weekly 行继承该 doc 当日最高分
    # （max(daily 7.0, weekly 6.0)，与逐行 upsert 的同步口径一致）
    assert {(row["raw_score"], row["score"]) for row in weekly} == {(7.0, 7.0)}

    written_empty = snapshots.replace_channel_snapshots("2026-08-09", "huggingface_daily_html", [])
    assert written_empty == 0


def test_real_postgres_clear_all_documents_removes_orphan_snapshots(repositories) -> None:
    documents, _, snapshots, _ = repositories
    documents.upsert_document(_document("doc-clear"))
    snapshots.upsert_rank_snapshot("doc-clear", "2026-08-08", "huggingface_daily_html", 1, 5.0, 5.0)

    # 模块级共享 schema 内还有前序用例遗留的文档，只断言清空语义不断言精确条数
    assert documents.clear_all_documents() >= 1

    assert documents.get_document_count() == 0
    assert snapshots.get_snapshot_doc_ids("2026-08-08") == set()


def test_real_postgres_snapshot_read_projects_translation_zh(repositories) -> None:
    documents, _, snapshots, _ = repositories
    documents.upsert_document(
        _document(
            "doc-x-zh",
            source="x",
            source_channel="x_daily_watchlist",
            translation_zh="中文译文",
            # published_at 为空的 X 行会回退 created_at 进入近期窗口；
            # 钉到窗口外，避免污染同模块共享 schema 下的窗口/排序用例
            created_at="2026-07-29T01:00:00+00:00",
        )
    )
    snapshots.upsert_rank_snapshot("doc-x-zh", "2026-07-29", "x_daily_watchlist", 1, 9.0, 9.0)

    rows = snapshots.get_snapshot_documents("2026-07-29", source_channel="x_daily_watchlist")

    assert len(rows) == 1
    assert rows[0]["translation_zh"] == "中文译文"


def test_real_postgres_list_recent_by_source_supports_non_x_published_date(repositories) -> None:
    documents, _, _, _ = repositories
    documents.upsert_document(
        _document(
            "doc-news-new",
            source="news",
            source_channel="tech_news",
            published_date="2026-08-07",
            created_at="2026-08-07T02:00:00+00:00",
        )
    )
    documents.upsert_document(
        _document(
            "doc-news-old",
            source="news",
            source_channel="tech_news",
            published_date="2026-08-05",
            created_at="2026-08-05T02:00:00+00:00",
        )
    )
    documents.upsert_document(
        _document(
            "doc-news-mid",
            source="news",
            source_channel="tech_news",
            published_date="2026-08-06",
            created_at="2026-08-06T09:00:00+00:00",
        )
    )
    rows = documents.list_recent_by_source("news", since_iso="2026-08-06T00:00:00+00:00", limit=10)
    # 非 X 源（published_at 恒空）：new 经 published_date 键进窗，mid 的
    # date-only 键在边界日词法偏严、经 created_at 兜底进窗；按业务时间链倒序
    assert [row["id"] for row in rows] == ["doc-news-new", "doc-news-mid"]


def test_real_postgres_list_recent_by_source_covers_restamped_trending_rows(repositories) -> None:
    documents, _, _, _ = repositories
    # github 榜单源语义：published_date 每日上榜刷新、created_at 保留首次入池。
    # 重上榜老仓必须随「近 N 小时上榜」窗口回窗，而不是被首次入池时间卡住。
    documents.upsert_document(
        _document(
            "doc-gh-retrend",
            source="github",
            source_channel="github_trending_daily",
            published_date="2026-08-17",
            created_at="2026-07-05T02:00:00+00:00",
        )
    )
    documents.upsert_document(
        _document(
            "doc-gh-stale",
            source="github",
            source_channel="github_trending_daily",
            published_date="2026-08-10",
            created_at="2026-06-01T02:00:00+00:00",
        )
    )
    rows = documents.list_recent_by_source(
        "github",
        since_iso="2026-08-16T00:00:00+00:00",
        limit=10,
    )
    assert [row["id"] for row in rows] == ["doc-gh-retrend"]


def test_real_postgres_list_recent_by_source_filters_window_and_orders(repositories) -> None:
    documents, _, _, _ = repositories
    # X 行钉死 created_at ≈ published_at（生产上首次入池时间贴近推文时间），
    # 让窗口断言只表达 published_at 语义；created_at 兜底进窗由 news/github
    # 用例覆盖
    documents.upsert_document(
        _document(
            "doc-x-new",
            source="x",
            source_channel="x_daily_watchlist",
            published_at="2026-08-07T01:30:00+00:00",
            created_at="2026-08-07T01:30:00+00:00",
            media='[{"type": "photo", "url": "https://pbs.twimg.com/a.jpg"}]',
        )
    )
    documents.upsert_document(
        _document(
            "doc-x-old",
            source="x",
            source_channel="x_daily_watchlist",
            published_at="2026-08-06T20:00:00+00:00",
            created_at="2026-08-06T20:00:00+00:00",
        )
    )
    documents.upsert_document(
        _document(
            "doc-x-stale",
            source="x",
            source_channel="x_daily_watchlist",
            published_at="2026-08-05T12:00:00+00:00",
            created_at="2026-08-05T12:00:00+00:00",
        )
    )
    # 其他源不受影响
    documents.upsert_document(_document("doc-arxiv", published_at="2026-08-07T01:00:00+00:00"))

    rows = documents.list_recent_by_source("x", since_iso="2026-08-06T18:00:00+00:00", limit=10)

    # 词法过滤掉窗口外旧推文；按 published_at 新到旧
    assert [row["id"] for row in rows] == ["doc-x-new", "doc-x-old"]
    # media JSON 串反序列化为列表
    assert rows[0]["media"] == [{"type": "photo", "url": "https://pbs.twimg.com/a.jpg"}]

    # until_iso 下推 SQL：上限词法过滤掉窗口外新推文（days_back 回移窗口的语义）
    bounded = documents.list_recent_by_source(
        "x",
        since_iso="2026-08-05T00:00:00+00:00",
        until_iso="2026-08-06T23:59:59+00:00",
        limit=10,
    )
    assert [row["id"] for row in bounded] == ["doc-x-old", "doc-x-stale"]


def test_real_postgres_today_count_github_uses_enriched_library_entries(
    repositories,
    database,
) -> None:
    documents, _, _, project_ingestion = repositories
    enrichments = PostgresGitHubProjectEnrichmentRepository(database)
    # github 源 documents 行（created_at 当日）不计入今日更新；候选池
    # first_seen_at 当日但未富化成功的项目也不计。今日更新中的 github
    # 部分只计 github_repo_enrichments 当日 enriched_at 且
    # status='succeeded' 的入库项目。
    baseline = documents.get_today_document_count()
    documents.upsert_document(
        _document(
            "doc-gh-today",
            source="github",
            source_channel="github_trending_daily",
        )
    )
    project_ingestion.upsert_github_repo_candidate(
        {
            "repo_id": "it-today-candidate-only",
            "full_name": "it/today-candidate-only",
            "url": "https://github.com/it/today-candidate-only",
            "first_seen_at": _CREATED_AT_TODAY,
        }
    )
    project_ingestion.upsert_github_repo_candidate(
        {
            "repo_id": "it-today-enriched-repo",
            "full_name": "it/today-enriched-repo",
            "url": "https://github.com/it/today-enriched-repo",
            "first_seen_at": _CREATED_AT_TODAY,
        }
    )
    project_ingestion.upsert_github_repo_candidate(
        {
            "repo_id": "it-old-enriched-repo",
            "full_name": "it/old-enriched-repo",
            "url": "https://github.com/it/old-enriched-repo",
            "first_seen_at": "2026-01-01T00:00:00+00:00",
        }
    )
    project_ingestion.upsert_github_repo_candidate(
        {
            "repo_id": "it-today-failed-repo",
            "full_name": "it/today-failed-repo",
            "url": "https://github.com/it/today-failed-repo",
            "first_seen_at": _CREATED_AT_TODAY,
        }
    )

    def _enrichment(repo_id: str, **overrides: Any) -> dict[str, Any]:
        payload = {
            "repo_id": repo_id,
            "category_slug": "agent",
            "category_name": "Agent",
            "description_zh": "测试项目",
            "source_fingerprint": "f" * 64,
            "prompt_version": "it-v1",
            "status": "succeeded",
            "enriched_at": _CREATED_AT_TODAY,
        }
        payload.update(overrides)
        return payload

    # 当日富化成功：计 +1
    enrichments.upsert_github_repo_enrichment(_enrichment("it-today-enriched-repo"))
    # 历史锚点的成功富化：不计
    enrichments.upsert_github_repo_enrichment(
        _enrichment(
            "it-old-enriched-repo",
            enriched_at="2026-01-01T00:00:00+00:00",
        )
    )
    # 当日富化失败：不计
    enrichments.upsert_github_repo_enrichment(_enrichment("it-today-failed-repo", status="failed"))

    # 只 +1（当日富化成功的入库项目）；github documents 行、纯候选、
    # 历史锚点与失败行均不计入。
    assert documents.get_today_document_count() == baseline + 1


def test_real_postgres_today_count_uses_scheduler_timezone_day(
    repositories,
    database,
) -> None:
    documents, _, _, project_ingestion = repositories
    enrichments = PostgresGitHubProjectEnrichmentRepository(database)
    # 「今日」= scheduler_timezone 自然日：今日凌晨（UTC 仍昨日）入库即计入；
    # 昨日深夜与明日凌晨的边界行均不计。
    zone = ZoneInfo(getattr(settings, "scheduler_timezone", "Asia/Shanghai") or "Asia/Shanghai")
    today = datetime.now(zone).date()

    def _at(day: Any, hour: int, minute: int) -> str:
        return datetime.combine(day, time(hour, minute)).replace(tzinfo=zone).isoformat()

    baseline = documents.get_today_document_count()
    documents.upsert_document(_document("doc-day-early", created_at=_at(today, 0, 30)))
    documents.upsert_document(
        _document(
            "doc-day-yesterday",
            created_at=_at(today - timedelta(days=1), 23, 30),
        )
    )
    documents.upsert_document(
        _document(
            "doc-day-tomorrow",
            created_at=_at(today + timedelta(days=1), 0, 30),
        )
    )
    project_ingestion.upsert_github_repo_candidate(
        {
            "repo_id": "it-day-early-repo",
            "full_name": "it/day-early-repo",
            "url": "https://github.com/it/day-early-repo",
            "first_seen_at": _at(today, 0, 30),
        }
    )
    enrichments.upsert_github_repo_enrichment(
        {
            "repo_id": "it-day-early-repo",
            "category_slug": "agent",
            "category_name": "Agent",
            "description_zh": "测试项目",
            "source_fingerprint": "e" * 64,
            "prompt_version": "it-v1",
            "status": "succeeded",
            "enriched_at": _at(today, 0, 30),
        }
    )

    # +2：今日凌晨的文档与富化入库各一；昨日/明日边界行不计。
    assert documents.get_today_document_count() == baseline + 2
