package main

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"mime"
	"net/http"
	"net/url"
	"runtime"
	"strings"
	"sync"
	"time"
)

type RefreshStatus struct {
	Running bool     `json:"running"`
	Done    int      `json:"done"`
	Total   int      `json:"total"`
	Errors  []string `json:"errors"`
}

type App struct {
	lib       *Library
	github    *GitHub
	catalog   []Game
	token     string
	host      string
	quit      chan struct{}
	quitOnce  sync.Once
	ctx       context.Context
	cancel    context.CancelFunc
	refreshMu sync.Mutex
	status    RefreshStatus
}

func newApp(lib *Library) (*App, error) {
	games, err := readCatalog()
	if err != nil {
		return nil, err
	}
	ctx, cancel := context.WithCancel(context.Background())
	return &App{lib: lib, github: newGitHub(""), catalog: games, token: randomID(), quit: make(chan struct{}), ctx: ctx, cancel: cancel, status: RefreshStatus{Errors: []string{}}}, nil
}

func reply(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

func fail(w http.ResponseWriter, status int, err error) {
	reply(w, status, map[string]string{"error": err.Error()})
}

const maxRequestBytes = 16 << 10

func decode(w http.ResponseWriter, r *http.Request, value any) error {
	mediaType, _, err := mime.ParseMediaType(r.Header.Get("Content-Type"))
	if err != nil || mediaType != "application/json" {
		return errors.New("请求必须使用 JSON")
	}
	decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, maxRequestBytes))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(value); err != nil {
		return errors.New("请求参数无效或过大")
	}
	if err := decoder.Decode(new(any)); err != io.EOF {
		return errors.New("请求包含多余数据或数据过大")
	}
	return nil
}

func (a *App) allGames() []Game {
	games := make([]Game, len(a.catalog))
	for i, game := range a.catalog {
		games[i] = cloneGame(game)
	}
	seen := map[string]bool{}
	for _, game := range games {
		seen[strings.ToLower(game.Repo)] = true
	}
	for _, game := range a.lib.snapshot().Games {
		key := strings.ToLower(game.Repo)
		if !seen[key] {
			games = append(games, game)
			seen[key] = true
		}
	}
	return games
}

func (a *App) game(repo string) (Game, bool) {
	for _, game := range a.allGames() {
		if strings.EqualFold(game.Repo, repo) {
			return game, true
		}
	}
	return Game{}, false
}

func (a *App) refreshStatus() RefreshStatus {
	a.refreshMu.Lock()
	defer a.refreshMu.Unlock()
	status := a.status
	status.Errors = append([]string{}, status.Errors...)
	return status
}

// Metadata and releases are independent: a partial success must not erase either cache.
func (a *App) fetchSnapshot(ctx context.Context, repo string, previous Snapshot) Snapshot {
	next := cloneSnapshot(previous)
	messages := []string{}
	details, err := a.github.repository(ctx, repo)
	repositoryOK := err == nil
	if err != nil {
		messages = append(messages, "Stars："+err.Error())
	} else {
		next.Stars = *details.Game.Stars
		next.PushedAt = details.PushedAt
		next.StarsCheckedAt = time.Now().UTC().Format(time.RFC3339)
	}
	release, err := a.github.latest(ctx, repo, runtime.GOARCH)
	var upstream *githubError
	if repositoryOK && errors.As(err, &upstream) && upstream.Status == http.StatusNotFound {
		// A verified public repo with no latest release is a useful empty result.
		next.Release = nil
		next.ReleaseCheckedAt = time.Now().UTC().Format(time.RFC3339)
	} else if err != nil {
		messages = append(messages, "下载信息："+err.Error())
	} else {
		next.Release = &release
		next.ReleaseCheckedAt = time.Now().UTC().Format(time.RFC3339)
	}
	next.Error = strings.Join(messages, "；")
	return next
}

func (a *App) startRefresh(games []Game) bool {
	a.refreshMu.Lock()
	if a.status.Running {
		a.refreshMu.Unlock()
		return false
	}
	a.status = RefreshStatus{Running: true, Total: len(games), Errors: []string{}}
	a.refreshMu.Unlock()
	go func() {
		defer func() {
			a.refreshMu.Lock()
			a.status.Running = false
			a.refreshMu.Unlock()
		}()
		for _, game := range games {
			if a.ctx.Err() != nil {
				return
			}
			previous := a.lib.snapshot().Snapshots[strings.ToLower(game.Repo)]
			next := a.fetchSnapshot(a.ctx, game.Repo, previous)
			message := next.Error
			if err := a.lib.updateSnapshot(game.Repo, next); err != nil {
				message = "保存游戏信息失败：" + err.Error()
			}
			a.refreshMu.Lock()
			a.status.Done++
			if message != "" {
				a.status.Errors = append(a.status.Errors, game.Repo+"："+message)
			}
			a.refreshMu.Unlock()
		}
	}()
	return true
}

func validToken(token string) bool {
	if len(token) > 256 {
		return false
	}
	for _, char := range token {
		if char < 33 || char > 126 {
			return false
		}
	}
	return true
}

