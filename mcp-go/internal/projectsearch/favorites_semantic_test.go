package projectsearch

import (
	"context"
	"errors"
	"reflect"
	"testing"
	"time"

	milvus "github.com/milvus-io/milvus-sdk-go/v2/client"
)

type fakeFavoriteLister struct {
	ids    []string
	err    error
	calls  int
	limits []int
}

func (f *fakeFavoriteLister) ListFavoriteRepoIDs(userID, limit int) ([]string, error) {
	f.calls++
	f.limits = append(f.limits, limit)
	return f.ids, f.err
}

type fakeFilteredVectors struct {
	calls []struct {
		repoIDs               []string
		chunkLimit, repoLimit int
		minScore              float64
	}
	fn func() ([]SemanticHit, error)
}

func (f *fakeFilteredVectors) SearchRepoIDsWithin(vector []float64, repoIDs []string, chunkLimit, repoLimit int, minScore float64) ([]SemanticHit, error) {
	f.calls = append(f.calls, struct {
		repoIDs               []string
		chunkLimit, repoLimit int
		minScore              float64
	}{repoIDs, chunkLimit, repoLimit, minScore})
	return f.fn()
}

func TestFavoritesSemanticSearchesWithinUserFavorites(t *testing.T) {
	lister := &fakeFavoriteLister{ids: []string{"acme/a", "acme/b", "R_kgDOSL4dpw"}}
	embedder := &semanticFakeEmbedder{fn: func(string) ([]float64, error) { return []float64{1, 0}, nil }}
	vectors := &fakeFilteredVectors{fn: func() ([]SemanticHit, error) {
		return []SemanticHit{{RepoID: "R_kgDOSL4dpw", Score: .81}, {RepoID: "acme/a", Score: .62}}, nil
	}}
	search := NewFavoritesSemantic(lister, embedder, vectors, FavoritesSemanticConfig{MinScore: .55})
	got, err := search.SearchFavoriteRepoIDs(7, "  长期记忆  ")
	if err != nil {
		t.Fatalf("SearchFavoriteRepoIDs: %v", err)
	}
	if want := []string{"R_kgDOSL4dpw", "acme/a"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("ids = %v, want score order %v", got, want)
	}
	if !reflect.DeepEqual(embedder.calls, []string{"长期记忆"}) || !reflect.DeepEqual(lister.limits, []int{1000}) {
		t.Fatalf("embedder calls %v, lister limits %v", embedder.calls, lister.limits)
	}
	call := vectors.calls[0]
	if !reflect.DeepEqual(call.repoIDs, lister.ids) || call.chunkLimit != 800 || call.repoLimit != 3 || call.minScore != .55 {
		t.Fatalf("vector call %+v", call)
	}
}

func TestFavoritesSemanticShortCircuits(t *testing.T) {
	embedder := &semanticFakeEmbedder{fn: func(string) ([]float64, error) { t.Fatal("embedder called"); return nil, nil }}
	vectors := &fakeFilteredVectors{fn: func() ([]SemanticHit, error) { t.Fatal("vectors called"); return nil, nil }}
	empty := &fakeFavoriteLister{}
	search := NewFavoritesSemantic(empty, embedder, vectors, FavoritesSemanticConfig{})
	for _, tc := range []struct {
		userID int
		query  string
	}{{7, ""}, {7, "   "}, {0, "rag"}, {7, "rag"}} {
		got, err := search.SearchFavoriteRepoIDs(tc.userID, tc.query)
		if err != nil || len(got) != 0 {
			t.Fatalf("%+v: got %v, err %v", tc, got, err)
		}
	}
	if empty.calls != 1 {
		t.Fatalf("lister calls = %d, want 1 (only the user with a real query)", empty.calls)
	}
	if _, err := NewFavoritesSemantic(nil, embedder, vectors, FavoritesSemanticConfig{}).SearchFavoriteRepoIDs(7, "rag"); err == nil {
		t.Fatal("missing dependencies must error so the caller falls back to lexical")
	}
}

func TestFavoritesSemanticPropagatesErrorsAndTimeout(t *testing.T) {
	boom := errors.New("boom")
	ok := &semanticFakeEmbedder{fn: func(string) ([]float64, error) { return []float64{1}, nil }}
	noHits := &fakeFilteredVectors{fn: func() ([]SemanticHit, error) { return nil, nil }}
	cases := map[string]*FavoritesSemantic{
		"lister": NewFavoritesSemantic(&fakeFavoriteLister{err: boom}, ok, noHits, FavoritesSemanticConfig{}),
		"embedder": NewFavoritesSemantic(&fakeFavoriteLister{ids: []string{"a/b"}},
			&semanticFakeEmbedder{fn: func(string) ([]float64, error) { return nil, boom }}, noHits, FavoritesSemanticConfig{}),
		"vectors": NewFavoritesSemantic(&fakeFavoriteLister{ids: []string{"a/b"}}, ok,
			&fakeFilteredVectors{fn: func() ([]SemanticHit, error) { return nil, boom }}, FavoritesSemanticConfig{}),
	}
	for name, search := range cases {
		if _, err := search.SearchFavoriteRepoIDs(7, "rag"); !errors.Is(err, boom) {
			t.Errorf("%s error = %v, want boom", name, err)
		}
	}

	release := make(chan struct{})
	defer close(release)
	slow := &semanticFakeEmbedder{fn: func(string) ([]float64, error) { <-release; return []float64{1}, nil }}
	search := NewFavoritesSemantic(&fakeFavoriteLister{ids: []string{"a/b"}}, slow, noHits, FavoritesSemanticConfig{TimeoutSeconds: .1})
	started := time.Now()
	if _, err := search.SearchFavoriteRepoIDs(7, "rag"); err == nil {
		t.Fatal("slow embedding must time out")
	}
	if elapsed := time.Since(started); elapsed > time.Second {
		t.Fatalf("timeout took %s", elapsed)
	}
}

func TestRepoIDInExpression(t *testing.T) {
	expr, ok := repoIDInExpression([]string{"acme/a", "", "acme/a", "R_kgDOSL4dpw", `bad"] or [`, "x/y.z-1_2"})
	if want := `repo_id in ["acme/a", "R_kgDOSL4dpw", "x/y.z-1_2"]`; !ok || expr != want {
		t.Fatalf("expr = %q ok=%v, want %q", expr, ok, want)
	}
	for _, ids := range [][]string{nil, {}, {""}, {`a"b`, "a b"}} {
		if expr, ok := repoIDInExpression(ids); ok || expr != "" {
			t.Fatalf("repoIDInExpression(%q) = %q, %v; want no filter", ids, expr, ok)
		}
	}
}

func TestSearchRepoIDsWithinSkipsMilvusWithoutSafeIDs(t *testing.T) {
	r, err := NewMilvusVectorRepositoryWithClientFactory(MilvusConfig{Dimension: 2}, func(context.Context, milvus.Config) (milvus.Client, error) {
		t.Fatal("Milvus must not be contacted without a repo filter")
		return nil, nil
	})
	if err != nil {
		t.Fatal(err)
	}
	got, err := r.SearchRepoIDsWithin([]float64{1, 0}, []string{`a"b`}, 10, 5, .5)
	if err != nil || len(got) != 0 {
		t.Fatalf("got %v, err %v", got, err)
	}
}
