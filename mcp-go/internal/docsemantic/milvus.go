package docsemantic

import (
	"context"
	"errors"
	"fmt"
	"net"
	"strconv"
	"strings"
	"sync"

	milvus "github.com/milvus-io/milvus-sdk-go/v2/client"
	"github.com/milvus-io/milvus-sdk-go/v2/entity"
)

// MilvusConfig 复用 MILVUS_* 连接配置；CollectionName 对应
// DOCUMENT_SEMANTIC_COLLECTION_NAME（默认 aigc_document_vectors_v1）。
type MilvusConfig struct {
	Host           string
	Port           int
	User           string
	Password       string
	DBName         string
	CollectionName string
	Dimension      int
	MetricType     string
}

// MilvusDocumentVectors 是只读适配器：首用时连接、校验 schema 并 load；
// 集合缺失时报错而**不建集合**（建集合归 backend indexer，读路径无副作用）。
type MilvusDocumentVectors struct {
	cfg MilvusConfig

	mu       sync.Mutex
	client   milvus.Client
	verified bool
	connect  func(context.Context, milvus.Config) (milvus.Client, error)
}

func NewMilvusDocumentVectors(cfg MilvusConfig) (*MilvusDocumentVectors, error) {
	if strings.TrimSpace(cfg.Host) == "" {
		cfg.Host = "localhost"
	}
	if cfg.Port == 0 {
		cfg.Port = 19530
	}
	if cfg.DBName == "" {
		cfg.DBName = "default"
	}
	if cfg.CollectionName == "" {
		cfg.CollectionName = "aigc_document_vectors_v1"
	}
	if cfg.MetricType == "" {
		cfg.MetricType = "COSINE"
	}
	if cfg.Dimension <= 0 {
		return nil, errors.New("milvus dimension must be positive")
	}
	return &MilvusDocumentVectors{cfg: cfg, connect: func(ctx context.Context, config milvus.Config) (milvus.Client, error) {
		return milvus.NewClient(ctx, config)
	}}, nil
}

// Close 断开连接；之后再检索会重连并重新校验。
func (m *MilvusDocumentVectors) Close() error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.verified = false
	if m.client == nil {
		return nil
	}
	err := m.client.Close()
	m.client = nil
	return err
}

// SearchDocuments 实现 VectorSearcher：带标量过滤的 ANN 检索，按相似度降序。
func (m *MilvusDocumentVectors) SearchDocuments(ctx context.Context, vector []float64, topK int, filter Filter) ([]Hit, error) {
	if len(vector) != m.cfg.Dimension {
		return nil, errors.New("query embedding dimension mismatch")
	}
	if topK <= 0 {
		return []Hit{}, nil
	}
	client, err := m.ensureVerified(ctx)
	if err != nil {
		return nil, err
	}
	query := make(entity.FloatVector, len(vector))
	for i, value := range vector {
		query[i] = float32(value)
	}
	param, err := entity.NewIndexHNSWSearchParam(max(64, topK))
	if err != nil {
		return nil, err
	}
	results, err := client.Search(ctx, m.cfg.CollectionName, nil, FilterExpression(filter), []string{"doc_id"},
		[]entity.Vector{query}, "embedding", entity.MetricType(strings.ToUpper(m.cfg.MetricType)), topK, param)
	if err != nil {
		return nil, err
	}
	if len(results) == 0 || results[0].IDs == nil {
		return []Hit{}, nil
	}
	result := results[0]
	count := min(result.IDs.Len(), len(result.Scores))
	hits := make([]Hit, 0, count)
	for i := 0; i < count; i++ {
		id, err := result.IDs.GetAsString(i)
		if err != nil {
			return nil, fmt.Errorf("read milvus doc_id at %d: %w", i, err)
		}
		hits = append(hits, Hit{ID: id, Score: float64(result.Scores[i])})
	}
	return hits, nil
}

// FilterExpression 把过滤条件渲染成 Milvus 布尔表达式；无条件时为空串。
func FilterExpression(filter Filter) string {
	var parts []string
	if filter.Source != "" {
		parts = append(parts, "source == "+strconv.Quote(filter.Source))
	}
	if filter.SinceDay > 0 {
		parts = append(parts, "published_day >= "+strconv.Itoa(filter.SinceDay))
	}
	if filter.UntilDay > 0 {
		parts = append(parts, "published_day < "+strconv.Itoa(filter.UntilDay))
	}
	return strings.Join(parts, " && ")
}

func (m *MilvusDocumentVectors) ensureVerified(ctx context.Context) (milvus.Client, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.verified && m.client != nil {
		return m.client, nil
	}
	if m.client == nil {
		client, err := m.connect(ctx, milvus.Config{
			Address:  net.JoinHostPort(m.cfg.Host, strconv.Itoa(m.cfg.Port)),
			Username: m.cfg.User,
			Password: m.cfg.Password,
			DBName:   m.cfg.DBName,
		})
		if err != nil {
			return nil, fmt.Errorf("connect to milvus: %w", err)
		}
		m.client = client
	}
	exists, err := m.client.HasCollection(ctx, m.cfg.CollectionName)
	if err != nil {
		return nil, fmt.Errorf("check milvus collection %q: %w", m.cfg.CollectionName, err)
	}
	if !exists {
		return nil, fmt.Errorf("milvus collection %q does not exist (run scripts/backfill_document_semantic_index.py)", m.cfg.CollectionName)
	}
	collection, err := m.client.DescribeCollection(ctx, m.cfg.CollectionName)
	if err != nil {
		return nil, fmt.Errorf("describe milvus collection %q: %w", m.cfg.CollectionName, err)
	}
	if err := ValidateSchema(collection, m.cfg.Dimension); err != nil {
		return nil, err
	}
	if err := m.client.LoadCollection(ctx, m.cfg.CollectionName, false); err != nil {
		return nil, fmt.Errorf("load milvus collection %q: %w", m.cfg.CollectionName, err)
	}
	m.verified = true
	return m.client, nil
}

// ValidateSchema 钉死 backend/app/repositories/document_vector_repo.py 的五字段契约。
func ValidateSchema(collection *entity.Collection, dimension int) error {
	if collection == nil || collection.Schema == nil {
		return errors.New("milvus collection schema is missing")
	}
	fields := make(map[string]*entity.Field, len(collection.Schema.Fields))
	for _, field := range collection.Schema.Fields {
		if field != nil {
			fields[field.Name] = field
		}
	}
	want := map[string]entity.FieldType{
		"doc_id":        entity.FieldTypeVarChar,
		"source":        entity.FieldTypeVarChar,
		"published_day": entity.FieldTypeInt64,
		"fingerprint":   entity.FieldTypeVarChar,
		"embedding":     entity.FieldTypeFloatVector,
	}
	if len(fields) != len(want) {
		return fmt.Errorf("unexpected document vector schema: %d fields", len(fields))
	}
	for name, fieldType := range want {
		field, ok := fields[name]
		if !ok || field.DataType != fieldType {
			return fmt.Errorf("unexpected document vector schema for %s", name)
		}
	}
	if docID := fields["doc_id"]; !docID.PrimaryKey || docID.AutoID {
		return errors.New("unexpected document vector schema: doc_id must be a manual primary key")
	}
	if got, _ := strconv.Atoi(fields["embedding"].TypeParams["dim"]); got != dimension {
		return fmt.Errorf("embedding dimension mismatch: collection=%d configured=%d", got, dimension)
	}
	return nil
}
