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
		if query.Get("q") != "topic:source-port archived:false" || query.Get("per_page") != "24" || query.Get("sort") != "stars" {
			t.Errorf("unexpected default query: %s", r.URL.RawQuery)
		}
		items := []map[string]any{{"full_name": "private/repo", "private": true}, {"full_name": "owner/../../evil"}}
		for i := 0; i < 30; i++ {
			items = append(items, map[string]any{"full_name": fmt.Sprintf("owner/game%d", i), "name": fmt.Sprintf("game%d", i), "description": "A port", "stargazers_count": 10 + i})
		}
		return apiResponse(200, jsonString(map[string]any{"items": items})), nil
	})
	games, err := g.search(context.Background(), "")
	if err != nil || len(games) != 24 || games[0].Stars == nil || *games[0].Stars != 10 {
		t.Fatalf("new project search = %v, %v", games, err)
	}
	if _, err := g.search(context.Background(), strings.Repeat("x", 181)); err == nil {
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
