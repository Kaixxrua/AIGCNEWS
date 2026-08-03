from __future__ import annotations

import uvicorn

from backend.app.core.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "backend.app.main:app",
        # 监听地址与端口统一由 settings（API_HOST / API_PORT）提供，
        # 消除 run_server / settings / 部署文档三处真相。
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
        # 只监听 backend/ 下的 Python 文件变化，排除 docker/volumes 等大目录
        reload_dirs=["backend"],
        reload_excludes=["docker/*", "data/*", ".venv/*", "*.pyc"],
    )
