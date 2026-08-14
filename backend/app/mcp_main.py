"""独立 MCP 进程（AIGC Radar MCP）的 ASGI 入口。

与主应用（main.py）同代码、同镜像、不同进程：主站迭代/重启不再中断
MCP 长连接会话。行为兼容性由契约测试锁定（tests/test_mcp_standalone_app.py）：

- 挂载面刻意收窄：仅 POST /api/mcp + /api/live、/api/ready、/api/version
  三个探活/版本端点；不挂任何 REST、管理、静态媒体路由（攻击面最小化）。
- 复用同一份 routes_mcp router 与依赖注入，wire format 与主进程逐字节一致。
- lifespan 只做 MCP 链路必需的初始化：PostgreSQL、错误事件采集、仓储上下文、
  模型供给运行时（语义搜索 embedding 惰性依赖）、项目搜索运行时、Redis
  （限流；故障 fail-open，与主进程同策略）。
- 刻意不做：调度器、RAG 组合、SMTP、默认管理员种子、附件对账、媒体静态挂载；
  也不校验 JWT 密钥——MCP 入站使用不透明 token（core.auth.OptionalMcpUser），
  主站 JWT 配置问题不应阻断 MCP 进程（进程解耦的意义所在）。

容器编排见 docker/docker-compose.yml 的 mcp-api 服务。
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from redis.asyncio import Redis

from backend.app.api import routes_mcp
from backend.app.api.exception_handlers import register_exception_handlers
from backend.app.core.app_version import resolve_app_version
from backend.app.core.config import settings
from backend.app.core.model_factory import (
    configure_model_provider_runtime,
    configure_runtime_provider_settings,
    create_chat_model,
    create_embedding_model,
)
from backend.app.core.postgres_database import postgres_database
from backend.app.core.postgres_migrations import pending_migration_labels
from backend.app.core.redis_client import close_redis_client, create_redis_client
from backend.app.monitoring.error_event_capture import ErrorEventCapture
from backend.app.monitoring.health import create_application_monitoring_runtime
from backend.app.repositories.application_repository_context import (
    configure_application_repositories,
)
from backend.app.repositories.application_repository_factory import (
    create_application_repositories,
)
from backend.app.repositories.postgres_error_event_repository import (
    PostgresErrorEventRepository,
)
from backend.app.services.project_search_runtime import ApplicationProjectSearchRuntime
from backend.app.services.runtime_provider.runtime import (
    ApplicationModelProviderRuntime,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

# 与 main.py 同模式：模块级只挂 Handler（install_handler 幂等，同进程重复导入
# 不会双挂——但注意 Handler 归属先导入者，因此本进程不得再 import main.py）。
# 仓储在 lifespan 内按当时的 postgres_database 全局绑定。
error_event_capture = ErrorEventCapture()
error_event_capture.install_handler()


async def _warmup_project_semantic_search(
    runtime: ApplicationProjectSearchRuntime,
) -> None:
    """后台预热项目语义搜索链路，不阻塞服务启动。"""
    try:
        result = await asyncio.to_thread(runtime.warmup_semantic_search)
        logger.info("[Startup] Project semantic search warmup: %s.", result.get("status"))
    except Exception as exc:
        logger.warning("[Startup] Project semantic search warmup failed (non-fatal): %s", exc)


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
        logger.warning("[Shutdown] %s task close failed (non-fatal): %s", name, exc)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Own only the resources the MCP endpoint chain needs (subset of main.py)."""
    postgres_opened = False
    repositories_configured = False
    project_search_runtime: ApplicationProjectSearchRuntime | None = None
    semantic_warmup_task: asyncio.Task[object] | None = None
    redis_client: Redis | None = None
    model_provider_runtime: ApplicationModelProviderRuntime | None = None

    app.state.database = postgres_database
    app.state.postgres_database = postgres_database
    app.state.application_database_backend = "postgres"
    app.state.redis = None
    app.state.project_search_runtime = None
    app.state.monitoring_runtime = None
    app.state.model_provider_runtime = None

    try:
        await asyncio.to_thread(postgres_database.open)
        postgres_opened = True
        error_event_capture.bind_repository(
            PostgresErrorEventRepository(postgres_database)
        )
        error_event_capture.start()
        try:
            await asyncio.to_thread(error_event_capture.prune_once)
        except Exception as exc:
            logger.warning("[Startup] Error event prune failed (non-fatal): %s", exc)
        # 迁移台账滞后自检与主进程同口径：只告警不阻断（briefings 等查询
        # 在 schema 滞后时会失败，启动日志必须显眼）。
        try:
            pending_migrations = await asyncio.to_thread(pending_migration_labels)
            if pending_migrations:
                logger.critical(
                    "[Startup] PostgreSQL 迁移台账滞后，%d 个迁移未应用: %s。"
                    "请执行 python scripts/migrate_postgres.py apply 后重启服务。",
                    len(pending_migrations),
                    ", ".join(pending_migrations),
                )
        except Exception as exc:
            logger.warning(
                "[Startup] PostgreSQL 迁移台账校验失败（非阻断）: %s", exc
            )
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
        # 语义搜索 embedding 经 model_factory 全局惰性取用，必须与主进程
        # 同口径绑定，否则 search_github_ai_projects 相关性排序行为漂移。
        model_provider_runtime = ApplicationModelProviderRuntime(
            chat_factory=create_chat_model,
            embedding_factory=create_embedding_model,
        )
        configure_model_provider_runtime(model_provider_runtime)
        app.state.model_provider_runtime = model_provider_runtime
        project_search_runtime = ApplicationProjectSearchRuntime()
        app.state.project_search_runtime = project_search_runtime

        if settings.project_semantic_search_enabled:
            semantic_warmup_task = asyncio.create_task(
                _warmup_project_semantic_search(project_search_runtime)
            )
            app.state.semantic_warmup_task = semantic_warmup_task

        # Redis 只服务限流（故障 fail-open）与 FastAPICache 兜底初始化；
        # 不承担 REST 缓存路由，因此不做主进程那种 development 模式全量清缓存。
        try:
            redis_client = create_redis_client()
            await redis_client.ping()
            FastAPICache.reset()
            FastAPICache.init(
                RedisBackend(redis_client),
                prefix="aigc-cache:",
            )
            app.state.redis = redis_client
            logger.info("[Startup] Redis cache initialized.")
        except Exception as exc:
            app.state.redis = None
            FastAPICache.reset()
            if redis_client is not None:
                try:
                    await close_redis_client(redis_client)
                except Exception as close_exc:
                    logger.warning(
                        "[Startup] Redis close after init failure failed (non-fatal): %s",
                        close_exc,
                    )
                else:
                    redis_client = None
            logger.warning("[Startup] Redis cache init failed (non-fatal): %s", exc)

        yield
    finally:
        await _cancel_background_task(
            semantic_warmup_task,
            name="Project semantic search warmup",
        )
        if project_search_runtime is not None:
            try:
                await project_search_runtime.close()
            except Exception as exc:
                logger.warning("[Shutdown] Project search runtime close failed (non-fatal): %s", exc)
            finally:
                app.state.project_search_runtime = None

        FastAPICache.reset()
        if redis_client is not None:
            try:
                await close_redis_client(redis_client)
                logger.info("[Shutdown] Redis cache connection closed.")
            except Exception as exc:
                logger.warning("[Shutdown] Redis close failed (non-fatal): %s", exc)
            finally:
                app.state.redis = None

        if model_provider_runtime is not None:
            try:
                await model_provider_runtime.close()
            except Exception as exc:
                logger.warning("[Shutdown] Model provider runtime close failed (non-fatal): %s", exc)
            finally:
                configure_model_provider_runtime(None)
                app.state.model_provider_runtime = None
        if repositories_configured:
            try:
                configure_runtime_provider_settings(None)
                configure_application_repositories(None)
            except Exception as exc:
                logger.warning("[Shutdown] Repository context close failed (non-fatal): %s", exc)
        app.state.monitoring_runtime = None
        if postgres_opened:
            # 先停采集线程（flush 残余批次），再关连接池——顺序反了末批
            # 会打到已关闭的 pool 上被丢弃。
            try:
                await asyncio.to_thread(error_event_capture.stop)
            except Exception as exc:
                logger.warning("[Shutdown] Error event capture stop failed (non-fatal): %s", exc)
            try:
                postgres_database.close()
                logger.info("[Shutdown] PostgreSQL connection pool closed.")
            except Exception as exc:
                logger.warning("[Shutdown] PostgreSQL close failed (non-fatal): %s", exc)


