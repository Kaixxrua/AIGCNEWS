package main

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"
	"testing"
	"time"
)

func gameDetailsFixture(repo string) Description {
	item := readyFixture(repo)
	item.GameNameZh, item.GameNameOriginal = "塞尔达传说：织梦岛", "The Legend of Zelda: Link's Awakening (2019)"
	item.PosterURL = "https://raw.githubusercontent.com/" + repo + "/main/docs/screen.jpg"
	item.PosterSourceURL = "https://github.com/" + repo + "/blob/main/README.md"
	item.PosterKind = "screenshot"
	return item
}

func TestGameDetailsUpgradeOldDescriptionWithoutLosingOfflineCache(t *testing.T) {
	app := descriptionApp(t)
	old := readyFixture("owner/game")
	old.DetailsVersion = 0
	if err := app.lib.saveDescriptions([]Description{old}); err != nil {
		t.Fatal(err)
	}
	calls := 0
	app.aigc.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		calls++
		return apiResponse(503, ""), nil
	})
	first, err := app.readDescriptions(context.Background(), []string{old.Repo})
	if err != nil || calls != 1 || first.Items[0].DescriptionZh != old.DescriptionZh || first.Items[0].Error == "" {
		t.Fatal("old ready description must try metadata upgrade and survive unavailable upstream")
	}
	detailed := gameDetailsFixture(old.Repo)
	app.aigc.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		calls++
		return apiResponse(200, jsonString(DescriptionsResponse{Items: []Description{detailed}})), nil
	})
	second, err := app.readDescriptions(context.Background(), []string{old.Repo})
	if err != nil || !readyGameDetails(second.Items[0]) || second.Items[0].GameNameZh != detailed.GameNameZh || second.Items[0].PosterURL != detailed.PosterURL {
		t.Fatal("metadata upgrade lost title or image")
	}
	restarted, err := newLibrary(app.lib.root)
	if err != nil {
		t.Fatal(err)
	}
	cached := restarted.snapshot().Descriptions["owner/game"]
	if !freshDescription(cached, time.Now()) || cached.GameNameOriginal != detailed.GameNameOriginal || cached.PosterSourceURL != detailed.PosterSourceURL {
		t.Fatal("game identity did not survive a library restart")
	}
	if _, err := app.readDescriptions(context.Background(), []string{old.Repo}); err != nil || calls != 2 {
		t.Fatal("completed game details were not reused")
	}
	// A rolling server upgrade or old response may still have only the brief.
	// It must not erase already saved names/images or extend their freshness.
	old.DescriptionZh = "新的中文简介，同时保留此前核实的游戏名称与图片。"
	if err := app.lib.saveDescriptions([]Description{old}); err != nil {
		t.Fatal(err)
	}
	cached = app.lib.snapshot().Descriptions["owner/game"]
	if cached.GameNameZh != detailed.GameNameZh || cached.PosterURL != detailed.PosterURL || cached.DescriptionZh != old.DescriptionZh {
		t.Fatal("legacy description response erased newer game identity")
	}
}

func TestUnknownGameDetailsAreCachedAsAttemptedWithoutInventingNames(t *testing.T) {
	item := readyFixture("owner/game")
	item.GameNameZh = "Unknown"
	item.GameNameOriginal = strings.Repeat("x", 161)
	item.PosterURL = "https://evil.test/poster.jpg"
	item.PosterSourceURL = "https://github.com/owner/game#readme"
	item.PosterKind = "cover"
	sanitizeGameDetails(&item)
	if item.GameNameZh != "" || item.GameNameOriginal != "" || item.PosterURL != "" || !freshDescription(item, time.Now()) {
		t.Fatal("unknown identity should remain explicitly empty without repeated enrichment")
	}
	item.DetailsVersion = 2
	item.GameNameZh = "未验证协议中的名称"
	sanitizeGameDetails(&item)
	if item.DetailsVersion != 0 || item.GameNameZh != "" || readyGameDetails(item) {
		t.Fatal("unknown metadata protocol accepted")
	}
}

