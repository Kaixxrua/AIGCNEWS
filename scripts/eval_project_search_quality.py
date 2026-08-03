#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable

INPUT_SCHEMA_VERSION = 1
REPORT_SCHEMA_VERSION = 2
DEFAULT_CUTOFFS = (3, 5, 10, 20)
MAX_RELEVANCE = 3


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


def recall_at_k(result_ids: Iterable[str], must_find: Iterable[str], k: int) -> float:
    expected = {str(value) for value in must_find if str(value)}
    if not expected:
        return 0.0
    observed = {str(value) for value in list(result_ids)[:k]}
    return len(expected & observed) / len(expected)


def percentile(values: Iterable[float], percentile_value: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * percentile_value) - 1))
    return ordered[index]


def _validate_payload(payload: dict[str, Any], cutoffs: tuple[int, ...]) -> tuple[list[dict[str, Any]], list[str]]:
    if payload.get("schema_version") != INPUT_SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {INPUT_SCHEMA_VERSION}")
    if not cutoffs or any(not isinstance(value, int) or value <= 0 for value in cutoffs):
        raise ValueError("cutoffs must contain positive integers")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("benchmark payload must contain at least one case")

    case_ids: set[str] = set()
    systems: list[str] | None = None
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("benchmark cases must be objects")
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError("case id must be nonempty")
        if case_id in case_ids:
            raise ValueError("case ids must be unique")
        case_ids.add(case_id)
        if not isinstance(case.get("intent"), str) or not case["intent"].strip():
            raise ValueError("case intent must be nonempty")
        must_find = case.get("must_find")
        if not isinstance(must_find, list) or any(not isinstance(value, str) or not value for value in must_find):
            raise ValueError("must_find must contain canonical repository ids")
        if len(must_find) != len(set(must_find)):
            raise ValueError("must_find repository ids must be unique")
        case_systems = case.get("systems")
        if not isinstance(case_systems, dict) or not case_systems:
            raise ValueError("benchmark cases must contain systems")
        names = sorted(case_systems)
        if systems is None:
            systems = names
        elif names != systems:
            raise ValueError("every case must contain the same systems")
        for name, result in case_systems.items():
            if not isinstance(name, str) or not name or not isinstance(result, dict):
                raise ValueError("systems must map names to result objects")
            result_ids = result.get("result_ids")
            relevance = result.get("relevance")
            if not isinstance(result_ids, list) or any(not isinstance(value, str) or not value for value in result_ids):
                raise ValueError("result_ids must contain canonical repository ids")
            if len(result_ids) != len(set(result_ids)):
                raise ValueError("result_ids must be unique")
            if not isinstance(relevance, list) or len(result_ids) != len(relevance):
                raise ValueError("result_ids and relevance must be position-aligned")
            if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or value > MAX_RELEVANCE for value in relevance):
                raise ValueError(f"relevance grades must be finite values from 0 to {MAX_RELEVANCE}")
            latency = result.get("latency_ms", 0.0)
            if isinstance(latency, bool) or not isinstance(latency, (int, float)) or not math.isfinite(latency) or latency < 0:
                raise ValueError("latency_ms must be a finite nonnegative number")
            if not isinstance(result.get("error", ""), str):
                raise ValueError("error must be a string")
            if "fallback_used" in result and not isinstance(result["fallback_used"], bool):
                raise ValueError("fallback_used must be a boolean")
    assert systems is not None
    return cases, systems


def _system_metrics(case: dict[str, Any], system: str, cutoffs: tuple[int, ...]) -> dict[str, float]:
    result = case["systems"][system]
    relevance = [float(value) for value in result["relevance"]]
    result_ids = [str(value) for value in result["result_ids"]]
    must_find = [str(value) for value in case["must_find"]]
    metrics: dict[str, float] = {
        "mrr": reciprocal_rank(relevance, max(cutoffs)),
        "latency_ms": float(result.get("latency_ms", 0.0)),
        "error_rate": float(bool(result.get("error"))),
        "zero_rate": float(not result_ids),
        "fallback_rate": float(bool(result.get("fallback_used", False))),
    }
    for cutoff in cutoffs:
        metrics[f"precision@{cutoff}"] = precision_at_k(relevance, cutoff)
        metrics[f"ndcg@{cutoff}"] = ndcg_at_k(relevance, cutoff)
        metrics[f"recall@{cutoff}"] = recall_at_k(result_ids, must_find, cutoff)
        metrics[f"success@{cutoff}"] = success_at_k(result_ids, must_find, cutoff)
    return metrics


def _aggregate_cases(per_case: list[dict[str, Any]], systems: list[str]) -> dict[str, dict[str, float]]:
    aggregate: dict[str, dict[str, float]] = {}
    for system in systems:
        metric_names = per_case[0]["systems"][system]
        metrics = {
            metric: mean(case["systems"][system][metric] for case in per_case)
            for metric in metric_names
            if metric != "latency_ms"
        }
        latencies = [case["systems"][system]["latency_ms"] for case in per_case]
        metrics.update(
            {
                "latency_mean_ms": mean(latencies),
                "latency_p50_ms": median(latencies),
                "latency_p95_ms": percentile(latencies, 0.95),
            }
        )
        aggregate[system] = metrics
    return aggregate


def _paired_deltas(aggregate: dict[str, dict[str, float]], systems: list[str]) -> dict[str, Any]:
    if len(systems) != 2:
        return {}
    if {"legacy", "v2"}.issubset(systems):
        baseline, candidate = "legacy", "v2"
    else:
        baseline, candidate = systems
    return {
        "baseline": baseline,
        "candidate": candidate,
        "metrics": {
            metric: aggregate[candidate][metric] - aggregate[baseline][metric]
            for metric in aggregate[baseline]
            if metric in aggregate[candidate]
        },
    }


def evaluate_cases(payload: dict[str, Any], cutoffs: tuple[int, ...] = DEFAULT_CUTOFFS) -> dict[str, Any]:
    cases, systems = _validate_payload(payload, cutoffs)
    per_case = [
        {
            "id": case["id"],
            "intent": case["intent"],
            "systems": {system: _system_metrics(case, system, cutoffs) for system in systems},
        }
        for case in cases
    ]
    aggregate = _aggregate_cases(per_case, systems)
    strata: dict[str, Any] = {}
    for intent in sorted({case["intent"] for case in per_case}):
        selected = [case for case in per_case if case["intent"] == intent]
        stratum_aggregate = _aggregate_cases(selected, systems)
        strata[intent] = {
            "case_count": len(selected),
            "systems": stratum_aggregate,
            "paired_deltas": _paired_deltas(stratum_aggregate, systems),
        }
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "input_schema_version": INPUT_SCHEMA_VERSION,
        "case_count": len(cases),
        "cutoffs": list(cutoffs),
        "systems": aggregate,
        "intent_strata": strata,
        "paired_deltas": _paired_deltas(aggregate, systems),
        "cases": per_case,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate paired project-discovery ranking snapshots.")
    parser.add_argument("fixture", type=Path, help="Judged benchmark JSON file.")
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
