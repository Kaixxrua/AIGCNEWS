package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"testing"
)

type transportFunc func(*http.Request) (*http.Response, error)

func (f transportFunc) RoundTrip(request *http.Request) (*http.Response, error) { return f(request) }

func apiResponse(status int, body string) *http.Response {
	return &http.Response{StatusCode: status, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(body))}
}

func testRelease(repo, tag string) Release {
	return Release{Tag: tag, Name: "Release " + tag, URL: "https://github.com/" + repo + "/releases/tag/" + tag, Published: "2026-11-08T01:00:00Z", Assets: []Asset{{ID: 10, Name: "game-windows-x64.zip", Size: 123, URL: "https://github.com/" + repo + "/releases/download/" + tag + "/game-windows-x64.zip"}}}
}

func jsonString(value any) string {
	b, err := json.Marshal(value)
	if err != nil {
		panic(err)
	}
	return string(b)
}

func TestParseRepoAndOfficialLinks(t *testing.T) {
	for _, input := range []string{"OpenRCT2/OpenRCT2", " https://github.com/OpenRCT2/OpenRCT2/ ", "https://github.com/OpenRCT2/OpenRCT2.git"} {
		repo, err := parseRepo(input)
		if err != nil || repo != "OpenRCT2/OpenRCT2" {
			t.Errorf("parseRepo(%q) = %q, %v", input, repo, err)
		}
	}
	for _, input := range []string{"", "owner/..", "owner/.", "owner/repo/../../evil", "http://github.com/owner/repo", "https://github.com.evil.com/owner/repo", "https://github.com@evil.com/owner/repo", "https://user@github.com/owner/repo", "https://github.com:443/owner/repo", "https://github.com/owner/repo?x=1", "https://github.com/owner/repo?", "https://github.com/owner/repo#readme", "https://github.com/owner/%72epo", "https://github.com//owner/repo", "owner/repo\nother", "owner\\repo", "owner/repo%2f.."} {
		if _, err := parseRepo(input); err == nil {
			t.Errorf("accepted malicious or invalid repo %q", input)
		}
	}
	const prefix = "https://github.com/owner/repo/releases/"
	for _, suffix := range []string{"download/v1/game-win64.zip", "download/release%2Fv1/game-win64.zip"} {
		if !officialReleaseURL(prefix+suffix, "OWNER/REPO", true) {
			t.Errorf("rejected official download %q", suffix)
		}
	}
	for _, input := range []string{"javascript:alert(1)", "http://github.com/owner/repo/releases/download/v1/a.zip", "https://github.com@evil.com/owner/repo/releases/download/v1/a.zip", "https://user@github.com/owner/repo/releases/download/v1/a.zip", "https://github.com.evil.com/owner/repo/releases/download/v1/a.zip", "https://github.com:443/owner/repo/releases/download/v1/a.zip", "https://github.com/other/repo/releases/download/v1/a.zip", prefix + "download/v1/../../evil.zip", prefix + "download/v1/%2e%2e/a.zip", prefix + "download/v1/a.zip?redirect=evil", prefix + "download/v1/a.zip#evil", prefix + "download/v1/%5cevil.zip", prefix + "download/v1/a%00.zip", prefix + "tag/v1"} {
		if officialReleaseURL(input, "owner/repo", true) {
			t.Errorf("accepted unsafe download %q", input)
		}
	}
	for _, input := range []string{prefix + "download/v1/a.zip", "https://evil.com/owner/repo/releases/tag/v1", "https://github.com/owner/other/releases/tag/v1"} {
		if officialReleaseURL(input, "owner/repo", false) {
			t.Errorf("accepted unsafe release page %q", input)
		}
	}
}

