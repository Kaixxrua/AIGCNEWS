#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sha256(value: str, field: str) -> str:
    normalized = value.strip().lower()
    if "@sha256:" in normalized:
        normalized = normalized.rsplit("@sha256:", 1)[1]
    elif normalized.startswith("sha256:"):
        normalized = normalized[7:]
    if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
        raise ValueError(f"{field} must contain a sha256 digest")
    return normalized


def _topology_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalized_payload(case_id: str, payload: Any) -> Any:
    if case_id == "ready" and isinstance(payload, dict):
        return {
            "status": payload.get("status"),
            "runtime_ready": payload.get("runtime_ready"),
            "scope": payload.get("scope"),
        }
    if case_id == "sse-report" and isinstance(payload, str):
        events = []
        for line in payload.splitlines():
            if not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                events.append({"kind": "done"})
                continue
            try:
                decoded = json.loads(data)
            except ValueError:
                events.append({"kind": "text"})
            else:
                events.append(
                    {
                        "kind": "json",
                        "keys": sorted(decoded) if isinstance(decoded, dict) else [],
                        "type": decoded.get("type") if isinstance(decoded, dict) else None,
                    }
                )
        return events[:4]
    return payload


def _request_cases(client: Any, *, shadow_cohort: bool = False) -> list[dict[str, Any]]:
    cases = [
        ("live", "GET", "/api/live", None),
        ("ready", "GET", "/api/ready", None),
        ("categories", "GET", "/api/projects/categories?source=github", None),
        ("projects-stars", "GET", "/api/projects?source=github&scope=all&page=1&page_size=10&sort=stars", None),
        ("projects-exact", "GET", "/api/projects?source=github&scope=all&q=DeusData%2Fcodebase-memory-mcp&page=1&page_size=10", None),
        ("projects-zh", "GET", "/api/projects?source=github&scope=all&q=%E4%BB%A3%E7%A0%81%E5%BA%93%E8%AE%B0%E5%BF%86MCP&page=1&page_size=10", None),
        (
            "mcp-initialize",
            "POST",
            "/api/mcp",
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        ),
        (
            "mcp-tools-list",
            "POST",
            "/api/mcp",
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        ),
        (
            "mcp-search-exact",
            "POST",
            "/api/mcp",
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "search_github_ai_projects",
                    "arguments": {"q": "DeusData/codebase-memory-mcp", "limit": 10, "page": 1},
                },
            },
        ),
        (
            "mcp-search-zh",
            "POST",
            "/api/mcp",
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "search_github_ai_projects",
                    "arguments": {"q": "代码库记忆MCP", "limit": 10, "page": 1},
                },
            },
        ),
        (
            "sse-report",
            "POST",
            "/api/report/daily/stream",
            {"source": "github", "period": "daily", "force_regenerate": False},
        ),
    ]
    if shadow_cohort:
        cases = [
            case
            for case in cases
            if case[0]
            in {
                "live",
                "categories",
                "projects-stars",
                "projects-exact",
                "mcp-initialize",
                "mcp-tools-list",
                "mcp-search-exact",
                "sse-report",
            }
        ]
    results = []
    for case_id, method, path, body in cases:
        response = client.request(method, path, json=body)
        content_type = response.headers.get("content-type", "").split(";", 1)[0]
        try:
            payload = response.json()
        except ValueError:
            payload = response.text
        results.append(
            {
                "case_id": case_id,
                "status_code": response.status_code,
                "content_type": content_type,
                "response_sha256": _digest(_normalized_payload(case_id, payload)),
            }
        )
    return results


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run isolated public project-catalog smoke and emit bounded evidence.")
    parser.add_argument("phase", choices=("shadow", "baseline", "postgres", "rollback"))
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--topology-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.phase in {"postgres", "rollback"} and args.baseline is None:
        raise ValueError("--baseline is required for postgres and rollback phases")

    from fastapi.testclient import TestClient

    from backend.app import main as application
    from backend.app.api import routes_report
    from backend.app.core.auth import RequireAdmin

    async def deterministic_briefing_stream(*args: Any, **kwargs: Any):
        yield "data: " + json.dumps(
            {"type": "progress", "data": "rehearsal"},
            separators=(",", ":"),
        ) + "\n\n"
        yield "data: [DONE]\n\n"

    original_scheduler_enabled = application.settings.scheduler_enabled
    application.settings.scheduler_enabled = False
    original_briefing_stream = routes_report._briefing_stream
    routes_report._briefing_stream = deterministic_briefing_stream
    application.app.dependency_overrides[RequireAdmin] = lambda: {"role": "admin", "id": 0}
    try:
        with TestClient(application.app) as client:
            cases = _request_cases(client, shadow_cohort=args.phase == "shadow")
            shadow = None
            if args.phase == "shadow":
                response = client.post("/api/ops/project-shadow/finalize")
                response.raise_for_status()
                shadow = response.json()
    finally:
        application.app.dependency_overrides.pop(RequireAdmin, None)
        routes_report._briefing_stream = original_briefing_stream
        application.settings.scheduler_enabled = original_scheduler_enabled

    failures = [case["case_id"] for case in cases if case["status_code"] != 200]
    mismatch_count = len(failures)
    if args.baseline is not None:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        expected = {case["case_id"]: case for case in baseline.get("cases", [])}
        comparable_fields = ("case_id", "status_code", "content_type", "response_sha256")
        for case in cases:
            if case["case_id"] == "ready":
                continue
            baseline_case = expected.get(case["case_id"], {})
            if any(baseline_case.get(field) != case.get(field) for field in comparable_fields):
                mismatch_count += 1

    kind = "shadow" if args.phase == "shadow" else ("rollback" if args.phase == "rollback" else "smoke")
    status = "passed" if mismatch_count == 0 else "failed"
    if args.phase == "shadow":
        snapshots = [shadow.get("catalog", {}), shadow.get("search", {})]
        complete = all(
            snapshot.get("accounting", {}).get("complete_coverage") is True
            for snapshot in snapshots
        )
        mismatch_count += sum(
            int(snapshot.get("accounting", {}).get("terminal_failures") or 0)
            for snapshot in snapshots
        )
        status = "match" if complete and mismatch_count == 0 else "mismatch"

    evidence = {
        "evidence_version": 1,
        "kind": kind,
        "status": status,
        "release_id": args.release_id,
        "revision": args.revision,
        "image_sha256": _sha256(args.image_digest, "image_digest"),
        "topology_sha256": _topology_digest(args.topology_file),
        "suite": "project-catalog-public-contract-v1",
        "environment": args.phase,
        "sample_count": len(cases),
        "mismatch_count": mismatch_count,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "cases": cases,
    }
    if shadow is not None:
        evidence["shadow"] = shadow
    evidence["result_sha256"] = _digest(evidence)
    _write(args.output, evidence)
    print(json.dumps({"status": status, "kind": kind, "sample_count": len(cases), "mismatch_count": mismatch_count}, sort_keys=True))
    return 0 if status in {"passed", "match"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
