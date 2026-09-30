package uisemantic

import (
	"context"
	"strings"
	"testing"

	milvus "github.com/milvus-io/milvus-sdk-go/v2/client"
	"github.com/milvus-io/milvus-sdk-go/v2/entity"
)

func TestInExpressionQuotesValues(t *testing.T) {
	if got := InExpression("vector_id", []string{"ab", `q"x`}); got != `vector_id in ["ab", "q\"x"]` {
		t.Fatalf("got %s", got)
	}
}

func TestNewMilvusStoreDefaultsAndValidation(t *testing.T) {
	if _, err := NewMilvusStore(MilvusConfig{}); err == nil {
		t.Fatal("dimension is required")
	}
	store, err := NewMilvusStore(MilvusConfig{Dimension: 4})
	if err != nil {
		t.Fatal(err)
	}
	if store.cfg.Host != "localhost" || store.cfg.Port != 19530 || store.cfg.DBName != "default" || store.cfg.CollectionName != "aigc_ui_catalog_vectors_v1" || store.cfg.MetricType != "COSINE" {
		t.Fatalf("defaults %#v", store.cfg)
	}
}

func TestMilvusStoreRejectsBadInputWithoutConnecting(t *testing.T) {
	store, _ := NewMilvusStore(MilvusConfig{Dimension: 2})
	connects := 0
	store.connect = func(context.Context, milvus.Config) (milvus.Client, error) {
		connects++
		return nil, context.Canceled
	}
	if _, err := store.Search(context.Background(), []float64{1}, KindIcon, 10); err == nil {
		t.Fatal("query dimension mismatch must fail")
	}
	if hits, err := store.Search(context.Background(), []float64{1, 0}, KindIcon, 0); err != nil || len(hits) != 0 {
		t.Fatalf("topK=0: %#v %v", hits, err)
	}
	if found, err := store.Existing(context.Background(), nil); err != nil || len(found) != 0 {
		t.Fatalf("empty lookup: %#v %v", found, err)
	}
	if err := store.Upsert(context.Background(), nil); err != nil {
		t.Fatalf("empty upsert: %v", err)
	}
	if connects != 0 {
		t.Fatalf("no-op calls must not connect, got %d", connects)
	}
	if err := store.Upsert(context.Background(), []Row{{ItemID: "x", Embedding: []float32{1}}}); err == nil || connects != 1 {
		t.Fatalf("connect failure must surface: err=%v connects=%d", err, connects)
	}
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}
}

func TestSchemaRoundTripsThroughValidateSchema(t *testing.T) {
	schema := Schema("aigc_ui_catalog_vectors_v1", 1024)
	if schema.CollectionName != "aigc_ui_catalog_vectors_v1" {
		t.Fatalf("name %q", schema.CollectionName)
	}
	if err := ValidateSchema(&entity.Collection{Schema: schema}, 1024); err != nil {
		t.Fatal(err)
	}
	if err := ValidateSchema(&entity.Collection{Schema: schema}, 768); err == nil || !strings.Contains(err.Error(), "dimension") {
		t.Fatalf("dimension mismatch: %v", err)
	}
}

func TestValidateSchemaRejectsForeignCollections(t *testing.T) {
	autoID := Schema("c", 4)
	autoID.Fields[0].AutoID = true
	extra := Schema("c", 4).WithField(entity.NewField().WithName("content").WithDataType(entity.FieldTypeVarChar))
	wrongType := Schema("c", 4)
	wrongType.Fields[2].DataType = entity.FieldTypeInt64
	for name, collection := range map[string]*entity.Collection{
		"nil":        nil,
		"no schema":  {},
		"auto id":    {Schema: autoID},
		"extra":      {Schema: extra},
		"wrong type": {Schema: wrongType},
	} {
		t.Run(name, func(t *testing.T) {
			if err := ValidateSchema(collection, 4); err == nil {
				t.Fatal("expected schema rejection")
			}
		})
	}
}
