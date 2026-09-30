package docsemantic

import (
	"context"
	"testing"

	"github.com/milvus-io/milvus-sdk-go/v2/entity"
)

func TestFilterExpression(t *testing.T) {
	cases := []struct {
		filter Filter
		want   string
	}{
		{Filter{}, ""},
		{Filter{Source: "arxiv"}, `source == "arxiv"`},
		{Filter{SinceDay: 20260929}, "published_day >= 20260929"},
		{Filter{Source: "x", SinceDay: 20260929, UntilDay: 20261001}, `source == "x" && published_day >= 20260929 && published_day < 20261001`},
		{Filter{Source: `a"b\c`}, `source == "a\"b\\c"`},
	}
	for _, tc := range cases {
		if got := FilterExpression(tc.filter); got != tc.want {
			t.Errorf("FilterExpression(%+v) = %q, want %q", tc.filter, got, tc.want)
		}
	}
}

func TestNewMilvusDocumentVectorsDefaults(t *testing.T) {
	m, err := NewMilvusDocumentVectors(MilvusConfig{Dimension: 3})
	if err != nil {
		t.Fatal(err)
	}
	want := MilvusConfig{Host: "localhost", Port: 19530, DBName: "default", CollectionName: "aigc_document_vectors_v1", Dimension: 3, MetricType: "COSINE"}
	if m.cfg != want {
		t.Fatalf("cfg = %+v, want %+v", m.cfg, want)
	}
	if _, err := NewMilvusDocumentVectors(MilvusConfig{}); err == nil {
		t.Fatal("expected invalid dimension error")
	}
}

func TestSearchDocumentsRejectsBadInputWithoutConnecting(t *testing.T) {
	m, err := NewMilvusDocumentVectors(MilvusConfig{Dimension: 3})
	if err != nil {
		t.Fatal(err)
	}
	m.connect = nil // 任何连接尝试都会 panic
	if _, err := m.SearchDocuments(context.Background(), []float64{1, 2}, 5, Filter{}); err == nil {
		t.Fatal("expected dimension mismatch")
	}
	hits, err := m.SearchDocuments(context.Background(), []float64{1, 2, 3}, 0, Filter{})
	if err != nil || len(hits) != 0 {
		t.Fatalf("topK=0 got %v %v", hits, err)
	}
}

func documentSchema(dim string, mutate func([]*entity.Field) []*entity.Field) *entity.Collection {
	fields := []*entity.Field{
		{Name: "doc_id", DataType: entity.FieldTypeVarChar, PrimaryKey: true},
		{Name: "source", DataType: entity.FieldTypeVarChar},
		{Name: "published_day", DataType: entity.FieldTypeInt64},
		{Name: "fingerprint", DataType: entity.FieldTypeVarChar},
		{Name: "embedding", DataType: entity.FieldTypeFloatVector, TypeParams: map[string]string{"dim": dim}},
	}
	if mutate != nil {
		fields = mutate(fields)
	}
	return &entity.Collection{Schema: &entity.Schema{Fields: fields}}
}

func TestValidateSchema(t *testing.T) {
	if err := ValidateSchema(documentSchema("1024", nil), 1024); err != nil {
		t.Fatalf("valid schema rejected: %v", err)
	}
	bad := map[string]*entity.Collection{
		"nil collection": nil,
		"nil schema":     {},
		"dimension":      documentSchema("768", nil),
		"auto id": documentSchema("1024", func(f []*entity.Field) []*entity.Field {
			f[0].AutoID = true
			return f
		}),
		"not primary": documentSchema("1024", func(f []*entity.Field) []*entity.Field {
			f[0].PrimaryKey = false
			return f
		}),
		"wrong type": documentSchema("1024", func(f []*entity.Field) []*entity.Field {
			f[2].DataType = entity.FieldTypeVarChar
			return f
		}),
		"missing field": documentSchema("1024", func(f []*entity.Field) []*entity.Field {
			return f[:4]
		}),
		"extra field": documentSchema("1024", func(f []*entity.Field) []*entity.Field {
			return append(f, &entity.Field{Name: "text", DataType: entity.FieldTypeVarChar})
		}),
	}
	for name, collection := range bad {
		if err := ValidateSchema(collection, 1024); err == nil {
			t.Errorf("%s: expected schema error", name)
		}
	}
}
