package uisemantic

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
// UI_SEMANTIC_COLLECTION_NAME（默认 aigc_ui_catalog_vectors_v1）。
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

// Row 是一条待写入的向量。
type Row struct {
	VectorID    string
	ItemID      string
	Kind        string
	Fingerprint string
	Embedding   []float32
}

// Hit 是一条语义命中，Fingerprint 供检索侧与当前目录复核。
type Hit struct {
	ItemID      string
	Fingerprint string
	Score       float64
}

// MilvusStore 是集合的唯一属主：同步路径缺集合时建集合与 HNSW 索引，
// 检索路径缺集合时报错而不建（读路径无副作用）。
type MilvusStore struct {
	cfg MilvusConfig

	mu      sync.Mutex
	client  milvus.Client
	ready   bool
	connect func(context.Context, milvus.Config) (milvus.Client, error)
}

func NewMilvusStore(cfg MilvusConfig) (*MilvusStore, error) {
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
		cfg.CollectionName = "aigc_ui_catalog_vectors_v1"
	}
	if cfg.MetricType == "" {
		cfg.MetricType = "COSINE"
	}
	if cfg.Dimension <= 0 {
		return nil, errors.New("milvus dimension must be positive")
	}
	return &MilvusStore{cfg: cfg, connect: func(ctx context.Context, config milvus.Config) (milvus.Client, error) {
		return milvus.NewClient(ctx, config)
	}}, nil
}

func (m *MilvusStore) Close() error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.ready = false
	if m.client == nil {
		return nil
	}
	err := m.client.Close()
	m.client = nil
	return err
}

// Existing 返回 vectorIDs 中已在集合里的主键；主键是十六进制摘要，可直接入表达式。
func (m *MilvusStore) Existing(ctx context.Context, vectorIDs []string) (map[string]bool, error) {
	found := make(map[string]bool, len(vectorIDs))
	if len(vectorIDs) == 0 {
		return found, nil
	}
	client, err := m.ensureReady(ctx, true)
	if err != nil {
		return nil, err
	}
	result, err := client.Query(ctx, m.cfg.CollectionName, nil, InExpression("vector_id", vectorIDs), []string{"vector_id"})
	if err != nil {
		return nil, fmt.Errorf("query milvus vector ids: %w", err)
	}
	column := result.GetColumn("vector_id")
	if column == nil {
		return found, nil
	}
	for i := 0; i < column.Len(); i++ {
		id, err := column.GetAsString(i)
		if err != nil {
			return nil, fmt.Errorf("read milvus vector_id at %d: %w", i, err)
		}
		found[id] = true
	}
	return found, nil
}

func (m *MilvusStore) Upsert(ctx context.Context, rows []Row) error {
	if len(rows) == 0 {
		return nil
	}
	client, err := m.ensureReady(ctx, true)
	if err != nil {
		return err
	}
	vectorIDs := make([]string, len(rows))
	itemIDs := make([]string, len(rows))
	kinds := make([]string, len(rows))
	fingerprints := make([]string, len(rows))
	embeddings := make([][]float32, len(rows))
	for i, row := range rows {
		if len(row.Embedding) != m.cfg.Dimension {
			return fmt.Errorf("embedding dimension mismatch for %s: got %d want %d", row.ItemID, len(row.Embedding), m.cfg.Dimension)
		}
		vectorIDs[i], itemIDs[i], kinds[i], fingerprints[i], embeddings[i] = row.VectorID, row.ItemID, row.Kind, row.Fingerprint, row.Embedding
	}
	_, err = client.Upsert(ctx, m.cfg.CollectionName, "",
		entity.NewColumnVarChar("vector_id", vectorIDs),
		entity.NewColumnVarChar("item_id", itemIDs),
		entity.NewColumnVarChar("kind", kinds),
		entity.NewColumnVarChar("fingerprint", fingerprints),
		entity.NewColumnFloatVector("embedding", m.cfg.Dimension, embeddings),
	)
	if err != nil {
		return fmt.Errorf("upsert milvus ui vectors: %w", err)
	}
	return nil
}

func (m *MilvusStore) Flush(ctx context.Context) error {
	client, err := m.ensureReady(ctx, true)
	if err != nil {
		return err
	}
	return client.Flush(ctx, m.cfg.CollectionName, false)
}

