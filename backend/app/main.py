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
    routes_ops,
    routes_papers,
    routes_report,
    routes_vision,
)
from backend.app.core.auth import validate_jwt_secret
from backend.app.core.config import settings
from backend.app.core.model_factory import (
    configure_model_provider_runtime,
    configure_runtime_provider_settings,
    create_chat_model,
    create_embedding_model,
)
from backend.app.core.operations import ApplicationOperationsRuntime
from backend.app.core.postgres_database import postgres_database
from backend.app.core.scheduler import create_scheduler_runtime
from backend.app.monitoring.health import create_application_monitoring_runtime
from backend.app.repositories.application_repository_context import (
    configure_application_repositories,
)
from backend.app.repositories.application_repository_factory import (
    create_application_repositories,
)
from backend.app.services.project_search_runtime import ApplicationProjectSearchRuntime
from backend.app.services.rag.composition import RagChatServiceProvider
from backend.app.services.runtime_provider.runtime import (
    ApplicationModelProviderRuntime,
)

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


async def _warmup_project_semantic_search(
    runtime: ApplicationProjectSearchRuntime,
) -> None:
    """后台预热项目语义搜索链路，不阻塞服务启动。"""
    try:
        result = await asyncio.to_thread(runtime.warmup_semantic_search)
        print(f"[Startup] Project semantic search warmup: {result.get('status')}.")
    except Exception as exc:
        print(f"[Startup] Project semantic search warmup failed (non-fatal): {exc}")


async def _cancel_background_task(
    task: asyncio.Task[object] | None,
    *,
    name: str,
) -> None:
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        print(f"[Shutdown] {name} task close failed (non-fatal): {exc}")