func TestReleaseRejectsUnsafeCachedOrRemoteLinks(t *testing.T) {
	release := testRelease("owner/repo", "v1")
	release.Assets[0].URL = "https://evil.com/game.exe"
	if _, err := prepareRelease("owner/repo", release, "amd64"); err == nil {
		t.Fatal("malicious asset URL accepted")
	}
	release = testRelease("owner/repo", "v1")
	release.URL = "javascript:alert(1)"
	if _, err := prepareRelease("owner/repo", release, "amd64"); err == nil {
		t.Fatal("malicious release URL accepted")
	}
}

func TestWindowsAssetClassificationAndArchitecture(t *testing.T) {
	cases := []struct {
		name    string
		windows bool
		arch    string
		kind    string
	}{
		{"game-windows-x64.zip", true, "amd64", "zip"},
		{"game-Win64.exe", true, "amd64", "installer"},
		{"game_win_arm64.7z", true, "arm64", "archive"},
		{"game-windows-aarch64.msi", true, "arm64", "installer"},
		{"game-win32.zip", true, "386", "zip"},
		{"game-windows-x86_64.zip", true, "amd64", "zip"},
		{"game.exe", true, "unknown", "installer"},
		{"game-windows.zip", true, "unknown", "zip"},
		{"game-linux-amd64.zip", false, "amd64", "zip"},
		{"game-darwin-arm64.zip", false, "arm64", "zip"},
		{"game-windows-x64-debug.zip", false, "amd64", "zip"},
		{"game-windows-x64-symbols.zip", false, "amd64", "zip"},
		{"game-windows-x64.zip.sha256", false, "amd64", "file"},
		{"game-win64-server.zip", false, "amd64", "zip"},
		{"dhewm3-mods-1.5.5_win32.zip", false, "386", "zip"},
		{"game-windows-addons.zip", false, "unknown", "zip"},
		{"game-source.zip", false, "unknown", "zip"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			asset := Asset{Name: tc.name, Windows: true, Arch: "malicious", Kind: "malicious", Recommended: true}
			classifyAsset(&asset)
			if asset.Windows != tc.windows || asset.Arch != tc.arch || asset.Kind != tc.kind || asset.Recommended {
				t.Fatalf("classification = %+v", asset)
			}
		})
	}
	release := testRelease("owner/repo", "v1")
	release.Assets = nil
	for _, name := range []string{"game-linux-x64.zip", "game-win32.zip", "game-win64.zip", "game-windows-arm64.zip"} {
		release.Assets = append(release.Assets, Asset{Name: name, URL: "https://github.com/owner/repo/releases/download/v1/" + name, Recommended: true})
	}
	for _, arch := range []string{"amd64", "arm64", "386"} {
		prepared, err := prepareRelease("owner/repo", release, arch)
		if err != nil {
			t.Fatal(err)
		}
		count := 0
		for _, asset := range prepared.Assets {
			if asset.Recommended {
				count++
				if !asset.Windows || asset.Arch != arch {
					t.Fatalf("wrong recommendation for %s: %+v", arch, asset)
				}
			}
		}
		if count != 1 || !prepared.Assets[0].Recommended {
			t.Fatalf("expected one first recommendation: %+v", prepared.Assets)
		}
	}
	if assetScore(Asset{Windows: true, Kind: "zip", Arch: "amd64"}, "arm64") >= 0 {
		t.Fatal("x64 binary recommended as native arm64")
	}
	if assetScore(Asset{Windows: true, Kind: "zip", Arch: "386"}, "amd64") < 0 {
		t.Fatal("x86 fallback should be compatible with Windows x64")
	}
}

