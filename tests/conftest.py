"""私有测试路径注入：让 backend.*（公共仓）与 aigcnews_private.*（本仓）同时可导入。

公共仓位置解析顺序：
1. 环境变量 ``AIGCNEWS_PUBLIC_REPO``（绝对路径）；
2. 本仓的同级兄弟检出 ``../AIGCNEWS``（本机既定布局）。

运行方式（本机）：``backend/.venv/bin/python -m pytest aigcnews_private/tests``，
或任意 Python 环境 ``python -m pytest tests``（需已安装公共仓依赖 + twitter-cli，
见 README.md 的运行时供给章节）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_PRIVATE_ROOT = Path(__file__).resolve().parents[1]


def _resolve_public_repo() -> Path:
    env = os.environ.get("AIGCNEWS_PUBLIC_REPO")
    if env:
        return Path(env).resolve()
    return (_PRIVATE_ROOT.parent / "AIGCNEWS").resolve()


for path in (str(_PRIVATE_ROOT), str(_resolve_public_repo())):
    if path not in sys.path:
        sys.path.insert(0, path)
