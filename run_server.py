from __future__ import annotations

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "backend.app.main:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
        # 只监听 backend/ 和 frontend/ 下的 Python 文件变化，排除 docker/volumes 等大目录
        reload_dirs=["backend"],
        reload_excludes=["docker/*", "data/*", ".venv/*", "*.pyc"],
    )
