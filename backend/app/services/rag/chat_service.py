from __future__ import annotations

from typing import Any, AsyncGenerator, Dict, List

from backend.app.repositories.document_repository import (
    DocumentRankingReader,
    DocumentStatisticsReader,
)
from backend.app.services.project_discovery import search_projects
from backend.app.services.rag.database_tools import TOOL_DEFINITIONS, run_tool_calls
from backend.app.services.rag.development_orchestrator import classify_development_request
from backend.app.services.rag.generator import GenerationOrchestrator, MAX_HISTORY_TURNS
from backend.app.services.rag.raw_openai_streamer import (
    ChatCompletionResult,
    ToolCallResult,
    chat_completions,
    stream_chat_completions,
)
from backend.app.services.rag.reranker import rerank
from backend.app.services.rag.retriever import HybridRetriever
from backend.app.services.rag.web_search_service import (
    WebSearchResult,
    format_search_results_as_context,
    web_search,
)


class ChatService:
    def __init__(
        self,
        retriever: HybridRetriever,
        *,
        ranking_reader: DocumentRankingReader,
        statistics_reader: DocumentStatisticsReader,
    ) -> None:
        self.retriever = retriever
        self._ranking_reader = ranking_reader
        self._statistics_reader = statistics_reader

    async def _run_tool_calls(self, tool_calls: List[ToolCallResult]):
        return await run_tool_calls(
            tool_calls,
            ranking_reader=self._ranking_reader,
            statistics_reader=self._statistics_reader,
        )

    async def stream_chat(
        self,
        query: str,
        history: List[Dict[str, str]] | None = None,
        max_history_turns: int = MAX_HISTORY_TURNS,
        temperature: float | None = None,
        web_search_enabled: bool = False,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        orchestrator = GenerationOrchestrator(
            self.retriever,
            stream_completion=stream_chat_completions,
            completion=chat_completions,
            web_searcher=web_search,
            web_context_formatter=format_search_results_as_context,
            reranker=rerank,
            database_tool_runner=self._run_tool_calls,
            tool_definitions=TOOL_DEFINITIONS,
            development_classifier=classify_development_request,
            project_searcher=search_projects,
        )
        async for event in orchestrator.stream_chat(
            query,
            history=history,
            max_history_turns=max_history_turns,
            temperature=temperature,
            web_search_enabled=web_search_enabled,
        ):
            yield event
