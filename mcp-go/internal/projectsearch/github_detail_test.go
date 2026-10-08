package projectsearch

import (
	"aigcnews/mcp-go/internal/mcpapp"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

type detailTransport func(*http.Request) (*http.Response, error)

func (f detailTransport) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func detailResponse(r *http.Request, status int, payload any) *http.Response {
	body, _ := json.Marshal(payload)
	return &http.Response{StatusCode: status, Header: http.Header{}, Body: io.NopCloser(strings.NewReader(string(body))), Request: r}
}

func detailReadmePayload(text string) map[string]any {
	return map[string]any{"content": base64.StdEncoding.EncodeToString([]byte(text)), "encoding": "base64", "size": len(text), "sha": "readme-v1", "html_url": "https://github.com/owner/repo/blob/main/README.md"}
}

func TestGitHubDetailPreservesMarkdownAndCaches(t *testing.T) {
	markdown := "# 安装 🐈\n\n```sh\npip install example\n```\n[Docs](https://example.com)\n"
	g := NewGitHubDetailClient(GitHubFallbackConfig{Enabled: true, UseToken: true, Token: "test-token"})
	now := time.Date(2026, 10, 8, 0, 0, 0, 0, time.UTC)
	g.now = func() time.Time { return now }
	calls := 0
	g.client.Transport = detailTransport(func(r *http.Request) (*http.Response, error) {
		calls++
		if r.URL.Scheme != "https" || r.URL.Host != "api.github.com" || r.Method != http.MethodGet || r.Header.Get("Authorization") != "Bearer test-token" {
			t.Fatalf("unexpected request: %s %s", r.Method, r.URL)
		}
		if strings.HasSuffix(r.URL.Path, "/readme") {
			return detailResponse(r, 200, detailReadmePayload(markdown)), nil
		}
		return detailResponse(r, 200, map[string]any{"full_name": "owner/repo", "private": false, "visibility": "public", "stargazers_count": 900, "description": "Example"}), nil
	})
	first, err := g.GetProjectDetail("owner/repo")
	if err != nil || first.Readme != markdown || first.ReadmeStatus != "available" || first.CacheHit || first.ReadmeSHA != "readme-v1" || !first.FetchedAt.Equal(now) {
		t.Fatalf("first detail: %+v, %v", first, err)
	}
	first.Project["description"] = "caller mutation"
	cached, err := g.GetProjectDetail("Owner/Repo")
	if err != nil || !cached.CacheHit || calls != 2 || cached.Project["description"] != "Example" || cached.Project["result_origin"] != "github_api" {
		t.Fatalf("cached detail: %+v, calls %d, %v", cached, calls, err)
	}
	now = now.Add(detailCacheTTL + time.Second)
	refreshed, err := g.GetProjectDetail("owner/repo")
	if err != nil || refreshed.CacheHit || calls != 4 || !refreshed.FetchedAt.Equal(now) {
		t.Fatalf("expired cache: %+v, calls %d, %v", refreshed, calls, err)
	}
}

func TestGitHubDetailRejectsNonPublicAndInvalidIdentifiers(t *testing.T) {
	for _, name := range []string{"", "repo", "https://github.com/a/b", "a/..", "a/.", "a/b/c", "a/%2e%2e", "a/b?ref=main", "a/b#readme", "a/b\n", "a@host/b", "a/" + strings.Repeat("x", 101)} {
		t.Run(name, func(t *testing.T) {
			g := NewGitHubDetailClient(GitHubFallbackConfig{Enabled: true})
			g.client.Transport = detailTransport(func(*http.Request) (*http.Response, error) {
				t.Fatal("invalid identifier caused network access")
				return nil, nil
			})
			if _, err := g.GetProjectDetail(name); !errors.Is(err, ErrPublicProjectNotFound) {
				t.Fatalf("invalid name: %v", err)
			}
		})
	}
	for _, evidence := range []map[string]any{{"private": true}, {"private": false, "visibility": "internal"}, {}, {"private": "false"}} {
		g := NewGitHubDetailClient(GitHubFallbackConfig{Enabled: true, UseToken: true, Token: "private-capable"})
		calls := 0
		g.client.Transport = detailTransport(func(r *http.Request) (*http.Response, error) {
			calls++
			evidence["full_name"] = "owner/repo"
			return detailResponse(r, 200, evidence), nil
		})
		if _, err := g.GetProjectDetail("owner/repo"); !errors.Is(err, ErrPublicProjectNotFound) || calls != 1 || len(g.cache) != 0 {
			t.Fatalf("non-public data exposed or cached: calls=%d, %v", calls, err)
		}
	}
	for _, name := range []string{"org/.github", "a/b", "some-org/repo_name.v2"} {
		if !mcpapp.ValidGitHubFullName(name) {
			t.Fatalf("valid name rejected: %s", name)
		}
	}
}

func TestGitHubDetailHandlesMissingAndFailedUpstreams(t *testing.T) {
	for _, tc := range []struct {
		name                     string
		repoStatus, readmeStatus int
		readme                   any
		want                     error
		status                   string
	}{
		{"missing-repo", 404, 200, nil, ErrPublicProjectNotFound, ""},
		{"missing-readme", 200, 404, nil, nil, "not_found"},
		{"rate-limited", 429, 200, nil, ErrGitHubDetailUnavailable, ""},
		{"readme-forbidden", 200, 403, nil, ErrGitHubDetailUnavailable, ""},
		{"readme-failure", 200, 500, nil, ErrGitHubDetailUnavailable, ""},
		{"invalid-base64", 200, 200, map[string]any{"encoding": "base64", "content": "!"}, ErrGitHubDetailUnavailable, ""},
		{"invalid-utf8", 200, 200, detailReadmePayload(string([]byte{0xff})), ErrGitHubDetailUnavailable, ""},
		{"missing-content", 200, 200, map[string]any{"encoding": "base64"}, ErrGitHubDetailUnavailable, ""},
		{"incomplete-content", 200, 200, map[string]any{"encoding": "base64", "content": "", "size": 1}, ErrGitHubDetailUnavailable, ""},
		{"large-declared-size", 200, 200, map[string]any{"size": maxReadmeBytes + 1}, ErrGitHubReadmeTooLarge, ""},
		{"large-content", 200, 200, detailReadmePayload(strings.Repeat("x", maxReadmeBytes+1)), ErrGitHubReadmeTooLarge, ""},
		{"empty-readme", 200, 200, detailReadmePayload(""), nil, "available"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			g := NewGitHubDetailClient(GitHubFallbackConfig{Enabled: true})
			g.client.Transport = detailTransport(func(r *http.Request) (*http.Response, error) {
				if strings.HasSuffix(r.URL.Path, "/readme") {
					return detailResponse(r, tc.readmeStatus, tc.readme), nil
				}
				return detailResponse(r, tc.repoStatus, map[string]any{"full_name": "owner/repo", "private": false}), nil
			})
			got, err := g.GetProjectDetail("owner/repo")
			if !errors.Is(err, tc.want) || got.ReadmeStatus != tc.status {
				t.Fatalf("detail: %+v, %v", got, err)
			}
			if err != nil && len(g.cache) != 0 {
				t.Fatal("upstream failure cached as success")
			}
		})
	}
}

