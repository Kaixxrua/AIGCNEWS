from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from redis.asyncio import Redis
from starlette.middleware.base import BaseHTTPMiddleware

from backend.app.api import (
    routes_attachments,
    routes_auth,
    routes_chat,
    routes_dashboard,
    routes_github_projects,
    routes_mcp,
    routes_monitor,
    routes_papers,
    routes_report,
    routes_vision,
)
from backend.app.api import routes_ops
from backend.app.core.config import settings
from backend.app.core.database import mysql_database
from backend.app.core.postgres_database import postgres_database
from backend.app.core.scheduler import start_scheduler, stop_scheduler


# ── 访客统计中间件 ─────────────────────────────────────────────────────────────
# 使用 Redis SET 记录每天不同 IP 地址的访问者
# Key 格式：visitor:{YYYY-MM-DD}（CST 时区），TTL 48 小时，自动过期清理
_VISITOR_EXCLUDE_PREFIXES = ("/api/media/",)  # 静态文件


class VisitorTrackingMiddleware(BaseHTTPMiddleware):
    """统计今日独立访客 IP：每次 HTTP 请求将来源 IP 写入 Redis SET。"""

    async def dispatch(self, request: Request, call_next):
        # 排除静态资源路径
        path = request.url.path
        if not any(path.startswith(p) for p in _VISITOR_EXCLUDE_PREFIXES):
            redis_client: Redis | None = getattr(request.app.state, "redis", None)
            if redis_client is not None:
                # 获取真实 IP（支持反向代理 X-Forwarded-For）
                forwarded_for = request.headers.get("x-forwarded-for")
                if forwarded_for:
                    ip = forwarded_for.split(",")[0].strip()
                else:
                    ip = request.client.host if request.client else "unknown"

                tz_cst = timezone(timedelta(hours=8))
                today_str = datetime.now(tz_cst).strftime("%Y-%m-%d")
                redis_key = f"visitor:{today_str}"
                try:
                    await redis_client.sadd(redis_key, ip)
                    await redis_client.expire(redis_key, 48 * 3600)  # 48 小时 TTL
                except Exception:
                    pass  # Redis 不可用时静默忽略，不影响正常请求

        return await call_next(request)


async def _warmup_reranker() -> None:
    """后台预热 Cross-Encoder 模型，不阻塞服务启动。"""
    try:
        from backend.app.services.rag.reranker import _get_cross_encoder

        await _get_cross_encoder()
        print("[Startup] Cross-Encoder model warmed up.")
    except Exception as exc:
        print(f"[Startup] Cross-Encoder warmup failed (non-fatal): {exc}")


