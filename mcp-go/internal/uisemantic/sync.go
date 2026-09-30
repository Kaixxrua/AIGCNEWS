package uisemantic

import (
	"context"
	"fmt"
	"math"
	"time"
)

// BatchEmbedder 批量 embed 文档文本，生产注入 projectsearch.OpenAIEmbeddingClient。
type BatchEmbedder interface {
	EmbedTexts(ctx context.Context, texts []string) ([][]float64, error)
}

// SyncStore 是同步路径的向量存储接缝，单测注入内存实现。
type SyncStore interface {
	Existing(ctx context.Context, vectorIDs []string) (map[string]bool, error)
	Upsert(ctx context.Context, rows []Row) error
	Flush(ctx context.Context) error
}

type SyncConfig struct {
	Dimension   int
	LookupBatch int // 每次按主键查已有向量的条数
	EmbedBatch  int // 每次 embedding 请求的条数
	MaxAttempts int // 单批 embedding 的最多尝试次数（含首次）
	// Backoff 返回第 attempt 次失败后的等待时长；nil 用指数退避 2s·2^(attempt-1)，封顶 60s。
	Backoff func(attempt int) time.Duration
}

type SyncReport struct {
	Total    int `json:"total"`
	Existing int `json:"existing"`
	Embedded int `json:"embedded"`
}

// Sync 只为集合里还没有（条目, 指纹）行的文档计算并写入向量；可随时中断，
// 下次启动从头比对即可续上。从不删除行：失效版本由检索侧按指纹过滤。
func Sync(ctx context.Context, documents []Document, embedder BatchEmbedder, store SyncStore, cfg SyncConfig) (SyncReport, error) {
	if cfg.LookupBatch <= 0 {
		cfg.LookupBatch = 512
	}
	if cfg.EmbedBatch <= 0 {
		cfg.EmbedBatch = 32
	}
	if cfg.MaxAttempts <= 0 {
		cfg.MaxAttempts = 5
	}
	if cfg.Backoff == nil {
		cfg.Backoff = defaultBackoff
	}
	report := SyncReport{Total: len(documents)}
	for start := 0; start < len(documents); start += cfg.LookupBatch {
		if err := ctx.Err(); err != nil {
			return report, err
		}
		chunk := documents[start:min(start+cfg.LookupBatch, len(documents))]
		ids := make([]string, len(chunk))
		for i, document := range chunk {
			ids[i] = document.VectorID()
		}
		existing, err := store.Existing(ctx, ids)
		if err != nil {
			return report, err
		}
		missing := make([]Document, 0, len(chunk))
		for i, document := range chunk {
			if existing[ids[i]] {
				report.Existing++
			} else {
				missing = append(missing, document)
			}
		}
		for batchStart := 0; batchStart < len(missing); batchStart += cfg.EmbedBatch {
			batch := missing[batchStart:min(batchStart+cfg.EmbedBatch, len(missing))]
			rows, err := embedBatch(ctx, batch, embedder, cfg)
			if err != nil {
				return report, err
			}
			if err := store.Upsert(ctx, rows); err != nil {
				return report, err
			}
			report.Embedded += len(rows)
		}
	}
	if report.Embedded > 0 {
		if err := store.Flush(ctx); err != nil {
			return report, err
		}
	}
	return report, nil
}

// defaultBackoff 是 2s·2^(attempt-1)，封顶 60s（先截断指数防移位溢出）。
func defaultBackoff(attempt int) time.Duration {
	if attempt < 1 {
		attempt = 1
	}
	return min(60*time.Second, 2*time.Second<<min(attempt-1, 5))
}

func embedBatch(ctx context.Context, batch []Document, embedder BatchEmbedder, cfg SyncConfig) ([]Row, error) {
	texts := make([]string, len(batch))
	for i, document := range batch {
		texts[i] = document.Text
	}
	var vectors [][]float64
	var err error
	for attempt := 1; ; attempt++ {
		vectors, err = embedder.EmbedTexts(ctx, texts)
		if err == nil {
			break
		}
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		if attempt >= cfg.MaxAttempts {
			return nil, fmt.Errorf("embed ui documents (%s…): %w", batch[0].ID, err)
		}
		timer := time.NewTimer(cfg.Backoff(attempt))
		select {
		case <-ctx.Done():
			timer.Stop()
			return nil, ctx.Err()
		case <-timer.C:
		}
	}
	if len(vectors) != len(batch) {
		return nil, fmt.Errorf("embedding API returned %d vectors for %d texts", len(vectors), len(batch))
	}
	rows := make([]Row, len(batch))
	for i, document := range batch {
		if cfg.Dimension > 0 && len(vectors[i]) != cfg.Dimension {
			return nil, fmt.Errorf("embedding dimension mismatch for %s: got %d want %d", document.ID, len(vectors[i]), cfg.Dimension)
		}
		embedding := make([]float32, len(vectors[i]))
		for j, value := range vectors[i] {
			if math.IsNaN(value) || math.IsInf(value, 0) {
				return nil, fmt.Errorf("embedding for %s contains a non-finite value", document.ID)
			}
			embedding[j] = float32(value)
		}
		rows[i] = Row{VectorID: document.VectorID(), ItemID: document.ID, Kind: document.Kind, Fingerprint: document.Fingerprint, Embedding: embedding}
	}
	return rows, nil
}