func TestGameDetailsRetainAvailableChineseBriefWhileUpgradeIsIncomplete(t *testing.T) {
	for _, status := range []string{"missing", "pending", "failed"} {
		t.Run(status, func(t *testing.T) {
			client := newAIGC()
			item := Description{Repo: "owner/game", Status: status, Source: "aigcnews", DescriptionZh: "这是一款已有中文简介的经典游戏。"}
			client.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
				return apiResponse(200, jsonString(DescriptionsResponse{Items: []Description{item}})), nil
			})
			result, err := client.get(context.Background(), []string{item.Repo})
			if err != nil || len(result.Items) != 1 {
				t.Fatalf("read available brief: %v", err)
			}
			got := result.Items[0]
			if got.Status != status || got.DescriptionZh != item.DescriptionZh || readyGameDetails(got) || freshDescription(got, time.Now()) {
				t.Fatal("incomplete metadata must retain Chinese text without appearing complete")
			}
			lib := testLibrary(t)
			if err := lib.saveDescriptions(result.Items); err != nil {
				t.Fatal(err)
			}
			if readyDescription(lib.snapshot().Descriptions["owner/game"]) {
				t.Fatal("incomplete result must not become a completed cache record")
			}
			item.DescriptionZh = "Untranslated upstream description"
			result, err = client.get(context.Background(), []string{item.Repo})
			if err != nil || result.Items[0].DescriptionZh != "" {
				t.Fatal("untranslated text was exposed as Chinese")
			}
		})
	}
}

func TestGamePosterOriginsPathsAndProvenanceAreConstrained(t *testing.T) {
	for _, raw := range []string{
		"https://raw.githubusercontent.com/owner/game/main/cover.png",
		"https://raw.githubusercontent.com/OWNER/GAME/release/v1/docs/cover.jpg",
		"https://user-images.githubusercontent.com/1234/abcd-5678.jpg",
		"https://github.com/user-attachments/assets/12345678-abcd-ef01-2345-1234567890ab",
	} {
		if !validGamePoster("owner/game", raw) {
			t.Errorf("upstream image rejected: %s", raw)
		}
	}
	for _, raw := range []string{
		"http://raw.githubusercontent.com/owner/game/main/cover.png",
		"https://raw.githubusercontent.com:443/owner/game/main/cover.png",
		"https://secret@raw.githubusercontent.com/owner/game/main/cover.png",
		"https://raw.githubusercontent.com.evil.test/owner/game/main/cover.png",
		"https://raw.githubusercontent.com/other/game/main/cover.png",
		"https://raw.githubusercontent.com/owner/game/main/../cover.png",
		"https://raw.githubusercontent.com/owner/game/main/%2e%2e/cover.png",
		"https://raw.githubusercontent.com/owner/game/main/cover.svg",
		"https://raw.githubusercontent.com/owner/game/main/cover.jpg?token=secret",
		"https://raw.githubusercontent.com/owner/game/main/cover.jpg?",
		"https://raw.githubusercontent.com/owner/game/main/cover.jpg#fragment",
		"https://raw.githubusercontent.com/owner/game/main\\cover.jpg",
		"https://user-images.githubusercontent.com/cover.jpg",
		"https://github.com/user-attachments/assets/12345678/extra",
		"https://github.com/owner/game/blob/main/cover.png",
		"https://127.0.0.1/cover.png",
		"data:image/png;base64,AA==", "javascript:alert(1)",
	} {
		if validGamePoster("owner/game", raw) {
			t.Errorf("unsafe image accepted: %s", raw)
		}
	}
	for _, source := range []string{
		"https://github.com/other/game#readme", "https://github.com/owner/game.evil/blob/main/README.md",
		"https://github.com:443/owner/game", "https://github.com/owner/game?secret=x",
		"https://github.com/owner/game/../other", "https://evil.test/owner/game",
	} {
		item := gameDetailsFixture("owner/game")
		item.PosterSourceURL = source
		sanitizeGameDetails(&item)
		if item.PosterURL != "" || item.PosterSourceURL != "" {
			t.Errorf("poster with invalid provenance accepted: %s", source)
		}
	}
}

