package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

// Exercise the local route and the remote response over real HTTP connections.
// Only the production destination is redirected to the test's loopback server.
func posterCacheHTTPReader(t *testing.T, app *App, status int, remote Description) (func() Description, *atomic.Int64) {
	t.Helper()
	calls := &atomic.Int64{}
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		if r.Method != http.MethodGet || r.URL.Path != "/api/v1/projects/descriptions" ||
			r.URL.Query().Get("repos") != "owner/game" || r.URL.Query().Get("gameDetails") != "true" || r.Header.Get("Authorization") != "" {
			t.Error("cache refresh must be an anonymous GET for the requested game")
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		if status != http.StatusOK {
			_, _ = w.Write([]byte(`{"detail":"sensitive upstream detail"}`))
			return
		}
		_ = json.NewEncoder(w).Encode(DescriptionsResponse{Items: []Description{remote}, PollAfter: 3})
	}))
	t.Cleanup(upstream.Close)
	target, err := url.Parse(upstream.URL)
	if err != nil {
		t.Fatal(err)
	}
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.Proxy = nil
	t.Cleanup(transport.CloseIdleConnections)
	app.aigc.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		forward := r.Clone(r.Context())
		forward.URL.Scheme, forward.URL.Host = target.Scheme, target.Host
		forward.Host = target.Host
		return transport.RoundTrip(forward)
	})
	app.aigc.setToken("unused-test-generation-token")
	local := httptest.NewUnstartedServer(app.handler())
	app.host = local.Listener.Addr().String()
	local.Start()
	t.Cleanup(local.Close)
	return func() Description {
		t.Helper()
		r, err := http.NewRequest(http.MethodGet, local.URL+"/api/descriptions?repos=owner/game", nil)
		if err != nil {
			t.Fatal(err)
		}
		r.Header.Set("Authorization", "Bearer "+app.token)
		response, err := local.Client().Do(r)
		if err != nil {
			t.Fatal(err)
		}
		defer response.Body.Close()
		var body DescriptionsResponse
		if response.StatusCode != http.StatusOK || json.NewDecoder(response.Body).Decode(&body) != nil || len(body.Items) != 1 {
			t.Fatalf("invalid local description response: HTTP %d, %+v", response.StatusCode, body)
		}
		return body.Items[0]
	}, calls
}

func TestPosterCacheRefreshHTTPReadsNewArtworkAfterOneMinute(t *testing.T) {
	for _, tc := range []struct {
		name   string
		status string
		oldURL bool
	}{
		{"missing image", "missing", false},
		{"failed search without image", "unavailable", false},
		{"failed search retaining old image", "unavailable", true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			app := descriptionApp(t)
			old := gameDetailsFixture("owner/game")
			old.CheckedAt = time.Now().Add(-61 * time.Second).UTC().Format(time.RFC3339)
			old.PosterStatus = tc.status
			if !tc.oldURL {
				old.PosterURL, old.PosterSourceURL, old.PosterKind = "", "", ""
			}
			if err := app.lib.saveDescriptions([]Description{old}); err != nil {
				t.Fatal(err)
			}
			completed := gameDetailsFixture(old.Repo)
			completed.PosterURL = "https://aigcnews.cn/api/media/site/game-posters/" + strings.Repeat("a", 64) + ".jpg"
			completed.PosterSourceURL = "https://gamesdb.launchbox-app.com/games/details/1-game"
			completed.PosterKind, completed.PosterStatus = "cover", "ready"
			read, calls := posterCacheHTTPReader(t, app, http.StatusOK, completed)
			got := read()
			if calls.Load() != 1 || got.PosterURL != completed.PosterURL || got.PosterStatus != "ready" ||
				got.DescriptionZh != old.DescriptionZh || got.CheckedAt == old.CheckedAt {
				t.Fatalf("stale incomplete artwork was not refreshed: calls=%d, %+v", calls.Load(), got)
			}
			if again := read(); calls.Load() != 1 || again.PosterURL != completed.PosterURL {
				t.Fatal("completed artwork should be reused without repeated network reads")
			}
			reloaded, err := newLibrary(app.lib.root)
			if err != nil || reloaded.snapshot().Descriptions[old.Repo].PosterURL != completed.PosterURL {
				t.Fatalf("refreshed artwork did not survive reload: %v", err)
			}
		})
	}
}

func TestPosterCacheHTTPRetainsHealthyAndRecentIncompleteRecords(t *testing.T) {
	for _, tc := range []struct {
		name   string
		age    time.Duration
		status string
		image  bool
	}{
		{"healthy artwork retains seven day cache", 6 * 24 * time.Hour, "ready", true},
		{"recent missing artwork", 30 * time.Second, "missing", false},
		{"recent failed search with old image", 30 * time.Second, "unavailable", true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			app := descriptionApp(t)
			old := gameDetailsFixture("owner/game")
			old.CheckedAt = time.Now().Add(-tc.age).UTC().Format(time.RFC3339)
			old.PosterStatus = tc.status
			if !tc.image {
				old.PosterURL, old.PosterSourceURL, old.PosterKind = "", "", ""
			}
			if err := app.lib.saveDescriptions([]Description{old}); err != nil {
				t.Fatal(err)
			}
			read, calls := posterCacheHTTPReader(t, app, http.StatusServiceUnavailable, Description{})
			for range 2 {
				got := read()
				if calls.Load() != 0 || got.CheckedAt != old.CheckedAt || got.PosterURL != old.PosterURL || got.DescriptionZh != old.DescriptionZh {
					t.Fatalf("fresh record caused unnecessary network request: calls=%d, %+v", calls.Load(), got)
				}
			}
		})
	}
}

func TestPosterCacheHTTPFailurePreservesPreviousArtworkAndText(t *testing.T) {
	app := descriptionApp(t)
	old := gameDetailsFixture("owner/game")
	old.PosterStatus = "unavailable"
	old.CheckedAt = time.Now().Add(-2 * time.Minute).UTC().Format(time.RFC3339)
	if err := app.lib.saveDescriptions([]Description{old}); err != nil {
		t.Fatal(err)
	}
	read, calls := posterCacheHTTPReader(t, app, http.StatusServiceUnavailable, Description{})
	got := read()
	if calls.Load() != 1 || !readyDescription(got) || got.PosterURL != old.PosterURL ||
		got.DescriptionZh != old.DescriptionZh || got.GameNameZh != old.GameNameZh || got.CheckedAt != old.CheckedAt ||
		got.Error == "" || strings.Contains(got.Error, "sensitive") {
		t.Fatalf("failed read did not safely retain ready artwork/text: calls=%d, %+v", calls.Load(), got)
	}
	// Returning the old ready state, rather than pending, keeps the browser out
	// of the generation-poll loop. The previous check time is not falsified.
	reloaded, err := newLibrary(app.lib.root)
	if err != nil {
		t.Fatal(err)
	}
	cached := reloaded.snapshot().Descriptions[old.Repo]
	if cached.DescriptionZh != old.DescriptionZh || cached.PosterURL != old.PosterURL || cached.CheckedAt != old.CheckedAt {
		t.Fatal("temporary remote failure overwrote the saved game details")
	}
}
