package main

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestTransferAutomaticallyFillsMissingPosterWithExistingChineseDetails(t *testing.T) {
	a, _, _ := prepareTransferApp(t)
	item := webPosterFixture()
	item.Repo = "OpenRCT2/OpenRCT2"
	item.PosterURL, item.PosterSourceURL, item.PosterKind = "", "", ""
	item.PosterStatus, item.PosterRetryAfter = "missing", 0
	if err := a.lib.saveDescriptions([]Description{item}); err != nil {
		t.Fatal(err)
	}
	a.aigc.setToken("test-enrichment-token")
	var posts atomic.Int32
	a.aigc.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		result := item
		if r.Method == http.MethodPost {
			posts.Add(1)
			var payload map[string]any
			if json.NewDecoder(r.Body).Decode(&payload) != nil || len(payload) != 2 || payload["repo"] != item.Repo || payload["gameDetails"] != true {
				t.Error("automatic missing-poster request should use ordinary enrichment")
			}
			result = webPosterFixture()
			result.Repo = item.Repo
		}
		return apiResponse(200, jsonString(DescriptionsResponse{Items: []Description{result}})), nil
	})
	ids, _, err := a.transfers.enqueue(TransferRequest{Repos: []string{item.Repo}, Arch: "amd64", Enrich: true})
	if err != nil || len(ids) != 1 {
		t.Fatal("enqueue", err)
	}
	job := waitTransfer(t, a, ids[0], "done")
	if posts.Load() != 1 || job.PosterURL != webPosterFixture().PosterURL || job.Description != item.DescriptionZh || job.GameNameZh != item.GameNameZh {
		t.Fatal("cached Chinese details prevented automatic missing-poster enrichment")
	}
}

func TestTransferPosterSearchHonorsCooldownAndKeepsDownloadsIndependent(t *testing.T) {
	for _, tc := range []struct {
		name                      string
		version, cooldown         int
		image, identity, wantPost bool
	}{
		{"legacy_missing", 0, 86400, false, true, true},
		{"web_missing", 1, 0, false, true, true},
		{"web_cooling", 1, 300, false, true, false},
		{"healthy", 1, 0, true, true, false},
		{"unresolved_identity", 1, 0, false, false, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			a, _, _ := prepareTransferApp(t)
			item := webPosterFixture()
			item.Repo = "OpenRCT2/OpenRCT2"
			item.PosterSearchVersion, item.PosterRetryAfter = tc.version, tc.cooldown
			if !tc.image {
				item.PosterURL, item.PosterSourceURL, item.PosterKind, item.PosterStatus = "", "", "", "missing"
			}
			if !tc.identity {
				item.GameNameOriginal = ""
			}
			job := TransferJob{ID: randomID(), Repo: item.Repo, Status: "running", Warnings: []string{}, Outputs: map[string]TransferOutput{}}
			a.transfers.mu.Lock()
			a.transfers.jobs = append(a.transfers.jobs, job)
			a.transfers.mu.Unlock()
			a.aigc.setToken("test-enrichment-token")
			posts := 0
			a.aigc.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
				result := item
				if r.Method == http.MethodPost {
					posts++
					result.PosterSearchVersion, result.PosterStatus, result.PosterRetryAfter = 1, "unavailable", 300
				}
				return apiResponse(200, jsonString(DescriptionsResponse{Items: []Description{result}})), nil
			})
			if err := a.transfers.enrich(context.Background(), job); err != nil {
				t.Fatal(err)
			}
			after, _ := a.transfers.job(job.ID)
			if (posts == 1) != tc.wantPost || posts > 1 || after.Description != item.DescriptionZh || !readyTransferDetails(after) {
				t.Fatal("poster cooldown or a failed lookup blocked existing Chinese details")
			}
			if !tc.image && tc.identity && len(after.Warnings) == 0 {
				t.Fatal("missing poster was silently reported as complete")
			}
		})
	}
}