func TestAIGCMetadataResponseAndLocalCacheDoNotExposeUntrustedImages(t *testing.T) {
	client := newAIGC()
	item := gameDetailsFixture("owner/game")
	item.PosterURL = "https://169.254.169.254/latest/meta-data/"
	item.GameNameZh = "恶意名称\n注入"
	client.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		return apiResponse(200, jsonString(DescriptionsResponse{Items: []Description{item}})), nil
	})
	result, err := client.get(context.Background(), []string{item.Repo})
	if err != nil || !readyGameDetails(result.Items[0]) || result.Items[0].PosterURL != "" || result.Items[0].GameNameZh != "" {
		t.Fatal("unsafe metadata passed through the AIGC response")
	}
	lib := testLibrary(t)
	if err := lib.saveDescriptions([]Description{item}); err != nil {
		t.Fatal(err)
	}
	restarted, err := newLibrary(lib.root)
	if err != nil {
		t.Fatal(err)
	}
	if cached := restarted.snapshot().Descriptions["owner/game"]; cached.PosterURL != "" || cached.GameNameZh != "" || cached.DescriptionZh != item.DescriptionZh {
		t.Fatal("unsafe poster survived local persistence")
	}
}

func TestGamePosterCSPDoesNotOpenScriptsOrConnectionsToOtherHosts(t *testing.T) {
	app := descriptionApp(t)
	w := call(app, "GET", "/", "")
	csp := w.Header().Get("Content-Security-Policy")
	for _, host := range []string{"https://raw.githubusercontent.com", "https://user-images.githubusercontent.com", "https://github.com", "https://upload.wikimedia.org", "https://aigcnews.cn"} {
		if !strings.Contains(csp, host) {
			t.Fatalf("poster origin missing from CSP: %s", host)
		}
	}
	for _, directive := range []string{"script-src 'self';", "connect-src 'self';", "frame-ancestors 'none';", "base-uri 'none';"} {
		if !strings.Contains(csp, directive) {
			t.Fatalf("poster change weakened %s", directive)
		}
	}
}

func wikipediaPosterFixture() Description {
	item := readyFixture("owner/game")
	item.GameNameZh = "塞尔达传说 王国之泪"
	item.GameNameOriginal = "The Legend of Zelda: Tears of the Kingdom"
	item.PosterURL = "https://upload.wikimedia.org/wikipedia/en/f/fb/The_Legend_of_Zelda_Tears_of_the_Kingdom_cover.jpg"
	item.PosterSourceURL = "https://en.wikipedia.org/wiki/The_Legend_of_Zelda:_Tears_of_the_Kingdom"
	item.PosterKind, item.PosterStatus = "cover", "ready"
	return item
}

