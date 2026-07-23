from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "eval_project_search_quality.py"
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


def test_evaluate_cases_compares_paired_systems() -> None:
    report = MODULE.evaluate_cases(
        {
            "cases": [
                {
                    "id": "agent-learning-zh",
                    "intent": "agent_learning",
                    "must_find": ["microsoft/ai-agents-for-beginners"],
                    "systems": {
                        "aigcnews": {
                            "result_ids": [
                                "microsoft/ai-agents-for-beginners",
                                "datawhalechina/hello-agents",
                            ],
                            "relevance": [3, 3],
                            "latency_ms": 250,
                        },
                        "web_search": {
                            "result_ids": ["example/unrelated"],
                            "relevance": [0],
                            "latency_ms": 1800,
                        },
                    },
                }
            ]
        }
    )

    assert report["case_count"] == 1
    assert report["systems"]["aigcnews"]["precision@5"] == pytest.approx(0.4)
    assert report["systems"]["aigcnews"]["success@3"] == 1.0
    assert report["systems"]["web_search"]["success@3"] == 0.0
    assert report["systems"]["aigcnews"]["latency_ms"] == 250


def test_evaluate_cases_rejects_unpaired_systems() -> None:
    with pytest.raises(ValueError, match="same systems"):
        MODULE.evaluate_cases(
            {
                "cases": [
                    {"id": "one", "systems": {"aigcnews": {"result_ids": [], "relevance": []}}},
                    {"id": "two", "systems": {"web_search": {"result_ids": [], "relevance": []}}},
                ]
            }
        )