async def _close_redis_client(redis_client: Redis) -> None:
    close_method = getattr(redis_client, "aclose", None)
    if close_method is not None:
        await close_method()
    else:
        await redis_client.close()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Own application resources from startup through failure-isolated shutdown."""
    # 安全检查必须先于一切资源初始化：公开/缺失的 JWT 密钥等于管理端点完全失守。
    validate_jwt_secret(getattr(settings, "JWT_SECRET_KEY", ""))

    postgres_opened = False
    repositories_configured = False
    project_search_runtime: ApplicationProjectSearchRuntime | None = None
    rag_provider: RagChatServiceProvider | None = None
    semantic_warmup_task: asyncio.Task[object] | None = None
    redis_client: Redis | None = None
    operations_runtime: ApplicationOperationsRuntime | None = None
    model_provider_runtime: ApplicationModelProviderRuntime | None = None
    scheduler_runtime = None

    app.state.database = postgres_database
    app.state.postgres_database = postgres_database
    app.state.application_database_backend = "postgres"
    app.state.redis = None
    app.state.project_search_runtime = None
    app.state.monitoring_runtime = None
    app.state.operations_runtime = None
    app.state.model_provider_runtime = None

    try:
        await asyncio.to_thread(postgres_database.open)
        postgres_opened = True
        app.state.monitoring_runtime = create_application_monitoring_runtime(
            postgres=postgres_database,
        )
        app.state.application_repositories = create_application_repositories(
            postgres=postgres_database,
        )
        configure_application_repositories(app.state.application_repositories)
        configure_runtime_provider_settings(
            app.state.application_repositories.runtime_provider_settings
        )
        repositories_configured = True
        operations_runtime = ApplicationOperationsRuntime(
            shutdown_grace_seconds=float(
                getattr(settings, "operations_shutdown_grace_seconds", 30.0)
            )
        )
        app.state.operations_runtime = operations_runtime
        model_provider_runtime = ApplicationModelProviderRuntime(
            chat_factory=create_chat_model,
            embedding_factory=create_embedding_model,
        )
        configure_model_provider_runtime(model_provider_runtime)
        app.state.model_provider_runtime = model_provider_runtime
        project_search_runtime = ApplicationProjectSearchRuntime()
        app.state.project_search_runtime = project_search_runtime
        rag_provider = RagChatServiceProvider(
            app.state.application_repositories,
            project_searcher=project_search_runtime.search_projects,
        )
        app.state.rag_chat_service_provider = rag_provider

        # 在后台异步预热项目语义搜索，不阻塞服务启动
        if settings.project_semantic_search_enabled:
            semantic_warmup_task = asyncio.create_task(
                _warmup_project_semantic_search(project_search_runtime)
            )
            app.state.semantic_warmup_task = semantic_warmup_task

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

            FastAPICache.reset()
            FastAPICache.init(
                RedisBackend(redis_client),
                prefix="aigc-cache:",
            )
            app.state.redis = redis_client
            print("[Startup] Redis cache initialized.")
        except Exception as exc:
            app.state.redis = None
            FastAPICache.reset()
            if redis_client is not None:
                try:
                    await _close_redis_client(redis_client)
                except Exception as close_exc:
                    print(
                        "[Startup] Redis close after init failure failed "
                        f"(non-fatal): {close_exc}"
                    )
                else:
                    redis_client = None
            print(f"[Startup] Redis cache init failed (non-fatal): {exc}")

        scheduler_enabled = bool(getattr(settings, "scheduler_enabled", True))
        scheduler_runtime = create_scheduler_runtime(
            app.state.application_repositories,
            enabled=scheduler_enabled,
            semantic_search_warmup=(
                project_search_runtime.warmup_semantic_search
            ),
        )
        app.state.scheduler_runtime = scheduler_runtime
        if scheduler_enabled:
            scheduler_runtime.start()

        yield
    finally:
        if scheduler_runtime is not None:
            try:
                await scheduler_runtime.stop()
            except Exception as exc:
                print(f"[Shutdown] Scheduler close failed (non-fatal): {exc}")
        if operations_runtime is not None:
            try:
                await operations_runtime.stop()
            except Exception as exc:
                print(f"[Shutdown] Operations close failed (non-fatal): {exc}")
            finally:
                app.state.operations_runtime = None

        await _cancel_background_task(
            semantic_warmup_task,
            name="Project semantic search warmup",
        )
        if project_search_runtime is not None:
            try:
                await project_search_runtime.close()
            except Exception as exc:
                print(f"[Shutdown] Project search runtime close failed (non-fatal): {exc}")
            finally:
                app.state.project_search_runtime = None

        FastAPICache.reset()
        if redis_client is not None:
            try:
                await _close_redis_client(redis_client)
                print("[Shutdown] Redis cache connection closed.")
            except Exception as exc:
                print(f"[Shutdown] Redis close failed (non-fatal): {exc}")
            finally:
                app.state.redis = None

        if rag_provider is not None:
            try:
                rag_provider.close()
            except Exception as exc:
                print(f"[Shutdown] RAG provider close failed (non-fatal): {exc}")
        if model_provider_runtime is not None:
            try:
                await model_provider_runtime.close()
            except Exception as exc:
                print(f"[Shutdown] Model provider runtime close failed (non-fatal): {exc}")
            finally:
                configure_model_provider_runtime(None)
                app.state.model_provider_runtime = None
        if repositories_configured:
            try:
                configure_runtime_provider_settings(None)
                configure_application_repositories(None)
            except Exception as exc:
                print(f"[Shutdown] Repository context close failed (non-fatal): {exc}")
        app.state.monitoring_runtime = None
        if postgres_opened:
            try:
                postgres_database.close()
                print("[Shutdown] PostgreSQL connection pool closed.")
            except Exception as exc:
                print(f"[Shutdown] PostgreSQL close failed (non-fatal): {exc}")


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

# 配置 CORS：仅允许白名单来源（本地开发 + 生产域名），不再通配。
_cors_allowed_origins = [
    origin.strip()
    for origin in getattr(settings, "cors_allowed_origins", "").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allowed_origins,
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