func TestPosterRequestFailureKeepsVerifiedChineseDetailsWithoutAutomaticRetryLoop(t *testing.T) {
	for _, status := range []int{429, 503, 0, 200} {
		t.Run(http.StatusText(status), func(t *testing.T) {
			a, _, _ := prepareTransferApp(t)
			item := webPosterFixture()
			item.Repo = "OpenRCT2/OpenRCT2"
			item.PosterURL, item.PosterSourceURL, item.PosterKind = "", "", ""
			item.PosterStatus, item.PosterRetryAfter = "missing", 0
			job := TransferJob{ID: randomID(), Repo: item.Repo, Status: "running", Automatic: true, Enrich: true, Warnings: []string{}, Outputs: map[string]TransferOutput{}}
			a.transfers.mu.Lock()
			a.transfers.jobs = append(a.transfers.jobs, job)
			a.transfers.mu.Unlock()
			a.aigc.setToken("test-enrichment-token")
			posts := 0
			a.aigc.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
				if r.Method == http.MethodGet {
					return apiResponse(200, jsonString(DescriptionsResponse{Items: []Description{item}})), nil
				}
				posts++
				if status == 0 {
					return nil, errors.New("temporary network failure")
				}
				if status == 200 {
					failed := item
					failed.Status = "failed"
					return apiResponse(200, jsonString(DescriptionsResponse{Items: []Description{failed}})), nil
				}
				return apiResponse(status, `{}`), nil
			})
			if err := a.transfers.enrich(context.Background(), job); err != nil {
				t.Fatal(err)
			}
			after, _ := a.transfers.job(job.ID)
			if posts != 1 || !readyTransferDetails(after) || after.Description != item.DescriptionZh || after.GameNameZh != item.GameNameZh || len(after.Warnings) != 1 || !strings.Contains(after.Warnings[0], "海报") {
				t.Fatal("poster HTTP failure discarded already verified Chinese details")
			}
			if !readyGameDetails(a.lib.snapshot().Descriptions[strings.ToLower(item.Repo)]) {
				t.Fatal("verified text was not cached")
			}
			if err := a.transfers.modify(job.ID, func(j *TransferJob) { j.Status = "done" }, true); err != nil {
				t.Fatal(err)
			}
			a.transfers.planAutomaticRetry(job.ID)
			after, _ = a.transfers.job(job.ID)
			if after.Status != "done" || after.NextRetryAt != "" {
				t.Fatal("poster-only failure caused automatic file transfer retries")
			}
		})
	}
}

func TestWebPosterEvictionClearsCachedArtworkButPreservesText(t *testing.T) {
	a := descriptionApp(t)
	old := webPosterFixture()
	old.CheckedAt = time.Now().Add(-8 * 24 * time.Hour).UTC().Format(time.RFC3339)
	if err := a.lib.saveDescriptions([]Description{old}); err != nil {
		t.Fatal(err)
	}
	a.aigc.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		if r.Method != http.MethodGet {
			t.Error("cache-only read triggered a paid search")
		}
		missing := old
		missing.PosterURL, missing.PosterSourceURL, missing.PosterKind = "", "", ""
		missing.PosterStatus, missing.PosterRetryAfter = "missing", 0
		return apiResponse(200, jsonString(DescriptionsResponse{Items: []Description{missing}})), nil
	})
	response := call(a, "GET", "/api/descriptions?repos=owner/game", "")
	var result DescriptionsResponse
	if response.Code != 200 || json.Unmarshal(response.Body.Bytes(), &result) != nil || len(result.Items) != 1 {
		t.Fatal("read failed")
	}
	for _, item := range []Description{result.Items[0], a.lib.snapshot().Descriptions[old.Repo]} {
		if item.PosterURL != "" || item.PosterSourceURL != "" || item.PosterStatus != "missing" || item.PosterSearchVersion != 1 || item.DescriptionZh != old.DescriptionZh || !needsPosterGeneration(item) {
			t.Fatal("evicted cached poster was restored by local fallback")
		}
	}
}

func webPosterFixture() Description {
	item := readyFixture("owner/game")
	item.GameNameZh, item.GameNameOriginal = "过山车大亨 2", "RollerCoaster Tycoon 2"
	item.PosterURL = "https://aigcnews.cn/api/media/site/game-posters/" + strings.Repeat("a1", 32) + ".jpg"
	item.PosterSourceURL = "https://thecoverproject.net/view.php?cover_id=5147"
	item.PosterKind, item.PosterStatus = "cover", "ready"
	item.PosterSearchVersion, item.PosterRetryAfter = 1, 60
	return item
}

