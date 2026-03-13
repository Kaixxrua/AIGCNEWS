from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from redis.asyncio import Redis

from backend.app.api import routes_chat, routes_dashboard, routes_monitor, routes_report
from backend.app.api import routes_ops
from backend.app.core.config import settings
from backend.app.core.scheduler import start_scheduler, stop_scheduler


async def _warmup_reranker() -> None:
    """后台预热 Cross-Encoder 模型，不阻塞服务启动。"""
    try:
        from backend.app.services.rag.reranker import _get_cross_encoder

        await _get_cross_encoder()
        print("[Startup] Cross-Encoder model warmed up.")
    except Exception as exc:
        print(f"[Startup] Cross-Encoder warmup failed (non-fatal): {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan：启动时预热模型、初始化 Redis Cache、开启调度器；关闭时优雅释放资源。"""
    # 在后台异步预热 Cross-Encoder 模型，不阻塞服务启动
    asyncio.create_task(_warmup_reranker())

    redis_client: Redis | None = None
    try:
        redis_client = Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
            password=settings.redis_password or None,
            decode_responses=False,
        )
        await redis_client.ping()
        FastAPICache.init(
            RedisBackend(redis_client),
            prefix="aigc-cache:",
        )
        app.state.redis = redis_client
        print("[Startup] Redis cache initialized.")
    except Exception as exc:
        app.state.redis = None
        print(f"[Startup] Redis cache init failed (non-fatal): {exc}")

    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()
        redis_in_app = getattr(app.state, "redis", None)
        if redis_in_app is not None:
            try:
                close_method = getattr(redis_in_app, "aclose", None)
                if close_method is not None:
                    await close_method()
                else:
                    await redis_in_app.close()
                print("[Shutdown] Redis cache connection closed.")
            except Exception as exc:
                print(f"[Shutdown] Redis close failed (non-fatal): {exc}")


app = FastAPI(
    title="RAG AIGC Agent API",
    version="1.0.0",
    lifespan=lifespan,
)

# 配置 CORS：允许前端 (localhost:5173) 访问后端
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_chat.router, prefix="/api", tags=["Chat"])
app.include_router(routes_dashboard.router, prefix="/api", tags=["Dashboard"])
app.include_router(routes_monitor.router, prefix="/api", tags=["Monitor"])
app.include_router(routes_report.router, prefix="/api", tags=["Report"])
app.include_router(routes_ops.router, prefix="/api", tags=["Ops"])