func (a *App) handler() http.Handler {
	mux := http.NewServeMux()
	web, _ := fs.Sub(assets, "web")
	mux.Handle("GET /", http.FileServer(http.FS(web)))
	mux.HandleFunc("GET /api/library", func(w http.ResponseWriter, r *http.Request) {
		reply(w, http.StatusOK, map[string]any{"games": a.allGames(), "snapshots": a.lib.snapshot().Snapshots, "root": a.lib.root, "version": version, "arch": runtime.GOARCH, "hasToken": a.github.hasToken()})
	})
	mux.HandleFunc("GET /api/status", func(w http.ResponseWriter, r *http.Request) {
		reply(w, http.StatusOK, a.refreshStatus())
	})
	mux.HandleFunc("POST /api/refresh", func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Repo string `json:"repo"`
		}
		if err := decode(w, r, &body); err != nil {
			fail(w, http.StatusBadRequest, err)
			return
		}
		games := a.allGames()
		if body.Repo != "" {
			repo, err := parseRepo(body.Repo)
			if err != nil {
				fail(w, http.StatusBadRequest, err)
				return
			}
			game, ok := a.game(repo)
			if !ok {
				fail(w, http.StatusNotFound, errors.New("请先把项目添加到游戏列表"))
				return
			}
			games = []Game{game}
		}
		if !a.startRefresh(games) {
			fail(w, http.StatusConflict, errors.New("正在刷新游戏信息，请稍候"))
			return
		}
		reply(w, http.StatusAccepted, a.refreshStatus())
	})
	mux.HandleFunc("GET /api/search", func(w http.ResponseWriter, r *http.Request) {
		params, err := url.ParseQuery(r.URL.RawQuery)
		if err != nil || len(params["minStars"]) > 1 || len(params["maxStars"]) > 1 {
			fail(w, http.StatusBadRequest, errors.New("搜索参数格式无效，Stars 上下限各只能指定一次"))
			return
		}
		bounds, err := parseStarBounds(params.Get("minStars"), params.Get("maxStars"))
		if err != nil {
			fail(w, http.StatusBadRequest, err)
			return
		}
		games, err := a.github.search(r.Context(), params.Get("q"), bounds)
		if err != nil {
			fail(w, http.StatusBadGateway, err)
			return
		}
		reply(w, http.StatusOK, games)
	})
	mux.HandleFunc("POST /api/games", func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Repo string `json:"repo"`
		}
		if err := decode(w, r, &body); err != nil {
			fail(w, http.StatusBadRequest, err)
			return
		}
		repo, err := parseRepo(body.Repo)
		if err != nil {
			fail(w, http.StatusBadRequest, err)
			return
		}
		if game, ok := a.game(repo); ok {
			reply(w, http.StatusOK, game)
			return
		}
		details, err := a.github.repository(r.Context(), repo)
		if err != nil {
			fail(w, http.StatusBadGateway, err)
			return
		}
		snapshot := Snapshot{Stars: *details.Game.Stars, PushedAt: details.PushedAt, StarsCheckedAt: time.Now().UTC().Format(time.RFC3339)}
		release, err := a.github.latest(r.Context(), details.Game.Repo, runtime.GOARCH)
		var upstream *githubError
		if err == nil {
			snapshot.Release = &release
			snapshot.ReleaseCheckedAt = time.Now().UTC().Format(time.RFC3339)
		} else if errors.As(err, &upstream) && upstream.Status == http.StatusNotFound {
			snapshot.ReleaseCheckedAt = time.Now().UTC().Format(time.RFC3339)
		} else {
			snapshot.Error = "下载信息：" + err.Error()
		}
		if err := a.lib.add(details.Game, snapshot); err != nil {
			fail(w, http.StatusInternalServerError, errors.New("保存项目失败："+err.Error()))
			return
		}
		reply(w, http.StatusCreated, details.Game)
	})
	mux.HandleFunc("POST /api/token", func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Token string `json:"token"`
		}
		if err := decode(w, r, &body); err != nil {
			fail(w, http.StatusBadRequest, err)
			return
		}
		token := strings.TrimSpace(body.Token)
		if !validToken(token) {
			fail(w, http.StatusBadRequest, errors.New("Token 格式不正确"))
			return
		}
		a.github.setToken(token)
		reply(w, http.StatusOK, map[string]bool{"hasToken": token != ""})
	})
	mux.HandleFunc("POST /api/quit", func(w http.ResponseWriter, r *http.Request) {
		if r.Body != nil && r.ContentLength != 0 {
			var body struct{}
			if err := decode(w, r, &body); err != nil {
				fail(w, http.StatusBadRequest, err)
				return
			}
		}
		reply(w, http.StatusOK, map[string]bool{"ok": true})
		a.quitOnce.Do(func() {
			go func() {
				time.Sleep(100 * time.Millisecond)
				a.cancel()
				close(a.quit)
			}()
		})
	})
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("Referrer-Policy", "no-referrer")
		w.Header().Set("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
		w.Header().Set("Cache-Control", "no-store")
		if r.Host != a.host {
			fail(w, http.StatusForbidden, errors.New("无效的本地访问地址"))
			return
		}
		if origin := r.Header.Get("Origin"); origin != "" && origin != "http://"+a.host {
			fail(w, http.StatusForbidden, errors.New("拒绝跨站请求"))
			return
		}
		if strings.HasPrefix(r.URL.Path, "/api/") {
			if r.Header.Get("Sec-Fetch-Site") == "cross-site" || subtle.ConstantTimeCompare([]byte(r.Header.Get("Authorization")), []byte("Bearer "+a.token)) != 1 {
				fail(w, http.StatusUnauthorized, errors.New("请通过 PortShelf.exe 重新打开本地界面"))
				return
			}
			if r.ContentLength > maxRequestBytes {
				fail(w, http.StatusRequestEntityTooLarge, fmt.Errorf("请求不得超过 %d 字节", maxRequestBytes))
				return
			}
		}
		mux.ServeHTTP(w, r)
	})
}
