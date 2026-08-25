from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # HuggingFace 镜像（国内加速，可在 .env 中设置 HF_ENDPOINT=https://hf-mirror.com）
    hf_endpoint: str = ""

    # 直连失败时供安全网页抓取器显式使用；不读取环境代理变量。
    outbound_proxy: str = ""

    # 微信公众号后台网页登录会话。密钥必须是 32 字节随机值的 URL-safe Base64，
    # 只由部署环境提供；缺失或非法时微信功能拒绝处理 secret，不降级为明文。
    wechat_session_encryption_key: str = ""
    wechat_session_encryption_key_version: str = "v1"
    wechat_http_timeout_seconds: float = 15.0

    # DailyHot 聚合热榜上游（编排内网自托管 DailyHotApi，见 docs/dailyhot-source.md）。
    # base_url 指向 compose 服务名；endpoints 逗号分隔，为 DailyHotApi 路由名。
    dailyhot_api_base_url: str = "http://dailyhot:6688"
    dailyhot_endpoints: str = "36kr,ithome,sspai,juejin,zhihu,huxiu,geekpark,ifanr"
    dailyhot_per_endpoint_limit: int = 5
    dailyhot_request_timeout_seconds: float = 8.0
    wechat_login_attempt_ttl_seconds: int = 300
    # 会话状态惰性上游复核间隔：DB 里的 active 只代表上次验证结果，超过该间隔
    # 读会话摘要时才重新向上游确认一次；取值对齐微信限流提示的约 30 分钟。
    wechat_session_revalidate_seconds: int = 1800
    wechat_sync_max_pages: int = 20
    wechat_sync_max_articles: int = 500
    wechat_sync_inter_page_delay_seconds: float = 1.0

    @field_validator("wechat_session_encryption_key_version")
    @classmethod
    def _validate_wechat_key_version(cls, value: str) -> str:
        if not value or len(value) > 64:
            raise ValueError("wechat_session_encryption_key_version must be 1..64 characters")
        return value

    @field_validator("wechat_session_encryption_key")
    @classmethod
    def _validate_wechat_key(cls, value: str) -> str:
        if not value:
            return value
        if value.startswith("CHANGEME"):
            raise ValueError(
                "wechat_session_encryption_key must not use the example placeholder"
            )
        return value

    @field_validator(
        "github_oauth_client_secret",
        "google_oauth_client_secret",
        "wechat_oauth_app_secret",
    )
    @classmethod
    def _validate_oauth_secret_placeholder(cls, value: str) -> str:
        if value.upper().startswith("CHANGEME"):
            raise ValueError("OAuth secrets must not use the example placeholder")
        return value

    @field_validator("oauth_state_ttl_seconds")
    @classmethod
    def _validate_oauth_state_ttl(cls, value: int) -> int:
        if not 60 <= value <= 900:
            raise ValueError("oauth_state_ttl_seconds must be within 60..900")
        return value

    @field_validator("oauth_handoff_ttl_seconds")
    @classmethod
    def _validate_oauth_handoff_ttl(cls, value: int) -> int:
        if not 30 <= value <= 600:
            raise ValueError("oauth_handoff_ttl_seconds must be within 30..600")
        return value

    # ── 支付收费骨架（ADR 0002）────────────────────────────────────────
    # 全局开关：默认 False，用户侧支付路由整组 404（feature gate 先例）；
    # 营业执照/商户号就位后逐渠道填凭证 + 置 True。
    payments_enabled: bool = False
    # 下单后未支付订单的挂起时长，超时由 payment_order_closing 任务关单。
    payments_order_ttl_minutes: int = 30
    # 渠道回调 notify_url 的公网基址（如 https://aigcradar.cn）；为空时
    # 下单走请求 Host 推导。骨架期可留空。
    payments_public_base_url: str = ""
    # 微信支付 v3 Native（扫码）：商户号凭证。骨架期全部留空 → 渠道 503。
    wechat_pay_appid: str = ""
    wechat_pay_mchid: str = ""
    wechat_pay_mch_serial_no: str = ""
    wechat_pay_api_v3_key: str = ""
    wechat_pay_private_key_path: str = ""
    # 微信支付公钥模式：回调验签用（商户平台 API 安全页可复制公钥 ID/下载公钥）。
    wechat_pay_public_key_id: str = ""
    wechat_pay_public_key_path: str = ""
    # 支付宝电脑网站支付（alipay.trade.page.pay）：RSA2 密钥对文件路径。
    alipay_appid: str = ""
    alipay_private_key_path: str = ""
    alipay_public_key_path: str = ""
    # Stripe（国际卡）：secret key + webhook 签名 secret。
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    @field_validator("wechat_pay_api_v3_key", "stripe_secret_key", "stripe_webhook_secret")
    @classmethod
    def _validate_payment_secret_placeholder(cls, value: str) -> str:
        # 沿用 wechat_session_encryption_key 先例：示例占位符直接拒绝，
        # 防止 .env.example 的 CHANGEME 被原样带进生产。
        if value.startswith("CHANGEME"):
            raise ValueError("payment secrets must not use the example placeholder")
        return value

    @field_validator("payments_order_ttl_minutes")
    @classmethod
    def _validate_payments_order_ttl(cls, value: int) -> int:
        # 关单窗口：太短用户来不及扫码，太久 pending 订单堆积。
        if not 5 <= value <= 24 * 60:
            raise ValueError("payments_order_ttl_minutes must be within 5..1440")
        return value

    # 推送渠道凭据静态加密（webhook secret、bot token 等）。密钥必须是 32 字节
    # 随机值的 URL-safe Base64，只由部署环境提供；缺失或非法时含凭据的渠道
    # 类型拒绝处理 secret，不降级为明文（email 渠道无凭据，不受影响）。
    push_channel_encryption_key: str = ""
    push_channel_encryption_key_version: str = "v1"
    telegram_push_enabled: bool = False
    telegram_bot_token: str = ""
    telegram_bot_username: str = ""
    telegram_webhook_secret: str = ""
    telegram_link_ttl_seconds: int = 300
    telegram_request_timeout_seconds: float = 5.0

    @field_validator("push_channel_encryption_key_version")
    @classmethod
    def _validate_push_channel_key_version(cls, value: str) -> str:
        if not value or len(value) > 64:
            raise ValueError(
                "push_channel_encryption_key_version must be 1..64 characters"
            )
        return value

    @field_validator("push_channel_encryption_key")
    @classmethod
    def _validate_push_channel_key(cls, value: str) -> str:
        if not value:
            return value
        if value.startswith("CHANGEME"):
            raise ValueError(
                "push_channel_encryption_key must not use the example placeholder"
            )
        return value

    # X 采集凭证池 cookie 静态加密（auth_token/ct0）。密钥必须是 32 字节随机
    # 值的 URL-safe Base64，只由部署环境提供；缺失或非法时写入侧拒绝处理
    # secret，不降级为明文；历史明文行读取兼容，下次写入时密封迁移。
    x_credential_encryption_key: str = ""
    x_credential_encryption_key_version: str = "v1"

    @field_validator("x_credential_encryption_key_version")
    @classmethod
    def _validate_x_credential_key_version(cls, value: str) -> str:
        if not value or len(value) > 64:
            raise ValueError(
                "x_credential_encryption_key_version must be 1..64 characters"
            )
        return value

    @field_validator("x_credential_encryption_key")
    @classmethod
    def _validate_x_credential_key(cls, value: str) -> str:
        if not value:
            return value
        if value.startswith("CHANGEME"):
            raise ValueError(
                "x_credential_encryption_key must not use the example placeholder"
            )
        return value

    # 内部 MCP Server auth_token 静态加密（与 X 凭证同一口径）：缺失或非法时
    # 写入侧拒绝处理 secret，不降级为明文；历史明文行读取兼容、写时密封。
    mcp_server_encryption_key: str = ""
    mcp_server_encryption_key_version: str = "v1"

    @field_validator("mcp_server_encryption_key_version")
    @classmethod
    def _validate_mcp_server_key_version(cls, value: str) -> str:
        if not value or len(value) > 64:
            raise ValueError(
                "mcp_server_encryption_key_version must be 1..64 characters"
            )
        return value

    @field_validator("mcp_server_encryption_key")
    @classmethod
    def _validate_mcp_server_key(cls, value: str) -> str:
        if not value:
            return value
        if value.startswith("CHANGEME"):
            raise ValueError(
                "mcp_server_encryption_key must not use the example placeholder"
            )
        return value


    # Monitor 管理的 OAuth client secret/app secret 加密密钥；业务凭据本身不从
    # env 配置，只有这个部署级 AES-256-GCM 密钥由环境注入并跨 worker 保持稳定。
    oauth_config_encryption_key: str = ""
    oauth_config_encryption_key_version: str = "v1"

    @field_validator("oauth_config_encryption_key_version")
    @classmethod
    def _validate_oauth_config_key_version(cls, value: str) -> str:
        if not value or len(value) > 64:
            raise ValueError(
                "oauth_config_encryption_key_version must be 1..64 characters"
            )
        return value

    @field_validator("oauth_config_encryption_key")
    @classmethod
    def _validate_oauth_config_key(cls, value: str) -> str:
        if not value:
            return value
        if value.startswith("CHANGEME"):
            raise ValueError(
                "oauth_config_encryption_key must not use the example placeholder"
            )
        return value

    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_user: str = ""
    milvus_password: str = ""
    milvus_db_name: str = "default"
    milvus_collection_name: str = "aigc_docs"
    milvus_dimension: int = 1024
    milvus_index_type: str = "HNSW"
    milvus_metric_type: str = "COSINE"
    project_semantic_search_enabled: bool = False
    project_ai_search_strategy: Literal["legacy", "shadow", "v2"] = "legacy"
    project_search_adoption_weight: float = 0.006
    project_semantic_heat_first: bool = True
    project_search_shadow_sample_rate: float = 0.0
    project_search_shadow_workers: int = 2
    project_search_shadow_capacity: int = 8
    project_search_shadow_timeout_seconds: float = 1.0
    project_search_shadow_recent_case_limit: int = 20
    project_search_shadow_shutdown_timeout_seconds: float = 5.0
    scheduler_shutdown_grace_seconds: float = 30.0
    operations_shutdown_grace_seconds: float = 30.0
    project_search_shadow_epoch: str = "default"
    project_semantic_indexing_enabled: bool = False
    project_semantic_collection_name: str = "aigc_github_projects_v1"
    project_semantic_index_version: str = "v1"
    project_semantic_min_score: float = 0.45
    project_semantic_repo_limit: int = 200
    project_semantic_chunk_limit: int = 800
    project_semantic_query_timeout_seconds: float = 6.0
    project_semantic_readme_max_chars: int = 40_000
    project_semantic_sync_batch_size: int = 100
    project_semantic_sync_concurrency: int = 20
    project_reranker_enabled: bool = False
    project_reranker_url: str = "https://api.siliconflow.cn/v1/rerank"
    project_reranker_model_name: str = "Pro/BAAI/bge-reranker-v2-m3"
    project_reranker_timeout_seconds: float = 1.0
    project_reranker_candidate_limit: int = 20
    project_reranker_min_candidates: int = 5

    # 工具网站收藏的内容安全审核：命中成人/不适宜内容时拒绝收藏。
    # fail_closed 开启时审核服务不可用也拒绝添加（稍后重试），关闭则放行并记审计日志。
    tool_website_moderation_enabled: bool = True
    tool_website_moderation_fail_closed: bool = True

    neo4j_uri: str = "bolt://localhost:7688"
    neo4j_username: str = "neo4j"
    neo4j_password: str = "12345678"

    # PostgreSQL 应用数据库配置
    postgres_host: str = ""
    postgres_port: int = 5432
    postgres_user: str = ""
    postgres_password: str = ""
    postgres_database: str = ""
    postgres_sslmode: str = "require"
    postgres_pool_min_size: int = 2
    postgres_pool_max_size: int = 20
    postgres_pool_timeout_seconds: float = 10.0
    postgres_connect_timeout_seconds: int = 5
    postgres_statement_timeout_ms: int = 15_000

    # Redis 连接配置
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = ""

    llm_provider: str = "openai"
    openai_api_key: str = ""
    openai_base_url: str = ""
    # Anthropic 原生 API（LLM_PROVIDER=anthropic 时使用，支持 Extended Thinking）
    anthropic_api_key: str = ""
    anthropic_base_url: str = ""  # 留空则使用官方端点；可填代理地址
    # 是否启用 Extended Thinking（仅 anthropic provider 有效）
    anthropic_thinking_budget: int = 5000  # thinking tokens 上限，0 = 不启用
    embedding_provider: str = "openai"

    # Embedding 独立的 API 配置（可选，留空则复用 OPENAI_API_KEY / OPENAI_BASE_URL）
    embedding_api_key: str = ""
    embedding_base_url: str = ""

    ollama_base_url: str = "http://127.0.0.1:11434"
    embedding_model_name: str = "nomic-embed-text"
    chat_model_name: str = "gemini-3.1-flash-lite-preview"
    # 推理模型（支持 reasoning_content 的模型，如 DeepSeek-R1）
    # 留空则复用 chat_model_name
    thinking_model_name: str = ""

    # 硅基流动 API 配置（Reranker / 视觉问答等）
    siliconflow_api_key: str = ""
    # Reranker 模型名称（硅基流动 /v1/rerank 接口）
    reranker_model_name: str = "Pro/BAAI/bge-reranker-v2-m3"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 150000
    # OpenAI 兼容分支单次请求超时（秒）。上游中转「连接挂着但零字节」
    # 悬挂时按此值失败，避免同步流式 invoke 无限等待拖垮调度锁。
    llm_request_timeout: float = 300.0
    # X 翻译单条任务硬超时；必须小于等于上游请求超时，避免任务租约长期占用。
    x_translation_timeout_seconds: float = 120.0

    # 联网搜索配置（使用 Kimi $web_search builtin_function）
    # KIMI_API_KEY：Moonshot AI 的 API Key（https://platform.moonshot.cn）
    # KIMI_BASE_URL：留空默认使用 https://api.moonshot.cn/v1
    # KIMI_MODEL：支持 $web_search 的模型，默认 kimi-k2-turbo-preview
    kimi_api_key: str = ""
    kimi_base_url: str = "https://api.moonshot.cn/v1"
    kimi_model: str = "kimi-k2-turbo-preview"

    github_token: str = ""
    mcp_github_fallback_enabled: bool = True
    mcp_github_fallback_use_token: bool = False
    mcp_github_fallback_timeout_seconds: float = 8.0
    # Product Hunt API v2 Developer Token（免费申请：https://www.producthunt.com/v2/oauth/applications）
    producthunt_api_token: str = ""
    huggingface_token: str = ""

    # JWT 鉴权配置
    # 无默认值：缺失或仍为公开示例值时应用拒绝启动（见 core/auth.validate_jwt_secret）。
    # 生成方式：openssl rand -hex 32
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080  # 7天

    # 开源自托管引导：用户表为空的首启动种子一个默认管理员，
    # 让无法配置 SMTP（注册 OTP 依赖邮件投递）的部署也能获得管理入口。
    # 默认值是公开凭据：仅空库种子一次，登录后必须立即改密（免 SMTP）；
    # 任一值置空则禁用种子。既有部署（用户表非空）完全不触发。
    DEFAULT_ADMIN_EMAIL: str = "admin@aigcnews.internal"
    DEFAULT_ADMIN_PASSWORD: str = "admin123456"

    # SMTP 邮件配置（Phase 4 邮箱验证码）
    # SMTP_HOST 为空时进入 dev 模式，验证码打印到日志
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "no-reply@example.com"
    SMTP_FROM_NAME: str = "AIGC_NEWS"
    SMTP_USE_TLS: bool = True

    # 邮件池（多服务商 failover + 本地配额护栏）：JSON 数组，非空时接管全部
    # 外发邮件；既有单 SMTP 配置（DB/env）自动并入为最低优先级兜底 entry。
    # 字段与限额口径（UTC 日/月窗口）见 .env.example 邮件池一节
    EMAIL_POOL_JSON: str = ""

    # 普通用户每日消息上限（0 = 不限制，仅对 role='user' 生效，admin 不受限）
    USER_DAILY_MESSAGE_LIMIT: int = 20

    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # 对外站点 origin（如 https://aigcnews.cn），用于生成绝对 pdf_media_url。
    # 留空则返回相对路径；绝不从 Host / X-Forwarded-Proto 头派生（可伪造）。
    public_base_url: str | None = None


    # OAuth 快捷登录（第一版 env-first；未加入 allowlist 或缺任一凭据时不暴露入口）。
    oauth_enabled_providers: str = ""
    github_oauth_client_id: str = ""
    github_oauth_client_secret: str = ""
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    wechat_oauth_app_id: str = ""
    wechat_oauth_app_secret: str = ""
    oauth_state_ttl_seconds: int = 300
    oauth_handoff_ttl_seconds: int = 120

    # CORS 允许的来源（逗号分隔）。浏览器直连 API 的场景只有前端，
    # 不再允许任意来源。
    cors_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173,https://aigcnews.cn,https://www.aigcnews.cn"

    # 可信反向代理（逗号分隔 IP/CIDR）：仅当直连对端命中该列表时才采信
    # X-Forwarded-For 首跳，否则以直连对端为准（防 XFF 伪造绕过 IP 级
    # 限速与污染访客统计）。默认仅回环（本机调试/单机直跑）；生产经编排
    # 内 nginx 回源时必须把编排网段加入（见 docker/docker-compose.yml：
    # 前端容器经内网 proxy_pass 到 aigc-backend），例如
    # TRUSTED_PROXY_IPS=127.0.0.1,::1,172.16.0.0/12
    trusted_proxy_ips: str = "127.0.0.1,::1"

    sse_heartbeat_interval: int = 15

    # 生产环境危险操作的第二授权通道（独立于 CLI 参数的环境授权，
    # 双通道同时满足才放行；settings 启动时从环境读取一次）。
    github_watcher_repair_production_authorized: bool = False

    scheduler_enabled: bool = True
    scheduler_timezone: str = "Asia/Shanghai"

    # 可插拔采集源开关（默认关闭）。X 与微信公众号链路的敏感实现以
    # 插件形式提供（见 services/source_plugins 契约与加载器）：关闭时
    # 相关路由与调度任务优雅降级，核心产品面不受影响；开启后优先加载
    # 仓库外私有包实现，回退仓库内过渡期实现。
    x_source_enabled: bool = False
    wechat_source_enabled: bool = False

    # 运行环境：development / production（开发环境热重载时自动清除 Redis 缓存）
    env: str = "production"

    # PDF 持久化存储目录（容器内路径，对应 docker-compose volume 映射）
    # 注意：该目录经 /api/media/papers 匿名静态挂载对外服务，禁止存放私有文件
    papers_storage_dir: str = "storage/papers"

    # 站点公开素材（联系合作页二维码、正文插图）存储目录（容器内路径，对应 volume 映射）
    # 注意：该目录经 /api/media/site 匿名静态挂载对外服务，仅存放站点公开图片
    site_assets_storage_dir: str = "storage/site"

    # 聊天私有附件（PDF）存储目录（容器内路径，对应 docker-compose volume 映射）
    # 必须位于 papers_storage_dir 的静态挂载树之外，附件仅允许经带鉴权的元数据 API 访问
    chat_uploads_storage_dir: str = "storage/chat_uploads"

    # X 视频封面抽帧缓存目录（容器内路径，对应 docker-compose volume 映射）
    x_media_cache_dir: str = "storage/x_media"

    # 微信公众号图片代理缓存目录（容器内路径，对应 docker-compose volume 映射）
    wechat_media_cache_dir: str = "storage/wechat"

    # 媒体代理磁盘缓存预算（wechat 图片与 X 封面共用）：容量上限 + 留存时长，
    # 超限按最旧优先驱逐，防止无认证代理被远程填盘
    media_cache_max_bytes: int = 536870912  # 512 MiB
    media_cache_max_age_seconds: int = 604800  # 7 天

    # X 看板媒体缓存预热（默认全部关闭，公共仓零行为变更）：
    # 采集完成后对看板首屏的路径式代理 URL 主动 GET 边缘入口，proxy_cache
    # 转热，用户首访不再撞 ~460ms 冷回源。base_url 指向边缘缓存入口
    # （如 http://127.0.0.1:8488）；为空时预热记日志跳过，本地/无边缘
    # 部署不报错。窗口默认 48h，覆盖 24h 滚动看板与 days_back 回翻。
    x_media_warmup_enabled: bool = False
    x_media_warmup_base_url: str = ""
    # 预热请求的 Host 头覆盖：边缘缓存键含 $host（如 aigcnews.cn），
    # 经 IP/隧道入口预热时必须带上生产 Host，否则暖的是另一组缓存键。
    x_media_warmup_host_header: str = ""
    x_media_warmup_window_hours: int = 48
    x_media_warmup_max_urls: int = 300
    x_media_warmup_concurrency: int = 8

    # 存量视频封面回填：单轮上限（每条代价 = 4MB 回源 + ffmpeg 抽帧），
    # 随预热周期渐进消化存量，避免单轮风暴
    x_poster_backfill_max_per_run: int = 8

    # MCP 工具调用计数持久化文件（容器内路径，对应 docker-compose volume 映射）
    mcp_tool_call_metrics_path: str = "storage/metrics/mcp_tool_calls.json"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