func TestGitHubErrorsHeadersAndLimits(t *testing.T) {
	for _, status := range []int{401, 403, 404, 429, 500} {
		t.Run(fmt.Sprint(status), func(t *testing.T) {
			g := newGitHub("test_token")
			g.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
				if r.URL.Host != "api.github.com" || r.URL.Scheme != "https" || r.Header.Get("Authorization") != "Bearer test_token" || r.Header.Get("X-GitHub-Api-Version") == "" {
					t.Errorf("incorrect authenticated GitHub request: %s", r.URL)
				}
				response := apiResponse(status, `{"message":"upstream secret should not surface"}`)
				response.Header.Set("X-RateLimit-Reset", "1893456000")
				return response, nil
			})
			var value any
			err := g.get(context.Background(), "/repos/owner/repo/releases/latest", &value)
			var upstream *githubError
			if !errors.As(err, &upstream) || upstream.Status != status || strings.Contains(err.Error(), "secret") {
				t.Fatalf("incorrect error: %v", err)
			}
			if (status == 403 || status == 429) && !strings.Contains(err.Error(), "Token") {
				t.Fatalf("rate limiting should explain recovery: %v", err)
			}
		})
	}
	for _, body := range []string{"invalid JSON", strings.Repeat(" ", (4<<20)+1)} {
		g := newGitHub("")
		g.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) { return apiResponse(200, body), nil })
		var result any
		if err := g.get(context.Background(), "/repos/owner/repo", &result); err == nil {
			t.Fatal("invalid or oversized response accepted")
		}
	}
	g := newGitHub("")
	for _, raw := range []string{"https://evil.com/", "http://api.github.com/", "https://token@api.github.com/", "https://api.github.com:443/"} {
		u, _ := url.Parse(raw)
		if err := g.client.CheckRedirect(&http.Request{URL: u}, []*http.Request{{}}); err == nil {
			t.Errorf("unsafe GitHub redirect accepted: %s", raw)
		}
	}
}

func TestSearchKeepsNewPublicProjectsAndCapsResults(t *testing.T) {
	g := newGitHub("")
	g.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		query := r.URL.Query()
		if query.Get("q") != `sourceport OR "source port" OR recompilation OR remake OR reimplementation OR decompilation archived:false` || query.Get("per_page") != "100" || query.Get("sort") != "stars" {
			t.Errorf("unexpected default query: %s", r.URL.RawQuery)
		}
		items := []map[string]any{{"full_name": "private/repo", "private": true}, {"full_name": "owner/../../evil"}}
		for i := 0; i < 30; i++ {
			items = append(items, map[string]any{"full_name": fmt.Sprintf("owner/game%d", i), "name": fmt.Sprintf("game%d", i), "description": "A source port of a classic game", "stargazers_count": 10 + i})
		}
		return apiResponse(200, jsonString(map[string]any{"items": items})), nil
	})
	games, err := g.search(context.Background(), "", starBounds{})
	if err != nil || len(games) != 24 || games[0].Stars == nil || *games[0].Stars != 39 {
		t.Fatalf("new project search = %v, %v", games, err)
	}
	if _, err := g.search(context.Background(), strings.Repeat("x", 181), starBounds{}); err == nil {
		t.Fatal("oversized search accepted")
	}
}

func TestRepositoryRejectsPrivateOrRelocatedProject(t *testing.T) {
	for _, body := range []string{`{"full_name":"owner/repo","private":true}`, `{"full_name":"other/repo","private":false}`, `{"full_name":"owner/../repo","private":false}`} {
		g := newGitHub("")
		g.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) { return apiResponse(200, body), nil })
		if _, err := g.repository(context.Background(), "owner/repo"); err == nil {
			t.Fatalf("unsafe repository accepted: %s", body)
		}
	}
}