func TestExplicitWebPosterSearchReplacesExistingImageAndRefreshesLocalCache(t *testing.T) {
	app := descriptionApp(t)
	old := gameDetailsFixture("owner/game")
	old.GameNameZh, old.GameNameOriginal = "过山车大亨 2", "RollerCoaster Tycoon 2"
	if err := app.lib.saveDescriptions([]Description{old}); err != nil {
		t.Fatal(err)
	}
	app.aigc.setToken("mock-web-poster-token")
	posts, gets := 0, 0
	completed := webPosterFixture()
	completed.DescriptionZh = old.DescriptionZh
	app.aigc.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		if r.Method == http.MethodPost {
			posts++
			var payload map[string]any
			if json.NewDecoder(r.Body).Decode(&payload) != nil || len(payload) != 3 || payload["repo"] != old.Repo || payload["gameDetails"] != true || payload["refreshPoster"] != true {
				t.Error("explicit refresh must forward only repository and two options")
			}
			pending := old
			pending.Status, pending.PosterStatus = "pending", "unavailable"
			pending.PosterSearchVersion = 1
			return apiResponse(202, jsonString(DescriptionsResponse{Items: []Description{pending}})), nil
		}
		gets++
		return apiResponse(200, jsonString(DescriptionsResponse{Items: []Description{completed}})), nil
	})
	first := call(app, "POST", "/api/descriptions", `{"repo":"owner/game","refreshPoster":true}`)
	var response DescriptionsResponse
	if first.Code != 202 || json.Unmarshal(first.Body.Bytes(), &response) != nil || len(response.Items) != 1 {
		t.Fatalf("refresh failed: %s", first.Body.String())
	}
	if got := response.Items[0]; got.Status != "pending" || got.PosterURL != old.PosterURL || got.GameNameZh != old.GameNameZh || got.DescriptionZh != old.DescriptionZh {
		t.Fatal("refresh pending erased the existing game text or image")
	}
	if freshDescription(app.lib.snapshot().Descriptions[old.Repo], time.Now()) {
		t.Fatal("fresh old image would hide web search completion")
	}
	second := call(app, "GET", "/api/descriptions?repos=owner/game", "")
	if second.Code != 200 || json.Unmarshal(second.Body.Bytes(), &response) != nil || len(response.Items) != 1 {
		t.Fatalf("refresh poll failed: %s", second.Body.String())
	}
	got := response.Items[0]
	if posts != 1 || gets != 1 || got.PosterURL != completed.PosterURL || got.PosterSourceURL != completed.PosterSourceURL || got.PosterSearchVersion != 1 || got.PosterRetryAfter != 60 {
		t.Fatal("web poster completion or cooldown was lost")
	}
	reloaded, err := newLibrary(app.lib.root)
	if err != nil {
		t.Fatal(err)
	}
	if cached := reloaded.snapshot().Descriptions[old.Repo]; cached.PosterURL != got.PosterURL || cached.PosterSearchVersion != 1 || cached.CheckedAt != got.CheckedAt || cached.PosterRetryAfter != 60 {
		t.Fatal("web poster state did not survive a library reload")
	}
}

func TestWebPosterSearchFailurePreservesImageWithoutReportingSuccess(t *testing.T) {
	item := webPosterFixture()
	item.PosterStatus, item.PosterRetryAfter = "unavailable", 300
	client := newAIGC()
	client.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		return apiResponse(200, jsonString(DescriptionsResponse{Items: []Description{item}})), nil
	})
	result, err := client.get(context.Background(), []string{item.Repo})
	if err != nil || len(result.Items) != 1 {
		t.Fatal("read retained game details", err)
	}
	got := result.Items[0]
	if got.PosterURL != item.PosterURL || got.PosterStatus != "unavailable" || got.PosterRetryAfter != 300 || got.DescriptionZh != item.DescriptionZh {
		t.Fatal("old image disguised the failed search as success")
	}
	lib := testLibrary(t)
	if err := lib.saveDescriptions(result.Items); err != nil {
		t.Fatal(err)
	}
	if cached := lib.snapshot().Descriptions[item.Repo]; cached.PosterStatus != "unavailable" || cached.PosterSearchVersion != 1 || cached.PosterRetryAfter != 300 {
		t.Fatal("poster search failure/cooldown erased on disk")
	}
}

