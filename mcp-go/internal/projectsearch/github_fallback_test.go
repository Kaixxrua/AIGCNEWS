package projectsearch

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
)

func resetFallbackCacheForTest() {
	fallbackCacheMu.Lock()
	defer fallbackCacheMu.Unlock()
	fallbackCache = map[string]fallbackCacheEntry{}
	fallbackCacheOrder = nil
}

func TestGitHubFallbackAggregatesDeduplicatesAndCaches(t *testing.T) {
	resetFallbackCacheForTest()
	var requests atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		if r.URL.Path != "/search/repositories" {
			t.Fatalf("path = %s", r.URL.Path)
		}
		if r.Header.Get("Accept") != "application/vnd.github+json" || r.Header.Get("User-Agent") != "RAG-AIGC-Agent/1.0" {
			t.Fatalf("headers = %#v", r.Header)
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"total_count": 2,
			"items": []map[string]any{
				{"id": 1, "full_name": "Acme/RAG", "html_url": "https://github.com/Acme/RAG", "stargazers_count": 1000, "forks_count": 2, "subscribers_count": 3, "topics": []string{"rag"}},
				{"id": 2, "full_name": "acme/other", "html_url": "https://github.com/acme/other", "stargazers_count": 900, "forks_count": 3, "subscribers_count": 4},
			},
		})
	}))
	defer server.Close()
	oldBase := githubAPIBase
	githubAPIBase = server.URL
	t.Cleanup(func() { githubAPIBase = oldBase; resetFallbackCacheForTest() })

	fallback := NewGitHubFallback(GitHubFallbackConfig{Enabled: true, TimeoutSeconds: 1})
	input := FallbackSearchInput{Q: "rag", Mode: "ai", Limit: 10, MinStars: 500}
	first, err := fallback.Search(input)
	if err != nil {
		t.Fatal(err)
	}
	if len(first.Items) != 2 || first.CacheHit || first.GitHubTotalCount != 2 {
		t.Fatalf("first result = %#v", first)
	}
	if got := strings.TrimSpace(first.Items[0]["full_name"].(string)); got != "Acme/RAG" {
		t.Fatalf("first item = %q", got)
	}
	first.Items[0]["full_name"] = "mutated"
	second, err := fallback.Search(input)
	if err != nil {
		t.Fatal(err)
	}
	if !second.CacheHit || second.Items[0]["full_name"] != "Acme/RAG" {
		t.Fatalf("cache isolation/result = %#v", second)
	}
	if requests.Load() != 2 {
		t.Fatalf("request count = %d, want 2 AI queries only", requests.Load())
	}
}

func TestGitHubFallbackRetriesToken401Anonymously(t *testing.T) {
	resetFallbackCacheForTest()
	var authorized, anonymous atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "" {
			authorized.Add(1)
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		anonymous.Add(1)
		_ = json.NewEncoder(w).Encode(map[string]any{"total_count": 1, "items": []map[string]any{{"full_name": "acme/rag", "stargazers_count": 900}}})
	}))
	defer server.Close()
	oldBase := githubAPIBase
	githubAPIBase = server.URL
	t.Cleanup(func() { githubAPIBase = oldBase; resetFallbackCacheForTest() })

	fallback := NewGitHubFallback(GitHubFallbackConfig{Enabled: true, UseToken: true, Token: "bad-token", TimeoutSeconds: 1})
	result, err := fallback.Search(FallbackSearchInput{Q: "rag", Mode: "ai", Limit: 5, MinStars: 500})
	if err != nil || len(result.Items) != 1 {
		t.Fatalf("result = %#v, err = %v", result, err)
	}
	if authorized.Load() != 2 || anonymous.Load() != 2 {
		t.Fatalf("401 retry counts = authorized %d anonymous %d", authorized.Load(), anonymous.Load())
	}
}

func TestGitHubFallbackReportsRateLimitWithoutReturningError(t *testing.T) {
	resetFallbackCacheForTest()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusForbidden)
	}))
	defer server.Close()
	oldBase := githubAPIBase
	githubAPIBase = server.URL
	t.Cleanup(func() { githubAPIBase = oldBase; resetFallbackCacheForTest() })

	fallback := NewGitHubFallback(GitHubFallbackConfig{Enabled: true, TimeoutSeconds: 1})
	result, err := fallback.Search(FallbackSearchInput{Q: "rag", Mode: "ai", Limit: 5, MinStars: 500})
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Items) != 0 || !strings.Contains(result.Error, "rate limited or forbidden: HTTP 403") {
		t.Fatalf("result = %#v", result)
	}
}
