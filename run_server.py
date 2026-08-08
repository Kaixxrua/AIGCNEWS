from __future__ import annotations

import uvicorn

from backend.app.core.config import settings

# 热重载只允许开发环境：生产（默认 ENV=production）必须为 False，
# 避免文件监听与多 worker 语义在生产进程上引入不确定行为。
_DEV_RELOAD = settings.env.lower() in ("development", "dev")

if __name__ == "__main__":
    uvicorn.run(
        "backend.app.main:app",
        # 监听地址与端口统一由 settings（API_HOST / API_PORT）提供，
        # 消除 run_server / settings / 部署文档三处真相。
        host=settings.api_host,
        port=settings.api_port,
        reload=_DEV_RELOAD,
        # 只监听 backend/ 下的 Python 文件变化，排除 docker/volumes 等大目录
        reload_dirs=["backend"] if _DEV_RELOAD else None,
        reload_excludes=["docker/*", "data/*", ".venv/*", "*.pyc"] if _DEV_RELOAD else None,
    )
