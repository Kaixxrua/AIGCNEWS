from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, Request

from backend.app.api.dependencies import get_rag_chat_service
from backend.app.services.rag.composition import RagChatServiceProvider


def _repositories():
    return SimpleNamespace(documents=MagicMock())


def test_provider_lazily_reuses_service_and_closes_owned_readers() -> None:
    vector = MagicMock()
    graph = MagicMock()
    project_searcher = MagicMock()
    provider = RagChatServiceProvider(
        _repositories(),
        vector_reader_factory=MagicMock(return_value=vector),
        graph_reader_factory=MagicMock(return_value=graph),
        project_searcher=project_searcher,
    )

    first = provider.get()
    second = provider.get()
    provider.close()
    provider.close()

    assert first is second
    assert first._project_searcher is project_searcher
    graph.close.assert_called_once_with()
    vector.close.assert_called_once_with()


def test_provider_does_not_construct_graph_when_vector_factory_fails() -> None:
    graph_factory = MagicMock()
    provider = RagChatServiceProvider(
        _repositories(),
        vector_reader_factory=MagicMock(side_effect=RuntimeError("vector failed")),
        graph_reader_factory=graph_factory,
    )

    try:
        provider.get()
    except RuntimeError as exc:
        assert str(exc) == "vector failed"
    else:
        raise AssertionError("provider should propagate composition failure")

    graph_factory.assert_not_called()


def test_provider_closes_vector_when_graph_factory_fails() -> None:
    vector = MagicMock()
    provider = RagChatServiceProvider(
        _repositories(),
        vector_reader_factory=MagicMock(return_value=vector),
        graph_reader_factory=MagicMock(side_effect=RuntimeError("graph failed")),
    )

    try:
        provider.get()
    except RuntimeError as exc:
        assert str(exc) == "graph failed"
    else:
        raise AssertionError("provider should propagate composition failure")

    vector.close.assert_called_once_with()


def test_provider_closes_both_readers_when_composition_fails() -> None:
    vector = MagicMock()
    graph = MagicMock()
    provider = RagChatServiceProvider(
        _repositories(),
        vector_reader_factory=MagicMock(return_value=vector),
        graph_reader_factory=MagicMock(return_value=graph),
    )

    with patch(
        "backend.app.services.rag.composition.HybridRetriever",
        side_effect=RuntimeError("composition failed"),
    ):
        try:
            provider.get()
        except RuntimeError as exc:
            assert str(exc) == "composition failed"
        else:
            raise AssertionError("provider should propagate composition failure")

    graph.close.assert_called_once_with()
    vector.close.assert_called_once_with()


def test_fastapi_dependency_reads_application_provider() -> None:
    app = FastAPI()
    service = MagicMock()
    provider = MagicMock(spec=RagChatServiceProvider)
    provider.get.return_value = service
    app.state.rag_chat_service_provider = provider
    request = MagicMock(spec=Request)
    request.app = app

    assert get_rag_chat_service(request) is service
    provider.get.assert_called_once_with()


def test_chat_route_does_not_construct_rag_infrastructure() -> None:
    path = Path("backend/app/api/routes_chat.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert "MilvusRepository" not in calls
    assert "GraphRepository" not in calls
    assert "HybridRetriever" not in calls
    assert "ChatService" not in calls
    assert "ConversationService" not in calls
    assert "backend.app.repositories.milvus_repo" not in imports
    assert "backend.app.repositories.graph_repo" not in imports
