from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "ci" / "delivery_sweeper.py"


def load_module():
    spec = importlib.util.spec_from_file_location("delivery_sweeper", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sweeper = load_module()
REPOSITORY = "owner/repository"
HEAD = "a" * 40
NOW = datetime(2026, 9, 17, 12, tzinfo=UTC)


def pull(number: int = 7, *, head: str = HEAD, branch: str = "session/example-100-200-3000"):
    return {
        "number": number,
        "title": "fix(workflow): reconcile delivery",
        "user": {"login": "github-actions[bot]"},
        "head": {"sha": head, "ref": branch, "repo": {"full_name": REPOSITORY}},
    }


def run(
    number: int = 7,
    *,
    head: str = HEAD,
    status: str = "completed",
    conclusion: str = "success",
    attempt: int = 1,
):
    return {
        "id": 99,
        "event": "pull_request",
        "head_sha": head,
        "status": status,
        "conclusion": conclusion,
        "run_attempt": attempt,
        "run_number": 10,
        "updated_at": "2026-09-17T11:55:00Z",
        "actor": {"login": "github-actions[bot]"},
        "pull_requests": [{"number": number}],
    }


class FakeClient:
    def __init__(
        self,
        pulls: list[dict[str, Any]],
        runs: list[dict[str, Any]],
        jobs: list[dict[str, Any]] | None = None,
    ):
        self.pulls = pulls
        self.runs = runs
        self.job_data = jobs or []
        self.merged: list[tuple[int, str, str]] = []
        self.approved: list[int] = []
        self.rerun: list[int] = []

    def open_pulls(self):
        return self.pulls

    def contract_runs(self, branch: str):
        return self.runs

    def jobs(self, run_id: int):
        return self.job_data

    def merge(self, number: int, head: str, title: str):
        self.merged.append((number, head, title))

    def approve(self, run_id: int):
        self.approved.append(run_id)

    def rerun_failed_jobs(self, run_id: int):
        self.rerun.append(run_id)


def test_merges_only_exact_validated_head_and_serializes_landings():
    client = FakeClient([pull(7), pull(8)], [run(7), run(8)])

    results = sweeper.reconcile(client, REPOSITORY, apply=True, now=NOW)

    assert [result.action for result in results] == ["merged"]
    assert client.merged == [(7, HEAD, "fix(workflow): reconcile delivery")]


def test_holds_when_success_belongs_to_stale_head():
    client = FakeClient([pull()], [run(head="b" * 40)])

    results = sweeper.reconcile(client, REPOSITORY, apply=True, now=NOW)

    assert results[0].action == "hold"
    assert "exact-head" in results[0].reason
    assert not client.merged


def test_retries_runner_assignment_failure_at_most_three_attempts():
    jobs = [{"conclusion": "failure", "runner_name": "", "steps": []}]
    client = FakeClient([pull()], [run(conclusion="failure", attempt=1)], jobs)

    results = sweeper.reconcile(client, REPOSITORY, apply=True, now=NOW)

    assert results[0].action == "rerun"
    assert client.rerun == [99]

    exhausted = FakeClient([pull()], [run(conclusion="failure", attempt=3)], jobs)
    results = sweeper.reconcile(exhausted, REPOSITORY, apply=True, now=NOW)
    assert results[0].action == "hold"
    assert not exhausted.rerun


def test_never_retries_real_test_failure():
    test_failure = FakeClient(
        [pull()],
        [run(conclusion="failure")],
        [{"conclusion": "failure", "runner_name": "ci-runner", "steps": [{"name": "test"}]}],
    )

    result = sweeper.reconcile(test_failure, REPOSITORY, apply=True, now=NOW)[0]

    assert result.action == "hold"
    assert not test_failure.rerun


def test_approves_all_fresh_exact_head_runs_without_serializing_ci():
    approval = FakeClient(
        [pull(7), pull(8)],
        [
            run(7, conclusion="action_required"),
            run(8, conclusion="action_required"),
        ],
    )

    results = sweeper.reconcile(approval, REPOSITORY, apply=True, now=NOW)

    assert [result.action for result in results] == ["approved", "approved"]
    assert approval.approved == [99, 99]
    assert not approval.merged


def test_approval_prevents_a_later_success_from_landing_in_same_sweep():
    approval = FakeClient(
        [pull(7), pull(8)],
        [run(7, conclusion="action_required"), run(8)],
    )

    results = sweeper.reconcile(approval, REPOSITORY, apply=True, now=NOW)

    assert [result.action for result in results] == ["approved", "hold"]
    assert results[1].reason == "waiting for approved validations before landing"
    assert not approval.merged


def test_dry_run_reports_approval_without_mutating():
    approval = FakeClient([pull()], [run(conclusion="action_required")])

    result = sweeper.reconcile(approval, REPOSITORY, apply=False, now=NOW)[0]

    assert result.action == "approve"
    assert not approval.approved


def test_never_approves_stale_run():
    stale = run(conclusion="action_required")
    stale["updated_at"] = "2026-09-15T11:55:00Z"
    approval = FakeClient([pull()], [stale])

    result = sweeper.reconcile(approval, REPOSITORY, apply=True, now=NOW)[0]

    assert result.action == "hold"
    assert result.reason == "approval request is stale"
    assert not approval.approved


def test_never_approves_non_bot_run():
    manual_pull = pull()
    manual_pull["user"]["login"] = "repository-owner"
    approval = FakeClient([manual_pull], [run(conclusion="action_required")])

    result = sweeper.reconcile(approval, REPOSITORY, apply=True, now=NOW)[0]

    assert result.action == "hold"
    assert result.reason == "workflow approval requires repository owner"
    assert not approval.approved


def test_ignores_forks_and_non_session_branches():
    fork = pull()
    fork["head"]["repo"]["full_name"] = "someone/fork"
    client = FakeClient([fork, pull(branch="feature/not-managed")], [run()])

    assert sweeper.reconcile(client, REPOSITORY, apply=True, now=NOW) == []


def test_never_merges_stale_successful_validation():
    stale = run()
    stale["updated_at"] = "2026-09-15T11:55:00Z"
    client = FakeClient([pull()], [stale])

    result = sweeper.reconcile(client, REPOSITORY, apply=True, now=NOW)[0]

    assert result.action == "hold"
    assert result.reason == "successful baseline is stale"
    assert not client.merged
