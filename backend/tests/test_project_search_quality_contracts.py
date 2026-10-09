import pytest

from backend.app.domain.search_semantics import build_project_lexical_retrieval_plan, build_project_search_intent
from backend.app.repositories.project_catalog import ProjectLexicalCandidate
from backend.app.services.project_search_ranking import rank_v2_project_candidate_ids


@pytest.mark.parametrize("query", ["RAG 评估框架", "RAG evaluation framework", "RAG evaluation tools"])
def test_artifact_words_do_not_exclude_cross_language_implementations(query):
    plan = build_project_lexical_retrieval_plan(build_project_search_intent(query))
    assert not plan.strict_terms
    assert {c.concept_id for c in plan.concepts} == {"rag", "llm_evaluation"}
    rag = next(c for c in plan.concepts if c.concept_id == "rag")
    assert "knowledge base" not in rag.aliases
    assert "知识库" not in rag.aliases


@pytest.mark.parametrize("query, expected", [
    ("framework", ("framework",)),
    ("Frobnicator RAG framework", ("Frobnicator",)),
    ("混元 RAG 工具", ("混元",)),
])
def test_unknown_names_and_bare_artifact_names_remain_literal(query, expected):
    plan = build_project_lexical_retrieval_plan(build_project_search_intent(query))
    assert plan.strict_terms == expected


def test_explicit_knowledge_base_query_retains_broad_recall():
    plan = build_project_lexical_retrieval_plan(build_project_search_intent("知识库"))
    assert "knowledge base" in plan.concepts[0].aliases


@pytest.mark.parametrize("query", ["Agent 任务跟踪", "agent task tracking"])
def test_task_tracking_is_one_specific_bilingual_concept(query):
    plan = build_project_lexical_retrieval_plan(build_project_search_intent(query))
    assert not plan.strict_terms
    assert [c.concept_id for c in plan.concepts] == ["agent_task_tracking"]
    assert "persistent memory" not in plan.concepts[0].aliases


def test_codebase_memory_does_not_mean_any_coding_assistant():
    plan = build_project_lexical_retrieval_plan(build_project_search_intent("代码库持久记忆"))
    assert "编程智能体" not in plan.concepts[0].aliases
    assert "knowledge graph" not in plan.concepts[0].aliases


def test_capability_evidence_and_requested_artifact_outrank_fame_and_vector_noise():
    candidates = [
        ProjectLexicalCandidate("archive/mentions", "strict", 2, profile_score=0),
        ProjectLexicalCandidate("course/tutorial", "strict", 2, profile_score=2, artifact_mismatch=True),
        ProjectLexicalCandidate("tool/evaluator", "strict", 2, profile_score=2),
    ]
    result = rank_v2_project_candidate_ids(
        candidates, candidates, ["archive/mentions", "course/tutorial"],
        adoption_stars={"archive/mentions": 1_000_000, "course/tutorial": 200_000, "tool/evaluator": 600},
        adoption_weight=0.006,
    )
    assert result == ["tool/evaluator", "archive/mentions", "course/tutorial"]
    assert rank_v2_project_candidate_ids(
        candidates, candidates, [], exact_repo_id="course/tutorial",
    )[0] == "course/tutorial"
