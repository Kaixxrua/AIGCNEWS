from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock

import pytest

from scripts import backfill_github_project_semantic_index as backfill


def _run(monkeypatch, capsys, argv: list[str], results: list[dict]) -> tuple[int, list[dict], str]:
    calls: list[dict] = []
    queue = list(results)

    def fake_sync(**kwargs):
        calls.append(kwargs)
        return queue.pop(0)

    monkeypatch.setattr(backfill, "sync_github_project_semantic_index", fake_sync)
    monkeypatch.setattr(backfill, "create_application_repositories", MagicMock())
    monkeypatch.setattr(backfill, "postgres_database", MagicMock())
    monkeypatch.setattr(sys, "argv", ["backfill", *argv])
    code = backfill.main()
    return code, calls, capsys.readouterr().out


def _batch(selected: int, last: str, status: str = "success") -> dict:
    return {"status": status, "selected": selected, "counts": {"succeeded": selected}, "last_repo_id": last}


def test_default_runs_one_reconciled_batch_with_legacy_output(monkeypatch, capsys) -> None:
    code, calls, out = _run(monkeypatch, capsys, [], [_batch(100, "b/two")])

    assert code == 0
    assert len(calls) == 1
    assert calls[0]["reconcile"] is True
    assert calls[0]["after_repo_id"] == ""
    assert json.loads(out) == _batch(100, "b/two")


def test_multi_batch_chains_cursor_and_reconciles_once(monkeypatch, capsys) -> None:
    code, calls, out = _run(
        monkeypatch,
        capsys,
        ["--limit", "2", "--max-batches", "0", "--profiles-only"],
        [_batch(2, "a/two"), _batch(2, "b/four"), _batch(1, "c/five")],
    )

    assert code == 0
    assert [call["after_repo_id"] for call in calls] == ["", "a/two", "b/four"]
    assert [call["reconcile"] for call in calls] == [True, False, False]
    assert all(call["fetch_readme"] is False for call in calls)
    lines = [json.loads(line) for line in out.strip().splitlines()]
    assert [line["batch"] for line in lines[:-1]] == [1, 2, 3]
    assert lines[-1] == {"batches": 3, "counts": {"succeeded": 5}, "last_repo_id": "c/five"}


@pytest.mark.parametrize("argv", [["--max-batches", "2"], ["--max-batches", "0"]])
def test_stops_on_failed_batch_with_nonzero_exit(monkeypatch, capsys, argv) -> None:
    code, calls, _ = _run(
        monkeypatch,
        capsys,
        ["--limit", "2", *argv],
        [_batch(2, "a/two", status="failed"), _batch(2, "b/four")],
    )

    assert code == 1
    assert len(calls) == 1


def test_max_batches_caps_the_loop(monkeypatch, capsys) -> None:
    code, calls, _ = _run(
        monkeypatch,
        capsys,
        ["--limit", "2", "--max-batches", "2", "--no-reconcile"],
        [_batch(2, "a/two"), _batch(2, "b/four"), _batch(2, "c/six")],
    )

    assert code == 0
    assert len(calls) == 2
    assert [call["reconcile"] for call in calls] == [False, False]
