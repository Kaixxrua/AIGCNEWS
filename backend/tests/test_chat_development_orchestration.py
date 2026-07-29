import asyncio
import types
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.services.rag import chat_service


async def collect(generator):
    return [event async for event in generator]


def make_service():
    retriever = MagicMock()
    retriever.search = AsyncMock(return_value=[])
    return (
        chat_service.ChatService(
            retriever,
            ranking_reader=MagicMock(),
            statistics_reader=MagicMock(),
        ),
        retriever,
    )


def test_direct_request_skips_search_and_tool_decision():
    service, retriever = make_service()

    async def fake_stream(**_kwargs):
        yield types.SimpleNamespace(reasoning="", content="直接实现")

    with patch.object(chat_service, "stream_chat_completions", fake_stream), patch.object(chat_service, "chat_completions") as tool_decision, patch.object(chat_service, "search_projects", new=AsyncMock()) as discovery, patch.object(chat_service, "web_search", new=AsyncMock()) as web:
        events = asyncio.run(collect(service.stream_chat("修改 LoginView.vue 登录按钮文案", web_search_enabled=True)))

    retriever.search.assert_not_called()
    tool_decision.assert_not_called()
    discovery.assert_not_awaited()
    web.assert_not_awaited()
    assert any(event["type"] == "content" for event in events)


def test_complex_request_searches_once_and_stops_at_choice():
    service, retriever = make_service()
    discovery_result = {
        "items": [{
            "id": "github:1", "full_name": "owner/workflow", "url": "https://github.com/owner/workflow",
            "description": "A workflow server platform", "tags": ["platform", "server"],
            "stars": 9000, "language": "Python", "pushed_at": "2026-07-01", "result_origin": "aigc_news_local",
        }],
        "result_origin": "aigc_news_local",
    }
    with patch.object(chat_service, "search_projects", new=AsyncMock(return_value=discovery_result)) as discovery, patch.object(chat_service, "chat_completions") as tool_decision:
        events = asyncio.run(collect(service.stream_chat("开发一个完整的工作流引擎平台，包含前端、后端和数据库")))

    discovery.assert_awaited_once()
    retriever.search.assert_not_called()
    tool_decision.assert_not_called()
    content = "".join(event["data"] for event in events if event["type"] == "content")
    assert "A：复用开源项目" in content
    assert "B：从零开发" in content


def test_follow_up_scratch_does_not_search_again():
    service, _ = make_service()
    history = [{"role": "assistant", "content": "请选择下一步：A 复用；B 从零开发；C 重新搜索"}]

    async def fake_stream(**_kwargs):
        yield types.SimpleNamespace(reasoning="", content="自研方案")

    with patch.object(chat_service, "stream_chat_completions", fake_stream), patch.object(chat_service, "search_projects", new=AsyncMock()) as discovery:
        events = asyncio.run(collect(service.stream_chat("B", history=history)))
    discovery.assert_not_awaited()
    assert "自研方案" in "".join(event["data"] for event in events if event["type"] == "content")
