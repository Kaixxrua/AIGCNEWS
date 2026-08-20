package projectsearch

import (
	"encoding/json"
	"io"
	"net/http"
	"reflect"
	"testing"
)

func rerankerProjects() []map[string]any {
	return []map[string]any{
		{"full_name": "a/one", "title": "One", "description": "first"},
		{"full_name": "b/two", "title": "Two", "tags": []any{"rag"}},
		{"full_name": "c/three", "language": "Go"},
		{"full_name": "d/four", "topics": []any{"mcp"}},
		{"full_name": "e/five", "description_zh": "第五"},
	}
}

func TestProjectRerankerGateIdentityFallbacks(t *testing.T) {
	projects := rerankerProjects()
	cases := []struct {
		name string
		cfg  RerankerConfig
		url  string
		want []string
	}{
		{"disabled", RerankerConfig{CandidateLimit: 20, MinCandidates: 5}, "", []string{"a/one", "b/two", "c/three", "d/four", "e/five"}},
		{"missing key", RerankerConfig{Enabled: true, CandidateLimit: 20, MinCandidates: 5}, "", []string{"a/one", "b/two", "c/three", "d/four", "e/five"}},
		{"too few candidates", RerankerConfig{Enabled: true, SiliconFlowAPIKey: "k", CandidateLimit: 20, MinCandidates: 5}, "", []string{"a/one", "b/two"}},
		{"unapproved scheme", RerankerConfig{Enabled: true, SiliconFlowAPIKey: "k", CandidateLimit: 20, MinCandidates: 5, URL: "http://api.siliconflow.cn/v1/rerank"}, "", []string{"a/one", "b/two", "c/three", "d/four", "e/five"}},
		{"unapproved host", RerankerConfig{Enabled: true, SiliconFlowAPIKey: "k", CandidateLimit: 20, MinCandidates: 5, URL: "https://example.com/v1/rerank"}, "", []string{"a/one", "b/two", "c/three", "d/four", "e/five"}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if tc.cfg.URL == "" {
				tc.cfg.URL = "https://api.siliconflow.cn/v1/rerank"
			}
			r := NewProjectReranker(tc.cfg)
			got := r.RerankRepoIDs("q", projects[:2])
			// For the too-few case, the candidate slice itself is two items;
			// all other cases deliberately exercise the five-item fallback.
			if tc.name != "too few candidates" {
				got = r.RerankRepoIDs("q", projects)
			}
			if !reflect.DeepEqual(got, tc.want) {
				t.Fatalf("got %#v want %#v", got, tc.want)
			}
		})
	}
}

func TestProjectRerankerHTTPSuccessAndRequestShape(t *testing.T) {
	r := NewProjectReranker(RerankerConfig{
		Enabled: true, URL: "https://api.siliconflow.cn/v1/rerank", ModelName: "m",
		TimeoutSeconds: 1, CandidateLimit: 24, MinCandidates: 5, SiliconFlowAPIKey: "secret",
	})
	var requestBody map[string]any
	r.client.Transport = roundTripperFunc(func(req *http.Request) (*http.Response, error) {
		if got := req.Header.Get("Authorization"); got != "Bearer secret" {
			t.Errorf("authorization %q", got)
		}
		if got := req.Header.Get("Content-Type"); got != "application/json" {
			t.Errorf("content type %q", got)
		}
		if err := json.NewDecoder(req.Body).Decode(&requestBody); err != nil {
			t.Errorf("decode request: %v", err)
		}
		return &http.Response{
			StatusCode: 200,
			Header:     make(http.Header),
			Body:       io.NopCloser(stringsReader(`{"results":[{"index":2,"relevance_score":0.4},{"index":0,"relevance_score":0.9},{"index":4,"relevance_score":0.1},{"index":1,"relevance_score":0.7},{"index":3,"relevance_score":0.6}]}`)),
		}, nil
	})
	got := r.RerankRepoIDs("query", rerankerProjects())
	want := []string{"a/one", "b/two", "d/four", "c/three", "e/five"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %#v want %#v", got, want)
	}
	if requestBody["model"] != "m" || requestBody["query"] != "query" || requestBody["return_documents"] != false {
		t.Fatalf("request scalar fields %#v", requestBody)
	}
	documents, ok := requestBody["documents"].([]any)
	if !ok || len(documents) != 5 || documents[0] != "a/one\nOne\nfirst" {
		t.Fatalf("documents %#v", requestBody["documents"])
	}
}

func TestProjectRerankerInvalidResponseFallsBack(t *testing.T) {
	cases := []string{
		`{"results":[{"index":0,"relevance_score":1}]}`,
		`{"results":[{"index":true,"relevance_score":1},{"index":1,"relevance_score":0}]}`,
		`{"results":[{"index":0,"relevance_score":1},{"index":0,"relevance_score":0},{"index":2,"relevance_score":0},{"index":3,"relevance_score":0},{"index":4,"relevance_score":0}]}`,
		`{"results":[{"index":0,"relevance_score":1},{"index":1,"relevance_score":0},{"index":2,"relevance_score":0},{"index":3,"relevance_score":0},{"index":5,"relevance_score":0}]}`,
	}
	for _, payload := range cases {
		r := NewProjectReranker(RerankerConfig{Enabled: true, URL: "https://api.siliconflow.cn/v1/rerank", TimeoutSeconds: 1, CandidateLimit: 20, MinCandidates: 5, SiliconFlowAPIKey: "k"})
		r.client.Transport = roundTripperFunc(func(*http.Request) (*http.Response, error) {
			return &http.Response{StatusCode: 200, Header: make(http.Header), Body: io.NopCloser(stringsReader(payload))}, nil
		})
		got := r.RerankRepoIDs("q", rerankerProjects())
		want := []string{"a/one", "b/two", "c/three", "d/four", "e/five"}
		if !reflect.DeepEqual(got, want) {
			t.Errorf("payload %s: got %#v want %#v", payload, got, want)
		}
	}
}
