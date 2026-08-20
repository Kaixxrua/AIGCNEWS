package projectsearch

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"net/url"
	"sort"
	"strings"
	"time"
)

// SemanticConfig 对齐 project_semantic_search 使用的 Python settings：
// PROJECT_SEMANTIC_SEARCH_ENABLED（默认 false）、
// PROJECT_SEMANTIC_REPO_LIMIT（默认 200）、PROJECT_SEMANTIC_CHUNK_LIMIT
// （默认 800）、PROJECT_SEMANTIC_MIN_SCORE（默认 0.45）以及
// PROJECT_SEMANTIC_QUERY_TIMEOUT_SECONDS（默认 6.0）。
type SemanticConfig struct {
	Enabled             bool
	RepoLimit           int
	ChunkLimit          int
	MinScore            float64
	QueryTimeoutSeconds float64
}

// EmbeddingClient 是 embedding HTTP 或本地实现的最小接缝。接口不带 ctx，
// 因而 ProjectSemanticSearch 以 goroutine + select 给每条 semantic query
// 施加 Python asyncio.wait_for 同义超时。
type EmbeddingClient interface {
	EmbedQuery(text string) ([]float64, error)
}

// VectorRepository 是 Milvus 读路径的最小接缝。milvus.go 的
// MilvusVectorRepository 实现此接口，单测可注入纯内存假实现。
type VectorRepository interface {
	SearchRepoIDs(queryVector []float64, chunkLimit, repoLimit int, minScore float64) ([]SemanticHit, error)
}

// ProjectSemanticSearch 移植 backend/app/services/project_semantic_search.py。
// 每条 semantic query 独立 embed → vector search；单 query 原样返回，多 query
// 用 RRF(k=60) 融合。错误如实返回，由上层 hybrid engine 按 Python
// gather(return_exceptions=True) 规则静默丢弃该语义 lane。
type ProjectSemanticSearch struct {
	embedder EmbeddingClient
	vectors  VectorRepository
	cfg      SemanticConfig
}

// NewProjectSemanticSearch 构造语义检索链。embedder 和 vectors 由 wiring
// 注入，便于在没有外部服务的单测中隔离 HTTP/Milvus。nil 依赖不会在构造
// 时报错；调用 SearchRepoIDs 时返回明确错误（semantic 开关关闭时仍短路
// 为 nil, nil，和 Python 一样不触碰未配置依赖）。
func NewProjectSemanticSearch(embedder EmbeddingClient, vectors VectorRepository, cfg SemanticConfig) *ProjectSemanticSearch {
	return &ProjectSemanticSearch{embedder: embedder, vectors: vectors, cfg: cfg}
}

// SearchRepoIDs 实现 SemanticSearcher。语义总闸关闭或 query 为空时返回
// 非 nil 空 slice；契约允许调用方把它当空 lane，且不触碰 embedder。
func (s *ProjectSemanticSearch) SearchRepoIDs(semanticQueries []string) ([]SemanticHit, error) {
	if !s.cfg.Enabled {
		return nil, nil
	}
	if len(semanticQueries) == 0 {
		return []SemanticHit{}, nil
	}
	if s.embedder == nil {
		return nil, errors.New("project semantic search: embedding client is nil")
	}
	if s.vectors == nil {
		return nil, errors.New("project semantic search: vector repository is nil")
	}

	rankings := make([][]SemanticHit, 0, len(semanticQueries))
	for _, semanticQuery := range semanticQueries {
		result, err := runWithTimeout(maxSeconds(s.cfg.QueryTimeoutSeconds), func() ([]SemanticHit, error) {
			vector, err := s.embedder.EmbedQuery(semanticQuery)
			if err != nil {
				return nil, err
			}
			hits, err := s.vectors.SearchRepoIDs(vector, s.cfg.ChunkLimit, s.cfg.RepoLimit, s.cfg.MinScore)
			if err != nil {
				return nil, err
			}
			return hits, nil
		})
		if err != nil {
			return nil, err
		}
		rankings = append(rankings, result)
	}
	if len(rankings) == 1 {
		return rankings[0], nil
	}
	return ReciprocalRankFusion(rankings, 60, s.cfg.RepoLimit), nil
}

