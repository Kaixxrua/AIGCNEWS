package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

var repoPattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}$`)

func parseRepo(raw string) (string, error) {
	raw = strings.TrimSpace(raw)
	if strings.HasPrefix(raw, "https://") {
		u, err := url.Parse(raw)
		if err != nil || u.Host != "github.com" || u.User != nil || u.RawQuery != "" || u.ForceQuery || u.Fragment != "" || u.RawPath != "" {
			return "", errors.New("请输入 github.com 的项目地址或 owner/repo")
		}
		raw = strings.TrimSuffix(strings.TrimPrefix(u.Path, "/"), "/")
	}
	raw = strings.TrimSuffix(raw, ".git")
	if !repoPattern.MatchString(raw) || strings.HasSuffix(raw, "/.") || strings.HasSuffix(raw, "/..") {
		return "", errors.New("项目格式应为 owner/repo，例如 OpenRCT2/OpenRCT2")
	}
	return raw, nil
}

type Asset struct {
	ID          int64  `json:"id"`
	Name        string `json:"name"`
	Size        int64  `json:"size"`
	URL         string `json:"browser_download_url"`
	Digest      string `json:"digest"`
	Windows     bool   `json:"windows"`
	Arch        string `json:"arch"`
	Kind        string `json:"kind"`
	Recommended bool   `json:"recommended"`
}

type Release struct {
	SupportedSystems []string `json:"supportedSystems,omitempty"`
	Tag              string   `json:"tag_name"`
	Name             string   `json:"name"`
	URL              string   `json:"html_url"`
	Published        string   `json:"published_at"`
	Assets           []Asset  `json:"assets"`
}

type repositoryDetails struct {
	Game     Game
	PushedAt string
}

type GitHub struct {
	client           *http.Client
	mu               sync.RWMutex
	token            string
	discoveryReadmes map[string]discoveryReadme
}

func newGitHub(token string) *GitHub {
	return &GitHub{token: token, client: &http.Client{Timeout: 25 * time.Second, CheckRedirect: func(r *http.Request, via []*http.Request) error {
		if len(via) >= 5 || r.URL.Scheme != "https" || r.URL.Host != "api.github.com" || r.URL.User != nil {
			return errors.New("GitHub API 重定向地址不受支持")
		}
		return nil
	}}}
}

func (g *GitHub) setToken(token string) {
	g.mu.Lock()
	defer g.mu.Unlock()
	g.token = token
}

func (g *GitHub) hasToken() bool {
	g.mu.RLock()
	defer g.mu.RUnlock()
	return g.token != ""
}

type githubError struct {
	Status  int
	Message string
}

func (e *githubError) Error() string { return e.Message }

func (g *GitHub) get(ctx context.Context, path string, out any) error {
	r, err := http.NewRequestWithContext(ctx, http.MethodGet, "https://api.github.com"+path, nil)
	if err != nil {
		return errors.New("GitHub 请求地址无效")
	}
	r.Header.Set("Accept", "application/vnd.github+json")
	r.Header.Set("User-Agent", "PortShelf/"+version)
	r.Header.Set("X-GitHub-Api-Version", "2022-11-28")
	g.mu.RLock()
	token := g.token
	g.mu.RUnlock()
	if token != "" {
		r.Header.Set("Authorization", "Bearer "+token)
	}
	resp, err := g.client.Do(r)
	if err != nil {
		return errors.New("连接 GitHub 失败，请检查网络或代理配置后重试")
	}
	defer resp.Body.Close()
	switch resp.StatusCode {
	case http.StatusOK:
	case http.StatusNotFound:
		message := "GitHub 项目不存在或不是公开项目"
		if strings.HasSuffix(path, "/releases/latest") {
			message = "项目暂无正式 GitHub Release，可打开上游发布页查看"
		}
		return &githubError{resp.StatusCode, message}
	case http.StatusUnauthorized:
		return &githubError{resp.StatusCode, "GitHub Token 无效或已过期，请在设置中更新"}
	case http.StatusForbidden, http.StatusTooManyRequests:
		reset := "稍后"
		if ts, err := strconv.ParseInt(resp.Header.Get("X-RateLimit-Reset"), 10, 64); err == nil {
			reset = time.Unix(ts, 0).Local().Format("15:04")
		}
		return &githubError{resp.StatusCode, fmt.Sprintf("GitHub 暂时限制了请求，请在 %s 重试，或在设置中填写自己的 GitHub Token", reset)}
	default:
		return &githubError{resp.StatusCode, fmt.Sprintf("GitHub 返回 HTTP %d，请稍后重试", resp.StatusCode)}
	}
	b, err := io.ReadAll(io.LimitReader(resp.Body, (4<<20)+1))
	if err != nil {
		return errors.New("读取 GitHub 返回的数据失败，请重试")
	}
	if len(b) > 4<<20 {
		return errors.New("GitHub 返回的数据过大")
	}
	if err := json.Unmarshal(b, out); err != nil {
		return errors.New("GitHub 返回的数据格式无效，请重试")
	}
	return nil
}

func (g *GitHub) repository(ctx context.Context, repo string) (repositoryDetails, error) {
	valid, err := parseRepo(repo)
	if err != nil {
		return repositoryDetails{}, err
	}
	var d struct {
		FullName    string `json:"full_name"`
		Name        string `json:"name"`
		Description string `json:"description"`
		Stars       int    `json:"stargazers_count"`
		PushedAt    string `json:"pushed_at"`
		Private     bool   `json:"private"`
	}
	if err := g.get(ctx, "/repos/"+valid, &d); err != nil {
		return repositoryDetails{}, err
	}
	canonical, err := parseRepo(d.FullName)
	if err != nil || d.Private {
		return repositoryDetails{}, errors.New("仅支持公开 GitHub 项目")
	}
	if !strings.EqualFold(canonical, valid) {
		return repositoryDetails{}, fmt.Errorf("项目已迁移，请使用新地址 %s 添加", canonical)
	}
	return repositoryDetails{Game: Game{Repo: canonical, Name: d.Name, Subtitle: canonical, Category: "自定义", Description: d.Description, DataNote: "运行要求以项目文档为准。部分移植需要自备原版游戏数据。", Guide: "https://github.com/" + canonical + "#readme", Mark: "GH", Color: "slate", Stars: &d.Stars}, PushedAt: d.PushedAt}, nil
}

type starBounds struct {
	min *int
	max *int
}

func parseStarBounds(minimum, maximum string) (starBounds, error) {
	parse := func(raw string) (*int, error) {
		if raw == "" {
			return nil, nil
		}
		for _, char := range raw {
			if char < '0' || char > '9' {
				return nil, errors.New("Stars 必须是 0 到 1000000000 之间的整数")
			}
		}
		value, err := strconv.ParseUint(raw, 10, 32)
		if err != nil || value > 1_000_000_000 {
			return nil, errors.New("Stars 必须是 0 到 1000000000 之间的整数")
		}
		stars := int(value)
		return &stars, nil
	}
	min, err := parse(minimum)
	if err != nil {
		return starBounds{}, err
	}
	max, err := parse(maximum)
	if err != nil {
		return starBounds{}, err
	}
	if min != nil && max != nil && *min > *max {
		return starBounds{}, errors.New("最低 Stars 不能超过最高 Stars")
	}
	return starBounds{min: min, max: max}, nil
}

func (bounds starBounds) qualifier() string {
	switch {
	case bounds.min != nil && bounds.max != nil:
		return fmt.Sprintf(" stars:%d..%d", *bounds.min, *bounds.max)
	case bounds.min != nil:
		return fmt.Sprintf(" stars:>=%d", *bounds.min)
	case bounds.max != nil:
		return fmt.Sprintf(" stars:<=%d", *bounds.max)
	default:
		return ""
	}
}

func (bounds starBounds) includes(stars int) bool {
	return (bounds.min == nil || stars >= *bounds.min) && (bounds.max == nil || stars <= *bounds.max)
}

const automaticGameQuery = `sourceport OR "source port" OR recompilation OR remake OR reimplementation OR decompilation`

type searchRepository struct {
	Readme      string   `json:"-"`
	FullName    string   `json:"full_name"`
	Name        string   `json:"name"`
	Description string   `json:"description"`
	Topics      []string `json:"topics"`
	Stars       int      `json:"stargazers_count"`
	Private     bool     `json:"private"`
}

var collectionNameMarker = regexp.MustCompile(`(?i)(^|[-_ ])(list|lists|collection|collections)([-_ ]|$)`)
var collectionDescriptionMarker = regexp.MustCompile(`(?i)(\bcurated\s+(list|collection)\b|^\s*(a\s+|an\s+)?(list|collection)\s+of\b)`)
var portMarker = regexp.MustCompile(`(?i)\bsource[ -]?ports?\b`)
var nativePortMarker = regexp.MustCompile(`(?i)\b(?:native|pc)(?:[ /-](?:pc|handheld))*[ -]ports?\b`)
var gameDescriptionMarker = regexp.MustCompile(`(?i)\b(games?|gameplay|playable)\b`)

type DiscoveryPage struct {
	Items           []Game `json:"items"`
	NextCursor      string `json:"nextCursor,omitempty"`
	EvidencePending bool   `json:"evidencePending,omitempty"`
	Warning         string `json:"warning,omitempty"`
	Page            int    `json:"page"`
	NextPage        int    `json:"nextPage"`
	HasMore         bool   `json:"hasMore"`
	TotalCandidates int    `json:"totalCandidates"`
	Incomplete      bool   `json:"incomplete"`
	LimitReached    bool   `json:"limitReached"`
}

type githubSearchPage struct {
	Items      []searchRepository `json:"items"`
	Total      int                `json:"total_count"`
	Incomplete bool               `json:"incomplete_results"`
}

func (g *GitHub) searchPage(ctx context.Context, query string, bounds starBounds, perPage, page int) (githubSearchPage, error) {
	var result githubSearchPage
	path := "/search/repositories?q=" + url.QueryEscape(query+" archived:false"+bounds.qualifier()) + "&sort=stars&order=desc&per_page=" + strconv.Itoa(perPage)
	if page > 0 {
		path += "&page=" + strconv.Itoa(page)
	}
	err := g.get(ctx, path, &result)
	return result, err
}

func filterSearchGames(repositories []searchRepository, bounds starBounds, automatic bool) ([]Game, error) {
	knownGames := map[string]bool{}
	if automatic {
		catalog, err := readCatalog()
		if err != nil {
			return nil, err
		}
		for _, game := range catalog {
			knownGames[strings.ToLower(game.Repo)] = true
		}
	}
	games := []Game{}
	seen := map[string]int{}
	for _, repo := range repositories {
		canonical, err := parseRepo(repo.FullName)
		if err != nil || repo.Private || !bounds.includes(repo.Stars) {
			continue
		}
		repo.FullName = canonical
		game := Game{Repo: canonical, Name: repo.Name, Description: repo.Description, Guide: "https://github.com/" + canonical + "#readme", Subtitle: canonical, Category: "GitHub", Mark: "GH", Color: "slate", Stars: &repo.Stars}
		if automatic {
			if !isGameCandidate(repo, knownGames) {
				continue
			}
			key := strings.ToLower(canonical)
			if index, exists := seen[key]; exists {
				if repo.Stars > *games[index].Stars {
					games[index] = game
				}
				continue
			}
			seen[key] = len(games)
		}
		games = append(games, game)
	}
	if automatic {
		sort.Slice(games, func(i, j int) bool {
			if *games[i].Stars == *games[j].Stars {
				return strings.ToLower(games[i].Repo) < strings.ToLower(games[j].Repo)
			}
			return *games[i].Stars > *games[j].Stars
		})
	}
	return games, nil
}

// Legacy array response remains capped for existing keyword-search clients.
func (g *GitHub) search(ctx context.Context, query string, bounds starBounds) ([]Game, error) {
	query = strings.TrimSpace(query)
	if len(query) > 180 {
		return nil, errors.New("搜索关键词太长")
	}
	automatic := query == ""
	perPage := 24
	if automatic {
		query, perPage = automaticGameQuery, 100
	}
	result, err := g.searchPage(ctx, query, bounds, perPage, 0)
	if err != nil {
		return nil, err
	}
	games, err := filterSearchGames(result.Items, bounds, automatic)
	if len(games) > 24 {
		games = games[:24]
	}
	return games, err
}

func (g *GitHub) latest(ctx context.Context, repo, arch string) (Release, error) {
	valid, err := parseRepo(repo)
	if err != nil {
		return Release{}, err
	}
	var release Release
	if err := g.get(ctx, "/repos/"+valid+"/releases/latest", &release); err != nil {
		return Release{}, err
	}
	return prepareRelease(valid, release, arch)
}

// Only link to an upstream repository's official GitHub release and asset paths.
func officialReleaseURL(raw, repo string, download bool) bool {
	u, err := url.Parse(raw)
	if err != nil || u.Scheme != "https" || u.Host != "github.com" || u.User != nil || u.RawQuery != "" || u.ForceQuery || u.Fragment != "" {
		return false
	}
	parts := strings.Split(u.Path, "/")
	if len(parts) < 4 || parts[0] != "" || !strings.EqualFold(parts[1]+"/"+parts[2], repo) || parts[3] != "releases" {
		return false
	}
	for _, part := range parts[1:] {
		if part == "" || part == "." || part == ".." || strings.ContainsAny(part, "\\\x00\r\n") {
			return false
		}
	}
	if download {
		return len(parts) >= 7 && parts[4] == "download"
	}
	return len(parts) == 4 || len(parts) >= 6 && parts[4] == "tag"
}

func prepareRelease(repo string, release Release, arch string) (Release, error) {
	if !officialReleaseURL(release.URL, repo, false) {
		return Release{}, errors.New("GitHub 发布页地址与项目不匹配")
	}
	if arch == "" {
		arch = runtime.GOARCH
	}
	release.Assets = append([]Asset{}, release.Assets...)
	for i := range release.Assets {
		if !officialReleaseURL(release.Assets[i].URL, repo, true) {
			return Release{}, errors.New("GitHub 下载地址与项目不匹配")
		}
		classifyAsset(&release.Assets[i])
	}
	sort.SliceStable(release.Assets, func(i, j int) bool {
		return assetScore(release.Assets[i], arch) > assetScore(release.Assets[j], arch)
	})
	if len(release.Assets) > 0 && assetScore(release.Assets[0], arch) > 0 {
		release.Assets[0].Recommended = true
	}
	release.SupportedSystems = supportedSystems(release.Assets)
	return release, nil
}

var windowsMarker = regexp.MustCompile(`windows|win32|win64|winportable|(^|[._-])win([._-]|$)`)
var nonGameMarker = regexp.MustCompile(`(^|[._-])(linux|macos|osx|darwin|android|ios|freebsd|symbols|debug|source|src|server|mods|addons)([._-]|$)`)

func classifyAsset(asset *Asset) {
	name := strings.ToLower(asset.Name)
	asset.Kind, asset.Arch, asset.Windows, asset.Recommended = "file", "unknown", false, false
	switch {
	case strings.HasSuffix(name, ".zip"):
		asset.Kind = "zip"
	case strings.HasSuffix(name, ".exe"), strings.HasSuffix(name, ".msi"):
		asset.Kind, asset.Windows = "installer", true
	case strings.HasSuffix(name, ".7z"), strings.HasSuffix(name, ".rar"):
		asset.Kind = "archive"
	}
	if windowsMarker.MatchString(name) {
		asset.Windows = true
	}
	switch {
	case strings.Contains(name, "arm64"), strings.Contains(name, "aarch64"):
		asset.Arch = "arm64"
	case strings.Contains(name, "x86_64"), strings.Contains(name, "amd64"), strings.Contains(name, "x64"), strings.Contains(name, "win64"):
		asset.Arch = "amd64"
	case strings.Contains(name, "i386"), strings.Contains(name, "i686"), strings.Contains(name, "x86"), strings.Contains(name, "win32"), strings.Contains(name, "32bit"):
		asset.Arch = "386"
	}
	if nonGameMarker.MatchString(name) || strings.Contains(name, "checksum") || strings.Contains(name, ".sha") || strings.Contains(name, "mingw-dev") || strings.HasSuffix(name, ".sig") || strings.HasSuffix(name, ".asc") || strings.HasSuffix(name, ".pdb") {
		asset.Windows = false
	}
}

func assetScore(asset Asset, arch string) int {
	if !asset.Windows || (asset.Kind != "zip" && asset.Kind != "installer" && asset.Kind != "archive") {
		return -1
	}
	if asset.Arch != "unknown" && asset.Arch != arch && !(arch == "amd64" && asset.Arch == "386") {
		return -1
	}
	score := 10
	if asset.Arch == arch {
		score += 20
	}
	if asset.Kind == "zip" {
		score += 8
	}
	if strings.Contains(strings.ToLower(asset.Name), "portable") {
		score += 5
	}
	return score
}
