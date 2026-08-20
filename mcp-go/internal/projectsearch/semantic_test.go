package projectsearch

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"reflect"
	"testing"
	"time"
)

type semanticFakeEmbedder struct {
	calls []string
	fn    func(string) ([]float64, error)
}

func (f *semanticFakeEmbedder) EmbedQuery(query string) ([]float64, error) {
	f.calls = append(f.calls, query)
	return f.fn(query)
}

type semanticFakeVectors struct {
	calls []struct {
		vector                []float64
		chunkLimit, repoLimit int
		minScore              float64
	}
	fn func([]float64, int, int, float64) ([]SemanticHit, error)
}

func (f *semanticFakeVectors) SearchRepoIDs(vector []float64, chunkLimit, repoLimit int, minScore float64) ([]SemanticHit, error) {
	f.calls = append(f.calls, struct {
		vector                []float64
		chunkLimit, repoLimit int
		minScore              float64
	}{vector, chunkLimit, repoLimit, minScore})
	return f.fn(vector, chunkLimit, repoLimit, minScore)
}

func TestProjectSemanticSearchDisabledShortCircuit(t *testing.T) {
	embedder := &semanticFakeEmbedder{fn: func(string) ([]float64, error) { t.Fatal("embedder called"); return nil, nil }}
	vectors := &semanticFakeVectors{fn: func([]float64, int, int, float64) ([]SemanticHit, error) { t.Fatal("vectors called"); return nil, nil }}
	search := NewProjectSemanticSearch(embedder, vectors, SemanticConfig{Enabled: false})
	got, err := search.SearchRepoIDs([]string{"rag"})
	if err != nil || len(got) != 0 {
		t.Fatalf("disabled result got %#v, err %v", got, err)
	}
}

func TestProjectSemanticSearchPerQueryRRFAndParameters(t *testing.T) {
	embedder := &semanticFakeEmbedder{fn: func(query string) ([]float64, error) {
		if query == "first" {
			return []float64{1, 0}, nil
		}
		return []float64{0, 1}, nil
	}}
	vectors := &semanticFakeVectors{fn: func(vector []float64, chunkLimit, repoLimit int, minScore float64) ([]SemanticHit, error) {
		if chunkLimit != 12 || repoLimit != 3 || minScore != .45 {
			t.Fatalf("parameters: %d %d %v", chunkLimit, repoLimit, minScore)
		}
		if vector[0] == 1 {
			return []SemanticHit{{RepoID: "a", Score: .9}, {RepoID: "b", Score: .8}}, nil
		}
		return []SemanticHit{{RepoID: "b", Score: .95}, {RepoID: "c", Score: .7}}, nil
	}}
	search := NewProjectSemanticSearch(embedder, vectors, SemanticConfig{Enabled: true, RepoLimit: 3, ChunkLimit: 12, MinScore: .45, QueryTimeoutSeconds: 1})
	got, err := search.SearchRepoIDs([]string{"first", "second"})
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"b", "a", "c"}
	if len(got) != len(want) {
		t.Fatalf("got %#v", got)
	}
	for i, hit := range got {
		if hit.RepoID != want[i] {
			t.Fatalf("rank %d got %#v want %s", i, hit, want[i])
		}
	}
	if !reflect.DeepEqual(embedder.calls, []string{"first", "second"}) {
		t.Fatalf("embed calls %#v", embedder.calls)
	}
}

func TestProjectSemanticSearchSingleQueryPreservesVectorRanking(t *testing.T) {
	embedder := &semanticFakeEmbedder{fn: func(string) ([]float64, error) { return []float64{1}, nil }}
	vectors := &semanticFakeVectors{fn: func([]float64, int, int, float64) ([]SemanticHit, error) {
		return []SemanticHit{{RepoID: "z", Score: .91}, {RepoID: "a", Score: .8}}, nil
	}}
	search := NewProjectSemanticSearch(embedder, vectors, SemanticConfig{Enabled: true, RepoLimit: 2, ChunkLimit: 8, QueryTimeoutSeconds: 1})
	got, err := search.SearchRepoIDs([]string{"one"})
	if err != nil {
		t.Fatal(err)
	}
	want := []SemanticHit{{RepoID: "z", Score: .91}, {RepoID: "a", Score: .8}}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %#v want %#v", got, want)
	}
}

