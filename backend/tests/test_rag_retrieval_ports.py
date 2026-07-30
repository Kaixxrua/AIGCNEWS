from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock

from langchain_core.documents import Document

from backend.app.services.rag.chat_service import ChatService
from backend.app.services.rag.generator import GenerationOrchestrator
from backend.app.services.rag.retriever import HybridRetriever


class FakeVectorReader:
    def is_available(self) -> bool:
        return True

    def search(self, query: str, top_k: int = 5) -> list[Document]:
        return []

    def search_by_source(self, source: str, top_k: int = 3) -> list[Document]:
        return []


class FakeGraphReader:
    def search(self, keywords: list[str], limit: int = 5) -> list[Document]:
        return []


class FakeRagRetriever:
    async def search(self, query: str, top_k: int = 5) -> list[Document]:
        return []


def test_hybrid_retriever_accepts_protocol_shaped_readers_without_model_construction() -> None:
    vector = FakeVectorReader()
    graph = FakeGraphReader()
    documents = MagicMock()

    retriever = HybridRetriever(vector, graph, documents, documents)

    assert retriever._milvus_repo is vector
    assert retriever._graph_repo is graph
    assert not hasattr(retriever, "_embeddings")
    assert not hasattr(retriever, "_llm")


def test_chat_consumers_accept_protocol_shaped_retriever() -> None:
    retriever = FakeRagRetriever()

    service = ChatService(
        retriever,
        ranking_reader=MagicMock(),
        statistics_reader=MagicMock(),
    )
    orchestrator = GenerationOrchestrator(
        retriever,
        project_searcher=MagicMock(),
    )

    assert service.retriever is retriever
    assert orchestrator.retriever is retriever


def test_rag_consumers_do_not_import_concrete_retriever_adapters() -> None:
    paths = [
        Path("backend/app/services/rag/retriever.py"),
        Path("backend/app/services/rag/chat_service.py"),
        Path("backend/app/services/rag/generator.py"),
    ]
    forbidden = {
        "backend.app.core.model_factory",
        "backend.app.repositories.graph_repo",
        "backend.app.repositories.milvus_repo",
    }

    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert imports.isdisjoint(forbidden), path
