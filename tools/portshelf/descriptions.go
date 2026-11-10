package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"
	"unicode"
	"unicode/utf8"
)

const aigcDescriptionsURL = "https://aigcnews.cn/api/v1/projects/descriptions"
const descriptionTTL = 7 * 24 * time.Hour

type Description struct {
	Repo             string `json:"repo"`
	Status           string `json:"status"`
	DescriptionZh    string `json:"descriptionZh"`
	GameNameZh       string `json:"gameNameZh,omitempty"`
	GameNameOriginal string `json:"gameNameOriginal,omitempty"`
	PosterURL        string `json:"posterUrl,omitempty"`
	PosterSourceURL  string `json:"posterSourceUrl,omitempty"`
	PosterKind       string `json:"posterKind,omitempty"`
	PosterStatus     string `json:"posterStatus,omitempty"`
	PosterRetryAfter int    `json:"posterRetryAfter,omitempty"`
	DetailsVersion   int    `json:"detailsVersion,omitempty"`
	Source           string `json:"source"`
	CheckedAt        string `json:"checkedAt"`
	Error            string `json:"error,omitempty"`
	RetryAfter       int    `json:"retryAfter,omitempty"`
}
type DescriptionsResponse struct {
	Items     []Description `json:"items"`
	PollAfter int           `json:"pollAfter"`
}
type AIGC struct {
	client *http.Client
	mu     sync.RWMutex
	token  string
}

func newAIGC() *AIGC {
	return &AIGC{client: &http.Client{Timeout: 25 * time.Second, CheckRedirect: func(r *http.Request, via []*http.Request) error {
		if len(via) >= 3 || r.URL.Scheme != "https" || r.URL.Host != "aigcnews.cn" || r.URL.User != nil {
			return errors.New("AIGCNEWS 重定向地址不受支持")
		}
		return nil
	}}}
}
func (a *AIGC) hasToken() bool        { a.mu.RLock(); defer a.mu.RUnlock(); return a.token != "" }
func (a *AIGC) setToken(token string) { a.mu.Lock(); defer a.mu.Unlock(); a.token = token }
func validAIGCToken(token string) bool {
	if len(token) > 4096 {
		return false
	}
	for _, char := range token {
		if char < 33 || char > 126 {
			return false
		}
	}
	return true
}

type descriptionError struct {
	Status  int
	Message string
}

