package docsemantic

import (
	"context"
	"errors"
	"reflect"
	"sync"
	"testing"
	"time"
)

type fakeEmbedder struct {
	mu     sync.Mutex
	calls  []string
	vector []float64
	err    error
	block  chan struct{}
}

func (f *fakeEmbedder) EmbedQuery(text string) ([]float64, error) {
	f.mu.Lock()
	f.calls = append(f.calls, text)
	f.mu.Unlock()
	if f.block != nil {
		<-f.block
	}
	return f.vector, f.err
}

func (f *fakeEmbedder) callCount() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return len(f.calls)
}

type fakeVectors struct {
	hits    []Hit
	err     error
	topK    int
	filter  Filter
	vector  []float64
	calls   int
	hasDead bool
}

func (f *fakeVectors) SearchDocuments(ctx context.Context, vector []float64, topK int, filter Filter) ([]Hit, error) {
	f.calls++
	f.vector, f.topK, f.filter = vector, topK, filter
	_, f.hasDead = ctx.Deadline()
	return f.hits, f.err
}

func TestSearchDocumentIDsAppliesMinScoreAndDedup(t *testing.T) {
	embedder := &fakeEmbedder{vector: []float64{1, 0}}
	vectors := &fakeVectors{hits: []Hit{
		{ID: "a", Score: .9}, {ID: "b", Score: .7}, {ID: "a", Score: .69},
		{ID: "", Score: .8}, {ID: "c", Score: .49}, {ID: "d", Score: .5},
	}}
	retriever := NewRetriever(embedder, vectors, Config{TopK: 7, MinScore: .5})
	got, err := retriever.SearchDocumentIDs("  openai 发布  ", " ArXiv ", "2026-09-29", "2026-10-01")
	if err != nil {
		t.Fatal(err)
	}
	if want := []string{"a", "b", "d"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("ids = %v, want %v", got, want)
	}
	if !reflect.DeepEqual(embedder.calls, []string{"openai 发布"}) {
		t.Fatalf("embedded %q", embedder.calls)
	}
	if vectors.topK != 7 || !vectors.hasDead || !reflect.DeepEqual(vectors.vector, []float64{1, 0}) {
		t.Fatalf("search call topK=%d deadline=%v vector=%v", vectors.topK, vectors.hasDead, vectors.vector)
	}
	if want := (Filter{Source: "arxiv", SinceDay: 20260929, UntilDay: 20261001}); vectors.filter != want {
		t.Fatalf("filter = %+v, want %+v", vectors.filter, want)
	}
}

func TestSearchDocumentIDsDefaults(t *testing.T) {
	retriever := NewRetriever(&fakeEmbedder{}, &fakeVectors{}, Config{})
	if retriever.cfg.TopK != 50 || retriever.cfg.TimeoutSeconds != 3 || retriever.cfg.CacheSize != 256 || retriever.cfg.MinScore != 0 {
		t.Fatalf("defaults %+v", retriever.cfg)
	}
}

func TestSearchDocumentIDsBlankQuerySkipsBackends(t *testing.T) {
	embedder, vectors := &fakeEmbedder{}, &fakeVectors{}
	got, err := NewRetriever(embedder, vectors, Config{}).SearchDocumentIDs("   ", "", "", "")
	if err != nil || len(got) != 0 || got == nil {
		t.Fatalf("got %#v err %v", got, err)
	}
	if embedder.callCount() != 0 || vectors.calls != 0 {
		t.Fatal("blank query must not reach embedding or Milvus")
	}
}

func TestSearchDocumentIDsMissingDependencies(t *testing.T) {
	if _, err := NewRetriever(nil, &fakeVectors{}, Config{}).SearchDocumentIDs("q", "", "", ""); err == nil {
		t.Fatal("expected error without embedder")
	}
	if _, err := NewRetriever(&fakeEmbedder{}, nil, Config{}).SearchDocumentIDs("q", "", "", ""); err == nil {
		t.Fatal("expected error without vectors")
	}
}

func TestSearchDocumentIDsPropagatesFailures(t *testing.T) {
	boom := errors.New("boom")
	if _, err := NewRetriever(&fakeEmbedder{err: boom}, &fakeVectors{}, Config{}).SearchDocumentIDs("q", "", "", ""); !errors.Is(err, boom) {
		t.Fatalf("embedding error = %v", err)
	}
	if _, err := NewRetriever(&fakeEmbedder{vector: []float64{1}}, &fakeVectors{err: boom}, Config{}).SearchDocumentIDs("q", "", "", ""); !errors.Is(err, boom) {
		t.Fatalf("vector error = %v", err)
	}
}

func TestSearchDocumentIDsEmbeddingFailureIsNotCached(t *testing.T) {
	embedder := &fakeEmbedder{err: errors.New("down")}
	retriever := NewRetriever(embedder, &fakeVectors{}, Config{})
	_, _ = retriever.SearchDocumentIDs("q", "", "", "")
	embedder.err, embedder.vector = nil, []float64{1}
	if _, err := retriever.SearchDocumentIDs("q", "", "", ""); err != nil {
		t.Fatal(err)
	}
	if embedder.callCount() != 2 {
		t.Fatalf("embed calls = %d, want 2", embedder.callCount())
	}
}

func TestSearchDocumentIDsTimesOutSlowEmbedding(t *testing.T) {
	embedder := &fakeEmbedder{vector: []float64{1}, block: make(chan struct{})}
	defer close(embedder.block)
	vectors := &fakeVectors{}
	started := time.Now()
	_, err := NewRetriever(embedder, vectors, Config{TimeoutSeconds: .05}).SearchDocumentIDs("q", "", "", "")
	if err == nil {
		t.Fatal("expected timeout error")
	}
	if elapsed := time.Since(started); elapsed > time.Second {
		t.Fatalf("timeout took %s", elapsed)
	}
	if vectors.calls != 0 {
		t.Fatal("Milvus must not be queried after the embedding budget is spent")
	}
}

func TestSearchDocumentIDsCachesQueryVectors(t *testing.T) {
	embedder := &fakeEmbedder{vector: []float64{1}}
	retriever := NewRetriever(embedder, &fakeVectors{}, Config{CacheSize: 2})
	for _, query := range []string{"a", "a", "b", " a ", "c", "a"} {
		if _, err := retriever.SearchDocumentIDs(query, "", "", ""); err != nil {
			t.Fatal(err)
		}
	}
	// a、b 进缓存；c 挤掉最早的 a，最后一次 a 重新 embedding。
	if want := []string{"a", "b", "c", "a"}; !reflect.DeepEqual(embedder.calls, want) {
		t.Fatalf("embedded %q, want %q", embedder.calls, want)
	}
}

func TestDayNumber(t *testing.T) {
	cases := map[string]int{
		"2026-09-29":          20260929,
		"2026-09-29T10:00:00": 20260929,
		" 2026-01-02 ":        20260102,
		"":                    0,
		"2026/09/29":          0,
		"2026-9-29":           0,
		"abcd-ef-gh":          0,
	}
	for in, want := range cases {
		if got := dayNumber(in); got != want {
			t.Errorf("dayNumber(%q) = %d, want %d", in, got, want)
		}
	}
}
