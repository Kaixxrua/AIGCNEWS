from __future__ import annotations

"""Application-lifetime composition for chat retrieval services."""

from threading import Lock
from typing import Any, Awaitable, Callable

from backend.app.repositories.application_repository_factory import ApplicationRepositories
from backend.app.repositories.graph_repo import GraphRepository
from backend.app.repositories.milvus_repo import MilvusRepository
from backend.app.services.rag.chat_service import ChatService
from backend.app.services.rag.ports import GraphRetrievalReader, VectorRetrievalReader
from backend.app.services.rag.retriever import HybridRetriever

VectorReaderFactory = Callable[[], VectorRetrievalReader]
GraphReaderFactory = Callable[[], GraphRetrievalReader]
ProjectSearcher = Callable[..., Awaitable[dict[str, Any]]]


class RagChatServiceProvider:
    """Lazily build and own the application chat retrieval graph."""

    def __init__(
        self,
        repositories: ApplicationRepositories,
        *,
        vector_reader_factory: VectorReaderFactory = MilvusRepository,
        graph_reader_factory: GraphReaderFactory = GraphRepository,
        project_searcher: ProjectSearcher | None = None,
    ) -> None:
        self._repositories = repositories
        self._vector_reader_factory = vector_reader_factory
        self._graph_reader_factory = graph_reader_factory
        self._project_searcher = project_searcher
        self._lock = Lock()
        self._service: ChatService | None = None
        self._graph_reader: GraphRetrievalReader | None = None

    def get(self) -> ChatService:
        with self._lock:
            if self._service is not None:
                return self._service

            vector_reader = self._vector_reader_factory()
            graph_reader = self._graph_reader_factory()
            try:
                retriever = HybridRetriever(
                    vector_reader,
                    graph_reader,
                    self._repositories.documents,
                    self._repositories.documents,
                )
                service_arguments = {
                    "ranking_reader": self._repositories.documents,
                    "statistics_reader": self._repositories.documents,
                }
                if self._project_searcher is not None:
                    service_arguments["project_searcher"] = self._project_searcher
                service = ChatService(
                    retriever,
                    **service_arguments,
                )
            except Exception:
                close = getattr(graph_reader, "close", None)
                if close is not None:
                    close()
                raise

            self._graph_reader = graph_reader
            self._service = service
            return service

    def close(self) -> None:
        with self._lock:
            graph_reader = self._graph_reader
            self._graph_reader = None
            self._service = None
        if graph_reader is not None:
            close = getattr(graph_reader, "close", None)
            if close is not None:
                close()
