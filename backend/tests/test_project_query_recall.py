from __future__ import annotations

import re

import pytest

from backend.app.domain.project_search_patterns import concept_search_pattern
from backend.app.domain.search_semantics import (
    build_client_project_search_intent,
    build_project_lexical_retrieval_plan,
    build_project_search_intent,
)


@pytest.mark.parametrize(("query", "terms"), [
    ("混元", ("混元",)), ("扣子", ("扣子",)), ("可灵", ("可灵",)),
    ("LangGraph 星火教程", ("LangGraph", "星火")),
    ("星火智能体工作流", ("星火",)),
])
def test_unknown_chinese_names_survive_concept_extraction(query, terms):
    plan = build_project_lexical_retrieval_plan(build_project_search_intent(query))
    assert plan.strict_terms == terms


@pytest.mark.parametrize(("query", "description"), [
    ("教程", "50+ tutorials and implementations for Generative AI Agent techniques"),
    ("tutorial", "End-to-end, code-first tutorials for production-grade GenAI agents"),
    ("workflow", "Automated workflows"), ("workflows", "Automated workflow"),
    ("llm", "tools for LLMs"), ("prompt", "Manage prompts"),
    ("截图", "Take screenshots"),
])
def test_known_inflections_are_recalled_without_substring_matching(query, description):
    plan = build_project_lexical_retrieval_plan(build_project_search_intent(query))
    assert any(
        re.search(concept_search_pattern(term), description, re.I)
        for concept in plan.concepts for term in (*concept.primary_terms, *concept.aliases)
    )


def test_host_lexical_hints_extend_the_original_query_without_duplicates():
    intent = build_client_project_search_intent("混元 RAG", {
        "language": "mixed", "lexical_terms": ["RAG", "offline", "Offline", "教程"],
        "semantic_queries": ["混元 RAG offline tutorials"],
    })
    plan = build_project_lexical_retrieval_plan(intent)
    assert plan.strict_terms == ("混元", "offline")
    assert [concept.concept_id for concept in plan.concepts] == ["rag", "learning"]
