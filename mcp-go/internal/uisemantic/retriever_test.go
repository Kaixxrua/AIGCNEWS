package uisemantic

import (
	"context"
	"errors"
	"reflect"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

type fakeQueryEmbedder struct {
	calls atomic.Int32
	delay time.Duration
	err   error
}

func (e *fakeQueryEmbedder) EmbedQuery(string) ([]float64, error) {
	e.calls.Add(1)
	if e.delay > 0 {
		time.Sleep(e.delay)
	}
	if e.err != nil {
		return nil, e.err
	}
	return []float64{1, 0}, nil
}

type fakeSearcher struct {
	hits  []Hit
	err   error
	kinds []string
	topK  int
}

func (s *fakeSearcher) Search(_ context.Context, _ []float64, kind string, topK int) ([]Hit, error) {
	s.kinds = append(s.kinds, kind)
	s.topK = topK
	return s.hits, s.err
}

func retrieverDocuments() []Document {
	return []Document{
		newDocument("tabler:shopping-cart", KindIcon, "shopping cart icon"),
		newDocument("lucide:shopping-cart", KindIcon, "shopping cart icon\ncommerce"),
		newDocument("tabler:home", KindIcon, "home icon"),
		newDocument("aurora", KindTemplate, "Aurora background"),
	}
}

func TestSearchIDsValidatesFingerprintsScoresAndDuplicates(t *testing.T) {
	documents := retrieverDocuments()
	searcher := &fakeSearcher{hits: []Hit{
		{ItemID: "lucide:shopping-cart", Fingerprint: documents[1].Fingerprint, Score: 0.81},
		{ItemID: "tabler:shopping-cart", Fingerprint: "stale-version", Score: 0.80}, // 旧文本版本
		{ItemID: "tabler:shopping-cart", Fingerprint: documents[0].Fingerprint, Score: 0.79},
		{ItemID: "lucide:shopping-cart", Fingerprint: documents[1].Fingerprint, Score: 0.70}, // 重复
		{ItemID: "removed:icon", Fingerprint: "whatever", Score: 0.75},                       // 已下架
		{ItemID: "aurora", Fingerprint: documents[3].Fingerprint, Score: 0.74},               // 别的 kind
		{ItemID: "tabler:home", Fingerprint: documents[2].Fingerprint, Score: 0.44},          // 低于阈值
	}}
	retriever := NewRetriever(&fakeQueryEmbedder{}, searcher, Config{TopK: 7, MinScore: 0.45}, documents)
	ids, err := retriever.SearchIDs("  购物车 ", KindIcon)
	if err != nil {
		t.Fatal(err)
	}
	if want := []string{"lucide:shopping-cart", "tabler:shopping-cart"}; !reflect.DeepEqual(ids, want) {
		t.Fatalf("ids %#v want %#v", ids, want)
	}
	if !reflect.DeepEqual(searcher.kinds, []string{KindIcon}) || searcher.topK != 7 {
		t.Fatalf("search kinds %#v topK %d", searcher.kinds, searcher.topK)
	}
}

func TestSearchIDsBlankQueryAndMissingDependencies(t *testing.T) {
	embedder := &fakeQueryEmbedder{}
	if ids, err := NewRetriever(embedder, &fakeSearcher{}, Config{}, nil).SearchIDs("   ", KindIcon); err != nil || len(ids) != 0 || embedder.calls.Load() != 0 {
		t.Fatalf("blank query: ids=%#v err=%v calls=%d", ids, err, embedder.calls.Load())
	}
	if _, err := NewRetriever(nil, &fakeSearcher{}, Config{}, nil).SearchIDs("cart", KindIcon); err == nil {
		t.Fatal("expected error without embedder")
	}
	if _, err := NewRetriever(embedder, nil, Config{}, nil).SearchIDs("cart", KindIcon); err == nil {
		t.Fatal("expected error without vector searcher")
	}
}

func TestSearchIDsPropagatesFailuresAndCachesOnlySuccess(t *testing.T) {
	embedder := &fakeQueryEmbedder{err: errors.New("HTTP 500")}
	retriever := NewRetriever(embedder, &fakeSearcher{}, Config{}, retrieverDocuments())
	if _, err := retriever.SearchIDs("cart", KindIcon); err == nil || !strings.Contains(err.Error(), "embedding") {
		t.Fatalf("err %v", err)
	}
	embedder.err = nil
	for range 3 {
		if _, err := retriever.SearchIDs("cart", KindIcon); err != nil {
			t.Fatal(err)
		}
	}
	if calls := embedder.calls.Load(); calls != 2 {
		t.Fatalf("failed embedding must not be cached and success must be: calls=%d", calls)
	}
	searchErr := NewRetriever(&fakeQueryEmbedder{}, &fakeSearcher{err: errors.New("collection missing")}, Config{}, nil)
	if _, err := searchErr.SearchIDs("cart", KindIcon); err == nil || !strings.Contains(err.Error(), "vector search") {
		t.Fatalf("err %v", err)
	}
}

func TestSearchIDsTimesOutSlowEmbedding(t *testing.T) {
	retriever := NewRetriever(&fakeQueryEmbedder{delay: 300 * time.Millisecond}, &fakeSearcher{}, Config{TimeoutSeconds: 0.05}, nil)
	started := time.Now()
	if _, err := retriever.SearchIDs("cart", KindIcon); err == nil || !strings.Contains(err.Error(), "timed out") {
		t.Fatalf("err %v", err)
	}
	if elapsed := time.Since(started); elapsed > 250*time.Millisecond {
		t.Fatalf("timeout not enforced: %s", elapsed)
	}
}

func TestNewRetrieverDefaults(t *testing.T) {
	retriever := NewRetriever(nil, nil, Config{}, nil)
	if retriever.cfg.TopK != 50 || retriever.cfg.TimeoutSeconds != 3 || retriever.cfg.CacheSize != 256 {
		t.Fatalf("defaults %#v", retriever.cfg)
	}
}

func TestFuseIsEqualWeightRRF(t *testing.T) {
	cases := []struct {
		name              string
		lexical, semantic []string
		want              []string
	}{
		{"no semantic keeps lexical", []string{"a", "b"}, nil, []string{"a", "b"}},
		{"semantic only", nil, []string{"x", "y"}, []string{"x", "y"}},
		// b 两路都有（1/62+1/61）> a 仅关键词第一（1/61）> x 仅语义第二（1/62）。
		{"overlap wins", []string{"a", "b"}, []string{"b", "x"}, []string{"b", "a", "x"}},
		// 同分：关键词先到者在前，再按语义名次。
		{"ties keep lexical first", []string{"a", "b"}, []string{"x", "y"}, []string{"a", "x", "b", "y"}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := Fuse(tc.lexical, tc.semantic); !reflect.DeepEqual(got, tc.want) {
				t.Fatalf("got %#v want %#v", got, tc.want)
			}
		})
	}
}

func TestVectorCacheEvictsOldest(t *testing.T) {
	cache := newVectorCache(2)
	cache.put("a", []float64{1})
	cache.put("b", []float64{2})
	cache.put("a", []float64{9}) // 已存在不覆盖、不改序
	cache.put("c", []float64{3})
	if _, ok := cache.get("a"); ok {
		t.Fatal("oldest entry must be evicted")
	}
	if value, ok := cache.get("b"); !ok || value[0] != 2 {
		t.Fatal("b must survive")
	}
}
