package config

import (
	"reflect"
	"testing"
)

// envMap 把键对表装成 lookupFunc。
func envMap(pairs map[string]string) lookupFunc {
	return func(name string) (string, bool) {
		v, ok := pairs[name]
		return v, ok
	}
}

// 默认值必须与 backend/app/core/config.py 逐字一致；漂移即违约。
func TestDefaults(t *testing.T) {
	var c Config
	if err := c.load(envMap(nil)); err != nil {
		t.Fatalf("load: %v", err)
	}
	if c.Port != 8000 {
		t.Errorf("Port = %d, want 8000", c.Port)
	}
	pg := c.Postgres
	want := Postgres{
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
	if pg != want {
		t.Errorf("Postgres = %+v, want %+v", pg, want)
	}
	if c.CORSAllowedOrigins != "http://localhost:5173,http://127.0.0.1:5173,https://aigcnews.cn,https://www.aigcnews.cn" {
		t.Errorf("CORSAllowedOrigins = %q", c.CORSAllowedOrigins)
	}
}

func TestEnvOverrides(t *testing.T) {
	var c Config
	err := c.load(envMap(map[string]string{
		"MCP_SERVER_PORT":                  "8002",
		"POSTGRES_HOST":                    "project-catalog-postgres",
		"POSTGRES_PORT":                    "5433",
		"POSTGRES_USER":                    "aigc",
		"POSTGRES_PASSWORD":                "s'ecret\\x",
		"POSTGRES_DATABASE":                "aigcnews",
		"POSTGRES_SSLMODE":                 "disable",
		"POSTGRES_POOL_MIN_SIZE":           "1",
		"POSTGRES_POOL_MAX_SIZE":           "4",
		"POSTGRES_POOL_TIMEOUT_SECONDS":    "2.5",
		"POSTGRES_CONNECT_TIMEOUT_SECONDS": "3",
		"POSTGRES_STATEMENT_TIMEOUT_MS":    "9000",
		"CORS_ALLOWED_ORIGINS":             " https://one.example, ,https://two.example ",
	}))
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if c.Port != 8002 {
		t.Errorf("Port = %d, want 8002", c.Port)
	}
	pg := c.Postgres
	if pg.Host != "project-catalog-postgres" || pg.Port != 5433 ||
		pg.User != "aigc" || pg.Password != `s'ecret\x` ||
		pg.Database != "aigcnews" || pg.SSLMode != "disable" ||
		pg.PoolMinSize != 1 || pg.PoolMaxSize != 4 ||
		pg.PoolTimeoutSeconds != 2.5 || pg.ConnectTimeoutSeconds != 3 ||
		pg.StatementTimeoutMillis != 9000 {
		t.Errorf("Postgres = %+v", pg)
	}
	if got := ParseCORSAllowedOrigins(c.CORSAllowedOrigins); !reflect.DeepEqual(got, []string{"https://one.example", "https://two.example"}) {
		t.Errorf("CORS origins = %#v", got)
	}
}

func TestInvalidValuesFailFast(t *testing.T) {
	for name, pairs := range map[string]map[string]string{
		"bad port":        {"MCP_SERVER_PORT": "eight thousand"},
		"bad pg port":     {"POSTGRES_PORT": "5432x"},
		"bad pool min":    {"POSTGRES_POOL_MIN_SIZE": "two"},
		"bad pool max":    {"POSTGRES_POOL_MAX_SIZE": "many"},
		"bad pool timout": {"POSTGRES_POOL_TIMEOUT_SECONDS": "soon"},
		"bad connect":     {"POSTGRES_CONNECT_TIMEOUT_SECONDS": "3.5"},
		"bad statement":   {"POSTGRES_STATEMENT_TIMEOUT_MS": "15s"},
		"port range":      {"MCP_SERVER_PORT": "70000"},
		"pg port range":   {"POSTGRES_PORT": "0"},
		"negative min":    {"POSTGRES_POOL_MIN_SIZE": "-1"},
		"zero max":        {"POSTGRES_POOL_MAX_SIZE": "0"},
		"min exceeds max": {"POSTGRES_POOL_MIN_SIZE": "5", "POSTGRES_POOL_MAX_SIZE": "4"},
		"zero timeout":    {"POSTGRES_POOL_TIMEOUT_SECONDS": "0"},
		"bad redis port":  {"REDIS_PORT": "six-three-seven-nine"},
		"bad redis db":    {"REDIS_DB": "0.5"},
		// PR 2.7 项目检索字段
		"bad ai strategy":      {"PROJECT_AI_SEARCH_STRATEGY": "LEGACY"},
		"unknown ai strategy":  {"PROJECT_AI_SEARCH_STRATEGY": "hybrid"},
		"bad semantic bool":    {"PROJECT_SEMANTIC_SEARCH_ENABLED": "enabled"},
		"bad heat first bool":  {"PROJECT_SEMANTIC_HEAT_FIRST": "y"},
		"bad semantic timeout": {"PROJECT_SEMANTIC_QUERY_TIMEOUT_SECONDS": "fast"},
		"bad adoption weight":  {"PROJECT_SEARCH_ADOPTION_WEIGHT": "high"},
		"bad reranker bool":    {"PROJECT_RERANKER_ENABLED": "on-fire"},
		"bad reranker limit":   {"PROJECT_RERANKER_CANDIDATE_LIMIT": "many"},
		"bad fallback bool":    {"MCP_GITHUB_FALLBACK_ENABLED": "maybe"},
		"bad fallback token":   {"MCP_GITHUB_FALLBACK_USE_TOKEN": "2"},
		"bad fallback timeout": {"MCP_GITHUB_FALLBACK_TIMEOUT_SECONDS": "slow"},
		// 文档语义通道
		"bad doc semantic bool":   {"DOCUMENT_SEMANTIC_SEARCH_ENABLED": "sure"},
		"bad doc top k":           {"DOCUMENT_SEMANTIC_TOP_K": "fifty"},
		"zero doc top k":          {"DOCUMENT_SEMANTIC_TOP_K": "0"},
		"huge doc top k":          {"DOCUMENT_SEMANTIC_TOP_K": "1001"},
		"bad doc min score":       {"DOCUMENT_SEMANTIC_MIN_SCORE": "half"},
		"bad doc semantic budget": {"DOCUMENT_SEMANTIC_TIMEOUT_SECONDS": "3s"},
	} {
		var c Config
		if err := c.load(envMap(pairs)); err == nil {
			t.Errorf("%s: 期望报错，实际成功", name)
		}
	}
}

// ProjectSearch 默认值必须与 backend/app/core/config.py（179-206、278-281 行）
// 逐字一致；漂移即违约。
func TestProjectSearchDefaults(t *testing.T) {
	var c Config
	if err := c.load(envMap(nil)); err != nil {
		t.Fatalf("load: %v", err)
	}
	want := ProjectSearch{
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
	if c.ProjectSearch != want {
		t.Errorf("ProjectSearch = %+v, want %+v", c.ProjectSearch, want)
	}
}

func TestProjectSearchEnvOverrides(t *testing.T) {
	var c Config
	err := c.load(envMap(map[string]string{
		"PROJECT_AI_SEARCH_STRATEGY":             "v2",
		"PROJECT_SEMANTIC_SEARCH_ENABLED":        "true",
		"PROJECT_SEMANTIC_HEAT_FIRST":            "0",
		"PROJECT_SEMANTIC_QUERY_TIMEOUT_SECONDS": "2.5",
		"PROJECT_SEMANTIC_REPO_LIMIT":            "50",
		"PROJECT_SEMANTIC_CHUNK_LIMIT":           "700",
		"PROJECT_SEMANTIC_MIN_SCORE":             "0.5",
		"PROJECT_SEMANTIC_COLLECTION_NAME":       "projects",
		"MILVUS_HOST":                            "milvus",
		"MILVUS_PORT":                            "19531",
		"MILVUS_DIMENSION":                       "768",
		"EMBEDDING_PROVIDER":                     "openai",
		"EMBEDDING_MODEL_NAME":                   "embed",
		"PROJECT_RERANKER_URL":                   "https://api.siliconflow.cn/v1/rerank",
		"PROJECT_RERANKER_MODEL_NAME":            "rerank",
		"PROJECT_RERANKER_TIMEOUT_SECONDS":       "2",
		"PROJECT_RERANKER_MIN_CANDIDATES":        "3",
		"PROJECT_SEARCH_ADOPTION_WEIGHT":         "0.01",
		"PROJECT_RERANKER_ENABLED":               "yes",
		"PROJECT_RERANKER_CANDIDATE_LIMIT":       "24",
		"GITHUB_TOKEN":                           "ghp_x",
		"MCP_GITHUB_FALLBACK_ENABLED":            "off",
		"MCP_GITHUB_FALLBACK_USE_TOKEN":          "on",
		"MCP_GITHUB_FALLBACK_TIMEOUT_SECONDS":    "4",
	}))
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	ps := c.ProjectSearch
	if ps.AIStrategy != "v2" || !ps.SemanticEnabled || ps.SemanticHeatFirst ||
		ps.SemanticQueryTimeoutSeconds != 2.5 || ps.SemanticRepoLimit != 50 ||
		ps.SemanticChunkLimit != 700 || ps.SemanticMinScore != 0.5 ||
		ps.SemanticCollectionName != "projects" || ps.MilvusHost != "milvus" ||
		ps.MilvusPort != 19531 || ps.MilvusDimension != 768 ||
		ps.EmbeddingModelName != "embed" || ps.RerankerModelName != "rerank" ||
		ps.RerankerTimeoutSeconds != 2 || ps.RerankerMinCandidates != 3 ||
		ps.AdoptionWeight != 0.01 || !ps.RerankerEnabled || ps.RerankerCandidateLimit != 24 ||
		ps.GitHubToken != "ghp_x" || ps.FallbackEnabled || !ps.FallbackUseToken ||
		ps.FallbackTimeoutSeconds != 4.0 {
		t.Errorf("ProjectSearch = %+v", ps)
	}
}

// Redis 与可信代理默认值必须与 backend/app/core/config.py 逐字一致；漂移即违约。
func TestRedisDefaults(t *testing.T) {
	var c Config
	if err := c.load(envMap(nil)); err != nil {
		t.Fatalf("load: %v", err)
	}
	want := Redis{
		Host:     "localhost",
		Port:     6379,
		DB:       0,
		Password: "",
	}
	if c.Redis != want {
		t.Errorf("Redis = %+v, want %+v", c.Redis, want)
	}
	if c.TrustedProxyIPs != "127.0.0.1,::1" {
		t.Errorf("TrustedProxyIPs = %q, want %q", c.TrustedProxyIPs, "127.0.0.1,::1")
	}
}

func TestRedisEnvOverrides(t *testing.T) {
	var c Config
	err := c.load(envMap(map[string]string{
		"REDIS_HOST":        "aigcnews-redis",
		"REDIS_PORT":        "6380",
		"REDIS_DB":          "2",
		"REDIS_PASSWORD":    `p@ss"word\x`,
		"TRUSTED_PROXY_IPS": "172.19.0.1,127.0.0.1",
	}))
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	r := c.Redis
	if r.Host != "aigcnews-redis" || r.Port != 6380 || r.DB != 2 ||
		r.Password != `p@ss"word\x` {
		t.Errorf("Redis = %+v", r)
	}
	if c.TrustedProxyIPs != "172.19.0.1,127.0.0.1" {
		t.Errorf("TrustedProxyIPs = %q", c.TrustedProxyIPs)
	}
}

// 空 REDIS_PASSWORD 与完全不设置等价：均落到默认空串。
func TestRedisEmptyPasswordEqualsUnset(t *testing.T) {
	var withEmpty Config
	if err := withEmpty.load(envMap(map[string]string{"REDIS_PASSWORD": ""})); err != nil {
		t.Fatalf("load with empty: %v", err)
	}
	var unset Config
	if err := unset.load(envMap(nil)); err != nil {
		t.Fatalf("load unset: %v", err)
	}
	if withEmpty.Redis != unset.Redis {
		t.Errorf("空 REDIS_PASSWORD=%+v, 未设置=%+v, 二者应一致", withEmpty.Redis, unset.Redis)
	}
}

// SchedulerTimezone 默认值与 config.py 344 行逐字一致，SCHEDULER_TIMEZONE 可覆盖。
func TestParseCORSAllowedOrigins(t *testing.T) {
	got := ParseCORSAllowedOrigins(" https://a.example, ,https://b.example,, ")
	want := []string{"https://a.example", "https://b.example"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("origins = %#v, want %#v", got, want)
	}
}

func TestSchedulerTimezone(t *testing.T) {
	var def Config
	if err := def.load(envMap(nil)); err != nil {
		t.Fatalf("load: %v", err)
	}
	if def.SchedulerTimezone != "Asia/Shanghai" {
		t.Errorf("SchedulerTimezone = %q, want %q", def.SchedulerTimezone, "Asia/Shanghai")
	}
	var overridden Config
	if err := overridden.load(envMap(map[string]string{"SCHEDULER_TIMEZONE": "UTC"})); err != nil {
		t.Fatalf("load: %v", err)
	}
	if overridden.SchedulerTimezone != "UTC" {
		t.Errorf("SchedulerTimezone = %q, want %q", overridden.SchedulerTimezone, "UTC")
	}
}

func TestDocumentSemanticDefaults(t *testing.T) {
	var c Config
	if err := c.load(envMap(nil)); err != nil {
		t.Fatalf("load: %v", err)
	}
	want := DocumentSemantic{Enabled: false, CollectionName: "aigc_document_vectors_v1", TopK: 50, MinScore: 0.5, TimeoutSeconds: 3.0}
	if c.DocumentSemantic != want {
		t.Errorf("DocumentSemantic = %+v, want %+v", c.DocumentSemantic, want)
	}
}

func TestDocumentSemanticEnvOverrides(t *testing.T) {
	var c Config
	err := c.load(envMap(map[string]string{
		"DOCUMENT_SEMANTIC_SEARCH_ENABLED":  "true",
		"DOCUMENT_SEMANTIC_COLLECTION_NAME": "docs_v2",
		"DOCUMENT_SEMANTIC_TOP_K":           "80",
		"DOCUMENT_SEMANTIC_MIN_SCORE":       "0.42",
		"DOCUMENT_SEMANTIC_TIMEOUT_SECONDS": "1.5",
	}))
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	want := DocumentSemantic{Enabled: true, CollectionName: "docs_v2", TopK: 80, MinScore: 0.42, TimeoutSeconds: 1.5}
	if c.DocumentSemantic != want {
		t.Errorf("DocumentSemantic = %+v, want %+v", c.DocumentSemantic, want)
	}
}