func TestPosterOnlyUpgradePollsThroughFreshV1CacheAndSurvivesRestart(t *testing.T) {
	app := descriptionApp(t)
	completed := wikipediaPosterFixture()
	old := completed
	old.PosterURL, old.PosterSourceURL, old.PosterKind, old.PosterStatus = "", "", "", ""
	if err := app.lib.saveDescriptions([]Description{old}); err != nil {
		t.Fatal(err)
	}
	app.aigc.setToken("mock-poster-token")
	gets, posts := 0, 0
	app.aigc.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		if r.Method == http.MethodPost {
			posts++
			pending := old
			pending.Status = "pending"
			return apiResponse(202, jsonString(DescriptionsResponse{Items: []Description{pending}, PollAfter: 1})), nil
		}
		gets++
		return apiResponse(200, jsonString(DescriptionsResponse{Items: []Description{completed}})), nil
	})
	first := call(app, "POST", "/api/descriptions", `{"repo":"owner/game"}`)
	var response DescriptionsResponse
	if first.Code != 202 || json.Unmarshal(first.Body.Bytes(), &response) != nil || len(response.Items) != 1 {
		t.Fatalf("poster-only request failed: %s", first.Body.String())
	}
	if got := response.Items[0]; got.Status != "pending" || got.DescriptionZh != old.DescriptionZh || got.GameNameZh != old.GameNameZh {
		t.Fatal("poster-only pending response erased the existing title or brief")
	}
	// A restart during the poster lookup must still poll the service, while
	// retaining the existing text for offline use.
	app.cancel()
	reloaded, err := newLibrary(app.lib.root)
	if err != nil {
		t.Fatal(err)
	}
	cached := reloaded.snapshot().Descriptions[old.Repo]
	if cached.DescriptionZh != old.DescriptionZh || cached.GameNameZh != old.GameNameZh || freshDescription(cached, time.Now()) {
		t.Fatal("poster-only lookup left a fresh cache that would hide completion")
	}
	restarted, err := newApp(reloaded)
	if err != nil {
		t.Fatal(err)
	}
	defer restarted.cancel()
	restarted.host = app.host
	stars := 10
	restarted.cacheDiscovery([]Game{{Repo: old.Repo, Name: "Game", Stars: &stars}}, old.CheckedAt)
	restarted.aigc.client.Transport = app.aigc.client.Transport
	second := call(restarted, "GET", "/api/descriptions?repos=owner/game", "")
	if second.Code != 200 || json.Unmarshal(second.Body.Bytes(), &response) != nil || len(response.Items) != 1 {
		t.Fatalf("poster completion poll failed: %s", second.Body.String())
	}
	got := response.Items[0]
	if gets != 1 || posts != 1 || got.PosterURL != completed.PosterURL || got.PosterStatus != "ready" || got.GameNameOriginal != old.GameNameOriginal || got.DescriptionZh != old.DescriptionZh {
		t.Fatal("poster completion was suppressed by the old v1 text cache")
	}
	reloaded, err = newLibrary(app.lib.root)
	if err != nil {
		t.Fatal(err)
	}
	cached = reloaded.snapshot().Descriptions[old.Repo]
	if cached.PosterURL != completed.PosterURL || cached.PosterSourceURL != completed.PosterSourceURL || cached.PosterStatus != "ready" || !freshDescription(cached, time.Now()) {
		t.Fatal("completed poster was not durably cached")
	}
}