// runWithTimeout deliberately does not attempt to cancel the injected interface:
// the contract has no ctx, matching Python asyncio.to_thread + wait_for where a
// timed-out worker may continue in the background. HTTP implementations carry
// their own client timeout as a second defensive boundary.
func runWithTimeout[T any](timeout time.Duration, fn func() (T, error)) (T, error) {
	resultCh := make(chan struct {
		value T
		err   error
	}, 1)
	go func() {
		value, err := fn()
		resultCh <- struct {
			value T
			err   error
		}{value: value, err: err}
	}()
	select {
	case result := <-resultCh:
		return result.value, result.err
	case <-time.After(timeout):
		var zero T
		return zero, fmt.Errorf("project semantic query timed out after %s", timeout)
	}
}

func maxSeconds(seconds float64) time.Duration {
	if seconds < 0.1 {
		seconds = 0.1
	}
	return time.Duration(seconds * float64(time.Second))
}

// ReciprocalRankFusion 对齐 project_semantic_search.reciprocal_rank_fusion：
// 每一路先按 repo_id 去重，rank 从 1 开始，score += 1/(60+rank)，best_rank
// 取最小；最终按 (-score, best_rank, repo_id) 排序并截 limit。
func ReciprocalRankFusion(rankings [][]SemanticHit, rankConstant, limit int) []SemanticHit {
	if rankConstant < 0 {
		rankConstant = 0
	}
	if limit <= 0 {
		return []SemanticHit{}
	}
	aggregates := make(map[string]semanticAggregate)
	for _, ranking := range rankings {
		seen := make(map[string]struct{}, len(ranking))
		for rank, hit := range ranking {
			if hit.RepoID == "" {
				continue
			}
			if _, ok := seen[hit.RepoID]; ok {
				continue
			}
			seen[hit.RepoID] = struct{}{}
			position := rank + 1
			item := aggregates[hit.RepoID]
			item.score += 1.0 / float64(rankConstant+position)
			if item.bestRank == 0 || position < item.bestRank {
				item.bestRank = position
			}
			aggregates[hit.RepoID] = item
		}
	}
	ordered := make([]semanticOrderedHit, 0, len(aggregates))
	for repoID, item := range aggregates {
		ordered = append(ordered, semanticOrderedHit{repoID: repoID, item: item})
	}
	sort.Slice(ordered, func(i, j int) bool {
		if ordered[i].item.score != ordered[j].item.score {
			return ordered[i].item.score > ordered[j].item.score
		}
		if ordered[i].item.bestRank != ordered[j].item.bestRank {
			return ordered[i].item.bestRank < ordered[j].item.bestRank
		}
		return ordered[i].repoID < ordered[j].repoID
	})
	if limit < len(ordered) {
		ordered = ordered[:limit]
	}
	out := make([]SemanticHit, 0, len(ordered))
	for _, item := range ordered {
		out = append(out, SemanticHit{RepoID: item.repoID, Score: item.item.score})
	}
	return out
}

type semanticAggregate struct {
	score    float64
	bestRank int
}

type semanticOrderedHit struct {
	repoID string
	item   semanticAggregate
}

// EmbeddingConfig 对齐 model_factory.create_embedding_model 的 OpenAI 兼容
// 分支（backend/app/core/config.py:238-259）：EMBEDDING_PROVIDER（默认
// openai）、EMBEDDING_API_KEY/EMBEDDING_BASE_URL、EMBEDDING_MODEL_NAME
// （默认 nomic-embed-text）、OPENAI_API_KEY/OPENAI_BASE_URL、以及
// SILICONFLOW_API_KEY。huggingface/ollama 属本地 provider，本移植只实现
// provider=openai；NewOpenAIEmbeddingClient 对其它 provider 返回禁用错误。
type EmbeddingConfig struct {
	Provider          string
	APIKey            string
	BaseURL           string
	ModelName         string
	SiliconFlowAPIKey string
	OpenAIAPIKey      string
	OpenAIBaseURL     string
	TimeoutSeconds    float64
}

// OpenAIEmbeddingClient 是 OpenAI 兼容 /embeddings 的同步客户端。
type OpenAIEmbeddingClient struct {
	cfg    EmbeddingConfig
	client *http.Client
}

