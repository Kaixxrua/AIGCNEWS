from __future__ import annotations

import pytest

from backend.app.services.search_semantics import (
    build_client_project_search_intent,
    build_project_lexical_retrieval_plan,
    build_project_search_intent,
)


def test_project_intent_normalizes_request_and_expands_known_bilingual_concepts() -> None:
    intent = build_project_search_intent("  帮我找一下学习 Agent 工作流的仓库  ")

    assert intent.schema_version == "project-search-intent-v1"
    assert intent.normalized_query == "学习 Agent 工作流的仓库"
    assert intent.language == "mixed"
    assert intent.semantic_queries[0] == intent.normalized_query
    assert "workflow automation" in intent.semantic_queries[1]
    assert intent.lexical_terms == ("Agent", "工作流")


def test_project_intent_extracts_bounded_chinese_concepts_and_aliases() -> None:
    intent = build_project_search_intent(
        "提升 AI 编程智能体编码速度 项目记忆 上下文压缩和任务依赖管理"
    )
    plan = build_project_lexical_retrieval_plan(intent)

    assert intent.lexical_terms == (
        "AI",
        "编程智能体",
        "编码速度",
        "项目记忆",
        "上下文压缩",
        "任务依赖管理",
    )
    assert intent.concept_ids == (
        "coding_assistant",
        "coding_productivity",
        "codebase_memory",
        "context_management",
        "agent_task_tracking",
    )
    assert "codebase memory" in intent.semantic_queries[1]
    assert "context compression" in intent.semantic_queries[1]
    assert plan.strict_terms == ()
    assert {concept.concept_id for concept in plan.concepts} == set(intent.concept_ids)
    assert all(
        alias not in plan.strict_terms
        for concept in plan.concepts
        for alias in concept.aliases
    )


def test_longest_chinese_phrase_wins_and_unknown_name_is_not_translated() -> None:
    intent = build_project_search_intent("星火智能体工作流")

    assert intent.lexical_terms == ("智能体工作流",)
    assert intent.concept_ids == ("workflow",)
    assert intent.intent_class == "general_discovery"
    assert "星火" not in " ".join(intent.bilingual_aliases)


def test_project_intent_preserves_technical_tokens() -> None:
    intent = build_project_search_intent("C++ .NET MCP RAG developer tools")

    assert intent.language == "en"
    assert intent.lexical_terms[:4] == ("C++", ".NET", "MCP", "RAG")
    assert intent.semantic_queries == ("C++ .NET MCP RAG developer tools",)


def test_client_intent_normalizes_deduplicates_and_preserves_server_query() -> None:
    intent = build_client_project_search_intent(
        "帮我找 MCP Python SDK",
        {
            "language": "mixed",
            "intent_class": "sdk",
            "lexical_terms": [" MCP ", "mcp", "Python", "SDK"],
            "semantic_queries": ["MCP Python SDK examples"],
            "topics": ["MCP", "mcp"],
            "languages": ["Python"],
            "artifact_types": ["SDK"],
            "must_have": ["MCP", "Python"],
            "should_have": ["examples"],
        },
    )

    assert intent.schema_version == "project-search-intent-client-v1"
    assert intent.normalized_query == "MCP Python SDK"
    assert intent.lexical_terms == ("MCP", "Python", "SDK")
    assert intent.topics == ("MCP",)


def test_client_intent_rejects_removed_protected_token() -> None:
    with pytest.raises(ValueError, match="protected"):
        build_client_project_search_intent(
            "C++ RAG framework",
            {
                "language": "en",
                "lexical_terms": ["framework"],
                "semantic_queries": ["retrieval framework"],
            },
        )


@pytest.mark.parametrize("control", ["\n", "\x7f", "\x85"])
def test_client_intent_rejects_control_characters(control: str) -> None:
    with pytest.raises(ValueError, match="control"):
        build_client_project_search_intent(
            "agent SDK",
            {
                "language": "en",
                "lexical_terms": [f"agent{control}SDK"],
                "semantic_queries": ["agent SDK"],
            },
        )


def test_client_intent_requires_exact_protected_token() -> None:
    with pytest.raises(ValueError, match="protected"):
        build_client_project_search_intent(
            "MCP SDK",
            {
                "language": "en",
                "lexical_terms": ["xmcp", "SDK"],
                "semantic_queries": ["Python SDK"],
            },
        )


def test_unknown_chinese_name_does_not_fabricate_translation() -> None:
    intent = build_project_search_intent("学习 LangGraph 星火教程")

    assert intent.language == "mixed"
    assert intent.semantic_queries == ("学习 LangGraph 星火教程", "学习 LangGraph 星火教程 tutorial learning")
