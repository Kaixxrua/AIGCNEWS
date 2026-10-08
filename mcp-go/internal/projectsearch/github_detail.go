package projectsearch

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"sync"
	"time"
	"unicode/utf8"

	"aigcnews/mcp-go/internal/mcpapp"
	"golang.org/x/sync/singleflight"
)

const (
	maxReadmeBytes   = 1 << 20
	detailCacheLimit = 64
	detailCacheTTL   = 5 * time.Minute
)

var (
	ErrPublicProjectNotFound   = mcpapp.ToolInputError{Message: "Public GitHub repository not found."}
	ErrGitHubDetailUnavailable = mcpapp.ToolInputError{Message: "GitHub project details are temporarily unavailable; try again later."}
	ErrGitHubDetailDisabled    = mcpapp.ToolInputError{Message: "GitHub project detail fetching is disabled."}
	ErrGitHubReadmeTooLarge    = mcpapp.ToolInputError{Message: "GitHub README exceeds the 1 MiB limit; view it on GitHub."}
)

type GitHubProjectDetail = mcpapp.GitHubProjectDetail

// GitHubDetailClient retrieves original Markdown. Semantic-index snapshots
// deliberately strip code blocks and links and cannot serve this use case.
type GitHubDetailClient struct {
	cfg    GitHubFallbackConfig
	client *http.Client
	now    func() time.Time
	mu     sync.Mutex
	cache  map[string]GitHubProjectDetail
	flight singleflight.Group
}

func NewGitHubDetailClient(cfg GitHubFallbackConfig) *GitHubDetailClient {
	client := NewGitHubFallback(cfg).client
	client.CheckRedirect = func(req *http.Request, via []*http.Request) error {
		if len(via) >= 3 || req.URL.Scheme != "https" || req.URL.Host != "api.github.com" || req.URL.User != nil {
			return errors.New("GitHub detail redirect rejected")
		}
		return nil
	}
	return &GitHubDetailClient{cfg: cfg, client: client, now: time.Now, cache: map[string]GitHubProjectDetail{}}
}

func (g *GitHubDetailClient) GetProjectDetail(fullName string) (GitHubProjectDetail, error) {
	if !mcpapp.ValidGitHubFullName(fullName) {
		return GitHubProjectDetail{}, ErrPublicProjectNotFound
	}
	if !g.cfg.Enabled {
		return GitHubProjectDetail{}, ErrGitHubDetailDisabled
	}
	key := strings.ToLower(fullName)
	result, err, _ := g.flight.Do(key, func() (any, error) {
		g.mu.Lock()
		cached, ok := g.cache[key]
		g.mu.Unlock()
		if ok && g.now().Before(cached.FetchedAt.Add(detailCacheTTL)) {
			cached.CacheHit = true
			return cached, nil
		}
		detail, err := g.fetch(fullName)
		if err != nil {
			return nil, err
		}
		g.mu.Lock()
		defer g.mu.Unlock()
		if len(g.cache) >= detailCacheLimit {
			var oldest string
			for name, item := range g.cache {
				if oldest == "" || item.FetchedAt.Before(g.cache[oldest].FetchedAt) {
					oldest = name
				}
			}
			delete(g.cache, oldest)
		}
		g.cache[key] = detail
		return detail, nil
	})
	if err != nil {
		return GitHubProjectDetail{}, err
	}
	detail := result.(GitHubProjectDetail)
	detail.Project = cloneMap(detail.Project)
	return detail, nil
}

