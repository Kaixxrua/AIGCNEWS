from __future__ import annotations

from backend.app.services.search_semantics import build_project_search_intent


def test_project_intent_normalizes_request_and_expands_known_bilingual_concepts() -> None:
    intent = build_project_search_intent("  帮我找一下学习 Agent 工作流的仓库  ")

    assert intent.schema_version == "project-search-intent-v1"
    assert intent.normalized_query == "学习 Agent 工作流的仓库"
    assert intent.language == "mixed"
    assert intent.semantic_queries[0] == intent.normalized_query
    assert "workflow automation" in intent.semantic_queries[1]
    assert isinstance(intent.lexical_terms, tuple)


def test_project_intent_preserves_technical_tokens() -> None:
    intent = build_project_search_intent("C++ .NET MCP RAG developer tools")

    assert intent.language == "en"
    assert intent.lexical_terms[:4] == ("C++", ".NET", "MCP", "RAG")
    assert intent.semantic_queries == ("C++ .NET MCP RAG developer tools",)


def test_unknown_chinese_name_does_not_fabricate_translation() -> None:
    intent = build_project_search_intent("学习 LangGraph 星火教程")

    assert intent.language == "mixed"
    assert intent.semantic_queries == ("学习 LangGraph 星火教程", "学习 LangGraph 星火教程 tutorial learning")
