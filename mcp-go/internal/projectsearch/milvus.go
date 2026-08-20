package projectsearch

import (
	"context"
	"errors"
	"fmt"
	"net"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	milvus "github.com/milvus-io/milvus-sdk-go/v2/client"
	"github.com/milvus-io/milvus-sdk-go/v2/entity"
)

// MilvusConfig 对齐 backend/app/core/config.py:170-178 与
// project_semantic_collection_name（:193）：MILVUS_HOST（默认 localhost）、
// MILVUS_PORT（19530）、MILVUS_USER/PASSWORD（空）、MILVUS_DB_NAME（default）、
// MILVUS_DIMENSION（1024）、MILVUS_INDEX_TYPE（HNSW）、MILVUS_METRIC_TYPE
// （COSINE）、PROJECT_SEMANTIC_COLLECTION_NAME（aigc_github_projects_v1）。
type MilvusConfig struct {
	Host                string
	Port                int
	User                string
	Password            string
	DBName              string
	CollectionName      string
	Dimension           int
	IndexType           string
	MetricType          string
	QueryTimeout        time.Duration
	QueryTimeoutSeconds float64
}

// MilvusVectorRepository 是 Milvus 只读检索适配器。它只在首次搜索时连接、
// 校验集合存在、校验 schema、load 集合；集合不存在时返回错误，**绝不
// auto-create**。这是和 Python ensure_collection（缺失时建集合+HNSW
// 索引）的有意 divergence：读路径不应在多副本部署中产生副作用或竞态。
type MilvusVectorRepository struct {
	cfg MilvusConfig

	mu        sync.Mutex
	client    milvus.Client
	connected bool
	verified  bool
	connect   func(context.Context, milvus.Config) (milvus.Client, error)
}

// NewMilvusVectorRepository 构造懒连接的 verify-only Milvus 读适配器。
// 构造阶段只校验本地参数，不触碰网络；网络/集合/schema 错误在首用时返回。
func NewMilvusVectorRepository(cfg MilvusConfig) (*MilvusVectorRepository, error) {
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
		cfg.CollectionName = "aigc_github_projects_v1"
	}
	if cfg.Dimension <= 0 {
		return nil, errors.New("milvus dimension must be positive")
	}
	if cfg.IndexType == "" {
		cfg.IndexType = "HNSW"
	}
	if cfg.MetricType == "" {
		cfg.MetricType = "COSINE"
	}
	if cfg.QueryTimeout <= 0 {
		if cfg.QueryTimeoutSeconds <= 0 {
			cfg.QueryTimeout = 6 * time.Second
		} else {
			cfg.QueryTimeout = semanticTimeout(cfg.QueryTimeoutSeconds)
		}
	}
	r := &MilvusVectorRepository{cfg: cfg}
	r.connect = func(ctx context.Context, config milvus.Config) (milvus.Client, error) {
		return milvus.NewClient(ctx, config)
	}
	return r, nil
}

// NewMilvusVectorRepositoryWithClientFactory is an internal test/wiring seam
// that avoids a real Milvus connection while retaining the production
// constructor's lazy lifecycle. The factory receives the SDK Config exactly as
// NewMilvusVectorRepository would pass it.
func NewMilvusVectorRepositoryWithClientFactory(cfg MilvusConfig, factory func(context.Context, milvus.Config) (milvus.Client, error)) (*MilvusVectorRepository, error) {
	r, err := NewMilvusVectorRepository(cfg)
	if err != nil {
		return nil, err
	}
	if factory == nil {
		return nil, errors.New("milvus client factory is nil")
	}
	r.connect = factory
	return r, nil
}

// Close disconnects the SDK client. It is safe before first use and after
// repeated calls. A later search reconnects and repeats verify-only checks.
func (r *MilvusVectorRepository) Close() error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.client == nil {
		r.connected = false
		r.verified = false
		return nil
	}
	err := r.client.Close()
	r.client = nil
	r.connected = false
	r.verified = false
	return err
}

