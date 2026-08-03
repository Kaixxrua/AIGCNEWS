from __future__ import annotations

import contextlib

import pytest

from backend.app.repositories.postgres_project_enrichment_repository import (
    _github_fingerprint,
)
from scripts import enrich_github_projects_run as enrich_run


class FakeCursor:
    def __init__(self, results: list) -> None:
        self._results = list(results)
        self.calls: list[tuple[str, tuple]] = []
        self._current = []

    def execute(self, sql, params=()) -> None:
        self.calls.append((sql, tuple(params)))
        self._current = self._results.pop(0)

    def fetchall(self):
        return self._current

    def fetchone(self):
        return self._current[0]


class FakeDB:
    def __init__(self, results: list) -> None:
        self.fake_cursor = FakeCursor(results)

    @contextlib.contextmanager
    def transaction(self):
        yield self

    @contextlib.contextmanager
    def cursor(self):
        yield self.fake_cursor


def _candidate_row(repo_id: str = "a/b") -> dict:
    return {
        "repo_id": repo_id,
        "full_name": repo_id,
        "title": repo_id,
        "url": f"https://github.com/{repo_id}",
        "description": "demo",
        "language": "Python",
        "topics_json": '["llm"]',
        "created_at": "2025-02-01",
        "pushed_at": "2026-01-01",
        "source_channels": "chan",
        "first_seen_at": "2026-08-03T06:40:00+00:00",
        "last_seen_at": "2026-08-03T06:40:00+00:00",
        "last_snapshot_at": "2026-08-03T06:40:00+00:00",
        "stars": 800,
        "forks": 5,
        "watchers": 800,
    }


def test_parse_iso_accepts_valid_and_rejects_invalid() -> None:
    assert (
        enrich_run.parse_iso("2026-08-03T06:30:00+00:00")
        == "2026-08-03T06:30:00+00:00"
    )
    with pytest.raises(SystemExit):
        enrich_run.parse_iso("not-a-date")


def test_count_run_candidates_scopes_params() -> None:
    db = FakeDB([[{"n": 7}]])
    total = enrich_run.count_run_candidates(
        db, channel="chan", first_seen_after="2026-08-03T00:00:00+00:00", min_stars=500
    )
    assert total == 7
    sql, params = db.fake_cursor.calls[0]
    assert params == ("%chan%", "2026-08-03T00:00:00+00:00", 500)
    assert "first_seen_at >=" in sql
    assert "NOT EXISTS" in sql
    assert "github_repo_enrichments" in sql
    assert "succeeded" in sql


def test_list_run_candidates_keyset_pagination_and_normalization() -> None:
    db = FakeDB([[_candidate_row()]])
    rows = enrich_run.list_run_candidates(
        db,
        channel="chan",
        first_seen_after="2026-08-03T00:00:00+00:00",
        min_stars=500,
        after_repo_id="a/a",
        limit=50,
    )
    sql, params = db.fake_cursor.calls[0]
    assert params == ("%chan%", "2026-08-03T00:00:00+00:00", 500, "a/a", 50)
    assert "c.repo_id > %s" in sql
    assert "ORDER BY c.repo_id" in sql

    assert len(rows) == 1
    row = rows[0]
    assert row["repo_id"] == "a/b"
    assert row["topics"] == ["llm"]
    assert row["stars"] == 800
    assert row["source_fingerprint"] == _github_fingerprint(
        {
            "full_name": "a/b",
            "description": "demo",
            "language": "Python",
            "topics_json": '["llm"]',
        }
    )


class _ExplodingEnricher:
    def __init__(self, *args, **kwargs) -> None:
        raise AssertionError("dry-run 不得实例化 LLM 富化器")


class _RecordingEnricher:
    def __init__(self, db) -> None:
        self.db = db
        self.seen: list[str] = []

    def _enrich_and_store(self, repo) -> bool:
        repo_id = str(repo.get("repo_id"))
        self.seen.append(repo_id)
        return repo_id != "bad/repo"


def _patch_repository(monkeypatch, db) -> None:
    class FakeRepository:
        def __init__(self, database) -> None:
            self._database = db

    monkeypatch.setattr(enrich_run, "PostgresGitHubProjectEnrichmentRepository", FakeRepository)


def test_main_dry_run_never_constructs_enricher(monkeypatch, capsys) -> None:
    db = FakeDB([[{"n": 3}]])
    _patch_repository(monkeypatch, db)
    monkeypatch.setattr(enrich_run, "GitHubProjectEnricher", _ExplodingEnricher)

    assert enrich_run.main([
        "--channel", "chan",
        "--first-seen-after", "2026-08-03T00:00:00+00:00",
        "--dry-run",
    ]) == 0
    out = capsys.readouterr().out
    assert '"pending": 3' in out
    assert '"status": "dry_run"' in out


def test_main_enriches_scoped_rows_respecting_max_total(monkeypatch) -> None:
    db = FakeDB([
        [{"n": 2}],
        [_candidate_row("good/repo"), _candidate_row("bad/repo")],
    ])
    _patch_repository(monkeypatch, db)
    enricher = _RecordingEnricher(db)
    monkeypatch.setattr(
        enrich_run, "GitHubProjectEnricher", lambda db: enricher
    )

    assert enrich_run.main([
        "--channel", "chan",
        "--first-seen-after", "2026-08-03T00:00:00+00:00",
        "--max-total", "2",
        "--concurrency", "1",
    ]) == 0
    assert sorted(enricher.seen) == ["bad/repo", "good/repo"]


def test_main_stops_when_scope_exhausted(monkeypatch) -> None:
    db = FakeDB([
        [{"n": 5}],
        [_candidate_row("good/repo")],
        [],
    ])
    _patch_repository(monkeypatch, db)
    enricher = _RecordingEnricher(db)
    monkeypatch.setattr(
        enrich_run, "GitHubProjectEnricher", lambda db: enricher
    )

    assert enrich_run.main([
        "--channel", "chan",
        "--first-seen-after", "2026-08-03T00:00:00+00:00",
        "--batch-limit", "1",
        "--concurrency", "1",
    ]) == 0
    assert enricher.seen == ["good/repo"]


def test_main_rejects_blank_channel() -> None:
    with pytest.raises(SystemExit):
        enrich_run.main([
            "--channel", "  ",
            "--first-seen-after", "2026-08-03T00:00:00+00:00",
        ])