func (e *descriptionError) Error() string { return e.Message }
func validChineseDescription(text string) bool {
	if strings.TrimSpace(text) == "" || utf8.RuneCountInString(text) > 512 {
		return false
	}
	hasHan := false
	for _, char := range text {
		if char >= '\u3040' && char <= '\u30ff' {
			return false
		}
		if unicode.Is(unicode.Han, char) {
			hasHan = true
		}
	}
	return hasHan
}
func readyDescription(item Description) bool {
	return item.Status == "ready" && item.Source == "aigcnews" && validChineseDescription(item.DescriptionZh)
}
func freshDescription(item Description, now time.Time) bool {
	checked, err := time.Parse(time.RFC3339, item.CheckedAt)
	return readyGameDetails(item) && err == nil && !checked.After(now.Add(5*time.Minute)) && now.Sub(checked) < descriptionTTL
}
func (a *AIGC) get(ctx context.Context, repos []string) (DescriptionsResponse, error) {
	v, _, err := a.request(ctx, http.MethodGet, repos)
	return v, err
}
func (a *AIGC) generate(ctx context.Context, repo string) (DescriptionsResponse, int, error) {
	return a.request(ctx, http.MethodPost, []string{repo})
}
func (a *AIGC) request(ctx context.Context, method string, repos []string) (DescriptionsResponse, int, error) {
	endpoint := aigcDescriptionsURL
	var body io.Reader
	if method == http.MethodGet {
		endpoint += "?gameDetails=true&repos=" + url.QueryEscape(strings.Join(repos, ","))
	} else {
		encoded, _ := json.Marshal(map[string]any{"repo": repos[0], "gameDetails": true})
		body = bytes.NewReader(encoded)
	}
	request, err := http.NewRequestWithContext(ctx, method, endpoint, body)
	if err != nil {
		return DescriptionsResponse{}, 0, errors.New("中文简介请求地址无效")
	}
	request.Header.Set("Accept", "application/json")
	request.Header.Set("User-Agent", "PortShelf/"+version)
	if method == http.MethodPost {
		a.mu.RLock()
		token := a.token
		a.mu.RUnlock()
		if token == "" {
			return DescriptionsResponse{}, 0, &descriptionError{401, "请先填写 AIGCNEWS MCP 登录凭证，再生成中文简介"}
		}
		request.Header.Set("Authorization", "Bearer "+token)
		request.Header.Set("Content-Type", "application/json")
	}
	response, err := a.client.Do(request)
	if err != nil {
		return DescriptionsResponse{}, 0, errors.New("连接 AIGCNEWS 失败，请检查网络或代理配置后重试")
	}
	defer response.Body.Close()
	if response.StatusCode != 200 && response.StatusCode != 202 {
		message := fmt.Sprintf("AIGCNEWS 返回 HTTP %d，请稍后重试", response.StatusCode)
		switch response.StatusCode {
		case 401:
			message = "AIGCNEWS 登录凭证无效或已过期，请重新填写"
		case 403:
			message = "此 AIGCNEWS 登录凭证暂无游戏资料生成权限，请检查账号权限或更新凭证"
		case 429:
			message = "AIGCNEWS 请求频率或生成额度已达上限，请稍后重试"
		case 422:
			message = "AIGCNEWS 暂未支持新版游戏资料富化，请在云端更新后重试"
		case 503:
			message = "AIGCNEWS 中文简介服务暂时不可用，请稍后重试"
		case 404:
			message = "AIGCNEWS 中文简介服务尚未就绪，请稍后重试"
		}
		return DescriptionsResponse{}, 0, &descriptionError{response.StatusCode, message}
	}
	encoded, err := io.ReadAll(io.LimitReader(response.Body, (1<<20)+1))
	if err != nil || len(encoded) > 1<<20 {
		return DescriptionsResponse{}, 0, errors.New("AIGCNEWS 中文简介响应读取失败或过大")
	}
	var result DescriptionsResponse
	if err := json.Unmarshal(encoded, &result); err != nil {
		return DescriptionsResponse{}, 0, errors.New("AIGCNEWS 中文简介响应格式无效")
	}
	if result.PollAfter < 1 || result.PollAfter > 60 {
		result.PollAfter = 3
	}
	allowed := map[string]string{}
	for _, repo := range repos {
		allowed[strings.ToLower(repo)] = repo
	}
	seen := map[string]bool{}
	for i := range result.Items {
		item := &result.Items[i]
		repo, err := parseRepo(item.Repo)
		key := strings.ToLower(repo)
		canonical, expected := allowed[key]
		if err != nil || !expected || seen[key] || item.Source != "aigcnews" {
			return DescriptionsResponse{}, 0, errors.New("AIGCNEWS 中文简介响应包含不匹配或重复的项目")
		}
		seen[key] = true
		item.Repo = canonical
		sanitizeGameDetails(item)
		item.CheckedAt = time.Now().UTC().Format(time.RFC3339)
		if len(item.Error) > 2000 {
			item.Error = "AIGCNEWS 未能完成中文简介，请稍后重试"
		}
		switch item.Status {
		case "ready":
			if !validChineseDescription(item.DescriptionZh) {
				item.Status, item.DescriptionZh, item.Error = "failed", "", "远端未返回有效中文简介，已保留原始简介"
			} else {
				item.Error, item.RetryAfter = "", 0
			}
		case "pending", "missing", "failed":
			// The richer profile can already have a verified legacy brief while
			// identity/artwork is still missing. Keep useful text without marking
			// the game details ready or suppressing the upgrade action.
			if !validChineseDescription(item.DescriptionZh) {
				item.DescriptionZh = ""
			}
		default:
			return DescriptionsResponse{}, 0, errors.New("AIGCNEWS 中文简介状态无效")
		}
	}
	if len(seen) != len(allowed) {
		return DescriptionsResponse{}, 0, errors.New("AIGCNEWS 未返回全部项目的中文简介状态")
	}
	return result, response.StatusCode, nil
}
func (a *App) allowedDescriptionRepos(raw []string) ([]string, error) {
	known := map[string]string{}
	for _, game := range a.allGames() {
		known[strings.ToLower(game.Repo)] = game.Repo
	}
	seen := map[string]bool{}
	repos := []string{}
	for _, value := range raw {
		repo, err := parseRepo(value)
		if err != nil {
			return nil, err
		}
		key := strings.ToLower(repo)
		if seen[key] {
			return nil, errors.New("中文简介查询不能包含重复项目")
		}
		seen[key] = true
		if canonical, ok := known[key]; ok {
			repos = append(repos, canonical)
			continue
		}
		if candidate, ok := a.discoveredCandidate(repo); ok {
			repos = append(repos, candidate.Game.Repo)
			continue
		}
		return nil, errors.New("请先发现或添加此公开项目，再查询中文简介")
	}
	return repos, nil
}
func (a *App) readDescriptions(ctx context.Context, repos []string) (DescriptionsResponse, error) {
	stored := a.lib.snapshot().Descriptions
	items := map[string]Description{}
	missing := []string{}
	for _, repo := range repos {
		if item := stored[strings.ToLower(repo)]; freshDescription(item, time.Now()) {
			items[strings.ToLower(repo)] = item
		} else {
			missing = append(missing, repo)
		}
	}
	response := DescriptionsResponse{Items: []Description{}, PollAfter: 3}
	if len(missing) > 0 {
		remote, err := a.aigc.get(ctx, missing)
		if err != nil {
			remote = DescriptionsResponse{PollAfter: 3, Items: []Description{}}
			for _, repo := range missing {
				remote.Items = append(remote.Items, Description{Repo: repo, Status: "failed", Source: "aigcnews", Error: err.Error()})
			}
		}
		if err := a.lib.saveDescriptions(remote.Items); err != nil {
			return DescriptionsResponse{}, err
		}
		response.PollAfter = remote.PollAfter
		for _, item := range remote.Items {
			key := strings.ToLower(item.Repo)
			items[key] = descriptionWithFallback(item, stored[key])
		}
	}
	for _, repo := range repos {
		response.Items = append(response.Items, items[strings.ToLower(repo)])
	}
	return response, nil
}
func descriptionWithFallback(current, previous Description) Description {
	if readyDescription(current) && !readyGameDetails(current) && readyGameDetails(previous) {
		previous.DescriptionZh = current.DescriptionZh
		previous.Error = "远端未返回中文名与图片，暂用上次保存的游戏资料"
		return previous
	}
	if readyDescription(current) || current.Status == "pending" || !readyDescription(previous) {
		return current
	}
	message := current.Error
	if message == "" {
		message = "远端中文简介尚未就绪"
	}
	previous.Error = message + "，暂用上次保存的中文简介"
	previous.RetryAfter = current.RetryAfter
	return previous
}