// SearchRepoIDs implements VectorRepository and the Python read path:
// dimension check → collection search with metric_type and ef=max(64,
// chunk_limit), limit=chunk_limit, output_fields=[repo_id] → per-repo max score
// → score threshold → (-score, repo_id) → repo_limit.
func (r *MilvusVectorRepository) SearchRepoIDs(queryVector []float64, chunkLimit, repoLimit int, minScore float64) ([]SemanticHit, error) {
	if len(queryVector) != r.cfg.Dimension {
		return nil, errors.New("query embedding dimension mismatch")
	}
	if chunkLimit <= 0 {
		return nil, errors.New("milvus chunk limit must be positive")
	}
	if repoLimit <= 0 {
		return []SemanticHit{}, nil
	}
	ctx, cancel := context.WithTimeout(context.Background(), r.cfg.QueryTimeout)
	defer cancel()
	if err := r.ensureVerified(ctx); err != nil {
		return nil, err
	}

	vector := make(entity.FloatVector, len(queryVector))
	for i, value := range queryVector {
		vector[i] = float32(value)
	}
	searchParam := &milvusSearchParam{params: map[string]interface{}{"ef": max(64, chunkLimit)}}
	results, err := r.client.Search(
		ctx,
		r.cfg.CollectionName,
		nil,
		"",
		[]string{"repo_id"},
		[]entity.Vector{vector},
		"embedding",
		entity.MetricType(strings.ToUpper(r.cfg.MetricType)),
		chunkLimit,
		searchParam,
	)
	if err != nil {
		return nil, err
	}
	if len(results) == 0 {
		return []SemanticHit{}, nil
	}
	result := results[0]
	column := result.Fields.GetColumn("repo_id")
	if column == nil {
		return nil, errors.New("milvus search result has no repo_id field")
	}
	scores := result.Scores
	aggregated := make(map[string]float64)
	count := column.Len()
	if len(scores) < count {
		count = len(scores)
	}
	for i := 0; i < count; i++ {
		repoID, err := column.GetAsString(i)
		if err != nil {
			return nil, fmt.Errorf("read milvus repo_id at %d: %w", i, err)
		}
		if repoID == "" {
			continue
		}
		score := float64(scores[i])
		if score < minScore {
			continue
		}
		if previous, ok := aggregated[repoID]; !ok || score > previous {
			aggregated[repoID] = score
		}
	}
	ordered := make([]SemanticHit, 0, len(aggregated))
	for repoID, score := range aggregated {
		ordered = append(ordered, SemanticHit{RepoID: repoID, Score: score})
	}
	sort.Slice(ordered, func(i, j int) bool {
		if ordered[i].Score != ordered[j].Score {
			return ordered[i].Score > ordered[j].Score
		}
		return ordered[i].RepoID < ordered[j].RepoID
	})
	if len(ordered) > repoLimit {
		ordered = ordered[:repoLimit]
	}
	return ordered, nil
}

// MilvusSearchParameters is the pure parameter representation used by the
// adapter and tests. It mirrors Python's param={metric_type, params:{ef}}.
type MilvusSearchParameters struct {
	MetricType string
	EF         int
	Limit      int
}

// BuildMilvusSearchParameters exposes the deterministic parameter assembly for
// unit tests and wiring diagnostics; it does not connect to Milvus.
func BuildMilvusSearchParameters(metricType string, chunkLimit int) MilvusSearchParameters {
	return MilvusSearchParameters{
		MetricType: strings.ToUpper(strings.TrimSpace(metricType)),
		EF:         max(64, chunkLimit),
		Limit:      chunkLimit,
	}
}

// milvusSearchParam lets the SDK carry the exact Python ef map without tying
// this read path to one Milvus index-specific generated parameter constructor.
type milvusSearchParam struct {
	params map[string]interface{}
}

func (p *milvusSearchParam) Params() map[string]interface{} {
	params := make(map[string]interface{}, len(p.params))
	for key, value := range p.params {
		params[key] = value
	}
	return params
}
func (p *milvusSearchParam) AddRadius(radius float64)      { p.params["radius"] = radius }
func (p *milvusSearchParam) AddRangeFilter(filter float64) { p.params["range_filter"] = filter }

func (r *MilvusVectorRepository) ensureVerified(ctx context.Context) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.verified && r.client != nil {
		return nil
	}
	if r.connect == nil {
		return errors.New("milvus client factory is nil")
	}
	if r.client == nil {
		config := milvus.Config{
			Address:  net.JoinHostPort(r.cfg.Host, strconv.Itoa(r.cfg.Port)),
			Username: r.cfg.User,
			Password: r.cfg.Password,
			DBName:   r.cfg.DBName,
		}
		client, err := r.connect(ctx, config)
		if err != nil {
			return fmt.Errorf("connect to milvus: %w", err)
		}
		r.client = client
		r.connected = true
	}
	hasCollection, err := r.client.HasCollection(ctx, r.cfg.CollectionName)
	if err != nil {
		return fmt.Errorf("check milvus collection %q: %w", r.cfg.CollectionName, err)
	}
	if !hasCollection {
		return fmt.Errorf("milvus collection %q does not exist (verify-only; auto-create disabled)", r.cfg.CollectionName)
	}
	collection, err := r.client.DescribeCollection(ctx, r.cfg.CollectionName)
	if err != nil {
		return fmt.Errorf("describe milvus collection %q: %w", r.cfg.CollectionName, err)
	}
	if err := validateMilvusCollectionSchema(collection, r.cfg.Dimension); err != nil {
		return err
	}
	if err := r.client.LoadCollection(ctx, r.cfg.CollectionName, false); err != nil {
		return fmt.Errorf("load milvus collection %q: %w", r.cfg.CollectionName, err)
	}
	r.verified = true
	return nil
}

