"""Pytest 全局隔离：测试进程不得写生产 MCP 工具调用计数文件。

背景：MCP_TOOL_CALL_METRICS 是模块级单例（backend/app/monitoring/mcp_tools.py），
record() 每次都会把计数持久化到 settings.mcp_tool_call_metrics_path
（相对 cwd 的 storage/metrics/mcp_tool_calls.json）。测试经 TestClient 全量
dispatch tools/call 时会与生产共用该文件，污染监控面板读数与 #578 下线评估
的零调用判据。

这里在导入任何 backend.app 模块之前（conftest 先于测试模块加载）把
MCP_TOOL_CALL_METRICS_PATH 指向本进程临时目录；Settings 无 env_prefix，
字段名大写即环境变量名。
"""

from __future__ import annotations

import os
import tempfile

import pytest

os.environ.setdefault(
    "MCP_TOOL_CALL_METRICS_PATH",
    os.path.join(
        tempfile.mkdtemp(prefix="aigcnews-test-metrics-"), "mcp_tool_calls.json"
    ),
)
_EXPECTED_METRICS_PATH = os.environ["MCP_TOOL_CALL_METRICS_PATH"]


@pytest.fixture(scope="session", autouse=True)
def _mcp_metrics_path_isolated() -> None:
    """防导入顺序回归：若 config 先于本 conftest 被导入，单例仍按生产路径创建。"""
    from backend.app.core.config import settings

    assert settings.mcp_tool_call_metrics_path == _EXPECTED_METRICS_PATH, (
        "MCP 工具计数路径未被隔离（实际为 "
        f"{settings.mcp_tool_call_metrics_path}），测试会写生产计数文件；"
        "请检查是否有模块在 conftest 之前导入了 backend.app.core.config。"
    )
