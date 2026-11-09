package main

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

func readyFixture(repo string) Description {
	return Description{Repo: repo, Status: "ready", DescriptionZh: "这是一款经典游戏的开源移植，支持现代电脑。", Source: "aigcnews", CheckedAt: time.Now().UTC().Format(time.RFC3339)}
}
func descriptionApp(t *testing.T) *App {
	t.Helper()
	app := testApp(t)
	stars := 10
	app.cacheDiscovery([]Game{{Repo: "owner/game", Name: "Game", Description: "Original English description", Stars: &stars}}, time.Now().UTC().Format(time.RFC3339))
	return app
}
func TestDescriptionEndpointsLimitScopeBeforeNetwork(t *testing.T) {
	app := descriptionApp(t)
	calls := 0
	app.aigc.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) { calls++; return apiResponse(500, `{}`), nil })
	for _, path := range []string{"/api/descriptions", "/api/descriptions?repos=", "/api/descriptions?repos=unknown/private", "/api/descriptions?repos=owner/game,OWNER/GAME", "/api/descriptions?repos=owner/game&repos=owner/game", "/api/descriptions?repos=%ZZ", "/api/descriptions?repos=" + strings.Repeat("owner/game,", 50) + "owner/game"} {
		if w := call(app, "GET", path, ""); w.Code != 400 {
			t.Errorf("invalid description scope accepted: %d %s", w.Code, path)
		}
	}
	if w := call(app, "POST", "/api/descriptions", `{"repo":"unknown/private"}`); w.Code != 400 {
		t.Fatal("unknown generation project allowed")
	}
	if w := call(app, "POST", "/api/descriptions", `{"repo":"owner/game"}`); w.Code != 401 {
		t.Fatal("missing AIGC token not rejected locally")
	}
	if calls != 0 {
		t.Fatalf("invalid request sent %d outbound requests", calls)
	}
	for _, route := range []struct{ method, path, body string }{{"GET", "/api/descriptions?repos=owner/game", ""}, {"POST", "/api/descriptions", `{"repo":"owner/game"}`}, {"POST", "/api/aigc-token", `{"token":"x"}`}} {
		r := request(app, route.method, route.path, route.body)
		r.Header.Del("Authorization")
		w := httptest.NewRecorder()
		app.handler().ServeHTTP(w, r)
		if w.Code != 401 {
			t.Errorf("local description endpoint lacks session auth: %s", route.path)
		}
	}
}

func TestAIGCTokenIsolationAndAnonymousReads(t *testing.T) {
	app := descriptionApp(t)
	const aigcSecret = "mcp_aigc_secret"
	const githubSecret = "github_secret"
	app.github.setToken(githubSecret)
	if w := call(app, "POST", "/api/aigc-token", `{"token":"`+aigcSecret+`"}`); w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	gets, posts := 0, 0
	app.aigc.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		if r.URL.Scheme != "https" || r.URL.Host != "aigcnews.cn" || r.URL.Path != "/api/v1/projects/descriptions" {
			t.Errorf("unapproved destination %s", r.URL)
		}
		if r.Method == "GET" {
			gets++
			if r.Header.Get("Authorization") != "" || r.URL.Query().Get("repos") != "owner/game" {
				t.Error("readonly request leaked token or altered repo")
			}
		}
		if r.Method == "POST" {
			posts++
			body, _ := io.ReadAll(r.Body)
			if r.Header.Get("Authorization") != "Bearer "+aigcSecret || string(body) != `{"repo":"owner/game"}` {
				t.Errorf("generation used incorrect credentials or input: %s", body)
			}
		}
		return apiResponse(200, jsonString(DescriptionsResponse{Items: []Description{readyFixture("owner/game")}, PollAfter: 3})), nil
	})
	if w := call(app, "GET", "/api/descriptions?repos=owner/game", ""); w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	if w := call(app, "POST", "/api/descriptions", `{"repo":"owner/game"}`); w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	if gets != 1 || posts != 1 {
		t.Fatalf("unexpected API calls: %d %d", gets, posts)
	}
	state, err := os.ReadFile(filepath.Join(app.lib.root, "library.json"))
	if err != nil || strings.Contains(string(state), aigcSecret) || strings.Contains(string(state), githubSecret) {
		t.Fatalf("credential persisted: %v", err)
	}
	w := call(app, "GET", "/api/library", "")
	if !strings.Contains(w.Body.String(), `"hasAigcToken":true`) || strings.Contains(w.Body.String(), aigcSecret) || strings.Contains(w.Body.String(), githubSecret) {
		t.Fatal("library token contract unsafe")
	}
	reloaded, err := newLibrary(app.lib.root)
	if err != nil {
		t.Fatal(err)
	}
	restarted, err := newApp(reloaded)
	if err != nil {
		t.Fatal(err)
	}
	defer restarted.cancel()
	if restarted.aigc.hasToken() || restarted.github.hasToken() {
		t.Fatal("credentials survived process restart")
	}
	if w := call(app, "POST", "/api/aigc-token", `{"token":""}`); w.Code != 200 || app.aigc.hasToken() {
		t.Fatal("token could not be cleared")
	}
	for _, token := range []string{"bad\ntoken", "bad token", strings.Repeat("x", 4097)} {
		if w := call(app, "POST", "/api/aigc-token", jsonString(map[string]string{"token": token})); w.Code != 400 {
			t.Fatal("invalid AIGC token accepted")
		}
	}
}