func (g *GitHubDetailClient) fetch(fullName string) (GitHubProjectDetail, error) {
	timeout := g.cfg.TimeoutSeconds
	if timeout <= 0 {
		timeout = 8
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(timeout*float64(time.Second)))
	defer cancel()
	repo, status, err := g.getJSON(ctx, "/repos/"+fullName, true)
	if status == http.StatusNotFound {
		return GitHubProjectDetail{}, ErrPublicProjectNotFound
	}
	if err != nil {
		return GitHubProjectDetail{}, err
	}
	// The shared GitHub token may see private repositories. Require positive
	// public evidence before fetching any README, including renamed repos.
	private, known := repo["private"].(bool)
	visibility := stringOr(repo["visibility"])
	canonical := stringOr(repo["full_name"])
	if !known || private || (visibility != "" && visibility != "public") || !mcpapp.ValidGitHubFullName(canonical) {
		return GitHubProjectDetail{}, ErrPublicProjectNotFound
	}
	detail := GitHubProjectDetail{
		Project: normalizeRepo(repo), ReadmeURL: "https://github.com/" + canonical + "#readme",
		ReadmeStatus: "not_found", FetchedAt: g.now().UTC(),
	}
	detail.Project["url"] = "https://github.com/" + canonical
	detail.Project["result_origin"] = "github_api"
	readme, status, err := g.getJSON(ctx, "/repos/"+canonical+"/readme", true)
	if status == http.StatusNotFound {
		return detail, nil
	}
	if err != nil {
		return GitHubProjectDetail{}, err
	}
	if intValue(readme["size"]) > maxReadmeBytes {
		return GitHubProjectDetail{}, ErrGitHubReadmeTooLarge
	}
	encoded, hasContent := readme["content"].(string)
	if stringOr(readme["encoding"]) != "base64" || !hasContent {
		return GitHubProjectDetail{}, ErrGitHubDetailUnavailable
	}
	content, err := base64.StdEncoding.DecodeString(encoded)
	if err != nil || !utf8.Valid(content) {
		return GitHubProjectDetail{}, ErrGitHubDetailUnavailable
	}
	if len(content) > maxReadmeBytes {
		return GitHubProjectDetail{}, ErrGitHubReadmeTooLarge
	}
	if size, present := readme["size"]; present && intValue(size) != len(content) {
		return GitHubProjectDetail{}, ErrGitHubDetailUnavailable
	}
	detail.Readme, detail.ReadmeStatus = string(content), "available"
	detail.ReadmeSHA = stringOr(readme["sha"])
	// html_url is provenance only, never an outbound request target.
	if source := stringOr(readme["html_url"]); strings.HasPrefix(source, "https://github.com/"+canonical+"/") {
		detail.ReadmeURL = source
	}
	return detail, nil
}

func (g *GitHubDetailClient) getJSON(ctx context.Context, path string, useToken bool) (map[string]any, int, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, "https://api.github.com"+path, nil)
	if err != nil {
		return nil, 0, ErrGitHubDetailUnavailable
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	req.Header.Set("X-GitHub-Api-Version", "2022-11-28")
	req.Header.Set("User-Agent", "AIGC-Radar-MCP/1.0")
	if useToken && g.cfg.UseToken && strings.TrimSpace(g.cfg.Token) != "" {
		req.Header.Set("Authorization", "Bearer "+g.cfg.Token)
	}
	response, err := g.client.Do(req)
	if err != nil {
		return nil, 0, ErrGitHubDetailUnavailable
	}
	defer response.Body.Close()
	if response.StatusCode == http.StatusUnauthorized && req.Header.Get("Authorization") != "" {
		_ = response.Body.Close()
		return g.getJSON(ctx, path, false)
	}
	if response.StatusCode != http.StatusOK {
		return nil, response.StatusCode, ErrGitHubDetailUnavailable
	}
	// Bound both upstream transfer and decoded content, including dishonest sizes.
	body, err := io.ReadAll(io.LimitReader(response.Body, 2*maxReadmeBytes+1))
	if err != nil {
		return nil, response.StatusCode, ErrGitHubDetailUnavailable
	}
	if len(body) > 2*maxReadmeBytes {
		return nil, response.StatusCode, ErrGitHubReadmeTooLarge
	}
	var payload map[string]any
	decoder := json.NewDecoder(strings.NewReader(string(body)))
	decoder.UseNumber()
	if err := decoder.Decode(&payload); err != nil || payload == nil {
		return nil, response.StatusCode, ErrGitHubDetailUnavailable
	}
	return payload, response.StatusCode, nil
}
