from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # HuggingFace 镜像（国内加速，可在 .env 中设置 HF_ENDPOINT=https://hf-mirror.com）
    hf_endpoint: str = ""

    # 直连失败时供安全网页抓取器显式使用；不读取环境代理变量。
    outbound_proxy: str = ""

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
    project_semantic_indexing_enabled: bool = False
    project_semantic_collection_name: str = "aigc_github_projects_v1"
    project_semantic_index_version: str = "v1"
    project_semantic_min_score: float = 0.45
    project_semantic_repo_limit: int = 200
    project_semantic_chunk_limit: int = 800
    project_semantic_query_timeout_seconds: float = 6.0
    project_semantic_readme_max_chars: int = 40_000
    project_semantic_readme_refresh_days: int = 14
    project_semantic_sync_batch_size: int = 100
    project_semantic_sync_concurrency: int = 20
    project_semantic_github_rate_limit_reserve: int = 200
    project_reranker_enabled: bool = False
    project_reranker_url: str = "https://api.siliconflow.cn/v1/rerank"
    project_reranker_model_name: str = "Pro/BAAI/bge-reranker-v2-m3"
    project_reranker_timeout_seconds: float = 1.0
    project_reranker_candidate_limit: int = 20
    project_reranker_min_candidates: int = 5

    neo4j_uri: str = "bolt://localhost:7688"
    neo4j_username: str = "neo4j"
    neo4j_password: str = "12345678"

    sqlite_path: str = "./data/sqlite/app.db"

    # MySQL 连接配置
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_database: str = "rag_aigc"
    project_catalog_backend: str = "mysql"

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

    # 联网搜索配置（使用 Kimi $web_search builtin_function）
    # KIMI_API_KEY：Moonshot AI 的 API Key（https://platform.moonshot.cn）
    # KIMI_BASE_URL：留空默认使用 https://api.moonshot.cn/v1
    # KIMI_MODEL：支持 $web_search 的模型，默认 kimi-k2-turbo-preview
    kimi_api_key: str = ""
    kimi_base_url: str = "https://api.moonshot.cn/v1"
    kimi_model: str = "kimi-k2-turbo-preview"

    # 旧三方搜索 API Keys（保留兼容，已废弃）
    tavily_api_key: str = ""
    brave_search_api_key: str = ""

    arxiv_mcp_url: str = ""
    github_mcp_url: str = ""
    news_source_url: str = ""
    github_token: str = ""
    mcp_github_fallback_enabled: bool = True
    mcp_github_fallback_use_token: bool = False
    mcp_github_fallback_timeout_seconds: float = 8.0
    # Product Hunt API v2 Developer Token（免费申请：https://www.producthunt.com/v2/oauth/applications）
    producthunt_api_token: str = ""
    huggingface_token: str = ""

    # JWT 鉴权配置
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080  # 7天

    # Redis OTP 配置
    REDIS_URL: str = "redis://localhost:6379/0"
    SMS_API_KEY: str = ""  # 保留兼容旧字段，新流程使用 EmailService

    # SMTP 邮件配置（Phase 4 邮箱验证码）
    # SMTP_HOST 为空时进入 dev 模式，验证码打印到日志
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "no-reply@example.com"
    SMTP_FROM_NAME: str = "AIGC_NEWS"
    SMTP_USE_TLS: bool = True

    # 注册邀请码（内测阶段固定值，可通过环境变量覆盖）
    AUTH_REGISTER_INVITE_CODE: str = "internal_testing"

    # 普通用户每日消息上限（0 = 不限制，仅对 role='user' 生效，admin 不受限）
    USER_DAILY_MESSAGE_LIMIT: int = 20

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_prefix: str = "/api"

    sse_heartbeat_interval: int = 15

    scheduler_timezone: str = "Asia/Shanghai"
    scheduler_cron_ingest: str = "0 */3 * * *"
    scheduler_cron_daily_brief: str = "0 9 * * *"

    log_level: str = "INFO"

    # 运行环境：development / production（开发环境热重载时自动清除 Redis 缓存）
    env: str = "production"

    # PDF 持久化存储目录（容器内路径，对应 docker-compose volume 映射）
    papers_storage_dir: str = "storage/papers"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