func (a *App) registerDescriptionRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/descriptions", func(w http.ResponseWriter, r *http.Request) {
		params, err := url.ParseQuery(r.URL.RawQuery)
		if err != nil || len(params["repos"]) != 1 {
			fail(w, 400, errors.New("请提供一次 repos 参数"))
			return
		}
		raw := strings.Split(params.Get("repos"), ",")
		if len(raw) < 1 || len(raw) > 50 {
			fail(w, 400, errors.New("每次最多查询 50 个项目的中文简介"))
			return
		}
		repos, err := a.allowedDescriptionRepos(raw)
		if err != nil {
			fail(w, 400, err)
			return
		}
		response, err := a.readDescriptions(r.Context(), repos)
		if err != nil {
			fail(w, 500, errors.New("保存中文简介失败："+err.Error()))
			return
		}
		reply(w, 200, response)
	})
	mux.HandleFunc("POST /api/descriptions", func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Repo string `json:"repo"`
		}
		if err := decode(w, r, &body); err != nil {
			fail(w, 400, err)
			return
		}
		repos, err := a.allowedDescriptionRepos([]string{body.Repo})
		if err != nil {
			fail(w, 400, err)
			return
		}
		response, status, err := a.aigc.generate(r.Context(), repos[0])
		if err != nil {
			code := 502
			var upstream *descriptionError
			if errors.As(err, &upstream) {
				code = upstream.Status
			}
			fail(w, code, err)
			return
		}
		previous := a.lib.snapshot().Descriptions
		if err := a.lib.saveDescriptions(response.Items); err != nil {
			fail(w, 500, errors.New("保存中文简介失败："+err.Error()))
			return
		}
		for i, item := range response.Items {
			response.Items[i] = descriptionWithFallback(item, previous[strings.ToLower(item.Repo)])
		}
		reply(w, status, response)
	})
	mux.HandleFunc("POST /api/aigc-token", func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Token string `json:"token"`
		}
		if err := decode(w, r, &body); err != nil {
			fail(w, 400, err)
			return
		}
		token := strings.TrimSpace(body.Token)
		if !validAIGCToken(token) {
			fail(w, 400, errors.New("AIGCNEWS 登录凭证格式不正确"))
			return
		}
		a.aigc.setToken(token)
		a.credentialsChanged()
		a.transfers.credentialsAvailable("aigc")
		reply(w, 200, map[string]bool{"hasAigcToken": token != ""})
	})
}