func TestSearchStarBoundsIncludeEdgesAndExcludePrivateProjects(t *testing.T) {
	cases := []struct {
		name, minimum, maximum string
		want                   []int
	}{
		{"unbounded", "", "", []int{501, 500, 499, 100, 99, 1, 0}},
		{"minimum included", "100", "", []int{501, 500, 499, 100}},
		{"maximum included", "", "100", []int{100, 99, 1, 0}},
		{"both edges included", "100", "500", []int{500, 499, 100}},
		{"one value", "100", "100", []int{100}},
		{"exact zero", "0", "0", []int{0}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			bounds, err := parseStarBounds(tc.minimum, tc.maximum)
			if err != nil {
				t.Fatal(err)
			}
			g := newGitHub("")
			g.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
				items := []map[string]any{{"full_name": "private/repo", "private": true, "stargazers_count": 100}, {"full_name": "owner/../../evil", "stargazers_count": 100}}
				for _, stars := range []int{501, 500, 499, 100, 99, 1, 0} {
					items = append(items, map[string]any{"full_name": fmt.Sprintf("owner/game%d", stars), "name": "A game", "description": "A source port of a classic game", "stargazers_count": stars, "private": false})
				}
				return apiResponse(http.StatusOK, jsonString(map[string]any{"items": items})), nil
			})
			games, err := g.search(context.Background(), "", bounds)
			if err != nil || len(games) != len(tc.want) {
				t.Fatalf("unexpected search results: got %d, want %d, error=%v", len(games), len(tc.want), err)
			}
			for i, game := range games {
				if game.Stars == nil || *game.Stars != tc.want[i] {
					t.Errorf("game %d has stars %v, want %d", i, game.Stars, tc.want[i])
				}
			}
		})
	}
}

func TestAutomaticSearchKeepsGamesAndRejectsCollectionsAndTools(t *testing.T) {
	candidates := []searchRepository{
		{FullName: "CorsixTH/CorsixTH", Name: "CorsixTH", Description: "Open source clone of Theme Hospital", Stars: 4658},
		{FullName: "dhewm/dhewm3", Name: "dhewm3", Description: "A Doom 3 source port", Stars: 2196},
		{FullName: "chocolate-doom/chocolate-doom", Name: "chocolate-doom", Description: "Conservative sourceport of Doom", Stars: 3000},
		{FullName: "NagyD/SDLPoP", Name: "SDLPoP", Description: "An open-source port of Prince of Persia", Stars: 1500},
		{FullName: "Zelda64Recomp/Zelda64Recomp", Name: "Zelda64Recomp", Description: "Static recompilation of Majora's Mask", Stars: 7621},
		{FullName: "example/topic-remake", Name: "topic-remake", Description: "A classic arcade remake", Topics: []string{"game-engine"}, Stars: 15},
		{FullName: "example/description-remake", Name: "description-remake", Description: "A remake of the original game", Stars: 10},
		{FullName: "example/adventure-remake", Name: "adventure-remake", Description: "A modern remake", Topics: []string{"adventure-game"}, Stars: 5},
		{FullName: "example/new-port", Name: "new-port", Description: "A new source port", Stars: 0},
		{FullName: "DHEWM/DHEWM3", Name: "dhewm3", Description: "A Doom 3 source port", Stars: 2196},
		{FullName: "SubmitGame/awesome-decomp-games", Name: "awesome-decomp-games", Description: "Game source ports and recompilation projects", Stars: 100000},
		{FullName: "example/games", Name: "games", Description: "Game source ports", Topics: []string{"awesome-list"}, Stars: 100001},
		{FullName: "example/ports-list", Name: "ports-list", Description: "Game source ports", Stars: 100002},
		{FullName: "example/catalog", Name: "catalog", Description: "A curated collection of game source ports", Stars: 100003},
		{FullName: "example/ports", Name: "ports", Description: "A list of source ports and game remakes", Stars: 100004},
		{FullName: "example/game-sdk", Name: "game-sdk", Description: "SDK for game recompilation", Stars: 100005},
		{FullName: "example/game-toolkit", Name: "game-toolkit", Description: "A toolkit for source ports", Stars: 100006},
		{FullName: "example/n64-emulator", Name: "n64-emulator", Description: "An emulator with recompilation", Stars: 100007},
		{FullName: "example/video-remake", Name: "video-remake", Description: "Remake videos using AI", Topics: []string{"video", "ai"}, Stars: 100008},
		{FullName: "example/network-remake", Name: "network-remake", Description: "A remake of a network client in Rust", Stars: 100009},
		{FullName: "example/luajit-remake", Name: "luajit-remake", Description: "A remake of LuaJIT", Topics: []string{"jit", "compiler"}, Stars: 100010},
		{FullName: "example/private-game", Name: "private-game", Description: "Game source port", Private: true, Stars: 100011},
		{FullName: "owner/../../invalid", Name: "invalid", Description: "Game source port", Stars: 100012},
	}
	g := newGitHub("")
	calls := 0
	g.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		calls++
		if r.URL.Query().Get("per_page") != "100" {
			t.Error("automatic discovery did not request 100 candidates")
		}
		return apiResponse(http.StatusOK, jsonString(map[string]any{"items": candidates})), nil
	})
	games, err := g.search(context.Background(), "", starBounds{})
	want := []string{"zelda64recomp/zelda64recomp", "corsixth/corsixth", "chocolate-doom/chocolate-doom", "dhewm/dhewm3", "nagyd/sdlpop", "example/topic-remake", "example/description-remake", "example/adventure-remake", "example/new-port"}
	if err != nil || calls != 1 || len(games) != len(want) {
		t.Fatalf("automatic discovery: error=%v calls=%d games=%+v", err, calls, games)
	}
	for i, game := range games {
		if strings.ToLower(game.Repo) != want[i] {
			t.Errorf("result %d = %s, want %s", i, game.Repo, want[i])
		}
		if game.Stars == nil || i > 0 && *games[i-1].Stars < *game.Stars {
			t.Errorf("results not sorted by real GitHub stars: %+v", game)
		}
	}
	if *games[len(games)-1].Stars != 0 || !strings.Contains(jsonString(games[len(games)-1]), `"stars":0`) {
		t.Fatal("zero-star game lost its known star count")
	}
}

