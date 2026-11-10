package main

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

func testApp(t *testing.T) *App {
	t.Helper()
	app, err := newApp(testLibrary(t))
	if err != nil {
		t.Fatal(err)
	}
	app.host = "127.0.0.1:12345"
	t.Cleanup(app.cancel)
	return app
}

func request(app *App, method, path, body string) *http.Request {
	r := httptest.NewRequest(method, "http://"+app.host+path, strings.NewReader(body))
	r.Header.Set("Authorization", "Bearer "+app.token)
	if body != "" {
		r.Header.Set("Content-Type", "application/json")
	}
	return r
}

func call(app *App, method, path, body string) *httptest.ResponseRecorder {
	w := httptest.NewRecorder()
	app.handler().ServeHTTP(w, request(app, method, path, body))
	return w
}

func TestHTTPHostOriginAndSessionIsolation(t *testing.T) {
	app := testApp(t)
	cases := []struct {
		name   string
		mutate func(*http.Request)
		status int
	}{
		{"valid", func(r *http.Request) {}, 200},
		{"dns rebinding", func(r *http.Request) { r.Host = "evil.com:12345" }, 403},
		{"different loopback name", func(r *http.Request) { r.Host = "localhost:12345" }, 403},
		{"foreign origin", func(r *http.Request) { r.Header.Set("Origin", "https://evil.com") }, 403},
		{"null origin", func(r *http.Request) { r.Header.Set("Origin", "null") }, 403},
		{"same origin", func(r *http.Request) { r.Header.Set("Origin", "http://"+app.host) }, 200},
		{"cross site", func(r *http.Request) { r.Header.Set("Sec-Fetch-Site", "cross-site") }, 401},
		{"missing bearer", func(r *http.Request) { r.Header.Del("Authorization") }, 401},
		{"wrong bearer", func(r *http.Request) { r.Header.Set("Authorization", "Bearer "+randomID()) }, 401},
		{"url bearer ignored", func(r *http.Request) { r.Header.Del("Authorization"); r.URL.RawQuery = "token=" + app.token }, 401},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			r := request(app, "GET", "/api/library", "")
			tc.mutate(r)
			w := httptest.NewRecorder()
			app.handler().ServeHTTP(w, r)
			if w.Code != tc.status {
				t.Fatalf("HTTP %d: %s", w.Code, w.Body.String())
			}
			if w.Header().Get("Cache-Control") != "no-store" || !strings.Contains(w.Header().Get("Content-Security-Policy"), "frame-ancestors 'none'") {
				t.Error("missing browser security headers")
			}
		})
	}
	other := testApp(t)
	if app.token == other.token {
		t.Fatal("session secret reused")
	}
	r := request(app, "GET", "/", "")
	r.Header.Del("Authorization")
	w := httptest.NewRecorder()
	app.handler().ServeHTTP(w, r)
	if w.Code != 200 {
		t.Fatalf("local app shell inaccessible: %d", w.Code)
	}
}

func TestAPIInputLimitsAndRemovedExecutionEndpoints(t *testing.T) {
	app := testApp(t)
	for _, body := range []string{`{"token":`, `{"token":"x","unknown":true}`, `{"token":"x"} {"token":"y"}`} {
		if w := call(app, "POST", "/api/token", body); w.Code != 400 {
			t.Errorf("invalid JSON accepted: %s => %d", body, w.Code)
		}
	}
	for _, contentType := range []string{"text/plain", "application/jsonp", ""} {
		r := request(app, "POST", "/api/token", `{"token":"x"}`)
		r.Header.Set("Content-Type", contentType)
		w := httptest.NewRecorder()
		app.handler().ServeHTTP(w, r)
		if w.Code != 400 {
			t.Errorf("incorrect media type accepted: %q", contentType)
		}
	}
	large := `{"token":"` + strings.Repeat("x", maxRequestBytes+1) + `"}`
	if w := call(app, "POST", "/api/token", large); w.Code != 413 {
		t.Errorf("oversized request not rejected: %d", w.Code)
	}
	r := request(app, "POST", "/api/token", large)
	r.ContentLength = -1
	w := httptest.NewRecorder()
	app.handler().ServeHTTP(w, r)
	if w.Code != 400 {
		t.Errorf("chunked oversized request not rejected: %d", w.Code)
	}
	for _, route := range []string{"download", "cancel", "launch", "open-folder"} {
		if w := call(app, "POST", "/api/"+route, `{}`); w.Code < 400 {
			t.Errorf("removed execution endpoint still available: %s", route)
		}
	}
	for _, token := range []string{strings.Repeat("x", 257), "bad token", "bad\ntoken", "bad\x00token", "令牌"} {
		if w := call(app, "POST", "/api/token", jsonString(map[string]string{"token": token})); w.Code != 400 {
			t.Errorf("invalid token accepted: %q", token)
		}
	}
}