func TestWebPostersOnlyAcceptHashedAIGCCacheAndSafeSourceLinks(t *testing.T) {
	item := webPosterFixture()
	sanitizeGameDetails(&item)
	if item.PosterURL == "" || item.PosterSourceURL == "" {
		t.Fatal("validated AIGC cached poster was rejected")
	}
	for _, raw := range []string{
		"https://aigcnews.cn/api/media/site/game-posters/a.jpg",
		"https://aigcnews.cn/api/media/site/game-posters/" + strings.Repeat("A", 64) + ".jpg",
		"https://aigcnews.cn/api/media/site/game-posters/" + strings.Repeat("a", 64) + ".svg",
		"https://aigcnews.cn/api/media/site/game-posters/%2e%2e/cover.jpg",
		"https://aigcnews.cn/api/media/site/other/" + strings.Repeat("a", 64) + ".jpg",
		strings.Replace(item.PosterURL, "/a1", "/%611", 1),
		item.PosterURL + "?url=https://private.example/image.jpg",
		item.PosterURL + "#fragment",
		strings.Replace(item.PosterURL, "aigcnews.cn", "aigcnews.cn:443", 1),
		strings.Replace(item.PosterURL, "aigcnews.cn", "secret@aigcnews.cn", 1),
		strings.Replace(item.PosterURL, "aigcnews.cn", "aigcnews.cn.evil.test", 1),
		"https://example.com/arbitrary-cover.jpg",
	} {
		if validGamePoster(item.Repo, raw) {
			t.Errorf("unsafe or arbitrary image was accepted: %s", raw)
		}
	}
	for _, source := range []string{
		"https://store.steampowered.com/app/285330/", "https://www.mobygames.com/game/7491/rollercoaster-tycoon-2/covers/", item.PosterSourceURL,
	} {
		if !validPublicPosterSource(source) {
			t.Errorf("public attribution link rejected: %s", source)
		}
	}
	for _, source := range []string{
		"http://example.com/cover", "https://localhost/cover", "https://metadata.google.internal/latest/", "https://host.local/cover", "https://host.lan/cover",
		"https://127.0.0.1/cover", "https://127.1/cover", "https://[::1]/cover", "https://169.254.169.254/latest/meta-data/", "https://10.0.0.1/cover",
		"https://secret@example.com/cover", "https://example.com:443/cover", "https://example.com/a/../cover", "https://example.com/a/%2e%2e/cover",
		"https://example.com/a%0acover", "https://example.com/a%5ccover", "javascript:alert(1)", "data:image/jpeg;base64,AAAA",
	} {
		unsafe := item
		unsafe.PosterSourceURL = source
		sanitizeGameDetails(&unsafe)
		if unsafe.PosterURL != "" || unsafe.PosterSourceURL != "" {
			t.Errorf("cached image with unsafe attribution accepted: %s", source)
		}
	}
	item.PosterSearchVersion = 8
	sanitizeGameDetails(&item)
	if item.PosterSearchVersion != 0 {
		t.Fatal("unknown search protocol accepted")
	}
}

func TestWebPosterRefreshStillRequiresKnownRepositoryAndSession(t *testing.T) {
	app := descriptionApp(t)
	calls := 0
	app.aigc.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		calls++
		return apiResponse(500, "{}"), nil
	})
	for _, body := range []string{
		`{"repo":"unknown/private","refreshPoster":true}`,
		`{"repo":"owner/game","refreshPoster":"true"}`,
		`{"repo":"owner/game","refreshPoster":true,"url":"https://example.com/cover"}`,
	} {
		if response := call(app, "POST", "/api/descriptions", body); response.Code != 400 {
			t.Fatalf("invalid poster request accepted: %d", response.Code)
		}
	}
	if response := call(app, "POST", "/api/descriptions", `{"repo":"owner/game","refreshPoster":true}`); response.Code != 401 {
		t.Fatal("poster search without AIGC credentials was accepted")
	}
	if calls != 0 {
		t.Fatal("invalid poster request reached an upstream provider")
	}
}