func TestAutomaticSearchFiltersBeforeLimitAndUsesRealStarsForDuplicates(t *testing.T) {
	candidates := []searchRepository{}
	for i := 0; i < 30; i++ {
		candidates = append(candidates, searchRepository{FullName: fmt.Sprintf("example/awesome%d", i), Name: "awesome-games", Description: "A game source port list", Stars: 100000 + i})
	}
	for i := 0; i < 30; i++ {
		candidates = append(candidates, searchRepository{FullName: fmt.Sprintf("example/game%d", i), Name: fmt.Sprintf("game%d", i), Description: "A game source port", Stars: i})
	}
	candidates = append(candidates, searchRepository{FullName: "EXAMPLE/GAME0", Name: "Game zero", Description: "A game source port", Stars: 100})
	g := newGitHub("")
	g.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		return apiResponse(http.StatusOK, jsonString(map[string]any{"items": candidates})), nil
	})
	games, err := g.search(context.Background(), "", starBounds{})
	if err != nil || len(games) != 24 || strings.ToLower(games[0].Repo) != "example/game0" || *games[0].Stars != 100 || *games[1].Stars != 29 || *games[23].Stars != 7 {
		t.Fatalf("filter/sort/deduplicate/limit failed: error=%v games=%+v", err, games)
	}
	seen := map[string]bool{}
	for _, game := range games {
		key := strings.ToLower(game.Repo)
		if seen[key] {
			t.Errorf("duplicate repository: %s", key)
		}
		seen[key] = true
	}
}

func TestLegacyKeywordSearchRetainsUnclassifiedCandidates(t *testing.T) {
	g := newGitHub("")
	g.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		if r.URL.Query().Get("q") != "remake archived:false" || r.URL.Query().Get("per_page") != "24" {
			t.Errorf("legacy keyword query changed: %s", r.URL)
		}
		return apiResponse(http.StatusOK, `{"items":[{"full_name":"example/network-remake","name":"network-remake","description":"A network client remake","stargazers_count":10}]}`), nil
	})
	games, err := g.search(context.Background(), "remake", starBounds{})
	if err != nil || len(games) != 1 || games[0].Repo != "example/network-remake" {
		t.Fatalf("explicit keyword results were automatically filtered: %v, %+v", err, games)
	}
}

