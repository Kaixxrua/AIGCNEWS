"""应用版本唯一真实来源：仓库根 server.json（MCP registry 清单）。

主应用（main.py）与独立 MCP 进程（mcp_main.py）共用此解析，
保证 /api/version 与 MCP serverInfo 在任何部署形态下同源。
"""

from __future__ import annotations

import json
from pathlib import Path


def resolve_app_version() -> str:
    """版本真实来源：仓库根 server.json（MCP registry 清单，由契约测试与
    MCP_SERVER_VERSION 保持一致）。容器内无该文件时回退到代码内常量。"""
    try:
        manifest = Path(__file__).resolve().parents[3] / "server.json"
        document = json.loads(manifest.read_text(encoding="utf-8"))
        version = document.get("version")
        if isinstance(version, str) and version.strip():
            return version.strip()
    except (OSError, ValueError):
        pass
    from backend.app.services.mcp.inbound.catalog import MCP_SERVER_VERSION

    return MCP_SERVER_VERSION
