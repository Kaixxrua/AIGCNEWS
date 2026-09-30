// Package docsemantic 是 search_documents / search_papers 的语义召回通道：
// 查询文本 → embedding → Milvus 一文一向量集合（backend 侧
// document_semantic_indexer 写入，主键即 documents.id）→ 按相似度排好的
// 文档 id。取行、过滤复核与和关键词结果的融合都在 postgres 适配器里做。
package docsemantic

import (
	"context"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"sync"
	"time"
)

// Config 对应 DOCUMENT_SEMANTIC_* 配置。
type Config struct {
	TopK           int     // 语义召回条数上限
	MinScore       float64 // 余弦相似度下限，低于此值视为不相关
	TimeoutSeconds float64 // embedding + 检索的总预算，超时即放弃语义通道
	CacheSize      int     // 查询向量缓存条数（翻页与重复提问免重复 embedding）
}

// Embedder 与 projectsearch.EmbeddingClient 同形，生产注入
// projectsearch.OpenAIEmbeddingClient。
type Embedder interface {
	EmbedQuery(text string) ([]float64, error)
}

// Filter 是下推到 Milvus 的标量过滤；Day 为 yyyymmdd，0 表示不限。
type Filter struct {
	Source   string
	SinceDay int
	UntilDay int
}

// Hit 是一条语义命中。
type Hit struct {
	ID    string
	Score float64
}

// VectorSearcher 是 Milvus 读路径的接缝，单测注入内存实现。
type VectorSearcher interface {
	SearchDocuments(ctx context.Context, vector []float64, topK int, filter Filter) ([]Hit, error)
}

// Retriever 组合 embedding 与向量检索。
type Retriever struct {
	embedder Embedder
	vectors  VectorSearcher
	cfg      Config
	cache    *vectorCache
}

func NewRetriever(embedder Embedder, vectors VectorSearcher, cfg Config) *Retriever {
	if cfg.TopK <= 0 {
		cfg.TopK = 50
	}
	if cfg.TimeoutSeconds <= 0 {
		cfg.TimeoutSeconds = 3
	}
	if cfg.CacheSize <= 0 {
		cfg.CacheSize = 256
	}
	return &Retriever{embedder: embedder, vectors: vectors, cfg: cfg, cache: newVectorCache(cfg.CacheSize)}
}

// SearchDocumentIDs 实现 postgres.SemanticDocumentSearcher：since/until 是
// 半开区间 [since, until) 的 YYYY-MM-DD（空串不限）。返回按相似度降序、已按
// MinScore 截断的文档 id；任何失败都返回 error，由调用方回落纯关键词结果。
func (r *Retriever) SearchDocumentIDs(query, source, since, until string) ([]string, error) {
	query = strings.TrimSpace(query)
	if query == "" {
		return []string{}, nil
	}
	if r.embedder == nil || r.vectors == nil {
		return nil, errors.New("document semantic search: dependencies are not configured")
	}
	filter := Filter{Source: strings.ToLower(strings.TrimSpace(source)), SinceDay: dayNumber(since), UntilDay: dayNumber(until)}
	timeout := time.Duration(r.cfg.TimeoutSeconds * float64(time.Second))
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()

	vector, ok := r.cache.get(query)
	if !ok {
		// EmbedQuery 不带 ctx：用 goroutine + select 施加预算，超时后后台请求
		// 由 HTTP 客户端自身超时兜底收尾（同 projectsearch.runWithTimeout）。
		type embedResult struct {
			vector []float64
			err    error
		}
		done := make(chan embedResult, 1)
		go func() {
			vector, err := r.embedder.EmbedQuery(query)
			done <- embedResult{vector: vector, err: err}
		}()
		select {
		case result := <-done:
			if result.err != nil {
				return nil, fmt.Errorf("document semantic embedding: %w", result.err)
			}
			vector = result.vector
			r.cache.put(query, vector)
		case <-ctx.Done():
			return nil, fmt.Errorf("document semantic embedding timed out after %s", timeout)
		}
	}
	hits, err := r.vectors.SearchDocuments(ctx, vector, r.cfg.TopK, filter)
	if err != nil {
		return nil, fmt.Errorf("document semantic vector search: %w", err)
	}
	ids := make([]string, 0, len(hits))
	seen := make(map[string]bool, len(hits))
	for _, hit := range hits {
		if hit.ID == "" || seen[hit.ID] || hit.Score < r.cfg.MinScore {
			continue
		}
		seen[hit.ID] = true
		ids = append(ids, hit.ID)
	}
	return ids, nil
}

// dayNumber 把 YYYY-MM-DD 前缀转成 yyyymmdd；与 indexer 的 published_day 同规则。
func dayNumber(value string) int {
	value = strings.TrimSpace(value)
	if len(value) < 10 || value[4] != '-' || value[7] != '-' {
		return 0
	}
	number, err := strconv.Atoi(value[0:4] + value[5:7] + value[8:10])
	if err != nil {
		return 0
	}
	return number
}

// vectorCache 是按插入序淘汰的小缓存：查询向量只依赖文本，永不过期。
type vectorCache struct {
	mu       sync.Mutex
	capacity int
	order    []string
	values   map[string][]float64
}

func newVectorCache(capacity int) *vectorCache {
	return &vectorCache{capacity: capacity, values: make(map[string][]float64, capacity)}
}

func (c *vectorCache) get(key string) ([]float64, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	value, ok := c.values[key]
	return value, ok
}

func (c *vectorCache) put(key string, value []float64) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if _, ok := c.values[key]; ok {
		return
	}
	if len(c.order) >= c.capacity {
		delete(c.values, c.order[0])
		c.order = c.order[1:]
	}
	c.order = append(c.order, key)
	c.values[key] = value
}