// Search 按 kind 过滤做 ANN 检索，返回按相似度降序的命中。
func (m *MilvusStore) Search(ctx context.Context, vector []float64, kind string, topK int) ([]Hit, error) {
	if len(vector) != m.cfg.Dimension {
		return nil, errors.New("query embedding dimension mismatch")
	}
	if topK <= 0 {
		return []Hit{}, nil
	}
	client, err := m.ensureReady(ctx, false)
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
	results, err := client.Search(ctx, m.cfg.CollectionName, nil, "kind == "+strconv.Quote(kind), []string{"item_id", "fingerprint"},
		[]entity.Vector{query}, "embedding", entity.MetricType(strings.ToUpper(m.cfg.MetricType)), topK, param)
	if err != nil {
		return nil, err
	}
	if len(results) == 0 {
		return []Hit{}, nil
	}
	result := results[0]
	items, fingerprints := result.Fields.GetColumn("item_id"), result.Fields.GetColumn("fingerprint")
	if items == nil || fingerprints == nil {
		return []Hit{}, nil
	}
	count := min(items.Len(), fingerprints.Len(), len(result.Scores))
	hits := make([]Hit, 0, count)
	for i := 0; i < count; i++ {
		itemID, err := items.GetAsString(i)
		if err != nil {
			return nil, fmt.Errorf("read milvus item_id at %d: %w", i, err)
		}
		fingerprint, err := fingerprints.GetAsString(i)
		if err != nil {
			return nil, fmt.Errorf("read milvus fingerprint at %d: %w", i, err)
		}
		hits = append(hits, Hit{ItemID: itemID, Fingerprint: fingerprint, Score: float64(result.Scores[i])})
	}
	return hits, nil
}

// InExpression 渲染 field in ["a", "b"]；值经 strconv.Quote 转义。
func InExpression(field string, values []string) string {
	quoted := make([]string, len(values))
	for i, value := range values {
		quoted[i] = strconv.Quote(value)
	}
	return field + " in [" + strings.Join(quoted, ", ") + "]"
}

func (m *MilvusStore) ensureReady(ctx context.Context, create bool) (milvus.Client, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.ready && m.client != nil {
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
		if !create {
			return nil, fmt.Errorf("milvus collection %q does not exist yet (created by the startup sync)", m.cfg.CollectionName)
		}
		if err := m.createCollection(ctx); err != nil {
			return nil, err
		}
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
	m.ready = true
	return m.client, nil
}

func (m *MilvusStore) createCollection(ctx context.Context) error {
	if err := m.client.CreateCollection(ctx, Schema(m.cfg.CollectionName, m.cfg.Dimension), 1); err != nil {
		return fmt.Errorf("create milvus collection %q: %w", m.cfg.CollectionName, err)
	}
	index, err := entity.NewIndexHNSW(entity.MetricType(strings.ToUpper(m.cfg.MetricType)), 16, 200)
	if err != nil {
		return err
	}
	if err := m.client.CreateIndex(ctx, m.cfg.CollectionName, "embedding", index, false); err != nil {
		return fmt.Errorf("create milvus index on %q: %w", m.cfg.CollectionName, err)
	}
	return nil
}

// Schema 是集合的五字段契约；ValidateSchema 按同一契约校验已有集合。
func Schema(name string, dimension int) *entity.Schema {
	return entity.NewSchema().
		WithName(name).
		WithDescription("AIGCNEWS UI template and icon semantic index").
		WithField(entity.NewField().WithName("vector_id").WithDataType(entity.FieldTypeVarChar).WithMaxLength(64).WithIsPrimaryKey(true).WithIsAutoID(false)).
		WithField(entity.NewField().WithName("item_id").WithDataType(entity.FieldTypeVarChar).WithMaxLength(255)).
		WithField(entity.NewField().WithName("kind").WithDataType(entity.FieldTypeVarChar).WithMaxLength(16)).
		WithField(entity.NewField().WithName("fingerprint").WithDataType(entity.FieldTypeVarChar).WithMaxLength(64)).
		WithField(entity.NewField().WithName("embedding").WithDataType(entity.FieldTypeFloatVector).WithDim(int64(dimension)))
}

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
		"vector_id":   entity.FieldTypeVarChar,
		"item_id":     entity.FieldTypeVarChar,
		"kind":        entity.FieldTypeVarChar,
		"fingerprint": entity.FieldTypeVarChar,
		"embedding":   entity.FieldTypeFloatVector,
	}
	if len(fields) != len(want) {
		return fmt.Errorf("unexpected ui vector schema: %d fields", len(fields))
	}
	for name, fieldType := range want {
		field, ok := fields[name]
		if !ok || field.DataType != fieldType {
			return fmt.Errorf("unexpected ui vector schema for %s", name)
		}
	}
	if vectorID := fields["vector_id"]; !vectorID.PrimaryKey || vectorID.AutoID {
		return errors.New("unexpected ui vector schema: vector_id must be a manual primary key")
	}
	if got, _ := strconv.Atoi(fields["embedding"].TypeParams["dim"]); got != dimension {
		return fmt.Errorf("embedding dimension mismatch: collection=%d configured=%d", got, dimension)
	}
	return nil
}