func TestGitHubDetailRedirectBoundaryAndRenames(t *testing.T) {
	for _, target := range []string{"http://api.github.com/repos/a/b", "https://evil.example/repos/a/b", "http://127.0.0.1/secret", "https://api.github.com:444/repos/a/b", "https://user@api.github.com/repos/a/b"} {
		g := NewGitHubDetailClient(GitHubFallbackConfig{Enabled: true, UseToken: true, Token: "private-token"})
		calls := 0
		g.client.Transport = detailTransport(func(r *http.Request) (*http.Response, error) {
			calls++
			response := detailResponse(r, 302, nil)
			response.Header.Set("Location", target)
			return response, nil
		})
		if _, err := g.GetProjectDetail("owner/repo"); !errors.Is(err, ErrGitHubDetailUnavailable) || calls != 1 {
			t.Fatalf("redirect %s crossed boundary: calls %d, %v", target, calls, err)
		}
	}
	g := NewGitHubDetailClient(GitHubFallbackConfig{Enabled: true})
	g.client.Transport = detailTransport(func(r *http.Request) (*http.Response, error) {
		switch r.URL.Path {
		case "/repos/old/repo":
			response := detailResponse(r, 301, nil)
			response.Header.Set("Location", "https://api.github.com/repositories/123")
			return response, nil
		case "/repositories/123":
			return detailResponse(r, 200, map[string]any{"full_name": "new/repo", "private": false}), nil
		case "/repos/new/repo/readme":
			return detailResponse(r, 200, detailReadmePayload("renamed README")), nil
		default:
			t.Fatalf("unexpected redirect path %s", r.URL.Path)
			return nil, nil
		}
	})
	got, err := g.GetProjectDetail("old/repo")
	if err != nil || got.Project["full_name"] != "new/repo" || got.ReadmeURL != "https://github.com/new/repo#readme" {
		t.Fatalf("rename: %+v, %v", got, err)
	}
}

