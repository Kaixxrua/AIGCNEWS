#!/usr/bin/env python3
"""Reconcile validated session PRs that missed their event-driven delivery step."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

SESSION_BRANCH = re.compile(r"session/[a-z0-9][a-z0-9-]{1,127}")
SESSION_PR_ACTOR = "github-actions[bot]"
RETRYABLE_CONCLUSIONS = {"failure", "cancelled", "timed_out", "startup_failure"}
MAX_RUN_ATTEMPTS = 3
MAX_VALIDATION_AGE = timedelta(hours=12)


class SweepError(RuntimeError):
    pass


class UpdateRefused(SweepError):
    """A definitively rejected update must not starve unrelated PRs."""


@dataclass(frozen=True)
class Result:
    pr: int
    head: str
    action: str
    reason: str
    run_id: int | None = None


class GitHub(Protocol):
    def open_pulls(self) -> list[dict[str, Any]]: ...

    def contract_runs(self, branch: str) -> list[dict[str, Any]]: ...

    def jobs(self, run_id: int) -> list[dict[str, Any]]: ...

    def prepare_merge(self, number: int, head: str) -> bool: ...

    def merge(self, number: int, head: str, title: str) -> None: ...

    def approve(self, run_id: int) -> None: ...

    def rerun_failed_jobs(self, run_id: int) -> None: ...


class ApiClient:
    def __init__(self, repository: str, token: str):
        if not re.fullmatch(r"[^/\s]+/[^/\s]+", repository):
            raise SweepError("repository must use owner/name format")
        if not token:
            raise SweepError("GitHub token is unavailable")
        self.repository = repository
        self.base = f"https://api.github.com/repos/{repository}"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "aigcnews-delivery-sweeper",
        }

    def request(
        self, method: str, path: str, document: dict[str, object] | None = None
    ) -> Any:
        body = json.dumps(document).encode() if document is not None else None
        request = urllib.request.Request(
            self.base + path, data=body, headers=self.headers, method=method
        )
        for attempt in range(4):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    payload = response.read()
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="replace")[:1000]
                if method == "PUT" and path.endswith("/update-branch") and exc.code == 422:
                    raise UpdateRefused(f"Branch update rejected (422): {detail}") from None
                if (
                    method != "GET"
                    or exc.code not in {429, 500, 502, 503, 504}
                    or attempt == 3
                ):
                    raise SweepError(
                        f"GitHub API {method} {path} failed ({exc.code}): {detail}"
                    ) from None
            except OSError as exc:
                if method != "GET" or attempt == 3:
                    raise SweepError(
                        f"GitHub API {method} {path} failed: {exc}"
                    ) from None
            time.sleep(2**attempt)
        return json.loads(payload) if payload else None

    def open_pulls(self) -> list[dict[str, Any]]:
        return self.request("GET", "/pulls?state=open&base=main&per_page=100")

    def contract_runs(self, branch: str) -> list[dict[str, Any]]:
        query = urllib.parse.urlencode(
            {"event": "pull_request", "branch": branch, "per_page": 20}
        )
        document = self.request(
            "GET", f"/actions/workflows/contract-baseline.yml/runs?{query}"
        )
        return document.get("workflow_runs", [])

    def jobs(self, run_id: int) -> list[dict[str, Any]]:
        document = self.request(
            "GET", f"/actions/runs/{run_id}/jobs?filter=latest&per_page=100"
        )
        return document.get("jobs", [])

    def prepare_merge(self, number: int, head: str) -> bool:
        main = self.request("GET", "/git/ref/heads/main")["object"]["sha"]
        comparison = self.request("GET", f"/compare/{main}...{head}")
        if comparison.get("status") not in {"ahead", "identical"}:
            # The owning task updates its branch before CI; landing never
            # creates a surprise merge commit after tests have completed.
            return False
        # All automated landings share one workflow concurrency group. Recheck
        # main immediately before the exact-head merge as a fail-closed guard.
        latest = self.request("GET", "/git/ref/heads/main")["object"]["sha"]
        if latest != main:
            raise SweepError("main advanced during merge validation")
        return True

    def merge(self, number: int, head: str, title: str) -> None:
        result = self.request(
            "PUT",
            f"/pulls/{number}/merge",
            {"sha": head, "merge_method": "squash", "commit_title": title},
        )
        if not result.get("merged"):
            raise SweepError(
                f"GitHub refused PR #{number} merge: {result.get('message', 'unknown')}"
            )

    def approve(self, run_id: int) -> None:
        self.request("POST", f"/actions/runs/{run_id}/approve", {})

    def rerun_failed_jobs(self, run_id: int) -> None:
        self.request("POST", f"/actions/runs/{run_id}/rerun-failed-jobs", {})


def same_repository(pr: dict[str, Any], repository: str) -> bool:
    return pr.get("head", {}).get("repo", {}).get("full_name") == repository


def exact_run(runs: list[dict[str, Any]], pr: dict[str, Any]) -> dict[str, Any] | None:
    head = pr["head"]["sha"]
    number = pr["number"]
    candidates = [
        run
        for run in runs
        if run.get("event") == "pull_request"
        and run.get("head_sha") == head
        and any(item.get("number") == number for item in run.get("pull_requests", []))
    ]
    return max(candidates, key=lambda item: item.get("run_number", 0), default=None)


def runner_assignment_failure(jobs: list[dict[str, Any]]) -> bool:
    failed = [job for job in jobs if job.get("conclusion") in RETRYABLE_CONCLUSIONS]
    return bool(failed) and all(
        not job.get("runner_name") and not job.get("steps") for job in failed
    )


def validation_is_fresh(run: dict[str, Any], now: datetime) -> bool:
    try:
        completed = datetime.fromisoformat(
            str(run["updated_at"]).replace("Z", "+00:00")
        )
    except (KeyError, TypeError, ValueError):
        return False
    age = now - completed
    return timedelta(0) <= age <= MAX_VALIDATION_AGE


def bot_authored_approval(pr: dict[str, Any], run: dict[str, Any]) -> bool:
    return (
        pr.get("user", {}).get("login") == SESSION_PR_ACTOR
        and run.get("actor", {}).get("login") == SESSION_PR_ACTOR
    )


def reconcile(
    client: GitHub,
    repository: str,
    *,
    apply: bool,
    now: datetime | None = None,
) -> list[Result]:
    results: list[Result] = []
    now = now or datetime.now(UTC)
    pulls = sorted(client.open_pulls(), key=lambda item: item["number"])
    for pr in pulls:
        number = pr["number"]
        branch = pr["head"]["ref"]
        head = pr["head"]["sha"]
        title = pr["title"]
        if not SESSION_BRANCH.fullmatch(branch) or not same_repository(pr, repository):
            continue
        run = exact_run(client.contract_runs(branch), pr)
        if run is None:
            results.append(
                Result(number, head, "hold", "no exact-head Contract Baseline run")
            )
            continue
        run_id = int(run["id"])
        status = run.get("status")
        conclusion = run.get("conclusion")
        if status != "completed":
            results.append(
                Result(number, head, "hold", f"baseline is {status}", run_id)
            )
            continue
        if conclusion == "success":
            if not validation_is_fresh(run, now):
                results.append(
                    Result(number, head, "hold", "successful baseline is stale", run_id)
                )
                continue
            try:
                prepared = not apply or client.prepare_merge(number, head)
            except UpdateRefused as exc:
                results.append(Result(number, head, "hold", str(exc), run_id))
                continue
            if not prepared:
                results.append(
                    Result(
                        number,
                        head,
                        "hold",
                        "base update required in owning task before new CI",
                        run_id,
                    )
                )
                continue
            if apply:
                client.merge(number, head, title)
            results.append(
                Result(
                    number,
                    head,
                    "merged" if apply else "merge",
                    "exact-head baseline passed",
                    run_id,
                )
            )
            # Serialize landings: a later PR must be reconsidered against the
            # newly advanced main on the next sweep.
            break
        if conclusion == "action_required":
            if not bot_authored_approval(pr, run):
                results.append(
                    Result(
                        number,
                        head,
                        "hold",
                        "workflow approval requires repository owner",
                        run_id,
                    )
                )
                continue
            if not validation_is_fresh(run, now):
                results.append(
                    Result(number, head, "hold", "approval request is stale", run_id)
                )
                continue
            if apply:
                client.approve(run_id)
            results.append(
                Result(
                    number,
                    head,
                    "approved" if apply else "approve",
                    "fresh exact-head workflow approval required",
                    run_id,
                )
            )
            # Approval starts the baseline asynchronously. Reconsider every PR
            # after that state transition on the next event or scheduled sweep.
            break
        jobs = client.jobs(run_id)
        attempt = int(run.get("run_attempt") or 1)
        if (
            conclusion in RETRYABLE_CONCLUSIONS
            and attempt < MAX_RUN_ATTEMPTS
            and validation_is_fresh(run, now)
            and runner_assignment_failure(jobs)
        ):
            if apply:
                client.rerun_failed_jobs(run_id)
            results.append(
                Result(
                    number,
                    head,
                    "rerun" if apply else "retry",
                    f"runner assignment failed on attempt {attempt}",
                    run_id,
                )
            )
            # As with merges and approvals, perform one mutation per sweep.
            break
        results.append(
            Result(number, head, "hold", f"baseline concluded {conclusion}", run_id)
        )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--token", default=os.environ.get("GH_TOKEN", ""))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        client = ApiClient(args.repository, args.token)
        results = reconcile(client, args.repository, apply=args.apply)
    except SweepError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps([asdict(result) for result in results], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
