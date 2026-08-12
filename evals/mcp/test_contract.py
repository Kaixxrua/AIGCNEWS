"""契约层测评：绕开 LLM，直接调用 aigc-radar 的全部 8 个工具。

（legacy 工具 get_project_library 已于 e703a17 从 server 删除，不在覆盖范围。）

验证内容（全部确定性断言，不消耗 LLM token）：
- 调用不返回 MCP 错误（isError=False）
- 返回内容为非空 JSON
- 关键字段存在（与各工具的公开契约一致）

pytest 下使用 mcp-eval 的 `mcp_session` fixture（@task 装饰器模式仅供
mcp-eval 自己的 runner 使用，在 pytest 里会与 fixture 解析冲突）。
"""

import json

import pytest

# 本套件依赖独立 .venv 中的 mcp-eval（见 README）；backend 开发环境
# 全量收集时优雅跳过，而不是 collection error。
pytest.importorskip("mcp_eval", reason="mcp-eval 未安装（见 evals/mcp/README.md）")


def _raw(mcp_session):
    """TestAgent 不转发 call_tool，取其内部 mcp_agent.Agent。"""
    return mcp_session.agent.agent


def _payload(result):
    """从 CallToolResult 提取 JSON payload，做统一前置断言。"""
    assert not result.isError, f"工具返回错误: {result.content}"
    assert result.content, "工具返回内容为空"
    text = result.content[0].text
    assert text and text.strip(), "文本载荷为空"
    return json.loads(text)


async def test_contract_search_github_ai_projects(mcp_session):
    data = _payload(
        await _raw(mcp_session).call_tool(
            "search_github_ai_projects", {"q": "RAG framework", "limit": 3}
        )
    )
    assert isinstance(data.get("items"), list) and data["items"], "items 应为非空列表"
    assert data.get("total", 0) > 0
    first = data["items"][0]
    assert first.get("full_name") and first.get("url") and "stars" in first


async def test_contract_search_github_projects(mcp_session):
    data = _payload(
        await _raw(mcp_session).call_tool(
            "search_github_projects", {"q": "screenshot", "limit": 3}
        )
    )
    assert isinstance(data.get("items"), list) and data["items"]
    assert all(item.get("stars", 0) >= 500 for item in data["items"]), "违反 500 星下限"


async def test_contract_search_papers(mcp_session):
    data = _payload(
        await _raw(mcp_session).call_tool(
            "search_papers", {"q": "mixture of experts", "limit": 3}
        )
    )
    assert isinstance(data.get("items"), list) and data["items"]
    first = data["items"][0]
    assert first.get("id") and first.get("title")
    assert isinstance(first.get("authors"), list) and first["authors"], "arXiv 条目应暴露非空作者数组"
    assert first.get("arxiv_id"), "arXiv 条目应暴露 arxiv_id"


async def test_contract_search_documents(mcp_session):
    data = _payload(
        await _raw(mcp_session).call_tool(
            "search_documents", {"q": "OpenAI", "source": "news", "limit": 3}
        )
    )
    assert isinstance(data.get("items"), list), "items 应为列表（允许为空）"


async def test_contract_get_paper_detail(mcp_session):
    search = _payload(
        await _raw(mcp_session).call_tool("search_papers", {"q": "attention", "limit": 1})
    )
    paper_id = search["items"][0]["id"]
    detail = _payload(
        await _raw(mcp_session).call_tool("get_paper_detail", {"paper_id": paper_id})
    )
    assert detail, "详情载荷不应为空"
    item = detail["item"]
    assert isinstance(item.get("authors"), list) and item["authors"], "详情应暴露非空作者数组"
    assert item.get("arxiv_id"), "详情应暴露 arxiv_id"


async def test_contract_get_top_items(mcp_session):
    data = _payload(
        await _raw(mcp_session).call_tool(
            "get_top_items", {"source": "github", "period": "daily", "limit": 3}
        )
    )
    assert isinstance(data.get("items"), list) and data["items"]
    assert data["items"][0].get("full_name") or data["items"][0].get("title")


async def test_contract_get_project_categories(mcp_session):
    data = _payload(await _raw(mcp_session).call_tool("get_project_categories", {}))
    assert data, "分类载荷不应为空"


async def test_contract_search_my_project_favorites(mcp_session):
    data = _payload(
        await _raw(mcp_session).call_tool(
            "search_my_project_favorites", {"q": "MCP", "limit": 3}
        )
    )
    assert isinstance(data.get("items"), list), "items 应为列表（收藏为空也合法）"
