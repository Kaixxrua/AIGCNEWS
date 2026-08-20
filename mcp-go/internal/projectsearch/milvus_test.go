package projectsearch

import (
	"testing"
	"time"
)

func TestBuildMilvusSearchParameters(t *testing.T) {
	cases := []struct {
		metric string
		limit  int
		want   MilvusSearchParameters
	}{
		{"cosine", 1, MilvusSearchParameters{MetricType: "COSINE", EF: 64, Limit: 1}},
		{" COSINE ", 800, MilvusSearchParameters{MetricType: "COSINE", EF: 800, Limit: 800}},
		{"ip", 100, MilvusSearchParameters{MetricType: "IP", EF: 100, Limit: 100}},
	}
	for _, tc := range cases {
		if got := BuildMilvusSearchParameters(tc.metric, tc.limit); got != tc.want {
			t.Errorf("BuildMilvusSearchParameters(%q,%d) = %#v, want %#v", tc.metric, tc.limit, got, tc.want)
		}
	}
}

func TestNewMilvusVectorRepositoryDefaultsAndDimensionValidation(t *testing.T) {
	r, err := NewMilvusVectorRepository(MilvusConfig{Dimension: 3})
	if err != nil {
		t.Fatal(err)
	}
	if r.cfg.Host != "localhost" || r.cfg.Port != 19530 || r.cfg.DBName != "default" || r.cfg.CollectionName != "aigc_github_projects_v1" || r.cfg.MetricType != "COSINE" || r.cfg.QueryTimeout != 6*time.Second {
		t.Fatalf("defaults %#v", r.cfg)
	}
	if _, err := r.SearchRepoIDs([]float64{1, 2}, 10, 2, .45); err == nil || err.Error() != "query embedding dimension mismatch" {
		t.Fatalf("dimension error %v", err)
	}
}

func TestNewMilvusVectorRepositoryRejectsInvalidDimension(t *testing.T) {
	if _, err := NewMilvusVectorRepository(MilvusConfig{}); err == nil {
		t.Fatal("expected invalid dimension error")
	}
}
