from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from functools import partial
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from redis.asyncio import Redis

from backend.app.api import (
    routes_attachments,
    routes_auth,
    routes_chat,
    routes_dashboard,
    routes_features,
    routes_feed,
    routes_github_projects,
    routes_monitor,
    routes_oauth,
    routes_ops,
    routes_papers,
    routes_payments,
    routes_projects_api,
    routes_push,
    routes_report,
    routes_site,
    routes_sitemap,
    routes_tracking,
    routes_ui_library,
    routes_vision,
    routes_wechat,
    routes_wechat_media,
    routes_x_media,
)
from backend.app.api.dashboard_cache_warmup import maintain_dashboard_cache
from backend.app.api.exception_handlers import register_exception_handlers
from backend.app.api.routes_dashboard import (
    build_dashboard_live_stats_compute,
    read_mcp_call_counts,
)
from backend.app.core.app_version import resolve_app_version
from backend.app.core.auth import hash_password, validate_jwt_secret
from backend.app.core.config import settings
from backend.app.core.model_factory import (
    configure_model_provider_runtime,
    configure_runtime_provider_settings,
    create_chat_model,
    create_embedding_model,
)
from backend.app.core.operations import ApplicationOperationsRuntime
from backend.app.core.postgres_database import postgres_database
from backend.app.core.postgres_migrations import pending_migration_labels
from backend.app.core.redis_client import close_redis_client, create_redis_client
from backend.app.core.scheduler import create_scheduler_runtime
from backend.app.monitoring.error_event_capture import ErrorEventCapture
from backend.app.monitoring.health import create_application_monitoring_runtime
from backend.app.monitoring.live_stats_broadcaster import (
    LiveStatsBroadcaster,
    set_live_stats_broadcaster,
)
from backend.app.monitoring.mcp_metrics_checkpoint import McpMetricsCheckpointRuntime
from backend.app.monitoring.mcp_redis_metrics import create_redis_mcp_tool_call_metrics
from backend.app.monitoring.mcp_tools import MCP_TOOL_NAMES, JsonMcpToolCallStore
from backend.app.repositories.application_repository_context import (
    configure_application_repositories,
)
from backend.app.repositories.application_repository_factory import (
    create_application_repositories,
)
from backend.app.repositories.postgres_error_event_repository import (
    PostgresErrorEventRepository,
)
from backend.app.repositories.postgres_mcp_metrics_checkpoint_repository import (
    PostgresMcpMetricsCheckpointRepository,
)
from backend.app.services.ai_ops import create_ai_ops_service
from backend.app.services.auth.default_admin_bootstrap import ensure_default_admin
from backend.app.services.auth.oauth.runtime_config import configure_oauth_settings_reader
from backend.app.services.chat import attachment_service
from backend.app.services.email.pool_config_provider import (
    configure_email_pool_settings_reader,
)
from backend.app.services.email.smtp_config_provider import (
    configure_smtp_settings_reader,
)
from backend.app.services.payments.plan_overrides import configure_plan_overrides_reader
from backend.app.services.payments.runtime_config import configure_payment_settings_reader
from backend.app.services.project_search_runtime import ApplicationProjectSearchRuntime
from backend.app.services.push.telegram_config_provider import (
    configure_telegram_settings_reader,
)
from backend.app.services.rag.composition import RagChatServiceProvider
from backend.app.services.runtime_provider.runtime import (
    ApplicationModelProviderRuntime,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

# 错误事件采集：root ERROR 级队列 Handler，现有 logger.error/exception 零改动
# 汇入 error_events 表。模块级只挂 Handler 收集 record；仓储在 lifespan 内
# 绑定（按当时的 postgres_database 全局构造，单测替换全局时落到 mock），
# listener 线程随连接池启停。
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
    """Own application resources from startup through failure-isolated shutdown."""
    # 安全检查必须先于一切资源初始化：公开/缺失的 JWT 密钥等于管理端点完全失守。
    validate_jwt_secret(getattr(settings, "JWT_SECRET_KEY", ""))

    postgres_opened = False
    repositories_configured = False
    project_search_runtime: ApplicationProjectSearchRuntime | None = None
    rag_provider: RagChatServiceProvider | None = None
    semantic_warmup_task: asyncio.Task[object] | None = None
    dashboard_warmup_task: asyncio.Task[None] | None = None
    live_stats_task: asyncio.Task[None] | None = None
    live_stats_broadcaster: LiveStatsBroadcaster | None = None
    mcp_metrics_checkpoint_runtime: McpMetricsCheckpointRuntime | None = None
    mcp_metrics_checkpoint_task: asyncio.Task[None] | None = None
    redis_client: Redis | None = None
    operations_runtime: ApplicationOperationsRuntime | None = None
    model_provider_runtime: ApplicationModelProviderRuntime | None = None
    scheduler_runtime = None
    ai_ops_task = None

    app.state.database = postgres_database
    app.state.postgres_database = postgres_database
    app.state.application_database_backend = "postgres"
    app.state.redis = None
    app.state.dashboard_warmup_task = None
    app.state.mcp_tool_call_metrics = None
    app.state.project_search_runtime = None
    app.state.monitoring_runtime = None
    app.state.operations_runtime = None
    app.state.model_provider_runtime = None
    app.state.live_stats_broadcaster = None
    app.state.mcp_metrics_checkpoint_runtime = None

    try:
        await asyncio.to_thread(postgres_database.open)
        postgres_opened = True
        # 采集线程随连接池启动：此后的 logger.error/exception（含下方迁移
        # 滞后 critical）都会落 error_events 表。
        error_event_capture.bind_repository(
            PostgresErrorEventRepository(postgres_database)
        )
        error_event_capture.start()
        # 启动即时清理 30 天前错误事件（周期清理由 capture 线程按小时执行）；
        # 迁移滞后（0037 未应用）等失败仅 WARNING 告警——WARNING 不入采集，
        # 避免"清理失败 → 写入错误事件"的自指。
        try:
            await asyncio.to_thread(error_event_capture.prune_once)
        except Exception as exc:
            logger.warning("[Startup] Error event prune failed (non-fatal): %s", exc)
        # 迁移台账滞后自检：代码先行、迁移未跑时（如 uq_briefings_date 缺失导致
        # 简报 ON CONFLICT 保存全线失败两天才被发现），启动日志必须显眼。
        # 只告警不阻断——让整站不可用换单点 schema 滞后会扩大故障面。
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
        # SMTP 配置热生效：绑定 DB reader 后，所有邮件发送路径（注册 OTP、
        # 报告推送、调度器简报）经 resolve_smtp_config 读 DB 行覆盖 env。
        configure_smtp_settings_reader(
            app.state.application_repositories.smtp_settings
        )
        configure_payment_settings_reader(
            app.state.application_repositories.payment_settings
        )
        configure_oauth_settings_reader(
            app.state.application_repositories.oauth_settings
        )
        # 套餐价格运行时覆盖热生效：绑定 DB reader 后，plans 端点与下单
        # 经 resolve_effective_plans 读覆盖行叠加 plans.py 默认价。
        configure_plan_overrides_reader(
            app.state.application_repositories.payment_plan_overrides
        )
        # Telegram 推送配置热生效：DB 行覆盖 telegram_* env（60s TTL），
        # 绑定/投递/webhook 校验路径统一走 resolve_telegram_config。
        configure_telegram_settings_reader(
            app.state.application_repositories.telegram_settings
        )
        # 邮件池配置热生效：DB 行覆盖 EMAIL_POOL_JSON env，同上口径。
        configure_email_pool_settings_reader(
            app.state.application_repositories.email_pool_settings
        )
        repositories_configured = True
        # 开源自托管引导：空库首启动种子默认管理员（无 SMTP 也能获得管理入口）。
        # 非空库为 no-op；失败仅记 critical 不阻断启动（对齐迁移台账自检口径）。
        try:
            seeded = await asyncio.to_thread(
                ensure_default_admin,
                repository=app.state.application_repositories.users,
                email=settings.DEFAULT_ADMIN_EMAIL,
                password=settings.DEFAULT_ADMIN_PASSWORD,
                hash_password=hash_password,
            )
            if seeded:
                logger.warning(
                    "[Startup] 空库已种子默认管理员 %s。"
                    "若仍使用公开默认密码，请登录后立即在站点内改密（免 SMTP）。",
                    settings.DEFAULT_ADMIN_EMAIL.strip().lower(),
                )
        except Exception as exc:
            logger.critical(
                "[Startup] 默认管理员种子失败（非阻断），全新部署将无法登录管理端: %s",
                exc,
            )
        # 附件元数据已落 PostgreSQL：启动时清理 TTL 到期元数据行，失败不阻塞启动。
        try:
            attachment_reconcile = await asyncio.to_thread(
                attachment_service.reconcile_orphan_attachments
            )
            logger.info(
                "[Startup] Attachment orphan reconciliation: %s.", attachment_reconcile
            )
        except Exception as exc:
            logger.warning(
                "[Startup] Attachment orphan reconciliation failed (non-fatal): %s",
                exc,
            )
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
            redis_client = create_redis_client()
            await redis_client.ping()

            # 开发环境：热重载时自动清除 API 缓存（aigc-cache:* 前缀），实现"保存即刷新"零感知体验
            # 注意：不能用 flushdb()，会清除 SMS 验证码等业务数据
            if settings.env.lower() in ("development", "dev"):
                cache_keys = await redis_client.keys("aigc-cache:*")
                if cache_keys:
                    await redis_client.delete(*cache_keys)
                    logger.info(
                        "[Startup][DEV] Cleared %s cache keys — reload complete.",
                        len(cache_keys),
                    )
                else:
                    logger.info("[Startup][DEV] No cache keys to clear.")

            FastAPICache.reset()
            FastAPICache.init(
                RedisBackend(redis_client),
                prefix="aigc-cache:",
            )
            app.state.redis = redis_client
            # MCP 调用计数迁移 Redis 聚合（PR 0.2）：主/独立 MCP 双进程共享
            # mcpmetrics:* 命名空间；历史 JSON 一次性种子并入（每源幂等），
            # 过渡期内双写 shadow，读路径 Redis 优先、故障回退本地 JSON。
            mcp_tool_call_metrics = create_redis_mcp_tool_call_metrics(
                redis_client,
                JsonMcpToolCallStore(settings.mcp_tool_call_metrics_path),
                "backend-api",
            )
            app.state.mcp_tool_call_metrics = mcp_tool_call_metrics
            await mcp_tool_call_metrics.seed_from_json(MCP_TOOL_NAMES)
            # Redis 继续承担热路径；PostgreSQL 仅做单行耐久快照。启动时选择
            # 两边较新的总量，之后周期 checkpoint，避免 Redis 数据盘丢失回退。
            mcp_metrics_checkpoint_runtime = McpMetricsCheckpointRuntime(
                mcp_tool_call_metrics,
                PostgresMcpMetricsCheckpointRepository(postgres_database),
                interval_seconds=float(
                    getattr(settings, "mcp_metrics_checkpoint_interval_seconds", 30.0)
                ),
            )
            app.state.mcp_metrics_checkpoint_runtime = mcp_metrics_checkpoint_runtime
            await mcp_metrics_checkpoint_runtime.restore_then_checkpoint()
            mcp_metrics_checkpoint_task = asyncio.create_task(
                mcp_metrics_checkpoint_runtime.run()
            )
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

        # 首页实时计数事件驱动分发：写路径 notify → 防抖重算 → Redis 常驻值
        # swap + SSE 广播；Redis 未就绪时以纯内存态运行（重启后首请求重算）。
        # compute 与 /dashboard/live-stats REST 同函数同口径，杜绝投影漂移。
        live_stats_broadcaster = LiveStatsBroadcaster(
            getattr(app.state, "redis", None),
            build_dashboard_live_stats_compute(app),
            mcp_probe=partial(read_mcp_call_counts, app),
        )
        app.state.live_stats_broadcaster = live_stats_broadcaster
        set_live_stats_broadcaster(live_stats_broadcaster)
        live_stats_task = asyncio.create_task(live_stats_broadcaster.run())
        if app.state.redis is not None:
            dashboard_warmup_task = asyncio.create_task(
                maintain_dashboard_cache(app.state.application_repositories)
            )
            app.state.dashboard_warmup_task = dashboard_warmup_task

        scheduler_enabled = bool(getattr(settings, "scheduler_enabled", True))
        job_configs = {}
        if scheduler_enabled:
            try:
                configs = await asyncio.to_thread(
                    app.state.application_repositories.scheduler_job_configs.list_scheduler_job_configs,
                )
                job_configs = {config.job_id: config for config in configs}
            except Exception as exc:
                logger.warning("[Startup] 加载调度器配置失败（非致命）: %s", exc)
        scheduler_runtime = create_scheduler_runtime(
            app.state.application_repositories,
            enabled=scheduler_enabled,
            semantic_search_warmup=(
                project_search_runtime.warmup_semantic_search
            ),
            job_config_overrides=job_configs,
            # 简报/订阅派发链路的邮件池配额护栏依赖 Redis（缺省 fail-open）
            redis_client=getattr(app.state, "redis", None),
        )
        app.state.scheduler_runtime = scheduler_runtime
        app.state.x_operation_lock = scheduler_runtime.x_operation_lock
        if scheduler_enabled:
            scheduler_runtime.start()

        app.state.ai_ops_service = create_ai_ops_service(app)
        ai_ops_task = asyncio.create_task(app.state.ai_ops_service.watch())

        yield
    finally:
        await _cancel_background_task(ai_ops_task, name="AI operations")
        if scheduler_runtime is not None:
            try:
                await scheduler_runtime.stop()
            except Exception as exc:
                logger.warning("[Shutdown] Scheduler close failed (non-fatal): %s", exc)
        if operations_runtime is not None:
            try:
                await operations_runtime.stop()
            except Exception as exc:
                logger.warning("[Shutdown] Operations close failed (non-fatal): %s", exc)
            finally:
                app.state.operations_runtime = None

        await _cancel_background_task(
            semantic_warmup_task,
            name="Project semantic search warmup",
        )
        await _cancel_background_task(
            live_stats_task,
            name="Live stats broadcaster",
        )
        await _cancel_background_task(
            dashboard_warmup_task,
            name="Dashboard cache warmup",
        )
        app.state.dashboard_warmup_task = None
        if live_stats_broadcaster is not None:
            try:
                await live_stats_broadcaster.aclose()
            except Exception as exc:
                logger.warning(
                    "[Shutdown] Live stats broadcaster close failed (non-fatal): %s", exc
                )
            finally:
                set_live_stats_broadcaster(None)
                app.state.live_stats_broadcaster = None
        if project_search_runtime is not None:
            try:
                await project_search_runtime.close()
            except Exception as exc:
                logger.warning("[Shutdown] Project search runtime close failed (non-fatal): %s", exc)
            finally:
                app.state.project_search_runtime = None

        if mcp_metrics_checkpoint_runtime is not None:
            await mcp_metrics_checkpoint_runtime.stop()
        await _cancel_background_task(
            mcp_metrics_checkpoint_task,
            name="MCP metrics PostgreSQL checkpoint",
        )
        app.state.mcp_metrics_checkpoint_runtime = None

        FastAPICache.reset()
        if redis_client is not None:
            try:
                await close_redis_client(redis_client)
                logger.info("[Shutdown] Redis cache connection closed.")
            except Exception as exc:
                logger.warning("[Shutdown] Redis close failed (non-fatal): %s", exc)
            finally:
                app.state.redis = None

        if rag_provider is not None:
            try:
                rag_provider.close()
            except Exception as exc:
                logger.warning("[Shutdown] RAG provider close failed (non-fatal): %s", exc)
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
                configure_smtp_settings_reader(None)
                configure_payment_settings_reader(None)
                configure_oauth_settings_reader(None)
                configure_plan_overrides_reader(None)
                configure_telegram_settings_reader(None)
                configure_email_pool_settings_reader(None)
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


# 交互式 API 文档与 OpenAPI schema 暴露内部路由/模型细节，仅开发环境开放；
# 生产环境（settings.env 非 development/dev，与启动缓存清理同一判定口径）关闭。
_API_DOCS_ENABLED = settings.env.lower() in ("development", "dev")

app = FastAPI(
    title="RAG AIGC Agent API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if _API_DOCS_ENABLED else None,
    redoc_url="/redoc" if _API_DOCS_ENABLED else None,
    openapi_url="/openapi.json" if _API_DOCS_ENABLED else None,
)

# 未捕获异常 → logger.exception → error_events；响应体与 Starlette 默认
# 纯文本 500 逐字节一致（行为兼容）。HTTPException 不受影响。
register_exception_handlers(app)


def _resolve_app_version() -> str:
    """委托共享解析（core.app_version）。"""
    return resolve_app_version()


_APP_VERSION = _resolve_app_version()


@app.get("/api/version", tags=["Monitor"])
async def api_version() -> dict[str, str]:
    """返回应用真实版本（与 server.json / MCP serverInfo 同源）。"""
    return {"name": "aigc-radar", "version": _APP_VERSION}

# ── 站点公开素材（联系合作页二维码、正文插图）：匿名可读是有意选择，仅放公开图片 ──
_site_assets_dir = settings.site_assets_storage_dir
os.makedirs(_site_assets_dir, exist_ok=True)
app.mount(
    "/api/media/site",
    StaticFiles(directory=_site_assets_dir),
    name="site_assets",
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

app.include_router(routes_auth.router, prefix="/api", tags=["Auth"])
app.include_router(routes_oauth.router, prefix="/api", tags=["Auth"])
app.include_router(routes_chat.router, prefix="/api", tags=["Chat"])
app.include_router(routes_attachments.router, prefix="/api", tags=["Attachments"])
app.include_router(routes_vision.router, prefix="/api", tags=["Vision"])
app.include_router(routes_papers.router, prefix="/api", tags=["Papers"])
app.include_router(routes_push.router, prefix="/api", tags=["Push"])
app.include_router(routes_tracking.router, prefix="/api")
app.include_router(routes_dashboard.router, prefix="/api", tags=["Dashboard"])
app.include_router(routes_features.router, prefix="/api", tags=["Features"])
app.include_router(routes_site.router, prefix="/api", tags=["Site"])
app.include_router(routes_ui_library.router, prefix="/api")
app.include_router(routes_github_projects.router, prefix="/api", tags=["GitHub Projects"])
app.include_router(routes_projects_api.router, prefix="/api", tags=["Projects API"])
# /api/mcp 不再由本进程服务：生产流量经 frontend 精确路由到 Go 网关
# （aigc-mcp-go，见 docs/mcp-go-w5-blue-green-cutover.md）；Python 入站
# 工具栈（routes_mcp.py 等）已随 W6-U4 删除。
app.include_router(routes_monitor.router, prefix="/api", tags=["Monitor"])
app.include_router(routes_report.router, prefix="/api", tags=["Report"])
app.include_router(routes_sitemap.router, prefix="/api", tags=["Sitemap"])
app.include_router(routes_feed.router, prefix="/api", tags=["Feed"])
app.include_router(routes_payments.router, prefix="/api", tags=["Payments"])
app.include_router(routes_ops.router, prefix="/api", tags=["Ops"])
app.include_router(routes_wechat.router, prefix="/api", tags=["WeChat"])
app.include_router(routes_x_media.router, prefix="/api", tags=["Media"])
app.include_router(routes_wechat_media.router, prefix="/api", tags=["Media"])
