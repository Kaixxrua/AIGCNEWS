from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI, Request

from backend.app.api.dependencies import get_rag_chat_service
from backend.app.services.rag.composition import RagChatServiceProvider


def _repositories():
    return SimpleNamespace(documents=MagicMock())


def test_provider_lazily_reuses_service_and_closes_owned_graph_reader() -> None:
    vector = MagicMock()
    graph = MagicMock()
    provider = RagChatServiceProvider(
        _repositories(),
        vector_reader_factory=MagicMock(return_value=vector),
        graph_reader_factory=MagicMock(return_value=graph),
    )

    first = provider.get()
    second = provider.get()
    provider.close()

    assert first is second
    graph.close.assert_called_once_with()


def test_provider_closes_graph_reader_when_composition_fails() -> None:
    graph = MagicMock()
    provider = RagChatServiceProvider(
        _repositories(),
        vector_reader_factory=MagicMock(side_effect=RuntimeError("vector failed")),
        graph_reader_factory=MagicMock(return_value=graph),
    )

    try:
        provider.get()
    except RuntimeError as exc:
        assert str(exc) == "vector failed"
    else:
        raise AssertionError("provider should propagate composition failure")

    graph.close.assert_not_called()


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
    assert "backend.app.repositories.milvus_repo" not in imports
    assert "backend.app.repositories.graph_repo" not in imports
