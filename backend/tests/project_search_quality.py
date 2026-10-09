"""Execute the bilingual quality corpus through real PostgreSQL and both engines.

Imported by the existing PostgreSQL catalog CI suite so the release gate cannot
silently disappear behind a new, unselected pytest file.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from statistics import mean

import pytest

from backend.tests.postgres_test_safety import postgres_test_sandbox
from scripts.eval_project_search_quality import ndcg_at_k, recall_at_k

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "backend/tests/fixtures/project_search_quality.json"


def seed_quality_catalog(database, profiles):
    candidate = ("repo_id", "full_name", "title", "url", "description", "language",
                 "topics_json", "stars", "forks", "watchers", "created_at", "pushed_at")
    enrichment = ("repo_id", "description_zh", "description_en", "tags_json",
                  "tags_zh_json", "tags_en_json", "category_slug", "category_name",
                  "subcategory_slug", "subcategory_name")
    with database.transaction() as connection, connection.cursor() as cursor:
        cursor.executemany(
            f"INSERT INTO github_repo_candidates ({','.join(candidate)}) "
            f"VALUES ({','.join(['%s'] * len(candidate))})",
            [[row.get(field) for field in candidate] for row in profiles],
        )
        cursor.executemany(
            f"INSERT INTO github_repo_enrichments ({','.join(enrichment)},"
            "source_fingerprint,prompt_version,status) "
            f"VALUES ({','.join(['%s'] * len(enrichment))},'quality','quality','succeeded')",
            [[row.get(field) or "" for field in enrichment] for row in profiles],
        )


def judge(case, ids):
    label = case["id"]
    assert len(ids) == len(set(ids)), f"{label}: duplicate results"
    if case.get("empty"):
        assert ids == [], f"{label}: unknown query returned {ids}"
        return None
    grades = case["judgments"]
    if case.get("exact_first"):
        assert ids[0] == case["exact_first"], (label, ids)
    assert not set(case.get("forbidden", [])) & set(ids[:10]), (label, ids)
    recall = recall_at_k(ids, case["must_find"], 10)
    assert recall >= case.get("min_recall10", 1), (label, "recall@10", recall, ids)
    ndcg = ndcg_at_k([grades.get(repo, 0) for repo in ids], 5, ideal_relevance=grades.values())
    assert ndcg >= case.get("min_ndcg5", 0.7), (label, "ndcg@5", ndcg, ids)
    return {"ndcg@5": ndcg, "recall@10": recall}


def verify_quality_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from backend.app.core.config import settings
    from backend.app.domain.search_semantics import build_project_lexical_retrieval_plan, build_project_search_intent
    from backend.app.repositories.postgres_project_catalog import PostgresProjectCatalogRepository
    from backend.app.services.project_discovery import search_catalog_projects, search_projects
    from backend.tests.test_postgres_project_catalog import Database

    payload = json.loads(CORPUS.read_text())
    cases = payload["cases"]
    # Fixed configuration; external services must not affect the release gate.
    monkeypatch.setattr(settings, "project_ai_search_strategy", "v2")
    monkeypatch.setattr(settings, "project_semantic_search_enabled", False)
    monkeypatch.setattr(settings, "project_reranker_enabled", False)
    monkeypatch.setattr(settings, "project_semantic_heat_first", True)
    monkeypatch.setattr(settings, "project_search_adoption_weight", 0.006)
    with postgres_test_sandbox() as sandbox:
        seed_quality_catalog(sandbox.database, payload["profiles"])
        repository = PostgresProjectCatalogRepository(database=sandbox.database)
        # Check the actual adapter SQL against real indexes. A tiny corpus
        # naturally prefers sequential scans, so disable them only in this
        # scratch transaction to test index eligibility, not timing.
        capture = Database([[]])
        PostgresProjectCatalogRepository(capture).find_lexical_candidate_lanes(
            q=build_project_lexical_retrieval_plan(build_project_search_intent("RAG evaluation framework")),
        )
        sql, params = capture.cursor.calls[1]
        with sandbox.database.transaction() as connection:
            connection.execute("SET LOCAL enable_seqscan = off")
            connection.execute("SET LOCAL enable_indexscan = off")
            connection.execute("SET LOCAL enable_nestloop = off")
            plan = connection.execute("EXPLAIN (FORMAT JSON) " + sql, params).fetchone()
        for index in ("idx_gh_candidates_profile_v2_trgm", "idx_gh_enrichments_profile_v2_trgm"):
            assert index in json.dumps(plan), f"v2 query no longer matches {index}"
        observed = {}
        durations = []

        async def replay():
            for case in cases:
                started = time.monotonic()
                result = await search_projects(
                    query=case["query"], mode="ai", limit=10, **case["filters"],
                    repository_factory=lambda: repository,
                    fallback_search=lambda **_: {"items": []},
                )
                durations.append((time.monotonic() - started) * 1000)
                observed[case["id"]] = [item["full_name"] for item in result["items"]]
                for item in result["items"]:
                    if case["filters"].get("language"):
                        assert item["language"] == case["filters"]["language"]
            # REST pagination must preserve the MCP order across page sizes.
            for page in (1, 2):
                result = await search_catalog_projects(
                    query=cases[0]["query"], page=page, page_size=5,
                    repository_factory=lambda: repository,
                )
                assert [r["full_name"] for r in result["items"]] == observed[cases[0]["id"]][(page-1)*5:page*5]
            # A broken semantic service must retain lexical answers; a noisy one
            # cannot put a famous unrelated archive above complete matches.
            class Semantic:
                def search_repo_ids(self, intent):
                    if self.fail:
                        raise RuntimeError("quality fixture: vector service unavailable")
                    return [{"repo_id": "quality/noisy-archive", "score": 0.999}]

            monkeypatch.setattr(settings, "project_semantic_search_enabled", True)
            for fail in (True, False):
                semantic = Semantic()
                semantic.fail = fail
                result = await search_projects(
                    query=cases[0]["query"], mode="ai", limit=5,
                    repository_factory=lambda: repository,
                    semantic_search_factory=lambda: semantic,
                )
                assert [r["full_name"] for r in result["items"]] == observed[cases[0]["id"]][:5]

        asyncio.run(replay())
        (tmp_path / "quality-python.json").write_text(json.dumps(observed, ensure_ascii=False, indent=2))
        request_path = tmp_path / "quality-input.json"
        response_path = tmp_path / "quality-go.json"
        request_path.write_text(json.dumps(cases, ensure_ascii=False))
        # The trusted local CI image already verifies Go 1.26 for every job.
        subprocess.run([sys.executable, str(ROOT / "scripts/ci/materialize_ui_catalog_fixture.py")],
                       cwd=ROOT, check=True, capture_output=True, text=True)
        result = subprocess.run(
            ["go", "test", "./internal/postgres", "-run", "^TestProjectQualityReplay$", "-count=1"],
            cwd=ROOT / "mcp-go", capture_output=True, text=True, timeout=240,
            env={**os.environ, "TEST_POSTGRES_DSN": sandbox.dsn,
                 "TEST_QUALITY_INPUT": str(request_path), "TEST_QUALITY_OUTPUT": str(response_path)},
        )
        assert result.returncode == 0, result.stdout + result.stderr
        go_results = json.loads(response_path.read_text())
        assert go_results == observed, {"python": observed, "go": go_results}
        pairs = {}
        metrics = []
        for case in cases:
            ids = observed[case["id"]]
            metric = judge(case, ids)
            if metric:
                metrics.append(metric)
            if pair := case.get("pair"):
                if pair in pairs:
                    # Small alias differences may admit an additional result;
                    # top-five relevant answers must be identical bilingually.
                    assert ids[:5] == pairs[pair][:5], (pair, ids, pairs[pair])
                pairs[pair] = ids
        report = {
            "cases": len(cases), "profiles": len(payload["profiles"]),
            "ndcg@5": mean(m["ndcg@5"] for m in metrics),
            "recall@10": mean(m["recall@10"] for m in metrics),
            "mean_latency_ms": mean(durations), "results": observed,
        }
        (tmp_path / "quality-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        assert report["ndcg@5"] >= 0.85, report
        assert report["recall@10"] == 1.0, report
        print(json.dumps({k: v for k, v in report.items() if k != "results"}, ensure_ascii=False))
