// Package config 从环境变量装载 mcp-server 的全部配置。
//
// 变量名与默认值逐一对齐 backend/app/core/config.py（pydantic-settings），
// 使 Go 进程与 Python 进程共用同一份 .env/compose 环境，金丝雀期切换零配置漂移。
// 解析失败（非法数字等）与 pydantic 同策略：启动即报错退出，不带病运行。
package config

import (
	"fmt"
	"os"
	"strconv"
	"strings"
)

// Postgres 镜像 backend.app.core.config.Settings 的 postgres_* 字段，
// 默认值与 Python 侧逐字一致（见 config.py 179-189 行）。
type Postgres struct {
	Host                   string
	Port                   int
	User                   string
	Password               string
	Database               string
	SSLMode                string
	PoolMinSize            int
	PoolMaxSize            int
	PoolTimeoutSeconds     float64
	ConnectTimeoutSeconds  int
	StatementTimeoutMillis int
}

// Redis 镜像 backend.app.core.config.Settings 的 redis_* 字段，
// 默认值与 Python 侧逐字一致（见 config.py 232-235 行）。
type Redis struct {
	Host     string // REDIS_HOST，默认 "localhost"
	Port     int    // REDIS_PORT，默认 6379
	DB       int    // REDIS_DB，默认 0
	Password string // REDIS_PASSWORD，默认 ""
}

// ProjectSearch 镜像 config.py 的项目检索字段（179-206 与 278-281 行），
// PR 2.7 引入。默认值与 Python 侧逐字一致；MILVUS_*/EMBEDDING_* 等语义
// 组件字段随 PR 2.8 语义检索落地时增补。
type ProjectSearch struct {
	AIStrategy                  string  // PROJECT_AI_SEARCH_STRATEGY，默认 "legacy"
	SemanticEnabled             bool    // PROJECT_SEMANTIC_SEARCH_ENABLED，默认 false
	SemanticHeatFirst           bool    // PROJECT_SEMANTIC_HEAT_FIRST，默认 true
	SemanticQueryTimeoutSeconds float64 // PROJECT_SEMANTIC_QUERY_TIMEOUT_SECONDS，默认 6.0
	SemanticRepoLimit           int     // PROJECT_SEMANTIC_REPO_LIMIT，默认 200
	SemanticChunkLimit          int     // PROJECT_SEMANTIC_CHUNK_LIMIT，默认 800
	SemanticMinScore            float64 // PROJECT_SEMANTIC_MIN_SCORE，默认 0.45
	SemanticCollectionName      string  // PROJECT_SEMANTIC_COLLECTION_NAME
	MilvusHost                  string  // MILVUS_HOST
	MilvusPort                  int     // MILVUS_PORT
	MilvusUser                  string  // MILVUS_USER
	MilvusPassword              string  // MILVUS_PASSWORD
	MilvusDBName                string  // MILVUS_DB_NAME
	MilvusDimension             int     // MILVUS_DIMENSION
	MilvusIndexType             string  // MILVUS_INDEX_TYPE
	MilvusMetricType            string  // MILVUS_METRIC_TYPE
	EmbeddingProvider           string  // EMBEDDING_PROVIDER
	EmbeddingAPIKey             string  // EMBEDDING_API_KEY
	EmbeddingBaseURL            string  // EMBEDDING_BASE_URL
	EmbeddingModelName          string  // EMBEDDING_MODEL_NAME
	OpenAIAPIKey                string  // OPENAI_API_KEY
	OpenAIBaseURL               string  // OPENAI_BASE_URL
	SiliconFlowAPIKey           string  // SILICONFLOW_API_KEY
	AdoptionWeight              float64 // PROJECT_SEARCH_ADOPTION_WEIGHT，默认 0.006
	RerankerEnabled             bool    // PROJECT_RERANKER_ENABLED，默认 false
	RerankerURL                 string  // PROJECT_RERANKER_URL
	RerankerModelName           string  // PROJECT_RERANKER_MODEL_NAME
	RerankerTimeoutSeconds      float64 // PROJECT_RERANKER_TIMEOUT_SECONDS
	RerankerCandidateLimit      int     // PROJECT_RERANKER_CANDIDATE_LIMIT，默认 20
	RerankerMinCandidates       int     // PROJECT_RERANKER_MIN_CANDIDATES，默认 5
	GitHubToken                 string  // GITHUB_TOKEN，默认 ""
	FallbackEnabled             bool    // MCP_GITHUB_FALLBACK_ENABLED，默认 true
	FallbackUseToken            bool    // MCP_GITHUB_FALLBACK_USE_TOKEN，默认 false
	FallbackTimeoutSeconds      float64 // MCP_GITHUB_FALLBACK_TIMEOUT_SECONDS，默认 8.0
}