func TestTokenStaysInMemoryAndLibraryContract(t *testing.T) {
	app := testApp(t)
	const secret = "github_pat_test_secret"
	if w := call(app, "POST", "/api/token", `{"token":"`+secret+`"}`); w.Code != 200 || !app.github.hasToken() {
		t.Fatalf("could not set session token: %d", w.Code)
	}
	if err := app.lib.updateSnapshot("owner/repo", Snapshot{Stars: 1}); err != nil {
		t.Fatal(err)
	}
	body, err := os.ReadFile(filepath.Join(app.lib.root, "library.json"))
	if err != nil || strings.Contains(string(body), secret) {
		t.Fatalf("token leaked into persisted state: %v", err)
	}
	w := call(app, "GET", "/api/library", "")
	var library struct {
		Games     []Game              `json:"games"`
		Snapshots map[string]Snapshot `json:"snapshots"`
		Root      string              `json:"root"`
		Version   string              `json:"version"`
		Arch      string              `json:"arch"`
		HasToken  bool                `json:"hasToken"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &library); err != nil || len(library.Games) == 0 || library.Snapshots == nil || library.Root == "" || library.Version == "" || library.Arch == "" || !library.HasToken || strings.Contains(w.Body.String(), secret) {
		t.Fatalf("invalid library response: %v, %s", err, w.Body.String())
	}
	if w := call(app, "POST", "/api/token", `{"token":""}`); w.Code != 200 || app.github.hasToken() {
		t.Fatal("could not clear token")
	}
}

func TestRefreshFailureAndPartialSuccessPreserveCache(t *testing.T) {
	app := testApp(t)
	oldRelease := testRelease("owner/repo", "v1")
	previous := Snapshot{Stars: 100, PushedAt: "old-push", StarsCheckedAt: "2026-01-01T00:00:00Z", ReleaseCheckedAt: "2026-01-02T00:00:00Z", Release: &oldRelease}
	app.github.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) { return apiResponse(500, `{}`), nil })
	next := app.fetchSnapshot(context.Background(), "owner/repo", previous)
	if next.Stars != previous.Stars || next.PushedAt != previous.PushedAt || next.StarsCheckedAt != previous.StarsCheckedAt || next.ReleaseCheckedAt != previous.ReleaseCheckedAt || next.Release.Tag != "v1" || next.Error == "" {
		t.Fatalf("failure discarded successful cache: %+v", next)
	}
	app.github.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		if strings.HasSuffix(r.URL.Path, "/releases/latest") {
			return apiResponse(404, `{}`), nil
		}
		return apiResponse(200, `{"full_name":"owner/repo","name":"Game","stargazers_count":200,"pushed_at":"new-push"}`), nil
	})
	next = app.fetchSnapshot(context.Background(), "owner/repo", previous)
	if next.Stars != 200 || next.PushedAt != "new-push" || next.StarsCheckedAt == previous.StarsCheckedAt || next.ReleaseCheckedAt == previous.ReleaseCheckedAt || next.Release != nil || next.Error != "" {
		t.Fatalf("verified public repo without release was not recorded: %+v", next)
	}
	if _, err := time.Parse(time.RFC3339, next.StarsCheckedAt); err != nil {
		t.Fatalf("invalid stars verification time: %v", err)
	}
	app.github.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		if strings.HasSuffix(r.URL.Path, "/releases/latest") {
			return apiResponse(404, `{}`), nil
		}
		return apiResponse(500, `{}`), nil
	})
	next = app.fetchSnapshot(context.Background(), "owner/repo", previous)
	if next.Release == nil || next.Release.Tag != "v1" || next.ReleaseCheckedAt != previous.ReleaseCheckedAt || next.StarsCheckedAt != previous.StarsCheckedAt || next.Error == "" {
		t.Fatalf("unverified repository discarded last release: %+v", next)
	}
	app.github.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		if strings.HasSuffix(r.URL.Path, "/releases/latest") {
			return apiResponse(200, jsonString(testRelease("owner/repo", "v2"))), nil
		}
		return apiResponse(429, `{}`), nil
	})
	next = app.fetchSnapshot(context.Background(), "owner/repo", previous)
	if next.Stars != previous.Stars || next.StarsCheckedAt != previous.StarsCheckedAt || next.ReleaseCheckedAt == previous.ReleaseCheckedAt || next.Release.Tag != "v2" || next.Error == "" {
		t.Fatalf("release success and stars failure were conflated: %+v", next)
	}
}

func waitRefresh(t *testing.T, app *App) RefreshStatus {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		status := app.refreshStatus()
		if !status.Running {
			return status
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatal("refresh did not finish")
	return RefreshStatus{}
}

func TestAsynchronousRefreshStatusAndConcurrentReads(t *testing.T) {
	app := testApp(t)
	app.catalog = []Game{{Repo: "owner/repo", Name: "Game"}}
	started, unblock := make(chan struct{}), make(chan struct{})
	var once sync.Once
	app.github.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		if strings.HasSuffix(r.URL.Path, "/releases/latest") {
			return apiResponse(200, jsonString(testRelease("owner/repo", "v1"))), nil
		}
		once.Do(func() { close(started) })
		select {
		case <-unblock:
		case <-r.Context().Done():
			return nil, r.Context().Err()
		}
		return apiResponse(200, `{"full_name":"owner/repo","name":"Game","stargazers_count":1234}`), nil
	})
	if w := call(app, "POST", "/api/refresh", `{}`); w.Code != 202 {
		t.Fatalf("refresh did not return immediately: %d", w.Code)
	}
	<-started
	if status := app.refreshStatus(); !status.Running || status.Total != 1 || status.Done != 0 || status.Errors == nil {
		t.Fatalf("invalid running status: %+v", status)
	}
	if w := call(app, "POST", "/api/refresh", `{}`); w.Code != 409 {
		t.Fatalf("simultaneous refresh accepted: %d", w.Code)
	}
	var readers sync.WaitGroup
	for i := 0; i < 8; i++ {
		readers.Add(1)
		go func() {
			defer readers.Done()
			for j := 0; j < 8; j++ {
				_ = app.lib.snapshot()
				_ = app.refreshStatus()
				app.github.setToken("temporary")
				_ = app.github.hasToken()
			}
		}()
	}
	close(unblock)
	readers.Wait()
	status := waitRefresh(t, app)
	if status.Done != 1 || status.Total != 1 || len(status.Errors) != 0 || app.lib.snapshot().Snapshots["owner/repo"].Stars != 1234 {
		t.Fatalf("refresh did not persist successful result: %+v", status)
	}
	if w := call(app, "POST", "/api/refresh", `{"repo":"unknown/repo"}`); w.Code != 404 {
		t.Fatalf("unknown project refreshed: %d", w.Code)
	}
}

func TestAddGameFetchesPublicMetadataAndReleaseBeforePersisting(t *testing.T) {
	app := testApp(t)
	calls := []string{}
	app.github.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		calls = append(calls, r.URL.Path)
		if strings.HasSuffix(r.URL.Path, "/releases/latest") {
			return apiResponse(200, jsonString(testRelease("owner/newgame", "v1"))), nil
		}
		return apiResponse(200, `{"full_name":"owner/newgame","name":"New game","description":"A classic game port","stargazers_count":23,"pushed_at":"2026-11-08T00:00:00Z"}`), nil
	})
	w := call(app, "POST", "/api/games", `{"repo":"https://github.com/owner/newgame"}`)
	if w.Code != 201 || len(calls) != 2 {
		t.Fatalf("new game was not fetched: %d, %v, %s", w.Code, calls, w.Body.String())
	}
	state := app.lib.snapshot()
	snapshot := state.Snapshots["owner/newgame"]
	if len(state.Games) != 1 || state.Games[0].Description != "A classic game port" || snapshot.Stars != 23 || snapshot.Release == nil || snapshot.StarsCheckedAt == "" || snapshot.ReleaseCheckedAt == "" {
		t.Fatalf("incomplete custom game: %+v", snapshot)
	}
	if w := call(app, "POST", "/api/games", `{"repo":"OWNER/NEWGAME"}`); w.Code != 200 || len(calls) != 2 {
		t.Fatal("duplicate add fetched upstream again")
	}
	if w := call(app, "POST", "/api/games", `{"repo":"https://evil.com/game.exe"}`); w.Code != 400 || len(calls) != 2 {
		t.Fatal("malicious repository reached network")
	}
	app.github.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		if strings.HasSuffix(r.URL.Path, "/releases/latest") {
			return apiResponse(404, `{}`), nil
		}
		return apiResponse(200, `{"full_name":"owner/norelease","name":"No release","stargazers_count":5}`), nil
	})
	if w := call(app, "POST", "/api/games", `{"repo":"owner/norelease"}`); w.Code != 201 {
		t.Fatalf("public project without release cannot be saved: %d", w.Code)
	}
	snapshot = app.lib.snapshot().Snapshots["owner/norelease"]
	if snapshot.Release != nil || snapshot.ReleaseCheckedAt == "" || snapshot.Error != "" || snapshot.Stars != 5 {
		t.Fatalf("verified missing release was not recorded: %+v", snapshot)
	}
}

func TestLibraryStartupUsesCacheWithoutNetwork(t *testing.T) {
	app := testApp(t)
	app.github.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		t.Errorf("cache read made unexpected network request: %s", r.URL)
		return apiResponse(500, `{}`), nil
	})
	if w := call(app, "GET", "/api/library", ""); w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	if w := call(app, "GET", "/api/status", ""); w.Code != 200 || app.refreshStatus().Running {
		t.Fatal("startup must not begin a refresh")
	}
}

func TestQuitRequiresSessionAndAcceptsEmptyBody(t *testing.T) {
	app := testApp(t)
	bad := request(app, "POST", "/api/quit", "")
	bad.Header.Del("Authorization")
	bad.Body = io.NopCloser(strings.NewReader(""))
	w := httptest.NewRecorder()
	app.handler().ServeHTTP(w, bad)
	if w.Code != 401 {
		t.Fatal("quit did not require session authorization")
	}
	if w := call(app, "POST", "/api/quit", ""); w.Code != 200 {
		t.Fatalf("empty quit body not accepted: %d", w.Code)
	}
	select {
	case <-app.quit:
	case <-time.After(time.Second):
		t.Fatal("quit was not signaled")
	}
}

func TestSearchSerializesKnownZeroStars(t *testing.T) {
	app := testApp(t)
	app.github.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		return apiResponse(200, `{"items":[{"full_name":"owner/newgame","name":"New game","description":"A new port","stargazers_count":0,"private":false}]}`), nil
	})
	w := call(app, "GET", "/api/search?q=port", "")
	var games []map[string]json.RawMessage
	if err := json.Unmarshal(w.Body.Bytes(), &games); w.Code != http.StatusOK || err != nil || len(games) != 1 {
		t.Fatalf("invalid search response: HTTP %d, %v, %s", w.Code, err, w.Body.String())
	}
	if stars, ok := games[0]["stars"]; !ok || string(stars) != "0" {
		t.Fatalf("known zero stars lost from search response: %s", w.Body.String())
	}
	var unknown map[string]json.RawMessage
	if err := json.Unmarshal([]byte(jsonString(Game{Repo: "owner/unqueried"})), &unknown); err != nil {
		t.Fatal(err)
	}
	if _, ok := unknown["stars"]; ok {
		t.Fatal("unqueried game should not claim a known star count")
	}
}

func TestSearchStarFilterQueriesWithoutKeywords(t *testing.T) {
	cases := []struct {
		name, parameters, query string
	}{
		{"no filters", "", `sourceport OR "source port" OR recompilation OR remake OR reimplementation OR decompilation fork:true`},
		{"empty filters", "?minStars=&maxStars=", `sourceport OR "source port" OR recompilation OR remake OR reimplementation OR decompilation fork:true`},
		{"minimum", "?minStars=500", `sourceport OR "source port" OR recompilation OR remake OR reimplementation OR decompilation fork:true stars:>=500`},
		{"maximum", "?maxStars=500", `sourceport OR "source port" OR recompilation OR remake OR reimplementation OR decompilation fork:true stars:<=500`},
		{"range", "?minStars=100&maxStars=500", `sourceport OR "source port" OR recompilation OR remake OR reimplementation OR decompilation fork:true stars:100..500`},
		{"zero minimum", "?minStars=0", `sourceport OR "source port" OR recompilation OR remake OR reimplementation OR decompilation fork:true stars:>=0`},
		{"zero maximum", "?maxStars=0", `sourceport OR "source port" OR recompilation OR remake OR reimplementation OR decompilation fork:true stars:<=0`},
		{"exact zero", "?minStars=0&maxStars=0", `sourceport OR "source port" OR recompilation OR remake OR reimplementation OR decompilation fork:true stars:0..0`},
		{"equal bounds", "?minStars=500&maxStars=500", `sourceport OR "source port" OR recompilation OR remake OR reimplementation OR decompilation fork:true stars:500..500`},
		{"maximum allowed", "?minStars=1000000000&maxStars=1000000000", `sourceport OR "source port" OR recompilation OR remake OR reimplementation OR decompilation fork:true stars:1000000000..1000000000`},
		{"legacy keyword", "?q=doom&minStars=50", "doom archived:false stars:>=50"},
		{"legacy keyword only", "?q=doom", "doom archived:false"},
		{"blank keyword", "?q=%20%20&minStars=50", `sourceport OR "source port" OR recompilation OR remake OR reimplementation OR decompilation fork:true stars:>=50`},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			app := testApp(t)
			calls := 0
			app.github.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
				calls++
				params := r.URL.Query()
				expectedPageSize := "100"
				if strings.HasPrefix(tc.name, "legacy") {
					expectedPageSize = "24"
				}
				if r.URL.Path != "/search/repositories" || params.Get("q") != tc.query || params.Get("sort") != "stars" || params.Get("order") != "desc" || params.Get("per_page") != expectedPageSize {
					t.Errorf("incorrect GitHub search request: %s", r.URL)
				}
				return apiResponse(http.StatusOK, `{"items":[]}`), nil
			})
			w := call(app, "GET", "/api/search"+tc.parameters, "")
			if w.Code != http.StatusOK || calls != 1 || strings.TrimSpace(w.Body.String()) != "[]" {
				t.Fatalf("unexpected search response: HTTP %d, calls=%d, body=%s", w.Code, calls, w.Body.String())
			}
		})
	}
}

func TestSearchRejectsInvalidStarFiltersBeforeGitHub(t *testing.T) {
	cases := []string{
		"minStars=-1", "maxStars=-1", "minStars=1.5", "maxStars=0.0", "minStars=abc", "maxStars=NaN", "minStars=1e3", "minStars=%2B1", "maxStars=%20", "minStars=1000000001", "maxStars=1000000001", "minStars=999999999999999999999999999999999", "minStars=501&maxStars=500", "minStars=1&maxStars=0", "minStars=%EF%BC%91", "minStars=%ZZ", "minStars=0&minStars=-1", "maxStars=1&maxStars=2",
	}
	app := testApp(t)
	calls := 0
	app.github.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		calls++
		return apiResponse(http.StatusOK, `{"items":[]}`), nil
	})
	for _, params := range cases {
		t.Run(params, func(t *testing.T) {
			w := call(app, "GET", "/api/search?"+params, "")
			var failure map[string]string
			if err := json.Unmarshal(w.Body.Bytes(), &failure); w.Code != http.StatusBadRequest || err != nil || failure["error"] == "" {
				t.Fatalf("invalid filter not rejected with JSON 400: HTTP %d, %v, %s", w.Code, err, w.Body.String())
			}
		})
	}
	if calls != 0 {
		t.Fatalf("invalid filters made %d GitHub requests", calls)
	}
}

func TestDiscoverHTTPValidatesPageAndBoundsBeforeNetwork(t *testing.T) {
	app := testApp(t)
	calls := 0
	app.github.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		calls++
		return apiResponse(200, `{"items":[],"total_count":0,"incomplete_results":false}`), nil
	})
	for _, params := range []string{"page=0", "page=11", "page=-1", "page=1.5", "page=", "page=abc", "page=%2B1", "page=%20", "page=%ZZ", "page=9999999999999999999999", "page=1&page=2", "cursor=a&cursor=b", "cursor=bad", "minStars=-1", "maxStars=1.2", "minStars=1000000001", "minStars=2&maxStars=1", "minStars=0&minStars=1", "maxStars=0&maxStars=1"} {
		w := call(app, "GET", "/api/discover?"+params, "")
		if w.Code != http.StatusBadRequest {
			t.Errorf("invalid discover parameters reached HTTP %d: %s", w.Code, params)
		}
	}
	if calls != 0 {
		t.Fatalf("invalid discover inputs sent %d network requests", calls)
	}
	w := call(app, "GET", "/api/discover?minStars=&maxStars=", "")
	var page DiscoveryPage
	if err := json.Unmarshal(w.Body.Bytes(), &page); err != nil || w.Code != 200 || page.Items == nil || page.Page != 1 || page.NextPage != 2 || page.NextCursor == "" || !page.HasMore || calls != 1 {
		t.Fatalf("default discover contract: %d %s %v", w.Code, w.Body.String(), err)
	}
}

func TestBatchAddsOnlyCachedPublicDiscoveryWithoutExtraRequests(t *testing.T) {
	app := testApp(t)
	calls := 0
	app.github.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		calls++
		if r.URL.Path != "/search/repositories" {
			t.Errorf("batch fetched additional metadata: %s", r.URL)
		}
		items := []searchRepository{
			{FullName: "owner/NewPort", Name: "Verified name", Description: "A source port", Stars: 0},
			{FullName: "owner/later", Name: "Later", Description: "A source port", Stars: 10},
			{FullName: "owner/private", Name: "Private", Description: "A source port", Stars: 20, Private: true},
			{FullName: "owner/awesome-games", Name: "awesome-games", Description: "A source port list", Stars: 100},
		}
		return apiResponse(200, jsonString(map[string]any{"items": items, "total_count": 4})), nil
	})
	if w := call(app, "GET", "/api/discover", ""); w.Code != 200 {
		t.Fatalf("discovery failed: %s", w.Body.String())
	}
	w := call(app, "POST", "/api/games/batch", `{"repos":["OWNER/NEWPORT","owner/newport","OpenRCT2/OpenRCT2","owner/unknown","owner/private","owner/awesome-games","../invalid"]}`)
	var result BatchResult
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil || w.Code != 200 || len(result.Added) != 1 || result.Added[0] != "owner/NewPort" || len(result.Skipped) != 2 || len(result.Failed) != 4 || calls != 1 {
		t.Fatalf("incorrect partial batch: %d %s %v calls=%d", w.Code, w.Body.String(), err, calls)
	}
	state := app.lib.snapshot()
	snapshot := state.Snapshots["owner/newport"]
	if len(state.Games) != 1 || state.Games[0].Name != "Verified name" || state.Games[0].Stars == nil || *state.Games[0].Stars != 0 || snapshot.Stars != 0 || snapshot.StarsCheckedAt == "" || snapshot.Release != nil || snapshot.ReleaseCheckedAt != "" || snapshot.Error != "" {
		t.Fatalf("batch trusted incorrect metadata or fabricated release: %+v, %+v", state.Games, snapshot)
	}
	if _, err := time.Parse(time.RFC3339, snapshot.StarsCheckedAt); err != nil {
		t.Fatal(err)
	}
	reloaded, err := newLibrary(app.lib.root)
	if err != nil || len(reloaded.snapshot().Games) != 1 {
		t.Fatalf("batch did not persist: %v", err)
	}
	newSession, err := newApp(reloaded)
	if err != nil {
		t.Fatal(err)
	}
	defer newSession.cancel()
	if next := newSession.addDiscovered([]string{"owner/later"}); len(next.Failed) != 1 || len(next.Added) != 0 {
		t.Fatalf("discovery trust survived beyond its session: %+v", next)
	}
}

func TestBatchRequestValidationAndAtomicDiskFailure(t *testing.T) {
	app := testApp(t)
	app.github.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		t.Errorf("batch performed an unexpected outbound request: %s", r.URL)
		return apiResponse(500, `{}`), nil
	})
	tooMany := make([]string, 101)
	for i := range tooMany {
		tooMany[i] = "owner/repo"
	}
	for _, body := range []string{`{}`, `{"repos":null}`, `{"repos":["owner/repo"],"name":"forged"}`, `{"repos":"owner/repo"}`, jsonString(map[string]any{"repos": tooMany})} {
		if w := call(app, "POST", "/api/games/batch", body); w.Code != 400 {
			t.Errorf("invalid batch accepted: %d %s", w.Code, body)
		}
	}
	if w := call(app, "POST", "/api/games/batch", `{"repos":[]}`); w.Code != 200 || strings.Contains(w.Body.String(), "null") {
		t.Fatalf("empty batch should be a no-op with arrays: %d %s", w.Code, w.Body.String())
	}
	stars := 10
	app.cacheDiscovery([]Game{{Repo: "owner/one", Name: "One", Stars: &stars}, {Repo: "owner/two", Name: "Two", Stars: &stars}}, "2026-11-09T01:00:00Z")
	if err := os.Mkdir(filepath.Join(app.lib.root, "library.json"), 0700); err != nil {
		t.Fatal(err)
	}
	w := call(app, "POST", "/api/games/batch", `{"repos":["owner/one","owner/two"]}`)
	var result BatchResult
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil || w.Code != 200 || len(result.Added) != 0 || len(result.Failed) != 2 || len(app.lib.snapshot().Games) != 0 {
		t.Fatalf("disk failure published partial batch: %d %s %v", w.Code, w.Body.String(), err)
	}
	if leftovers, _ := filepath.Glob(filepath.Join(app.lib.root, ".library-*")); len(leftovers) != 0 {
		t.Fatalf("failed atomic batch left temporary files: %v", leftovers)
	}
}

func TestDiscoveryCacheIsBoundedAndConcurrentBatchesDoNotDuplicate(t *testing.T) {
	app := testApp(t)
	games := []Game{}
	for _, repo := range discoveryCandidates(0, maxDiscoveredCandidates+1) {
		stars := repo.Stars
		games = append(games, Game{Repo: repo.FullName, Name: repo.Name, Stars: &stars})
	}
	app.cacheDiscovery(games, "2026-11-09T01:00:00Z")
	if len(app.candidates) != maxDiscoveredCandidates || len(app.candidateOrder) != maxDiscoveredCandidates {
		t.Fatalf("candidate cache exceeded bound: %d", len(app.candidates))
	}
	if _, ok := app.discoveredCandidate("ports/game0"); ok {
		t.Fatal("oldest candidate was not evicted")
	}
	*games[1].Stars = 999999
	entry, ok := app.discoveredCandidate("ports/game1")
	if !ok || *entry.Game.Stars != 999 {
		t.Fatal("candidate cache shares caller-owned pointer")
	}
	*entry.Game.Stars = 123456
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for j := 0; j < 4; j++ {
				app.cacheDiscovery([]Game{games[2]}, "2026-11-09T02:00:00Z")
				result := app.addDiscovered([]string{"ports/game1", "PORTS/GAME2"})
				if len(result.Failed) != 0 {
					t.Errorf("concurrent batch failed: %+v", result)
				}
				_ = app.lib.snapshot()
			}
		}()
	}
	wg.Wait()
	state := app.lib.snapshot()
	if len(state.Games) != 2 || *state.Games[0].Stars != 999 {
		t.Fatalf("concurrent batch duplicated or mutated entries: %+v", state.Games)
	}
}

func TestDiscoverHTTPContinuesPastTenPagesOnlyWithBoundedCursor(t *testing.T) {
	app := testApp(t)
	calls := 0
	app.github.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		calls++
		if r.URL.Query().Get("page") != "1" || !strings.HasSuffix(r.URL.Query().Get("q"), "stars:10..99") {
			t.Errorf("invalid upstream discovery page/bounds: %s", r.URL)
		}
		return apiResponse(200, `{"items":[],"total_count":0}`), nil
	})
	bounds, _ := parseStarBounds("10", "")
	cursor := encodeDiscoveryCursor(discoveryCursor{Version: 1, Query: 1, Page: 1, Next: 11, Bounds: discoveryBounds(bounds), Ranges: []discoveryRange{{Min: 10, Max: 99}}})
	w := call(app, "GET", "/api/discover?minStars=10&page=11&cursor="+cursor, "")
	var page DiscoveryPage
	if err := json.Unmarshal(w.Body.Bytes(), &page); err != nil || w.Code != 200 || page.Page != 11 || page.NextPage != 12 || !page.HasMore || calls != 1 {
		t.Fatalf("valid later cursor rejected: %d %s %v", w.Code, w.Body.String(), err)
	}
	w = call(app, "GET", "/api/discover?minStars=20&page=11&cursor="+cursor, "")
	if w.Code != 400 || calls != 1 {
		t.Fatalf("cursor escaped requested bounds: %d calls=%d", w.Code, calls)
	}
}