func discoveryCandidates(start, count int) []searchRepository {
	items := make([]searchRepository, 0, count)
	for i := start; i < start+count; i++ {
		items = append(items, searchRepository{FullName: fmt.Sprintf("ports/game%d", i), Name: fmt.Sprintf("Game %d", i), Description: "A source port of a classic game", Stars: 1000 - i})
	}
	return items
}

func TestDiscoverLoadsTwoFullPagesWithoutTwentyFourLimit(t *testing.T) {
	g := newGitHub("")
	calls := 0
	g.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		calls++
		params := r.URL.Query()
		if r.URL.Path != "/search/repositories" || params.Get("per_page") != "100" || params.Get("sort") != "stars" || params.Get("order") != "desc" || params.Get("q") != automaticGameQuery+" archived:false stars:0..1000" {
			t.Errorf("invalid paginated GitHub query: %s", r.URL)
		}
		items := discoveryCandidates(0, 100)
		if params.Get("page") == "2" {
			items = discoveryCandidates(100, 50)
		} else if params.Get("page") != "1" {
			t.Errorf("invalid page: %s", params.Get("page"))
		}
		return apiResponse(200, jsonString(map[string]any{"items": items, "total_count": 150, "incomplete_results": false})), nil
	})
	bounds, _ := parseStarBounds("0", "1000")
	first, err := g.discoverNext(context.Background(), bounds, 1, "")
	if err != nil || len(first.Items) != 100 || first.Page != 1 || first.NextPage != 2 || !first.HasMore || first.TotalCandidates != 150 || first.Incomplete || first.LimitReached {
		t.Fatalf("first page was truncated or malformed: %+v, %v", first, err)
	}
	second, err := g.discoverNext(context.Background(), bounds, first.NextPage, first.NextCursor)
	if err != nil || len(second.Items) != 50 || second.Page != 2 || second.NextPage != 3 || !second.HasMore || second.NextCursor == "" || second.LimitReached || calls != 2 {
		t.Fatalf("second page incorrect: %+v, %v, calls=%d", second, err, calls)
	}
}

func TestDiscoverPaginationUsesCandidatesIncludingEmptyFilteredPages(t *testing.T) {
	cases := []struct {
		name                      string
		page, total               int
		incomplete, emptyFiltered bool
		wantMore, wantLimit       bool
	}{
		{"filtered empty can continue", 1, 200, false, true, true, false},
		{"no candidates continues other query", 1, 0, false, true, true, false},
		{"incomplete upstream", 1, 250, true, false, true, false},
		{"before thousand", 9, 1500, false, false, true, false},
		{"same-star thousand cap continues other query", 10, 1500, false, false, true, true},
		{"exact thousand advances query", 10, 1000, false, false, true, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			g := newGitHub("")
			g.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
				items := discoveryCandidates(0, 100)
				if tc.emptyFiltered {
					items = []searchRepository{{FullName: "example/awesome-games", Name: "awesome-games", Description: "A source port list", Stars: 999}}
				}
				return apiResponse(200, jsonString(map[string]any{"items": items, "total_count": tc.total, "incomplete_results": tc.incomplete})), nil
			})
			bounds, _ := parseStarBounds("10", "10")
			result, err := g.discoverNext(context.Background(), bounds, tc.page, "")
			if err != nil || result.HasMore != tc.wantMore || result.LimitReached != tc.wantLimit || result.Incomplete != tc.incomplete || result.TotalCandidates != tc.total {
				t.Fatalf("pagination metadata: %+v, %v", result, err)
			}
			if result.Items == nil || tc.emptyFiltered && len(result.Items) != 0 || tc.wantMore && result.NextPage != tc.page+1 || !tc.wantMore && result.NextPage != 0 {
				t.Fatalf("empty page or nextPage contract incorrect: %+v", result)
			}
		})
	}
}
