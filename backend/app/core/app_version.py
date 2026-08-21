"""应用版本唯一真实来源：仓库根 server.json（MCP registry 清单）。

任何部署形态下 /api/version 与 MCP serverInfo 同源；容器内无该文件时
回退到下方代码内常量。
"""

from __future__ import annotations

import json
from pathlib import Path

# 容器内无 server.json 时的回退版本。入站 MCP 栈退役（W6）后不再从
# services.mcp 取常量；与清单同值由 tests/test_api_version_endpoint.py 守住。
_FALLBACK_APP_VERSION = "1.2.0"


def resolve_app_version() -> str:
    """版本真实来源：仓库根 server.json（MCP registry 清单）。容器内无该
    文件时回退到 _FALLBACK_APP_VERSION。"""
    try:
        manifest = Path(__file__).resolve().parents[3] / "server.json"
        document = json.loads(manifest.read_text(encoding="utf-8"))
        version = document.get("version")
        if isinstance(version, str) and version.strip():
            return version.strip()
    except (OSError, ValueError):
        pass
    return _FALLBACK_APP_VERSION