func TestDescriptionTTLAndFailuresPreserveReadyAndOriginalEnglish(t *testing.T) {
	app := descriptionApp(t)
	if result := app.addDiscovered([]string{"owner/game"}); len(result.Added) != 1 {
		t.Fatal(result)
	}
	item := readyFixture("owner/game")
	if err := app.lib.saveDescriptions([]Description{item}); err != nil {
		t.Fatal(err)
	}
	calls := 0
	mode := "failure"
	app.aigc.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		calls++
		switch mode {
		case "failure":
			return apiResponse(503, `{"error":"sensitive upstream implementation detail"}`), nil
		case "english":
			english := readyFixture("owner/game")
			english.DescriptionZh = "An open source game port."
			return apiResponse(200, jsonString(DescriptionsResponse{Items: []Description{english}, PollAfter: 3})), nil
		case "pending":
			return apiResponse(200, jsonString(DescriptionsResponse{Items: []Description{{Repo: "owner/game", Status: "pending", Source: "aigcnews", RetryAfter: 3}}, PollAfter: 3})), nil
		default:
			return apiResponse(200, jsonString(DescriptionsResponse{Items: []Description{readyFixture("owner/game")}, PollAfter: 3})), nil
		}
	})
	if result, err := app.readDescriptions(context.Background(), []string{"owner/game"}); err != nil || !readyDescription(result.Items[0]) || calls != 0 {
		t.Fatalf("fresh cache was not reused: %+v %v", result, err)
	}
	item.CheckedAt = time.Now().Add(-8 * 24 * time.Hour).UTC().Format(time.RFC3339)
	if err := app.lib.saveDescriptions([]Description{item}); err != nil {
		t.Fatal(err)
	}
	for _, phase := range []string{"failure", "english"} {
		mode = phase
		response, err := app.readDescriptions(context.Background(), []string{"owner/game"})
		if err != nil || !readyDescription(response.Items[0]) || response.Items[0].CheckedAt != item.CheckedAt || response.Items[0].Error == "" || strings.Contains(response.Items[0].Error, "sensitive") {
			t.Fatalf("expired good text lost on %s: %+v %v", phase, response, err)
		}
		if cached := app.lib.snapshot().Descriptions["owner/game"]; cached.DescriptionZh != item.DescriptionZh || cached.CheckedAt != item.CheckedAt {
			t.Fatalf("failure overwrote ready: %+v", cached)
		}
	}
	mode = "pending"
	response, err := app.readDescriptions(context.Background(), []string{"owner/game"})
	if err != nil || response.Items[0].Status != "pending" || response.PollAfter != 3 || response.Items[0].RetryAfter != 3 || !readyDescription(app.lib.snapshot().Descriptions["owner/game"]) {
		t.Fatalf("pending poll or stored ready lost: %+v %v", response, err)
	}
	mode = "ready"
	response, err = app.readDescriptions(context.Background(), []string{"owner/game"})
	if err != nil || !readyDescription(response.Items[0]) || response.Items[0].CheckedAt == item.CheckedAt || app.lib.snapshot().Games[0].Description != "Original English description" {
		t.Fatalf("refresh failed or original overwritten: %+v %v", response, err)
	}
}

