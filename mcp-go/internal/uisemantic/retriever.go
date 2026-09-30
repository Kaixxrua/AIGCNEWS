package uisemantic

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"strings"
	"sync"
	"time"
)

// Config 对应 UI_SEMANTIC_* 配置。
type Config struct {
	TopK           int     // 每次语义召回条数上限
	MinScore       float64 // 余弦相似度下限，低于此值视为不相关
	TimeoutSeconds float64 // embedding + 检索的总预算，超时即放弃语义通道
	CacheSize      int     // 查询向量缓存条数
}

// QueryEmbedder 与 projectsearch.EmbeddingClient 同形。
type QueryEmbedder interface {
	EmbedQuery(text string) ([]float64, error)
}

// VectorSearcher 是检索路径的向量存储接缝，单测注入内存实现。
type VectorSearcher interface {
	Search(ctx context.Context, vector []float64, kind string, topK int) ([]Hit, error)
}

// Retriever 组合 embedding 与向量检索，并只认当前目录的（条目, 指纹）。
type Retriever struct {
	embedder QueryEmbedder
	vectors  VectorSearcher
	cfg      Config
	cache    *vectorCache
	current  map[string]map[string]string // kind → item id → fingerprint
}

func NewRetriever(embedder QueryEmbedder, vectors VectorSearcher, cfg Config, documents []Document) *Retriever {
	if cfg.TopK <= 0 {
		cfg.TopK = 50
	}
	if cfg.TimeoutSeconds <= 0 {
		cfg.TimeoutSeconds = 3
	}
	if cfg.CacheSize <= 0 {
		cfg.CacheSize = 256
	}
	current := map[string]map[string]string{}
	for _, document := range documents {
		if current[document.Kind] == nil {
			current[document.Kind] = map[string]string{}
		}
		current[document.Kind][document.ID] = document.Fingerprint
	}
	return &Retriever{embedder: embedder, vectors: vectors, cfg: cfg, cache: newVectorCache(cfg.CacheSize), current: current}
}

// SearchIDs 返回 kind 类条目中按相似度降序、已按 MinScore 截断且指纹与当前
// 目录一致的条目 id；任何失败都返回 error，由调用方回落纯关键词结果。
func (r *Retriever) SearchIDs(query, kind string) ([]string, error) {
	query = strings.TrimSpace(query)
	if query == "" {
		return []string{}, nil
	}
	if r.embedder == nil || r.vectors == nil {
		return nil, errors.New("ui semantic search: dependencies are not configured")
	}
	timeout := time.Duration(r.cfg.TimeoutSeconds * float64(time.Second))
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()

	vector, ok := r.cache.get(query)
	if !ok {
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
				return nil, fmt.Errorf("ui semantic embedding: %w", result.err)
			}
			vector = result.vector
			r.cache.put(query, vector)
		case <-ctx.Done():
			return nil, fmt.Errorf("ui semantic embedding timed out after %s", timeout)
		}
	}
	hits, err := r.vectors.Search(ctx, vector, kind, r.cfg.TopK)
	if err != nil {
		return nil, fmt.Errorf("ui semantic vector search: %w", err)
	}
	current := r.current[kind]
	ids := make([]string, 0, len(hits))
	seen := make(map[string]bool, len(hits))
	for _, hit := range hits {
		if hit.Score < r.cfg.MinScore || seen[hit.ItemID] || current[hit.ItemID] == "" || current[hit.ItemID] != hit.Fingerprint {
			continue
		}
		seen[hit.ItemID] = true
		ids = append(ids, hit.ItemID)
	}
	return ids, nil
}

// RRFConstant 与文档混合检索一致。
const RRFConstant = 60

// Fuse 对关键词与语义两路按等权 RRF 融合；同分时关键词先到者在前，
// 再按语义名次。任一路为空时原样返回另一路。
func Fuse(lexical, semantic []string) []string {
	if len(semantic) == 0 {
		return lexical
	}
	scores := map[string]float64{}
	order := make([]string, 0, len(lexical)+len(semantic))
	for _, ranking := range [][]string{lexical, semantic} {
		for rank, id := range ranking {
			if _, ok := scores[id]; !ok {
				order = append(order, id)
			}
			scores[id] += 1 / float64(RRFConstant+rank+1)
		}
	}
	sort.SliceStable(order, func(i, j int) bool { return scores[order[i]] > scores[order[j]] })
	return order
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