func TestProjectSemanticSearchErrorBubbles(t *testing.T) {
	wantErr := errors.New("embed failed")
	embedder := &semanticFakeEmbedder{fn: func(string) ([]float64, error) { return nil, wantErr }}
	search := NewProjectSemanticSearch(embedder, &semanticFakeVectors{}, SemanticConfig{Enabled: true, QueryTimeoutSeconds: 1})
	_, err := search.SearchRepoIDs([]string{"one"})
	if !errors.Is(err, wantErr) {
		t.Fatalf("got %v want %v", err, wantErr)
	}
}

func TestProjectSemanticSearchTimeout(t *testing.T) {
	embedder := &semanticFakeEmbedder{fn: func(string) ([]float64, error) { time.Sleep(200 * time.Millisecond); return []float64{1}, nil }}
	vectors := &semanticFakeVectors{fn: func([]float64, int, int, float64) ([]SemanticHit, error) { return nil, nil }}
	search := NewProjectSemanticSearch(embedder, vectors, SemanticConfig{Enabled: true, QueryTimeoutSeconds: .1})
	started := time.Now()
	_, err := search.SearchRepoIDs([]string{"one"})
	if err == nil || time.Since(started) > time.Second {
		t.Fatalf("timeout err=%v elapsed=%s", err, time.Since(started))
	}
}

type roundTripperFunc func(*http.Request) (*http.Response, error)

func (f roundTripperFunc) RoundTrip(req *http.Request) (*http.Response, error) { return f(req) }

func TestOpenAIEmbeddingClientRequestBodyAndKeyChain(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/embeddings" {
			t.Errorf("path %s", r.URL.Path)
		}
		if got := r.Header.Get("Authorization"); got != "Bearer embedding-key" {
			t.Errorf("authorization %q", got)
		}
		var body map[string]any
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(body, map[string]any{"model": "embed-model", "input": "RAG tools"}) {
			t.Errorf("body %#v", body)
		}
		_, _ = io.WriteString(w, `{"data":[{"embedding":[0.1,0.2]}]}`)
	}))
	defer server.Close()
	client := NewOpenAIEmbeddingClient(EmbeddingConfig{Provider: "openai", BaseURL: server.URL + "/v1", ModelName: "embed-model", APIKey: "embedding-key", OpenAIAPIKey: "openai-key", TimeoutSeconds: 1})
	got, err := client.EmbedQuery("RAG tools")
	if err != nil || !reflect.DeepEqual(got, []float64{.1, .2}) {
		t.Fatalf("got %#v err %v", got, err)
	}
}

func TestOpenAIEmbeddingClientSiliconFlowFallbackKeyAndWire(t *testing.T) {
	var called bool
	client := NewOpenAIEmbeddingClient(EmbeddingConfig{Provider: "openai", BaseURL: "https://api.siliconflow.cn/v1", ModelName: "silicon-model", SiliconFlowAPIKey: "silicon-key", OpenAIAPIKey: "openai-key", TimeoutSeconds: 1})
	client.client.Transport = roundTripperFunc(func(req *http.Request) (*http.Response, error) {
		called = true
		if req.URL.Host != "api.siliconflow.cn" || req.URL.Path != "/v1/embeddings" {
			t.Errorf("url %s", req.URL)
		}
		if got := req.Header.Get("Authorization"); got != "Bearer silicon-key" {
			t.Errorf("authorization %q", got)
		}
		var body map[string]any
		if err := json.NewDecoder(req.Body).Decode(&body); err != nil {
			t.Fatal(err)
		}
		if body["model"] != "silicon-model" || body["input"] != "query" {
			t.Errorf("body %#v", body)
		}
		return &http.Response{StatusCode: 200, Body: io.NopCloser(stringsReader(`{"data":[{"embedding":[1]}]}`)), Header: make(http.Header)}, nil
	})
	got, err := client.EmbedQuery("query")
	if err != nil || !called || !reflect.DeepEqual(got, []float64{1}) {
		t.Fatalf("got %#v called=%v err=%v", got, called, err)
	}
}

type stringsReader string

func (s stringsReader) Read(p []byte) (int, error) {
	if len(s) == 0 {
		return 0, io.EOF
	}
	n := copy(p, s)
	return n, nil
}
func (s stringsReader) Close() error { return nil }