# MCP 端点机器对机器调用为主，交互式文档/OpenAPI 在任何环境都不开放
# （主进程仅 development 开放）；探活/版本端点足够小，无需 schema 暴露。
app = FastAPI(
    title="AIGC Radar MCP",
    version=resolve_app_version(),
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# 未捕获异常 → logger.exception → error_events；响应体与主进程同一投射。
register_exception_handlers(app)

# CORS 与主进程同白名单：浏览器 MCP 客户端（如 inspector）行为保持一致，
# 且必须暴露 MCP 会话/协议头。
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

app.include_router(routes_mcp.router, prefix="/api", tags=["MCP"])

_MCP_APP_VERSION = resolve_app_version()


@app.get("/api/version", tags=["Monitor"])
async def mcp_version() -> dict[str, str]:
    """返回应用真实版本（与 server.json / MCP serverInfo 同源）。"""
    return {"name": "aigc-radar", "version": _MCP_APP_VERSION}


@app.get("/api/live", tags=["Monitor"])
async def mcp_liveness() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/ready", tags=["Monitor"])
async def mcp_readiness(request: Request) -> dict[str, object]:
    """就绪探针：与主进程 /api/ready 同口径（匿名可达，明细只进日志）。"""
    runtime = getattr(request.app.state, "monitoring_runtime", None)
    if runtime is None:
        raise HTTPException(
            status_code=503,
            detail={"status": "not_ready", "runtime_ready": False},
        )
    result = await asyncio.to_thread(runtime.readiness)
    if result.get("runtime_ready"):
        return result
    logger.warning("[Monitor] readiness check failed: %s", result)
    raise HTTPException(
        status_code=503,
        detail={"status": "not_ready", "runtime_ready": False},
    )
