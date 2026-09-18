#!/usr/bin/env python3
"""Read-only delivery probe using a merged PR's landing commit as identity."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{40}")


def contains(root: Path, ancestor: str, descendant: str) -> bool:
    if not SHA.fullmatch(ancestor) or not SHA.fullmatch(descendant):
        raise ValueError("invalid commit identity")
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=root,
        capture_output=True,
        check=False,
        timeout=10,
    )
    if result.returncode not in (0, 1):
        raise ValueError("commit ancestry cannot be verified")
    return result.returncode == 0


def evaluate(
    root: Path, landing: str, state: dict, replacement: dict | None = None
) -> dict:
    if state.get("schema") != "aigcnews.production-state.v1":
        raise ValueError("unsupported production state")
    active = state.get("active_release")
    if active and contains(root, landing, active):
        return {"status": "active", "landing_sha": landing, "active_sha": active}
    if replacement:
        candidate = replacement["source_sha"]
        if not contains(root, landing, candidate):
            raise ValueError("replacement does not contain this task")
        status = replacement.get("status")
        if status not in ("queued", "in_progress", "failed"):
            raise ValueError("replacement status must be verified")
        return {
            "status": "replacement_failed"
            if status == "failed"
            else "superseded_waiting",
            "landing_sha": landing,
            "replacement": replacement,
            "instruction": "Pause duplicate publishing; follow the replacement until production contains landing_sha.",
        }
    return {
        "status": "waiting",
        "landing_sha": landing,
        "in_progress": state.get("in_progress"),
    }


def inspect_session(root: Path, branch: str, state: dict) -> dict:
    """Resolve squash landing and replacement ownership through read-only API calls."""
    token = os.environ.get("GH_TOKEN", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "Kaixxrua/AIGCNEWS")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("invalid repository")

    def get(path):
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        request = urllib.request.Request(
            "https://api.github.com/repos/" + repository + path, headers=headers
        )
        with urllib.request.urlopen(request, timeout=4) as response:
            return json.load(response)

    query = urllib.parse.urlencode(
        {
            "state": "closed",
            "head": repository.split("/")[0] + ":" + branch,
            "base": "main",
            "per_page": 100,
        }
    )
    pulls = get("/pulls?" + query)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    matches = [
        p
        for p in pulls
        if p.get("merged_at")
        and p["head"]["sha"] == head
        and p["head"]["repo"]["full_name"] == repository
    ]
    if len(matches) != 1:
        raise ValueError("no unique merged PR for current session SHA")
    task = matches[0]
    landing = task["merge_commit_sha"]
    result = evaluate(root, landing, state)
    result["task"] = {
        "pr": task["number"],
        "session": branch,
        "title": task["title"],
        "url": task["html_url"],
    }
    if result["status"] == "active":
        return result
    candidate = state.get("in_progress")
    if candidate and candidate != landing:
        if not isinstance(candidate, str) or not SHA.fullmatch(candidate):
            raise ValueError("invalid in-progress commit")
        owners = get("/commits/" + candidate + "/pulls")
        owners = [
            p
            for p in owners
            if p.get("merged_at")
            and p.get("merge_commit_sha") == candidate
            and p["base"]["ref"] == "main"
        ]
        replacement = {
            "source_sha": candidate,
            "status": "in_progress",
            "tasks": [
                {
                    "pr": p["number"],
                    "session": p["head"]["ref"],
                    "title": p["title"],
                    "url": p["html_url"],
                }
                for p in owners
            ],
        }
        resolved = evaluate(root, landing, state, replacement)
        resolved["task"] = result["task"]
        return resolved
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--landing-sha", required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--replacement", type=Path)
    args = parser.parse_args()
    try:
        state = json.loads(args.state.read_text())
        replacement = (
            json.loads(args.replacement.read_text()) if args.replacement else None
        )
        print(
            json.dumps(evaluate(args.repository, args.landing_sha, state, replacement))
        )
    except (ValueError, OSError, KeyError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status": "unverified", "error": str(exc)}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