// validateMilvusCollectionSchema is verify-only and intentionally strict. The
// schema is the seven-field index contract from project_vector_repo.py:
// chunk_id VARCHAR(64) PK, repo_id VARCHAR(255), chunk_kind VARCHAR(16),
// chunk_index INT64, source_fingerprint VARCHAR(64), content VARCHAR(16384),
// embedding FLOAT_VECTOR(dim).
func validateMilvusCollectionSchema(collection *entity.Collection, dimension int) error {
	if collection == nil || collection.Schema == nil {
		return errors.New("milvus collection schema is missing")
	}
	fields := make(map[string]*entity.Field, len(collection.Schema.Fields))
	for _, field := range collection.Schema.Fields {
		if field == nil {
			return errors.New("milvus collection schema contains nil field")
		}
		fields[field.Name] = field
	}
	required := map[string]struct{}{
		"chunk_id": {}, "repo_id": {}, "chunk_kind": {}, "chunk_index": {},
		"source_fingerprint": {}, "content": {}, "embedding": {},
	}
	if len(fields) != len(required) {
		return fmt.Errorf("unexpected Milvus schema: expected fields %v, got %v", sortedFieldNames(required), sortedEntityFieldNames(fields))
	}
	for name := range required {
		if _, ok := fields[name]; !ok {
			return fmt.Errorf("unexpected Milvus schema: missing field %q", name)
		}
	}
	chunkID := fields["chunk_id"]
	if chunkID.DataType != entity.FieldTypeVarChar || !chunkID.PrimaryKey || chunkID.AutoID || varcharMaxLength(chunkID) != 64 {
		return errors.New("unexpected Milvus schema for chunk_id")
	}
	if fields["repo_id"].DataType != entity.FieldTypeVarChar || varcharMaxLength(fields["repo_id"]) != 255 {
		return errors.New("unexpected Milvus schema for repo_id")
	}
	if fields["chunk_kind"].DataType != entity.FieldTypeVarChar || varcharMaxLength(fields["chunk_kind"]) != 16 {
		return errors.New("unexpected Milvus schema for chunk_kind")
	}
	if fields["chunk_index"].DataType != entity.FieldTypeInt64 {
		return errors.New("unexpected Milvus schema for chunk_index")
	}
	if fields["source_fingerprint"].DataType != entity.FieldTypeVarChar || varcharMaxLength(fields["source_fingerprint"]) != 64 {
		return errors.New("unexpected Milvus schema for source_fingerprint")
	}
	if fields["content"].DataType != entity.FieldTypeVarChar || varcharMaxLength(fields["content"]) != 16384 {
		return errors.New("unexpected Milvus schema for content")
	}
	embedding := fields["embedding"]
	if embedding.DataType != entity.FieldTypeFloatVector || fieldDimension(embedding) != dimension {
		return fmt.Errorf("embedding dimension mismatch: collection=%d configured=%d", fieldDimension(embedding), dimension)
	}
	return nil
}

func varcharMaxLength(field *entity.Field) int {
	if field == nil {
		return 0
	}
	return parseFieldInt(field.TypeParams, "max_length")
}

func fieldDimension(field *entity.Field) int {
	if field == nil {
		return 0
	}
	return parseFieldInt(field.TypeParams, "dim")
}

func parseFieldInt(params map[string]string, key string) int {
	value, err := strconv.Atoi(params[key])
	if err != nil {
		return 0
	}
	return value
}

func sortedFieldNames(fields map[string]struct{}) []string {
	names := make([]string, 0, len(fields))
	for name := range fields {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}

func sortedEntityFieldNames(fields map[string]*entity.Field) []string {
	names := make([]string, 0, len(fields))
	for name := range fields {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}

func semanticTimeout(seconds float64) time.Duration {
	if seconds < 0.1 {
		seconds = 0.1
	}
	return time.Duration(seconds * float64(time.Second))
}
