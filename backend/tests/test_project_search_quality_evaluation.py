from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "eval_project_search_quality.py"
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "project_search_quality_cases.json"
SPEC = importlib.util.spec_from_file_location("eval_project_search_quality", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_ranking_metrics_reward_relevant_results_near_the_top() -> None:
    relevance = [3, 0, 2, 1]

    assert MODULE.precision_at_k(relevance, 3) == pytest.approx(2 / 3)
    assert MODULE.reciprocal_rank(relevance, 3) == 1.0
    assert MODULE.ndcg_at_k(relevance, 3) == pytest.approx(0.9558305893)
    assert MODULE.success_at_k(["owner/a", "owner/b"], ["owner/b"], 1) == 0.0
    assert MODULE.success_at_k(["owner/a", "owner/b"], ["owner/b"], 2) == 1.0
    assert MODULE.recall_at_k(["owner/a", "owner/b"], ["owner/a", "owner/b", "owner/c"], 2) == pytest.approx(2 / 3)


def test_quality_fixture_produces_stratified_paired_report() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    report = MODULE.evaluate_cases(payload)

    assert report["schema_version"] == 2
    assert report["input_schema_version"] == 1
    assert report["case_count"] == 5
    assert report["cutoffs"] == [3, 5, 10, 20]
    assert list(report["systems"]) == ["legacy", "v2"]
    assert report["systems"]["legacy"]["success@10"] == pytest.approx(3 / 5)
    assert report["systems"]["v2"]["success@10"] == 1.0
    assert report["systems"]["legacy"]["zero_rate"] == pytest.approx(1 / 5)
    assert report["systems"]["legacy"]["fallback_rate"] == pytest.approx(1 / 5)
    assert report["systems"]["legacy"]["latency_p50_ms"] == 250
    assert report["systems"]["legacy"]["latency_p95_ms"] == 900
    assert report["paired_deltas"]["baseline"] == "legacy"
    assert report["paired_deltas"]["candidate"] == "v2"
    assert report["paired_deltas"]["metrics"]["success@10"] == pytest.approx(2 / 5)
    broad = report["intent_strata"]["broad_coding_productivity"]
    assert broad["case_count"] == 2
    assert broad["systems"]["legacy"]["success@10"] == 0.0
    assert broad["systems"]["v2"]["success@10"] == 1.0
    assert [case["id"] for case in report["cases"]] == [case["id"] for case in payload["cases"]]


def test_evaluate_cases_rejects_unpaired_systems() -> None:
    with pytest.raises(ValueError, match="same systems"):
        MODULE.evaluate_cases(
            {
                "schema_version": 1,
                "cases": [
                    {"id": "one", "intent": "test", "must_find": [], "systems": {"legacy": {"result_ids": [], "relevance": []}}},
                    {"id": "two", "intent": "test", "must_find": [], "systems": {"v2": {"result_ids": [], "relevance": []}}},
                ],
            }
        )


def test_evaluate_cases_rejects_unaligned_result_ids_and_relevance() -> None:
    with pytest.raises(ValueError, match="position-aligned"):
        MODULE.evaluate_cases(
            {
                "schema_version": 1,
                "cases": [
                    {
                        "id": "unaligned",
                        "intent": "learning",
                        "must_find": [],
                        "systems": {
                            "legacy": {
                                "result_ids": ["owner/a", "owner/b"],
                                "relevance": [3],
                                "latency_ms": 1,
                                "error": "",
                            }
                        },
                    }
                ],
            }
        )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"schema_version": 2, "cases": [{"id": "one", "intent": "test", "must_find": [], "systems": {"legacy": {"result_ids": [], "relevance": []}}}]}, "schema_version"),
        (
            {
                "schema_version": 1,
                "cases": [
                    {"id": "duplicate", "intent": "test", "must_find": [], "systems": {"legacy": {"result_ids": [], "relevance": []}}},
                    {"id": "duplicate", "intent": "test", "must_find": [], "systems": {"legacy": {"result_ids": [], "relevance": []}}},
                ],
            },
            "unique",
        ),
        (
            {
                "schema_version": 1,
                "cases": [
                    {
                        "id": "bad-grade",
                        "intent": "test",
                        "must_find": [],
                        "systems": {"legacy": {"result_ids": ["owner/a"], "relevance": [4]}},
                    }
                ],
            },
            "relevance",
        ),
        (
            {
                "schema_version": 1,
                "cases": [
                    {
                        "id": "negative-latency",
                        "intent": "test",
                        "must_find": [],
                        "systems": {"legacy": {"result_ids": [], "relevance": [], "latency_ms": -1}},
                    }
                ],
            },
            "latency_ms",
        ),
    ],
)
def test_evaluate_cases_rejects_invalid_contract(payload: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        MODULE.evaluate_cases(payload)