// DocumentSemantic 是 search_documents / search_papers 语义通道配置（Go 独有；
// 向量由 backend document_semantic_indexer 写入 DOCUMENT_SEMANTIC_COLLECTION_NAME，
// Milvus 连接与 embedding 复用 ProjectSearch 的 MILVUS_* / EMBEDDING_*）。
type DocumentSemantic struct {
	Enabled        bool    // DOCUMENT_SEMANTIC_SEARCH_ENABLED，默认 false
	CollectionName string  // DOCUMENT_SEMANTIC_COLLECTION_NAME，默认 aigc_document_vectors_v1
	TopK           int     // DOCUMENT_SEMANTIC_TOP_K，默认 50
	MinScore       float64 // DOCUMENT_SEMANTIC_MIN_SCORE，默认 0.5
	TimeoutSeconds float64 // DOCUMENT_SEMANTIC_TIMEOUT_SECONDS，默认 3.0
}

// Config 是 mcp-server 的根配置。
type Config struct {
	// Port 为 HTTP 监听端口（容器内恒 8000，compose 映射 127.0.0.1:8002:8000）。
	// Python 侧由 uvicorn --port 旗标给出，Go 侧改由环境变量注入。
	Port     int
	Postgres Postgres
	Redis    Redis
	// TrustedProxyIPs 对齐 Python 侧 trusted_proxy_ips（config.py 334 行），
	// 逗号分隔的可信代理 IP 串，默认 "127.0.0.1,::1"，原样装载不做解析。
	TrustedProxyIPs string
	// PublicBaseURL 对齐 public_base_url（config.py 324 行）：对外站点 origin，
	// 仅来自 PUBLIC_BASE_URL 配置，绝不从请求派生（防缓存投毒）。默认 None →
	// Go 侧空串；消费方自行 TrimRight("/",)（对齐 Python 的 rstrip("/")）。
	PublicBaseURL string
	// CORSAllowedOrigins 对齐 cors_allowed_origins（config.py 325-327 行），
	// 保留逗号分隔原串；HTTP 层通过 ParseCORSAllowedOrigins 做同口径清洗。
	CORSAllowedOrigins string
	// SchedulerTimezone 对齐 scheduler_timezone（config.py 344 行）：看板
	// "今日" 统计的时区锚，默认 "Asia/Shanghai"。
	SchedulerTimezone string
	// ProjectSearch 项目库检索（PR 2.7 search_github_projects 引擎与
	// GitHub fallback）。
	ProjectSearch ProjectSearch
	// DocumentSemantic 文档检索的语义通道。
	DocumentSemantic DocumentSemantic
}

// lookup 从环境取值；与 os.LookupEnv 同形，便于测试注入。
type lookupFunc func(string) (string, bool)

