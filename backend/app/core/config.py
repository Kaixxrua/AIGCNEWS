from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # HuggingFace 镜像（国内加速，可在 .env 中设置 HF_ENDPOINT=https://hf-mirror.com）
    hf_endpoint: str = ""

    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_user: str = ""
    milvus_password: str = ""
    milvus_db_name: str = "default"
    milvus_collection_name: str = "aigc_docs"
    milvus_dimension: int = 1024
    milvus_index_type: str = "HNSW"
    milvus_metric_type: str = "COSINE"

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
    embedding_provider: str = "ollama"

    ollama_base_url: str = "http://127.0.0.1:11434"
    embedding_model_name: str = "nomic-embed-text"
    chat_model_name: str = "gemini-3.1-flash-lite-preview"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 8192

    arxiv_mcp_url: str = ""
    github_mcp_url: str = ""
    news_source_url: str = ""
    github_token: str = ""
    # Product Hunt API v2 Developer Token（免费申请：https://www.producthunt.com/v2/oauth/applications）
    producthunt_api_token: str = ""
    huggingface_token: str = ""

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_prefix: str = "/api"

    sse_heartbeat_interval: int = 15

    scheduler_timezone: str = "Asia/Shanghai"
    scheduler_cron_ingest: str = "0 */3 * * *"
    scheduler_cron_daily_brief: str = "0 9 * * *"

    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
