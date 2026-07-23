#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import mean
from typing import Any, Iterable


DEFAULT_CUTOFFS = (3, 5, 10)


def precision_at_k(relevance: Iterable[float], k: int) -> float:
    values = list(relevance)[:k]
    if k <= 0:
        raise ValueError("k must be positive")
    return sum(value > 0 for value in values) / k


def reciprocal_rank(relevance: Iterable[float], k: int) -> float:
    if k <= 0:
        raise ValueError("k must be positive")
    for rank, value in enumerate(list(relevance)[:k], start=1):
        if value > 0:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(relevance: Iterable[float], k: int) -> float:
    if k <= 0:
        raise ValueError("k must be positive")
    values = list(relevance)[:k]

    def dcg(items: list[float]) -> float:
        return sum((2**value - 1) / math.log2(rank + 1) for rank, value in enumerate(items, start=1))

    ideal = sorted(values, reverse=True)
    ideal_score = dcg(ideal)
    return dcg(values) / ideal_score if ideal_score else 0.0


def success_at_k(result_ids: Iterable[str], must_find: Iterable[str], k: int) -> float:
    expected = {str(value) for value in must_find if str(value)}
    if not expected:
        return 0.0
    observed = {str(value) for value in list(result_ids)[:k]}
    return float(bool(expected & observed))


def _system_metrics(case: dict[str, Any], system: str, cutoffs: tuple[int, ...]) -> dict[str, float]:
    result = case["systems"][system]
    relevance = [float(value) for value in result.get("relevance", [])]
    result_ids = [str(value) for value in result.get("result_ids", [])]
    must_find = [str(value) for value in case.get("must_find", [])]
    metrics: dict[str, float] = {
        "mrr": reciprocal_rank(relevance, max(cutoffs)),
        "latency_ms": float(result.get("latency_ms", 0.0)),
        "error": float(bool(result.get("error"))),
        "empty": float(not result_ids),
    }
    for cutoff in cutoffs:
        metrics[f"precision@{cutoff}"] = precision_at_k(relevance, cutoff)
        metrics[f"ndcg@{cutoff}"] = ndcg_at_k(relevance, cutoff)
        metrics[f"success@{cutoff}"] = success_at_k(result_ids, must_find, cutoff)
    return metrics


def evaluate_cases(payload: dict[str, Any], cutoffs: tuple[int, ...] = DEFAULT_CUTOFFS) -> dict[str, Any]:
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("benchmark payload must contain at least one case")
    systems = sorted({name for case in cases for name in case.get("systems", {})})
    if not systems:
        raise ValueError("benchmark cases must contain systems")

    per_case: list[dict[str, Any]] = []
    aggregate: dict[str, dict[str, float]] = {}
    for case in cases:
        case_systems = case.get("systems", {})
        if set(case_systems) != set(systems):
            raise ValueError("every case must contain the same systems")
        system_metrics = {system: _system_metrics(case, system, cutoffs) for system in systems}
        per_case.append(
            {
                "id": str(case.get("id") or ""),
                "intent": str(case.get("intent") or "unspecified"),
                "systems": system_metrics,
            }
        )

    for system in systems:
        metric_names = per_case[0]["systems"][system]
        aggregate[system] = {
            metric: mean(case["systems"][system][metric] for case in per_case)
            for metric in metric_names
        }

    return {
        "schema_version": 1,
        "case_count": len(cases),
        "cutoffs": list(cutoffs),
        "systems": aggregate,
        "cases": per_case,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate paired AIGCNEWS and Web Search project-discovery snapshots."
    )
    parser.add_argument("fixture", type=Path, help="Private judged benchmark JSON file.")
    parser.add_argument("--output", type=Path, help="Write the machine-readable report to this file.")
    args = parser.parse_args()

    payload = json.loads(args.fixture.read_text(encoding="utf-8"))
    report = evaluate_cases(payload)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
