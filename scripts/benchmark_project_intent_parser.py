#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from statistics import mean, median
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.services.project_discovery import search_projects


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile_value)))
    return ordered[index]


async def run_case(case: dict[str, Any], repetitions: int) -> dict[str, Any]:
    query = str(case["query"])
    systems: dict[str, Any] = {}
    timings: dict[str, list[float]] = {"deterministic": [], "host_intent": []}
    latest: dict[str, dict[str, Any]] = {}
    for repetition in range(repetitions):
        order = ("deterministic", "host_intent")
        if repetition % 2:
            order = tuple(reversed(order))
        for system in order:
            started = perf_counter()
            try:
                result = await search_projects(
                    query=query,
                    mode="ai",
                    language=str(case.get("language") or ""),
                    category=str(case.get("category") or ""),
                    subcategory=str(case.get("subcategory") or ""),
                    scope=str(case.get("scope") or "all"),
                    sort=case.get("sort"),
                    page=1,
                    limit=int(case.get("limit") or 10),
                    client_intent=case.get("intent") if system == "host_intent" else None,
                )
                latest[system] = result
                error = ""
            except Exception as exc:
                latest[system] = {"items": []}
                error = type(exc).__name__
            elapsed = (perf_counter() - started) * 1000
            timings[system].append(elapsed)
            systems[system] = {
                "result_ids": [
                    str(item.get("full_name") or item.get("id") or "")
                    for item in latest[system].get("items") or []
                ],
                "relevance": list(case.get("relevance", {}).get(system, [])),
                "latency_ms": elapsed,
                "error": error,
            }
    for system in systems:
        values = timings[system]
        systems[system]["latency_ms"] = mean(values)
        systems[system]["latency_p50_ms"] = median(values)
        systems[system]["latency_p95_ms"] = percentile(values, 0.95)
        systems[system]["fallback_used"] = bool(latest[system].get("fallback_used"))
    return {
        "id": str(case.get("id") or ""),
        "intent": str(case.get("intent_class") or "unspecified"),
        "must_find": list(case.get("must_find") or []),
        "systems": systems,
    }


async def benchmark(payload: dict[str, Any], repetitions: int) -> dict[str, Any]:
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("private fixture must contain cases")
    return {
        "schema_version": 1,
        "benchmark": "project-host-intent",
        "repetitions": repetitions,
        "cases": [await run_case(case, repetitions) for case in cases],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare deterministic and MCP host-supplied project search intent."
    )
    parser.add_argument("fixture", type=Path, help="Private query, host intent, and judgment fixture JSON.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()

    payload = json.loads(args.fixture.read_text(encoding="utf-8"))
    report = asyncio.run(benchmark(payload, max(1, min(args.repetitions, 20))))
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