// NewOpenAIEmbeddingClient 构造 embedding 客户端。base URL 取
// EMBEDDING_BASE_URL，否则 OPENAI_BASE_URL；key 按
// EMBEDDING_API_KEY → siliconflow host 时 SILICONFLOW_API_KEY → OPENAI_API_KEY
// 选择。siliconflow host 的 Transport.Proxy=nil，等价 Python trust_env=False；
// 其它 host 使用 ProxyFromEnvironment（等价 trust_env=True 的代理行为）。
func NewOpenAIEmbeddingClient(cfg EmbeddingConfig) *OpenAIEmbeddingClient {
	timeout := maxSeconds(cfg.TimeoutSeconds)
	transport := http.DefaultTransport.(*http.Transport).Clone()
	base := strings.TrimSpace(cfg.BaseURL)
	if base == "" {
		base = strings.TrimSpace(cfg.OpenAIBaseURL)
	}
	if isSiliconFlowURL(base) {
		transport.Proxy = nil
	} else {
		transport.Proxy = http.ProxyFromEnvironment
	}
	return &OpenAIEmbeddingClient{cfg: cfg, client: &http.Client{Timeout: timeout, Transport: transport}}
}

// Close 关闭 transport 的空闲连接。
func (c *OpenAIEmbeddingClient) Close() {
	if transport, ok := c.client.Transport.(*http.Transport); ok {
		transport.CloseIdleConnections()
	}
}

// EmbedQuery 调用 POST {base}/embeddings，body 为
// {"model": model, "input": text}，并读取 data[0].embedding。
func (c *OpenAIEmbeddingClient) EmbedQuery(text string) ([]float64, error) {
	if strings.ToLower(strings.TrimSpace(c.cfg.Provider)) != "" && strings.ToLower(strings.TrimSpace(c.cfg.Provider)) != "openai" {
		return nil, fmt.Errorf("unsupported embedding provider %q", c.cfg.Provider)
	}
	base := strings.TrimRight(strings.TrimSpace(c.cfg.BaseURL), "/")
	if base == "" {
		base = strings.TrimRight(strings.TrimSpace(c.cfg.OpenAIBaseURL), "/")
	}
	if base == "" {
		return nil, errors.New("embedding base URL is empty")
	}
	endpoint := base + "/embeddings"
	if strings.HasSuffix(base, "/embeddings") {
		endpoint = base
	}
	key := strings.TrimSpace(c.cfg.APIKey)
	if key == "" && isSiliconFlowURL(base) {
		key = strings.TrimSpace(c.cfg.SiliconFlowAPIKey)
	}
	if key == "" {
		key = strings.TrimSpace(c.cfg.OpenAIAPIKey)
	}
	requestBody := struct {
		Model string `json:"model"`
		Input string `json:"input"`
	}{Model: c.cfg.ModelName, Input: text}
	body, err := json.Marshal(requestBody)
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(context.Background(), http.MethodPost, endpoint, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	if key != "" {
		req.Header.Set("Authorization", "Bearer "+key)
	}
	resp, err := c.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		data, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return nil, fmt.Errorf("embedding API HTTP %d: %s", resp.StatusCode, strings.TrimSpace(string(data)))
	}
	var payload struct {
		Data []struct {
			Embedding []float64 `json:"embedding"`
		} `json:"data"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&payload); err != nil {
		return nil, err
	}
	if len(payload.Data) == 0 || len(payload.Data[0].Embedding) == 0 {
		return nil, errors.New("embedding API response has no data[0].embedding")
	}
	for _, value := range payload.Data[0].Embedding {
		if math.IsNaN(value) || math.IsInf(value, 0) {
			return nil, errors.New("embedding API response contains non-finite value")
		}
	}
	return payload.Data[0].Embedding, nil
}

func isSiliconFlowURL(raw string) bool {
	parsed, err := url.Parse(raw)
	if err != nil {
		return strings.Contains(strings.ToLower(raw), "siliconflow.")
	}
	return strings.Contains(strings.ToLower(parsed.Hostname()), "siliconflow.")
}