async def _warmup_project_semantic_search() -> None:
    """后台预热项目语义搜索链路，不阻塞服务启动。"""
    try:
        from backend.app.services.project_semantic_search import (
            warmup_project_semantic_search,
        )

        result = await asyncio.to_thread(warmup_project_semantic_search)
        print(f"[Startup] Project semantic search warmup: {result.get('status')}.")
    except Exception as exc:
        print(f"[Startup] Project semantic search warmup failed (non-fatal): {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan：启动时预热模型、初始化 Redis Cache、开启调度器；关闭时优雅释放资源。"""
    app.state.database = mysql_database
    app.state.postgres_database = postgres_database
    project_catalog_backend = str(settings.project_catalog_backend or "").strip().lower()
    postgres_required = (
        project_catalog_backend == "postgres"
        or bool(getattr(settings, "project_catalog_sync_worker_enabled", False))
    )
    shadow_requested = (
        project_catalog_backend == "mysql"
        and bool(getattr(settings, "project_catalog_shadow_enabled", False))
        and str(
            getattr(settings, "project_catalog_shadow_backend", "postgres") or ""
        ).strip().lower()
        == "postgres"
    )
    postgres_opened = False
    if postgres_required:
        await asyncio.to_thread(postgres_database.open)
        postgres_opened = True
    elif shadow_requested:
        try:
            await asyncio.to_thread(postgres_database.open)
            postgres_opened = True
        except Exception as exc:
            print(
                "[Startup] Project catalog shadow unavailable "
                f"(non-fatal): {type(exc).__name__}"
            )
    if shadow_requested and postgres_opened:
        from backend.app.services.project_catalog_shadow import (
            start_project_catalog_shadow,
        )

        start_project_catalog_shadow(settings)

    # 在后台异步预热模型，不阻塞服务启动
    asyncio.create_task(_warmup_reranker())
    semantic_warmup_task = None
    if settings.project_semantic_search_enabled:
        semantic_warmup_task = asyncio.create_task(_warmup_project_semantic_search())
        app.state.semantic_warmup_task = semantic_warmup_task

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

        # 开发环境：热重载时自动清除 API 缓存（aigc-cache:* 前缀），实现"保存即刷新"零感知体验
        # 注意：不能用 flushdb()，会清除 SMS 验证码等业务数据
        if settings.env.lower() in ("development", "dev"):
            cache_keys = await redis_client.keys("aigc-cache:*")
            if cache_keys:
                await redis_client.delete(*cache_keys)
                print(
                    f"[Startup][DEV] Cleared {len(cache_keys)} cache keys — reload complete."
                )
            else:
                print("[Startup][DEV] No cache keys to clear.")

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
        if semantic_warmup_task is not None and not semantic_warmup_task.done():
            semantic_warmup_task.cancel()
            try:
                await semantic_warmup_task
            except asyncio.CancelledError:
                pass
        try:
            from backend.app.services.project_semantic_search import (
                close_project_semantic_search,
            )

            await asyncio.to_thread(close_project_semantic_search)
        except Exception as exc:
            print(f"[Shutdown] Project semantic search close failed (non-fatal): {exc}")
        try:
            from backend.app.services.project_reranker import close_project_reranker

            await close_project_reranker()
        except Exception as exc:
            print(f"[Shutdown] Project reranker close failed (non-fatal): {exc}")
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
        if shadow_requested:
            from backend.app.services.project_catalog_shadow import (
                stop_project_catalog_shadow,
            )

            await asyncio.to_thread(
                stop_project_catalog_shadow,
                float(
                    getattr(
                        settings,
                        "project_catalog_shadow_shutdown_timeout_seconds",
                        5.0,
                    )
                ),
            )
        if postgres_opened:
            postgres_database.close()
            print("[Shutdown] PostgreSQL connection pool closed.")
        mysql_database.close()
        print("[Shutdown] MySQL connection pool closed.")


app = FastAPI(
    title="RAG AIGC Agent API",
    version="1.0.0",
    lifespan=lifespan,
)

# ── 静态文件：挂载 PDF 存储目录，前端可通过 /api/media/papers/{arxiv_id}.pdf 访问 ──
_papers_dir = settings.papers_storage_dir
os.makedirs(_papers_dir, exist_ok=True)
app.mount(
    "/api/media/papers",
    StaticFiles(directory=_papers_dir),
    name="papers",
)

# 配置 CORS：允许前端 (localhost:5173) 访问后端
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Mcp-Session-Id", "MCP-Protocol-Version"],
)

# 访客统计中间件（在 CORS 之后注册，确保跨域预检请求不计入访客）
app.add_middleware(VisitorTrackingMiddleware)

app.include_router(routes_auth.router, prefix="/api", tags=["Auth"])
app.include_router(routes_chat.router, prefix="/api", tags=["Chat"])
app.include_router(routes_attachments.router, prefix="/api", tags=["Attachments"])
app.include_router(routes_vision.router, prefix="/api", tags=["Vision"])
app.include_router(routes_papers.router, prefix="/api", tags=["Papers"])
app.include_router(routes_dashboard.router, prefix="/api", tags=["Dashboard"])
app.include_router(routes_github_projects.router, prefix="/api", tags=["GitHub Projects"])
app.include_router(routes_mcp.router, prefix="/api", tags=["MCP"])
app.include_router(routes_monitor.router, prefix="/api", tags=["Monitor"])
app.include_router(routes_report.router, prefix="/api", tags=["Report"])
app.include_router(routes_ops.router, prefix="/api", tags=["Ops"])