func TestAIGCRejectsUntrustedResponsesAndRedirects(t *testing.T) {
	good := readyFixture("owner/game")
	for _, text := range []string{"English only", "冒険ゲームです。", strings.Repeat("中", 513)} {
		client := newAIGC()
		invalid := good
		invalid.DescriptionZh = text
		client.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
			return apiResponse(200, jsonString(DescriptionsResponse{Items: []Description{invalid}})), nil
		})
		result, err := client.get(context.Background(), []string{"owner/game"})
		if err != nil || result.Items[0].Status != "failed" || result.Items[0].DescriptionZh != "" {
			t.Fatalf("invalid Chinese text accepted as ready: %+v %v", result, err)
		}
	}
	foreign := readyFixture("other/game")
	wrongSource := good
	wrongSource.Source = "untrusted"
	bodies := []string{
		`not json`, strings.Repeat(" ", (1<<20)+1),
		jsonString(DescriptionsResponse{Items: []Description{good, good}}),
		jsonString(DescriptionsResponse{Items: []Description{foreign}}),
		jsonString(DescriptionsResponse{Items: []Description{wrongSource}}),
		`{"items":[]}`,
	}
	for _, body := range bodies {
		client := newAIGC()
		client.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) { return apiResponse(200, body), nil })
		if _, err := client.get(context.Background(), []string{"owner/game"}); err == nil {
			t.Fatal("malformed or mismatched description accepted")
		}
	}
	for _, status := range []int{401, 403, 404, 429, 503} {
		client := newAIGC()
		client.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
			return apiResponse(status, `<script>secret</script>`), nil
		})
		_, err := client.get(context.Background(), []string{"owner/game"})
		var upstream *descriptionError
		if !errors.As(err, &upstream) || upstream.Status != status || strings.Contains(err.Error(), "script") || strings.Contains(err.Error(), "secret") {
			t.Fatalf("unsafe remote error: %v", err)
		}
	}
	client := newAIGC()
	client.setToken("mcp_secret")
	calls := 0
	client.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		calls++
		response := apiResponse(307, "")
		response.Header.Set("Location", "https://evil.example/steal")
		return response, nil
	})
	if _, _, err := client.generate(context.Background(), "owner/game"); err == nil || calls != 1 {
		t.Fatal("token could follow cross-host redirect")
	}
	for _, raw := range []string{"http://aigcnews.cn/", "https://user@aigcnews.cn/", "https://aigcnews.cn:443/", "https://aigcnews.cn.evil.example/"} {
		target, _ := url.Parse(raw)
		if err := client.client.CheckRedirect(&http.Request{URL: target}, []*http.Request{{}}); err == nil {
			t.Errorf("unsafe redirect allowed: %s", raw)
		}
	}
}

func TestDescriptionPendingStatusAndDiskFailure(t *testing.T) {
	app := descriptionApp(t)
	app.aigc.setToken("mcp_token")
	app.aigc.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		return apiResponse(202, jsonString(DescriptionsResponse{Items: []Description{{Repo: "owner/game", Status: "pending", Source: "aigcnews", RetryAfter: 3}}, PollAfter: 3})), nil
	})
	if w := call(app, "POST", "/api/descriptions", `{"repo":"owner/game"}`); w.Code != 202 || !strings.Contains(w.Body.String(), `"status":"pending"`) {
		t.Fatalf("pending generation contract lost: %d %s", w.Code, w.Body.String())
	}
	if len(app.lib.snapshot().Descriptions) != 0 {
		t.Fatal("pending persisted as reliable cache")
	}
	if err := os.Mkdir(filepath.Join(app.lib.root, "library.json"), 0700); err != nil {
		t.Fatal(err)
	}
	app.aigc.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		return apiResponse(200, jsonString(DescriptionsResponse{Items: []Description{readyFixture("owner/game")}, PollAfter: 3})), nil
	})
	if w := call(app, "GET", "/api/descriptions?repos=owner/game", ""); w.Code != 500 || len(app.lib.snapshot().Descriptions) != 0 {
		t.Fatal("failed cache replacement published memory")
	}
}

func TestConcurrentDescriptionsBatchAndTokensPreserveState(t *testing.T) {
	app := descriptionApp(t)
	var wg sync.WaitGroup
	for i := 0; i < 6; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for j := 0; j < 3; j++ {
				if err := app.lib.saveDescriptions([]Description{readyFixture("owner/game")}); err != nil {
					t.Error(err)
				}
				_ = app.addDiscovered([]string{"owner/game"})
				app.aigc.setToken("temporary")
				_ = app.aigc.hasToken()
				_ = app.lib.snapshot()
			}
		}()
	}
	wg.Wait()
	state := app.lib.snapshot()
	if len(state.Games) != 1 || !readyDescription(state.Descriptions["owner/game"]) {
		t.Fatalf("concurrent writes lost cache or games: %+v", state.Games)
	}
	reloaded, err := newLibrary(app.lib.root)
	if err != nil || !readyDescription(reloaded.snapshot().Descriptions["owner/game"]) {
		t.Fatalf("ready cache did not survive reload: %v", err)
	}
}