func TestGitHubDetailTimeoutLimitsAndTokenFallback(t *testing.T) {
	g := NewGitHubDetailClient(GitHubFallbackConfig{Enabled: true, TimeoutSeconds: 0.01})
	g.client.Transport = detailTransport(func(r *http.Request) (*http.Response, error) {
		if _, ok := r.Context().Deadline(); !ok {
			t.Fatal("no request deadline")
		}
		<-r.Context().Done()
		return nil, r.Context().Err()
	})
	if _, err := g.GetProjectDetail("owner/repo"); !errors.Is(err, ErrGitHubDetailUnavailable) {
		t.Fatal(err)
	}
	g.client.Transport = detailTransport(func(r *http.Request) (*http.Response, error) {
		response := detailResponse(r, 200, nil)
		response.Body = io.NopCloser(strings.NewReader(strings.Repeat("x", 2*maxReadmeBytes+1)))
		return response, nil
	})
	if _, err := g.GetProjectDetail("owner/repo"); !errors.Is(err, ErrGitHubReadmeTooLarge) {
		t.Fatal(err)
	}
	g.cfg.Enabled = false
	if _, err := g.GetProjectDetail("owner/repo"); !errors.Is(err, ErrGitHubDetailDisabled) {
		t.Fatal(err)
	}
	g = NewGitHubDetailClient(GitHubFallbackConfig{Enabled: true, UseToken: true, Token: "expired"})
	calls := 0
	g.client.Transport = detailTransport(func(r *http.Request) (*http.Response, error) {
		calls++
		if r.Header.Get("Authorization") != "" {
			return detailResponse(r, 401, nil), nil
		}
		if strings.HasSuffix(r.URL.Path, "/readme") {
			return detailResponse(r, 200, detailReadmePayload("public")), nil
		}
		return detailResponse(r, 200, map[string]any{"full_name": "owner/repo", "private": false}), nil
	})
	if got, err := g.GetProjectDetail("owner/repo"); err != nil || got.Readme != "public" || calls != 4 {
		t.Fatalf("token fallback: %+v, calls %d, %v", got, calls, err)
	}
}

func TestGitHubDetailConcurrentCacheAndBound(t *testing.T) {
	g := NewGitHubDetailClient(GitHubFallbackConfig{Enabled: true})
	var calls atomic.Int32
	g.client.Transport = detailTransport(func(r *http.Request) (*http.Response, error) {
		calls.Add(1)
		if strings.HasSuffix(r.URL.Path, "/readme") {
			return detailResponse(r, 200, detailReadmePayload("public")), nil
		}
		return detailResponse(r, 200, map[string]any{"full_name": strings.TrimPrefix(r.URL.Path, "/repos/"), "private": false}), nil
	})
	var wg sync.WaitGroup
	for range 20 {
		wg.Go(func() {
			if _, err := g.GetProjectDetail("owner/repo"); err != nil {
				t.Error(err)
			}
		})
	}
	wg.Wait()
	if calls.Load() != 2 {
		t.Fatalf("duplicate upstream calls: %d", calls.Load())
	}
	for i := range detailCacheLimit + 5 {
		if _, err := g.GetProjectDetail(fmt.Sprintf("owner/repo-%d", i)); err != nil {
			t.Fatal(err)
		}
	}
	if len(g.cache) != detailCacheLimit {
		t.Fatalf("cache is unbounded: %d", len(g.cache))
	}
}