func (c *Config) load(lookup lookupFunc) error {
	c.Port = 8000
	c.Postgres = Postgres{
		Host:                   "",
		Port:                   5432,
		User:                   "",
		Password:               "",
		Database:               "",
		SSLMode:                "require",
		PoolMinSize:            2,
		PoolMaxSize:            20,
		PoolTimeoutSeconds:     10.0,
		ConnectTimeoutSeconds:  5,
		StatementTimeoutMillis: 15_000,
	}
	c.Redis = Redis{
		Host:     "localhost",
		Port:     6379,
		DB:       0,
		Password: "",
	}
	c.TrustedProxyIPs = "127.0.0.1,::1"
	c.CORSAllowedOrigins = "http://localhost:5173,http://127.0.0.1:5173,https://aigcnews.cn,https://www.aigcnews.cn"
	c.SchedulerTimezone = "Asia/Shanghai"
	if err := loadInt(lookup, "MCP_SERVER_PORT", &c.Port); err != nil {
		return err
	}
	loadString(lookup, "POSTGRES_HOST", &c.Postgres.Host)
	if err := loadInt(lookup, "POSTGRES_PORT", &c.Postgres.Port); err != nil {
		return err
	}
	loadString(lookup, "POSTGRES_USER", &c.Postgres.User)
	loadString(lookup, "POSTGRES_PASSWORD", &c.Postgres.Password)
	loadString(lookup, "POSTGRES_DATABASE", &c.Postgres.Database)
	loadString(lookup, "POSTGRES_SSLMODE", &c.Postgres.SSLMode)
	if err := loadInt(lookup, "POSTGRES_POOL_MIN_SIZE", &c.Postgres.PoolMinSize); err != nil {
		return err
	}
	if err := loadInt(lookup, "POSTGRES_POOL_MAX_SIZE", &c.Postgres.PoolMaxSize); err != nil {
		return err
	}
	if err := loadFloat(lookup, "POSTGRES_POOL_TIMEOUT_SECONDS", &c.Postgres.PoolTimeoutSeconds); err != nil {
		return err
	}
	if err := loadInt(lookup, "POSTGRES_CONNECT_TIMEOUT_SECONDS", &c.Postgres.ConnectTimeoutSeconds); err != nil {
		return err
	}
	if err := loadInt(lookup, "POSTGRES_STATEMENT_TIMEOUT_MS", &c.Postgres.StatementTimeoutMillis); err != nil {
		return err
	}
	loadString(lookup, "REDIS_HOST", &c.Redis.Host)
	if err := loadInt(lookup, "REDIS_PORT", &c.Redis.Port); err != nil {
		return err
	}
	if err := loadInt(lookup, "REDIS_DB", &c.Redis.DB); err != nil {
		return err
	}
	loadString(lookup, "REDIS_PASSWORD", &c.Redis.Password)
	loadString(lookup, "TRUSTED_PROXY_IPS", &c.TrustedProxyIPs)
	loadString(lookup, "PUBLIC_BASE_URL", &c.PublicBaseURL)
	loadString(lookup, "CORS_ALLOWED_ORIGINS", &c.CORSAllowedOrigins)
	loadString(lookup, "SCHEDULER_TIMEZONE", &c.SchedulerTimezone)
	c.ProjectSearch = ProjectSearch{
		AIStrategy:                  "legacy",
		SemanticEnabled:             false,
		SemanticHeatFirst:           true,
		SemanticQueryTimeoutSeconds: 6.0,
		SemanticRepoLimit:           200,
		SemanticChunkLimit:          800,
		SemanticMinScore:            0.45,
		SemanticCollectionName:      "aigc_github_projects_v1",
		MilvusHost:                  "localhost",
		MilvusPort:                  19530,
		MilvusDBName:                "default",
		MilvusDimension:             1024,
		MilvusIndexType:             "HNSW",
		MilvusMetricType:            "COSINE",
		EmbeddingProvider:           "openai",
		EmbeddingModelName:          "nomic-embed-text",
		AdoptionWeight:              0.006,
		RerankerEnabled:             false,
		RerankerURL:                 "https://api.siliconflow.cn/v1/rerank",
		RerankerModelName:           "Pro/BAAI/bge-reranker-v2-m3",
		RerankerTimeoutSeconds:      1.0,
		RerankerCandidateLimit:      20,
		RerankerMinCandidates:       5,
		GitHubToken:                 "",
		FallbackEnabled:             true,
		FallbackUseToken:            false,
		FallbackTimeoutSeconds:      8.0,
	}
	loadString(lookup, "PROJECT_AI_SEARCH_STRATEGY", &c.ProjectSearch.AIStrategy)
	if err := loadBool(lookup, "PROJECT_SEMANTIC_SEARCH_ENABLED", &c.ProjectSearch.SemanticEnabled); err != nil {
		return err
	}
	if err := loadBool(lookup, "PROJECT_SEMANTIC_HEAT_FIRST", &c.ProjectSearch.SemanticHeatFirst); err != nil {
		return err
	}
	if err := loadInt(lookup, "PROJECT_SEMANTIC_REPO_LIMIT", &c.ProjectSearch.SemanticRepoLimit); err != nil {
		return err
	}
	if err := loadInt(lookup, "PROJECT_SEMANTIC_CHUNK_LIMIT", &c.ProjectSearch.SemanticChunkLimit); err != nil {
		return err
	}
	if err := loadFloat(lookup, "PROJECT_SEMANTIC_MIN_SCORE", &c.ProjectSearch.SemanticMinScore); err != nil {
		return err
	}
	loadString(lookup, "PROJECT_SEMANTIC_COLLECTION_NAME", &c.ProjectSearch.SemanticCollectionName)
	loadString(lookup, "MILVUS_HOST", &c.ProjectSearch.MilvusHost)
	if err := loadInt(lookup, "MILVUS_PORT", &c.ProjectSearch.MilvusPort); err != nil {
		return err
	}
	loadString(lookup, "MILVUS_USER", &c.ProjectSearch.MilvusUser)
	loadString(lookup, "MILVUS_PASSWORD", &c.ProjectSearch.MilvusPassword)
	loadString(lookup, "MILVUS_DB_NAME", &c.ProjectSearch.MilvusDBName)
	if err := loadInt(lookup, "MILVUS_DIMENSION", &c.ProjectSearch.MilvusDimension); err != nil {
		return err
	}
	loadString(lookup, "MILVUS_INDEX_TYPE", &c.ProjectSearch.MilvusIndexType)
	loadString(lookup, "MILVUS_METRIC_TYPE", &c.ProjectSearch.MilvusMetricType)
	loadString(lookup, "EMBEDDING_PROVIDER", &c.ProjectSearch.EmbeddingProvider)
	loadString(lookup, "EMBEDDING_API_KEY", &c.ProjectSearch.EmbeddingAPIKey)
	loadString(lookup, "EMBEDDING_BASE_URL", &c.ProjectSearch.EmbeddingBaseURL)
	loadString(lookup, "EMBEDDING_MODEL_NAME", &c.ProjectSearch.EmbeddingModelName)
	loadString(lookup, "OPENAI_API_KEY", &c.ProjectSearch.OpenAIAPIKey)
	loadString(lookup, "OPENAI_BASE_URL", &c.ProjectSearch.OpenAIBaseURL)
	loadString(lookup, "SILICONFLOW_API_KEY", &c.ProjectSearch.SiliconFlowAPIKey)
	if err := loadFloat(lookup, "PROJECT_SEMANTIC_QUERY_TIMEOUT_SECONDS", &c.ProjectSearch.SemanticQueryTimeoutSeconds); err != nil {
		return err
	}
	if err := loadFloat(lookup, "PROJECT_SEARCH_ADOPTION_WEIGHT", &c.ProjectSearch.AdoptionWeight); err != nil {
		return err
	}
	if err := loadBool(lookup, "PROJECT_RERANKER_ENABLED", &c.ProjectSearch.RerankerEnabled); err != nil {
		return err
	}
	loadString(lookup, "PROJECT_RERANKER_URL", &c.ProjectSearch.RerankerURL)
	loadString(lookup, "PROJECT_RERANKER_MODEL_NAME", &c.ProjectSearch.RerankerModelName)
	if err := loadFloat(lookup, "PROJECT_RERANKER_TIMEOUT_SECONDS", &c.ProjectSearch.RerankerTimeoutSeconds); err != nil {
		return err
	}
	if err := loadInt(lookup, "PROJECT_RERANKER_CANDIDATE_LIMIT", &c.ProjectSearch.RerankerCandidateLimit); err != nil {
		return err
	}
	if err := loadInt(lookup, "PROJECT_RERANKER_MIN_CANDIDATES", &c.ProjectSearch.RerankerMinCandidates); err != nil {
		return err
	}
	loadString(lookup, "GITHUB_TOKEN", &c.ProjectSearch.GitHubToken)
	if err := loadBool(lookup, "MCP_GITHUB_FALLBACK_ENABLED", &c.ProjectSearch.FallbackEnabled); err != nil {
		return err
	}
	if err := loadBool(lookup, "MCP_GITHUB_FALLBACK_USE_TOKEN", &c.ProjectSearch.FallbackUseToken); err != nil {
		return err
	}
	if err := loadFloat(lookup, "MCP_GITHUB_FALLBACK_TIMEOUT_SECONDS", &c.ProjectSearch.FallbackTimeoutSeconds); err != nil {
		return err
	}
	c.DocumentSemantic = DocumentSemantic{
		CollectionName: "aigc_document_vectors_v1",
		TopK:           50,
		MinScore:       0.5,
		TimeoutSeconds: 3.0,
	}
	if err := loadBool(lookup, "DOCUMENT_SEMANTIC_SEARCH_ENABLED", &c.DocumentSemantic.Enabled); err != nil {
		return err
	}
	loadString(lookup, "DOCUMENT_SEMANTIC_COLLECTION_NAME", &c.DocumentSemantic.CollectionName)
	if err := loadInt(lookup, "DOCUMENT_SEMANTIC_TOP_K", &c.DocumentSemantic.TopK); err != nil {
		return err
	}
	if err := loadFloat(lookup, "DOCUMENT_SEMANTIC_MIN_SCORE", &c.DocumentSemantic.MinScore); err != nil {
		return err
	}
	if err := loadFloat(lookup, "DOCUMENT_SEMANTIC_TIMEOUT_SECONDS", &c.DocumentSemantic.TimeoutSeconds); err != nil {
		return err
	}
	if c.DocumentSemantic.TopK <= 0 || c.DocumentSemantic.TopK > 1000 {
		return fmt.Errorf("config: DOCUMENT_SEMANTIC_TOP_K 必须在 1..1000 之间")
	}
	if c.ProjectSearch.SemanticRepoLimit <= 0 || c.ProjectSearch.SemanticChunkLimit <= 0 || c.ProjectSearch.MilvusDimension <= 0 {
		return fmt.Errorf("config: semantic and Milvus sizes must be positive")
	}
	// PROJECT_AI_SEARCH_STRATEGY 是 pydantic Literal 字段：非法值在 Python
	// 侧启动即校验失败，Go 同策略 fail-fast（引擎内 _resolve_strategy 的
	// 非法→legacy 映射是第二层防御，不替代启动校验）。
	switch c.ProjectSearch.AIStrategy {
	case "legacy", "shadow", "v2":
	default:
		return fmt.Errorf("config: PROJECT_AI_SEARCH_STRATEGY=%q 必须是 legacy/shadow/v2 之一", c.ProjectSearch.AIStrategy)
	}
	if c.Port < 1 || c.Port > 65_535 {
		return fmt.Errorf("config: MCP_SERVER_PORT=%d 超出 1..65535", c.Port)
	}
	if c.Postgres.Port < 1 || c.Postgres.Port > 65_535 {
		return fmt.Errorf("config: POSTGRES_PORT=%d 超出 1..65535", c.Postgres.Port)
	}
	if c.Postgres.PoolMinSize < 0 {
		return fmt.Errorf("config: POSTGRES_POOL_MIN_SIZE=%d 不得为负", c.Postgres.PoolMinSize)
	}
	if c.Postgres.PoolMaxSize < 1 || c.Postgres.PoolMinSize > c.Postgres.PoolMaxSize {
		return fmt.Errorf(
			"config: Postgres 池大小非法 min=%d max=%d",
			c.Postgres.PoolMinSize,
			c.Postgres.PoolMaxSize,
		)
	}
	if c.Postgres.PoolTimeoutSeconds <= 0 || c.Postgres.ConnectTimeoutSeconds <= 0 ||
		c.Postgres.StatementTimeoutMillis <= 0 {
		return fmt.Errorf("config: Postgres 超时配置必须为正值")
	}
	return nil
}