func TestWikipediaPosterRequiresExactGameProvenanceAndRasterImage(t *testing.T) {
	for _, path := range []string{
		"/wikipedia/en/f/fb/The_Legend_of_Zelda_Tears_of_the_Kingdom_cover.jpg",
		"/wikipedia/en/thumb/f/fb/Cover.jpg/300px-Cover.jpg",
		"/wikipedia/commons/thumb/a/ab/Cover.png/600px-Cover.png",
		"/wikipedia/commons/a/ab/Cover.webp",
	} {
		item := wikipediaPosterFixture()
		item.PosterURL = "https://upload.wikimedia.org" + path
		sanitizeGameDetails(&item)
		if item.PosterURL == "" || item.PosterStatus != "ready" {
			t.Errorf("verified raster cover rejected: %s", path)
		}
	}
	for _, raw := range []string{
		"https://upload.wikimedia.org/wikipedia/en/f/fb/Cover.svg",
		"https://upload.wikimedia.org/wikipedia/en/thumb/f/fb/Cover.svg/600px-Cover.svg.png",
		"https://upload.wikimedia.org/wikipedia/en/f/fb/Cover.gif",
		"https://upload.wikimedia.org/wikipedia/en/f/fb/Cover.jpg?tracking=1",
		"https://upload.wikimedia.org/wikipedia/en/f/fb/Cover.jpg#fragment",
		"https://upload.wikimedia.org/wikipedia/en/f/fb/%2e%2e/Cover.jpg",
		"https://upload.wikimedia.org/wikipedia/en/f/fb/Cover%2fextra.jpg",
		"https://upload.wikimedia.org/wikipedia/en/f/fb/Cover%5cextra.jpg",
		"https://upload.wikimedia.org/wikipedia/en/x/xx/Cover.jpg",
		"https://upload.wikimedia.org/wikipedia/fr/f/fb/Cover.jpg",
		"https://upload.wikimedia.org.evil.test/wikipedia/en/f/fb/Cover.jpg",
		"https://upload.wikimedia.org:443/wikipedia/en/f/fb/Cover.jpg",
		"https://secret@upload.wikimedia.org/wikipedia/en/f/fb/Cover.jpg",
	} {
		item := wikipediaPosterFixture()
		item.PosterURL = raw
		sanitizeGameDetails(&item)
		if item.PosterURL != "" || item.PosterStatus == "ready" {
			t.Errorf("unsafe cover accepted: %s", raw)
		}
	}
	for _, source := range []string{
		"https://en.wikipedia.org/wiki/The_Legend_of_Zelda",
		"https://en.wikipedia.org/wiki/The_Legend_of_Zelda:_Breath_of_the_Wild",
		"https://en.wikipedia.org/wiki/The_Legend_of_Zelda:_Tears_of_the_Kingdom_(2023)",
		"https://en.wikipedia.org/wiki/The_Legend_of_Zelda:_Tears_of_the_Kingdom?source=1",
		"https://en.wikipedia.org/w/index.php?title=The_Legend_of_Zelda:_Tears_of_the_Kingdom",
		"https://en.wikipedia.org:443/wiki/The_Legend_of_Zelda:_Tears_of_the_Kingdom",
		"https://commons.wikimedia.org/wiki/The_Legend_of_Zelda:_Tears_of_the_Kingdom",
		"https://github.com/owner/game#readme",
	} {
		item := wikipediaPosterFixture()
		item.PosterSourceURL = source
		sanitizeGameDetails(&item)
		if item.PosterURL != "" || item.PosterSourceURL != "" {
			t.Errorf("mismatched article accepted: %s", source)
		}
	}
	if !validWikipediaPosterSource("Link’s Awakening", "https://en.wikipedia.org/wiki/Link%27s_Awakening_(video_game)") {
		t.Fatal("equivalent apostrophe and video game suffix should match")
	}
}

func TestPosterRetryStateSurvivesOfflineCacheWithoutExtendingCooldown(t *testing.T) {
	app := descriptionApp(t)
	item := wikipediaPosterFixture()
	item.PosterURL, item.PosterSourceURL, item.PosterKind = "", "", ""
	item.PosterStatus, item.PosterRetryAfter = "unavailable", 300
	item.CheckedAt = time.Now().UTC().Add(-2 * time.Minute).Format(time.RFC3339)
	if err := app.lib.saveDescriptions([]Description{item}); err != nil {
		t.Fatal(err)
	}
	app.cancel()
	reloaded, err := newLibrary(app.lib.root)
	if err != nil {
		t.Fatal(err)
	}
	restarted, err := newApp(reloaded)
	if err != nil {
		t.Fatal(err)
	}
	defer restarted.cancel()
	restarted.aigc.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		t.Error("fresh cached text should not repeatedly query poster status")
		return apiResponse(503, ""), nil
	})
	result, err := restarted.readDescriptions(context.Background(), []string{item.Repo})
	if err != nil || len(result.Items) != 1 {
		t.Fatal("read cached poster retry state")
	}
	got := result.Items[0]
	if got.PosterStatus != "unavailable" || got.PosterRetryAfter != 300 || got.CheckedAt != item.CheckedAt || got.GameNameZh != item.GameNameZh {
		t.Fatal("cached read erased failure state or restarted the retry timer")
	}
	for _, seconds := range []int{-1, 86401} {
		invalid := item
		invalid.PosterRetryAfter = seconds
		sanitizeGameDetails(&invalid)
		if invalid.PosterRetryAfter != 0 {
			t.Fatal("unbounded poster cooldown accepted")
		}
	}
}
