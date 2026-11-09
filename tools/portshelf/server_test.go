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