// Load 读取进程环境，返回完整配置；任何变量非法即返回具名错误。
func Load() (Config, error) {
	var c Config
	if err := c.load(os.LookupEnv); err != nil {
		return Config{}, err
	}
	return c, nil
}

// ParseCORSAllowedOrigins reproduces the Python middleware's comma-separated
// allowlist construction: trim each entry and discard empty entries.
func ParseCORSAllowedOrigins(raw string) []string {
	parts := strings.Split(raw, ",")
	origins := make([]string, 0, len(parts))
	for _, part := range parts {
		if origin := strings.TrimSpace(part); origin != "" {
			origins = append(origins, origin)
		}
	}
	return origins
}

func loadString(lookup lookupFunc, name string, dst *string) {
	if v, ok := lookup(name); ok {
		*dst = v
	}
}

func loadInt(lookup lookupFunc, name string, dst *int) error {
	v, ok := lookup(name)
	if !ok || strings.TrimSpace(v) == "" {
		return nil
	}
	n, err := strconv.Atoi(strings.TrimSpace(v))
	if err != nil {
		return fmt.Errorf("config: %s=%q 不是合法整数: %w", name, v, err)
	}
	*dst = n
	return nil
}

func loadFloat(lookup lookupFunc, name string, dst *float64) error {
	v, ok := lookup(name)
	if !ok || strings.TrimSpace(v) == "" {
		return nil
	}
	f, err := strconv.ParseFloat(strings.TrimSpace(v), 64)
	if err != nil {
		return fmt.Errorf("config: %s=%q 不是合法浮点数: %w", name, v, err)
	}
	*dst = f
	return nil
}

// loadBool 解析布尔环境变量。pydantic-settings 的 bool 接受
// true/1/yes/on 与 false/0/no/off（大小写不敏感）；Go 侧同口径，
// 其余值启动即报错（与 pydantic 校验失败同策略）。
func loadBool(lookup lookupFunc, name string, dst *bool) error {
	v, ok := lookup(name)
	if !ok || strings.TrimSpace(v) == "" {
		return nil
	}
	switch strings.ToLower(strings.TrimSpace(v)) {
	case "true", "1", "yes", "on":
		*dst = true
	case "false", "0", "no", "off":
		*dst = false
	default:
		return fmt.Errorf("config: %s=%q 不是合法布尔值", name, v)
	}
	return nil
}
