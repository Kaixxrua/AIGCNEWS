from __future__ import annotations

import asyncio
import sys
import types
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

config = types.ModuleType("backend.app.core.config")
config.settings = types.SimpleNamespace(
    thinking_model_name="thinking-model",
    chat_model_name="chat-model",
    llm_temperature=0.2,
    llm_max_tokens=4096,
    mcp_github_fallback_enabled=False,
    mcp_github_fallback_use_token=False,
    mcp_github_fallback_timeout_seconds=8.0,
    github_token="",
)
sys.modules["backend.app.core.config"] = config

langchain_core = types.ModuleType("langchain_core")
langchain_documents = types.ModuleType("langchain_core.documents")


@dataclass
class Document:
    page_content: str
    metadata: dict


langchain_documents.Document = Document
sys.modules.setdefault("langchain_core", langchain_core)
sys.modules.setdefault("langchain_core.documents", langchain_documents)

retriever_module = types.ModuleType("backend.app.services.rag.retriever")
retriever_module.HybridRetriever = object
sys.modules.setdefault("backend.app.services.rag.retriever", retriever_module)
reranker_module = types.ModuleType("backend.app.services.rag.reranker")
reranker_module.RELEVANCE_THRESHOLD = 0.25
reranker_module.rerank = AsyncMock()
sys.modules.setdefault("backend.app.services.rag.reranker", reranker_module)

from backend.app.services.rag import chat_service


async def collect(generator):
    return [event async for event in generator]


def test_non_development_generation_preserves_tool_rag_web_and_source_order():
    retriever = MagicMock()
    vector_doc = Document(
        "vector context",
        {
            "id": "rag-1",
            "retriever": "vector",
            "score": 0.2,
            "source": "arxiv",
            "title": "RAG paper",
            "url": "https://example.test/rag",
        },
    )
    ranked_doc = Document(
        "ranked context",
        {
            "id": "rag-1",
            "retriever": "vector",
            "rerank_score": 8.5,
            "source": "arxiv",
            "title": "RAG paper",
            "url": "https://example.test/rag",
        },
    )
    retriever.search = AsyncMock(return_value=[vector_doc])
    service = chat_service.ChatService(retriever)
    tool_call = chat_service.ToolCallResult(
        id="call-1", name="query_ranking", arguments='{"source":"github","limit":3}'
    )
    decision = chat_service.ChatCompletionResult(tool_calls=[tool_call])
    web_result = chat_service.WebSearchResult(
        title="Web result", url="https://example.test/web", snippet="web context"
    )
    tool_source = {
        "id": "db-1",
        "source": "github",
        "title": "DB project",
        "url": "https://example.test/db",
        "score": 10.0,
        "published_date": "",
    }
    streamed_calls = []

    async def fake_stream(**kwargs):
        streamed_calls.append(kwargs)
        yield types.SimpleNamespace(reasoning="分析", content="回答")

    with (
        patch.object(chat_service, "classify_development_request") as classify,
        patch.object(chat_service, "chat_completions", new=AsyncMock(return_value=decision)) as decide,
        patch.object(chat_service, "web_search", new=AsyncMock(return_value=[web_result])) as web,
        patch.object(chat_service, "rerank", new=AsyncMock(return_value=[ranked_doc])) as rerank,
        patch.object(
            service,
            "_run_tool_calls",
            new=AsyncMock(
                return_value=(
                    [{"role": "tool", "tool_call_id": "call-1", "content": "db data"}],
                    [tool_source],
                    "[db-query] db data",
                )
            ),
        ) as run_tools,
        patch.object(chat_service, "stream_chat_completions", fake_stream),
    ):
        classify.return_value = types.SimpleNamespace(
            route="rag", score=0, reasons=(), search_mode="local"
        )
        events = asyncio.run(
            collect(
                service.stream_chat(
                    "今日有哪些项目？",
                    history=[{"role": "user", "content": "上一问"}],
                    temperature=0.4,
                    web_search_enabled=True,
                )
            )
        )

    assert [event["type"] for event in events] == [
        "status",
        "status",
        "status",
        "sources",
        "thinking",
        "content",
    ]
    assert events[0]["data"] == "searching"
    assert events[1]["data"] == "querying database"
    assert events[2]["data"] == "reranking"
    assert events[3]["data"] == [
        tool_source,
        {
            "id": "rag-1",
            "score": 8.5,
            "source": "arxiv",
            "title": "RAG paper",
            "url": "https://example.test/rag",
            "published_date": "",
        },
        {
            "id": "web-1",
            "score": 0.0,
            "source": "web",
            "title": "Web result",
            "url": "https://example.test/web",
            "published_date": "",
        },
    ]
    retriever.search.assert_awaited_once_with("今日有哪些项目？")
    web.assert_awaited_once_with("今日有哪些项目？", max_results=6)
    rerank.assert_awaited_once_with(
        "今日有哪些项目？", [vector_doc], threshold=0.25
    )
    run_tools.assert_awaited_once_with([tool_call])
    assert decide.await_args.kwargs["tools"] is chat_service.TOOL_DEFINITIONS
    assert decide.await_args.kwargs["tool_choice"] == "auto"
    assert streamed_calls[0]["model"] == "thinking-model"
    assert streamed_calls[0]["temperature"] == 0.4
    assert streamed_calls[0]["max_tokens"] == 4096
    messages = streamed_calls[0]["messages"]
    assert [message["role"] for message in messages] == [
        "system",
        "user",
        "assistant",
        "tool",
        "user",
    ]
    assert messages[2]["tool_calls"][0]["function"] == {
        "name": "query_ranking",
        "arguments": '{"source":"github","limit":3}',
    }
    assert "[db-query] db data" in messages[-1]["content"]
    assert "ranked context" in messages[-1]["content"]
    assert "web context" in messages[-1]["content"]


def test_tool_call_runner_preserves_input_order_and_error_messages():
    calls = [
        chat_service.ToolCallResult("one", "first", '{"value":1}'),
        chat_service.ToolCallResult("missing", "unknown", "{}"),
        chat_service.ToolCallResult("broken", "second", "not-json"),
    ]

    def first(value: int):
        return {
            "formatted": f"first={value}",
            "docs": [{"id": "db-1", "title": "One", "url": "u1"}],
        }

    def second():
        raise RuntimeError("database unavailable")

    with patch.dict(chat_service._TOOL_EXECUTORS, {"first": first, "second": second}):
        messages, sources, context = asyncio.run(chat_service.ChatService._run_tool_calls(calls))

    assert messages == [
        {"role": "tool", "tool_call_id": "one", "content": "first=1"},
        {"role": "tool", "tool_call_id": "missing", "content": "未知工具: unknown"},
        {
            "role": "tool",
            "tool_call_id": "broken",
            "content": "工具执行出错: database unavailable",
        },
    ]
    assert sources == [
        {
            "id": "db-1",
            "score": 0.0,
            "source": "",
            "title": "One",
            "url": "u1",
            "published_date": "",
        }
    ]
    assert context == "[db-query] first=1"
