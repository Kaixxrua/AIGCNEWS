package main

import (
	"context"
	"encoding/base64"
	"fmt"
	"net/http"
	"reflect"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
)

func TestGameDiscoveryUsesEvidenceInsteadOfEnglishWordOrSDKBlacklist(t *testing.T) {
	cases := []struct {
		name, description, readme string
		topics                    []string
		want                      bool
	}{
		{"OpenSC2K", "Open Source remake of Sim City 2000 using rust and godot", "Download a package from Releases. You also need your own copy of the original game files.", nil, true},
		{"OpenGothic", "Reimplementation of Gothic 2 Notr", "", []string{"rpg-engine", "remake"}, true},
		{"doukutsu-rs", "A faithful and open-source remake of Cave Story's engine written in Rust", "", []string{"metroidvania"}, true},
		{"keeperfx", "Open source remake and Fan Expansion of Dungeon Keeper.", "", []string{"rts", "simulation"}, true},
		{"LibreQuake", "A free and open source Quake remake with art under the BSD license", "A free content first-person shooter game. Must be paired with a compatible engine to be played.", nil, true},
		{"microcraft", "A minicraft remake", "A Minicraft remake with some neat extras. Beat the wizard to win the game!", nil, true},
		{"remake", "やり直すんだ。そして、次はうまくやる。", "# 人生重开模拟器", nil, true},
		{"B2recomp", "Unofficial static recompilation of Bayonetta 2 for Windows. No game files, keys or SDK code included.", "", nil, true},
		{"new-linux-game", "A puzzle game available only for Linux", "", nil, true},
		{"new-game", "An adventure game built using the SDL SDK", "", []string{"ADVENTURE-GAME"}, true},
		{"game-remake", "A game remake built with a game development framework", "", []string{"GAME"}, true},
		{"game-and-launcher", "A game recompiled for PC, with online play and a launcher with chat.", "", []string{"launcher", "recompilation"}, true},
		{"btrace", "Production-safe tracing and diagnostics for Java with no restart or recompilation.", "", nil, false},
		{"reportviewercore", "Recompilation of Microsoft.ReportViewer for .NET Core", "", nil, false},
		{"ps2-web-recomp", "PS2 games in the browser: static recompilation with a native runtime", "", nil, false},
		{"ps3recomp", "Static recompilation runtime libraries for PlayStation 3 titles", "", nil, false},
		{"RecompOne", "PSX Static Recompiler and Runtime", "", []string{"recompilation"}, false},
		{"framework", "A reusable game engine for making games", "Create your own games with this general-purpose engine.", []string{"game"}, false},
		{"engine", "A modern 2D Game-Engine and Editor", "An engine to create games.", []string{"game"}, false},
		{"panel", "A free open-source game server management panel", "", []string{"game"}, false},
		{"backend", "Scalable open-source game backend server", "", []string{"game"}, false},
		{"launcher", "A cross-platform game launcher", "", []string{"game"}, false},
		{"database", "Native port of a key-value database for Windows", "An in-memory database and cache server.", nil, false},
		{"awesome-remakes", "Playable game source ports", "", nil, false},
		{"engine-toolkit", "Toolkit for game ports", "", nil, false},
		{"game-tutorial", "A game with walkthrough lessons", "", []string{"game"}, false},
		{"video-remake", "Remake videos using AI", "For video editing. https://example.test/game\n```\nplayable game\n```", nil, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			repo := searchRepository{FullName: "independent/" + tc.name, Name: tc.name, Description: tc.description, Topics: tc.topics, Readme: tc.readme}
			if got := isGameCandidate(repo, nil); got != tc.want {
				t.Fatalf("candidate=%v want=%v", got, tc.want)
			}
		})
	}
}

func readmeResponse(text string) *http.Response {
	return apiResponse(200, jsonString(map[string]any{"encoding": "base64", "content": base64.StdEncoding.EncodeToString([]byte(text)), "size": len(text), "path": "README.md"}))
}

func TestDiscoveryReadsActualLinkedChineseReadmeAndCachesEvidence(t *testing.T) {
	g := newGitHub("")
	var mu sync.Mutex
	paths := []string{}
	g.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		mu.Lock()
		paths = append(paths, r.URL.Path)
		mu.Unlock()
		switch r.URL.Path {
		case "/repos/demo/remake/readme":
			return readmeResponse("# Remake\nEnglish | [简体中文](./README-zh_CN.md)\n[bad](https://evil.test/README-cn.md)"), nil
		case "/repos/demo/remake/contents/README-zh_CN.md":
			return readmeResponse("# 人生重开模拟器"), nil
		default:
			t.Errorf("unexpected request %s", r.URL)
			return apiResponse(404, `{}`), nil
		}
	})
	for i := 0; i < 2; i++ {
		items := []searchRepository{{FullName: "demo/remake", Name: "remake", Description: "やり直すんだ。", Stars: 10}}
		if err := g.resolveGameEvidence(context.Background(), items); err != nil {
			t.Fatal(err)
		}
		games, err := filterSearchGames(items, starBounds{}, true)
		if err != nil || len(games) != 1 {
			t.Fatalf("localized evidence was ignored: %v %+v", err, games)
		}
	}
	if !reflect.DeepEqual(paths, []string{"/repos/demo/remake/readme", "/repos/demo/remake/contents/README-zh_CN.md"}) {
		t.Fatalf("unbounded/repeated evidence requests: %v", paths)
	}
}

func TestDiscoveryReadmeFailureKeepsConfirmedGamesAndRetriesSamePage(t *testing.T) {
	g := newGitHub("")
	readmeCalls := 0
	g.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		if r.URL.Path == "/search/repositories" {
			return apiResponse(200, `{"total_count":2,"items":[{"full_name":"demo/confirmed","name":"confirmed","description":"A source port of a classic game","stargazers_count":20},{"full_name":"demo/remake","name":"remake","description":"A classic remake","stargazers_count":10}]}`), nil
		}
		if r.URL.Path == "/repos/demo/remake/readme" {
			readmeCalls++
			if readmeCalls == 1 {
				return apiResponse(429, `{}`), nil
			}
			return readmeResponse("A remake of a classic game."), nil
		}
		t.Fatalf("unexpected endpoint: %s", r.URL)
		return nil, nil
	})
	bounds, _ := parseStarBounds("10", "")
	first, err := g.discoverNext(context.Background(), bounds, 1, "")
	if err != nil || len(first.Items) != 1 || !first.EvidencePending || first.Warning == "" || first.NextPage != 1 || first.NextCursor != "" || !first.HasMore {
		t.Fatalf("confirmed game lost or unknown page skipped: %+v %v", first, err)
	}
	second, err := g.discoverNext(context.Background(), bounds, first.NextPage, first.NextCursor)
	if err != nil || second.EvidencePending || len(second.Items) != 2 || second.NextPage != 2 || second.NextCursor == "" || readmeCalls != 2 {
		t.Fatalf("retry did not fill evidence: %+v %v", second, err)
	}
}

func TestDiscoverySplitsThousandCandidateLimitAndKeepsTenStarBoundary(t *testing.T) {
	g := newGitHub("")
	calls := 0
	g.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		if r.URL.Path != "/search/repositories" {
			t.Fatalf("discovery requested download eligibility: %s", r.URL)
		}
		calls++
		q := r.URL.Query().Get("q")
		if !strings.HasPrefix(q, automaticGameQuery+" ") {
			return apiResponse(200, `{"items":[],"total_count":0}`), nil
		}
		part := strings.Split(q, " stars:")
		var min, max int
		if len(part) != 2 {
			t.Fatalf("missing bounded query %q", q)
		}
		if _, err := fmt.Sscanf(part[1], "%d..%d", &min, &max); err != nil {
			t.Fatal(err)
		}
		page, _ := strconv.Atoi(r.URL.Query().Get("page"))
		if page < 1 || page > 10 {
			t.Fatalf("illegal upstream page=%d", page)
		}
		items := []searchRepository{}
		for stars := 1409; stars >= 9; stars-- {
			if stars >= min && stars <= max {
				items = append(items, searchRepository{FullName: fmt.Sprintf("ports/game%d", stars), Name: "game", Description: "A source port of a classic game", Stars: stars})
			}
		}
		total := len(items)
		start := (page - 1) * 100
		end := start + 100
		if start > total {
			start = total
		}
		if end > total {
			end = total
		}
		return apiResponse(200, jsonString(map[string]any{"items": items[start:end], "total_count": total})), nil
	})
	bounds, _ := parseStarBounds("10", "")
	seen := map[string]int{}
	page, cursor := 1, ""
	for {
		result, err := g.discoverNext(context.Background(), bounds, page, cursor)
		if err != nil || result.LimitReached || result.EvidencePending {
			t.Fatalf("split failed: %+v %v", result, err)
		}
		for _, game := range result.Items {
			seen[strings.ToLower(game.Repo)] = *game.Stars
		}
		if !result.HasMore {
			break
		}
		page, cursor = result.NextPage, result.NextCursor
		if calls > 40 {
			t.Fatal("discovery made no progress")
		}
	}
	if len(seen) != 1400 || seen["ports/game10"] != 10 || seen["ports/game9"] != 0 || page <= 10 {
		t.Fatalf("discovery truncated or changed threshold: count=%d page=%d", len(seen), page)
	}
}

func TestDiscoverySameStarCapContinuesOtherQueriesAndRejectsTamperedCursor(t *testing.T) {
	g := newGitHub("")
	g.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		return apiResponse(200, `{"items":[],"total_count":1200}`), nil
	})
	bounds, _ := parseStarBounds("10", "10")
	c := discoveryCursor{Version: 1, Query: 0, Page: 10, Next: 10, Bounds: discoveryBounds(bounds), Ranges: []discoveryRange{{Min: 10, Max: 10}}}
	result, err := g.discoverNext(context.Background(), bounds, 10, encodeDiscoveryCursor(c))
	if err != nil || !result.LimitReached || !result.HasMore || result.NextPage != 11 {
		t.Fatalf("same-stars cap stopped all searches: %+v %v", result, err)
	}
	next, err := parseDiscoveryCursor(result.NextCursor, bounds, 11)
	if err != nil || next.Query != 1 || next.Page != 1 {
		t.Fatalf("did not continue next query: %+v %v", next, err)
	}
	invalid := []string{"not-base64", strings.Repeat("a", 4097)}
	for _, change := range []func(*discoveryCursor){func(c *discoveryCursor) { c.Version = 9 }, func(c *discoveryCursor) { c.Query = 99 }, func(c *discoveryCursor) { c.Page = 11 }, func(c *discoveryCursor) { c.Next++ }, func(c *discoveryCursor) { c.Bounds.Min = 0 }, func(c *discoveryCursor) { c.Ranges = []discoveryRange{{Min: 9, Max: 10}} }, func(c *discoveryCursor) { c.Ranges = []discoveryRange{{Min: 10, Max: 10}, {Min: 10, Max: 10}} }} {
		bad := next
		change(&bad)
		invalid = append(invalid, encodeDiscoveryCursor(bad))
	}
	for _, raw := range invalid {
		if _, err := parseDiscoveryCursor(raw, bounds, 11); err == nil {
			t.Errorf("invalid cursor accepted %q", raw)
		}
	}
}

func TestDiscoveryIndependentHoldoutDistinguishesGamesFromDevelopmentComponents(t *testing.T) {
	cases := []struct {
		name, description, readme string
		topics                    []string
		want                      bool
	}{
		{"game2048", "2048 Open Fun Game - multiplatform implementation in Kotlin and KorGE game engine", "2048 game with AI, Bookmarks, Auto Replay, History and other fun features", nil, true},
		{"megaglest-source", "MegaGlest real-time strategy game engine (cross-platform, 3-d)", "MegaGlest is an entertaining free and open source cross-platform 3D real-time strategy game, where you control the armies of one of seven different factions.", []string{"game", "rts"}, true},
		{"quakespasm", "QuakeSpasm -- A modern, cross-platform Quake game engine based on FitzQuake.", "Quakespasm allows loading new games (mods) on the fly. Controller Support: the SDL2 variant supports game controllers.", []string{"sdl2"}, true},
		{"Blitzkrieg", "Blitzkrieg is a 2003 real-time tactics video game. The game was developed using an in-house game engine.", "All libraries from the SDK directory are needed for compilation.", nil, true},
		{"goldeneye-pc-port", "GoldenEye 007 as a native PC game for Windows and Linux. Not an emulator.", "", []string{"decompilation"}, true},
		{"WindowSmash", "Experimental Windows x64 native porting toolkit for Super Smash Bros. Ultimate: static AArch64 recompilation and a runtime.", "Super Smash Bros. Ultimate as a native Windows program, built on your own PC from your own copy of the game. Install and play.\n\nAn emulator solves that by translating the game while you play. This project translates the game once ahead of time.", nil, true},
		{"DInput8HookingExample", "Minimal example how to create a custom DInput8.dll to hook into games", "", []string{"game"}, false},
		{"SunshineGameFinder", "For use with the streaming tool, searches your computer for various common game install paths", "", []string{"game"}, false},
		{"ExaGameBooster", "Game performance optimization service", "", []string{"game"}, false},
		{"rpgwizard", "2D RPG Game creator", "", []string{"game", "rpg-engine"}, false},
		{"EgretGameEngine", "A game client engine in Egret", "", []string{"game"}, false},
		{"zExpression", "脚本与编译器内部的语法引擎内核，也是一种op内核，可以轻松实现自己的脚本引擎", "", []string{"game"}, false},
		{"GamePhanes", "An open-source game coding agent environment and benchmark for Godot.", "", nil, false},
		{"GameEngineBook", "The Complete Game Development with Blender Book. Now Free.", "", nil, false},
		{"metal-cpp", "Metal-cpp is a low-overhead C++ interface for Metal that helps developers add Metal functionality to graphics apps, games, and game engines.", "", []string{"cpp-library"}, false},
		{"distill", "Asset pipeline system for game engines & editor suites.", "", nil, false},
		{"sead", "Decompilation of sead: the standard C++ library for first-party Nintendo games", "", nil, false},
		{"KCP_tunnel", "A KCP Tunnel for Games - TCP & ICMP", "", []string{"game"}, false},
		{"GOAP", "A Python implementation of the Goal Oriented Action Planner.", "", []string{"game"}, false},
		{"controller", "A First-Person Controller for Unity.", "", []string{"game"}, false},
		{"discord-multiplayer-template", "A quickstart Phaser template for creating multiplayer Discord Activities", "", []string{"game"}, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			repo := searchRepository{FullName: "holdout/" + tc.name, Name: tc.name, Description: tc.description, Topics: tc.topics, Readme: tc.readme}
			if got := isGameCandidate(repo, nil); got != tc.want {
				t.Fatalf("holdout=%v want=%v", got, tc.want)
			}
		})
	}
}

func TestAutomaticDiscoveryDefersFailedEvidenceWithoutBlockingLaterPages(t *testing.T) {
	g := newGitHub("")
	g.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		if r.URL.Path == "/search/repositories" {
			return apiResponse(200, `{"total_count":2,"items":[{"full_name":"demo/known","name":"known","description":"A puzzle game","stargazers_count":10},{"full_name":"demo/unclear","name":"unclear","description":"A remake","stargazers_count":15}]}`), nil
		}
		return apiResponse(403, `{}`), nil
	})
	bounds, _ := parseStarBounds("10", "")
	result, err := g.discoverAutomatic(context.Background(), bounds, 1, "")
	if err != nil || len(result.Items) != 1 || !result.EvidencePending || !strings.Contains(result.Warning, "下一轮") || result.NextPage != 2 || result.NextCursor == "" {
		t.Fatalf("one README blocked automatic progress: %+v %v", result, err)
	}
	next, err := parseDiscoveryCursor(result.NextCursor, bounds, 2)
	if err != nil || next.Query != 1 {
		t.Fatalf("automatic progress did not advance: %+v %v", next, err)
	}
}

func TestAutomaticDiscoveryCursorSurvivesRestartWithoutWindowsRelease(t *testing.T) {
	m := automationTestManager(t)
	config := automationTestEnable(t, m, 10)
	bounds := starBounds{min: &config.MinStars, max: config.MaxStars}
	cursor := encodeDiscoveryCursor(discoveryCursor{Version: 1, Query: 1, Page: 3, Next: 42, Bounds: discoveryBounds(bounds), Ranges: []discoveryRange{{Min: 10, Max: 99}}})
	m.discover = func(context.Context, starBounds, int, string) (DiscoveryPage, error) {
		return DiscoveryPage{Items: automationTestGames(1), HasMore: true, NextPage: 42, NextCursor: cursor}, nil
	}
	m.latest = func(context.Context, string, string) (Release, error) {
		return Release{}, &githubError{Status: 404, Message: "No Windows release"}
	}
	m.runOnce()
	if m.state.Page != 42 || m.state.DiscoveryCursor != cursor || len(m.app.lib.snapshot().Games) != 1 || m.state.DayCount != 0 {
		t.Fatalf("discovery tied to download or cursor lost: %+v", m.state)
	}
	restored, err := newAutomation(m.app)
	if err != nil {
		t.Fatal(err)
	}
	restored.maintain = func(AutomationConfig) {}
	restored.discover = func(_ context.Context, got starBounds, page int, raw string) (DiscoveryPage, error) {
		if page != 42 || raw != cursor || got.min == nil || *got.min != 10 {
			t.Fatalf("restart changed bounds/progress: page=%d cursor=%q", page, raw)
		}
		return DiscoveryPage{Items: []Game{}}, nil
	}
	restored.runOnce()
	if restored.state.Page != 1 || restored.state.DiscoveryCursor != "" || restored.state.LastError != "" {
		t.Fatalf("completed cycle did not restart safely: %+v", restored.state)
	}
}

func TestDiscoveryTopicAndIncidentalGameWordsOnlyRequestEvidence(t *testing.T) {
	for _, description := range []string{
		"Godot JVM GDExtension. Support Kotlin, Java and Scala.",
		"A lightweight game server framework implemented with Actor Model",
		"A navigation mesh toolset for .NET, Unity3D, games, servers",
		"DirectX hook and game overlay solution to overlay in your game",
		"Open source Xbox streaming(remote play) client",
		"高性能golang网络库，游戏开发脚手架",
		"Vibe Coding Automation Framework",
		"Rust on PSP. Panic and allocation support. Access PSP system libraries.",
		"A Fabric mod designed to improve the chunk performance of Minecraft.",
		"Repository of cards & artwork",
		"A custom counter that displays your heart rate in game.",
		"Generate APNG Images for Steam Game Covers",
		"Electron Game Updater for Windows",
		"In-game times for locations.",
		"Mod manager for various PC games.",
		"A simple and lightweight game updater/patcher.",
	} {
		repo := searchRepository{FullName: "unseen/project", Name: "project", Description: description, Topics: []string{"game", "card-game"}}
		if metadataGameCandidate(repo, nil) || isGameCandidate(repo, nil) {
			t.Errorf("a domain topic became positive evidence: %q", description)
		}
	}
}

func TestDiscoveryActualReadPathRejectsDevelopmentRolesButKeepsPlayableProjects(t *testing.T) {
	g := newGitHub("")
	readmes := map[string]string{
		"yicaoyimuys/EgretGameEngine": "EgretGameEngine\n===============\nEgret游戏开发使用框架，便于快速开发，以及各项目组间统一开发规范\n\nMVC模块、Net模块、示例游戏Demo。",
		"luis-l/BonsaiBehaviourTree":  "Advanced behavior tree solution with a graphical editor\nVisual editor to build and view behaviour trees.\nSeamless integration with Unity.\nClick on a game object with behaviour tree component.",
		"demo/unknown":                "A project tagged game. The game object component has a position property.",
		"demo/actual":                 "A playable adventure game. You control a character and explore the world.",
		"demo/native":                 "Native Windows program built from your own copy of the game.\nAn emulator solves that by translating the game while you play.",
	}
	var mu sync.Mutex
	readCalls := map[string]int{}
	g.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		if r.URL.Path == "/search/repositories" {
			return apiResponse(200, `{"total_count":5,"items":[{"full_name":"yicaoyimuys/EgretGameEngine","name":"EgretGameEngine","description":"A game client engine in Egret","topics":["game"],"stargazers_count":48},{"full_name":"luis-l/BonsaiBehaviourTree","name":"BonsaiBehaviourTree","description":"A component for Unity","topics":["game"],"stargazers_count":400},{"full_name":"demo/unknown","name":"unknown","description":"A related project","topics":["game"],"stargazers_count":25},{"full_name":"demo/actual","name":"actual","description":"A related project","topics":["game"],"stargazers_count":10},{"full_name":"demo/native","name":"native","description":"An experimental runtime","topics":["game"],"stargazers_count":15}]}`), nil
		}
		key := strings.TrimSuffix(strings.TrimPrefix(r.URL.Path, "/repos/"), "/readme")
		text, ok := readmes[key]
		if r.Method != "GET" || !ok {
			t.Errorf("unexpected request: %s %s", r.Method, r.URL)
			return apiResponse(404, `{}`), nil
		}
		mu.Lock()
		readCalls[key]++
		mu.Unlock()
		return readmeResponse(text), nil
	})
	bounds, _ := parseStarBounds("10", "")
	result, err := g.discoverNext(context.Background(), bounds, 1, "")
	if err != nil || result.EvidencePending || len(result.Items) != 2 || result.Items[0].Repo != "demo/native" || result.Items[1].Repo != "demo/actual" {
		t.Fatalf("README role/positive evidence lost in the actual API path: %+v %v", result, err)
	}
	for _, repo := range []string{"yicaoyimuys/EgretGameEngine", "demo/unknown", "demo/actual", "demo/native"} {
		if readCalls[repo] != 1 {
			t.Fatalf("uncertain topic candidate bypassed README: %s %v", repo, readCalls)
		}
	}
	if readCalls["luis-l/BonsaiBehaviourTree"] != 0 {
		t.Fatalf("explicit component identity should avoid an unnecessary README request: %v", readCalls)
	}
}

func TestDiscoveryReadmeEvidenceIsBoundedAndDoesNotFollowRemoteLinks(t *testing.T) {
	g := newGitHub("")
	calls := 0
	g.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		calls++
		if r.URL.Host != "api.github.com" || r.URL.Path != "/repos/demo/unknown/readme" {
			t.Errorf("untrusted README location was followed: %s", r.URL)
		}
		return readmeResponse("[简体中文](https://evil.test/README-zh.md)\n[local](../README-cn.md)\n" + strings.Repeat("x", discoveryReadmeBytes) + "\nA playable game"), nil
	})
	evidence, err := g.readGameEvidence(context.Background(), "demo/unknown")
	if err != nil || len(evidence) != discoveryReadmeBytes || strings.Contains(evidence, "playable") || calls != 1 {
		t.Fatalf("unbounded or remote evidence: bytes=%d requests=%d err=%v", len(evidence), calls, err)
	}
}

func TestAutomaticLegacyQueryPagesRestartWithoutLosingQueuedWorkOrQuota(t *testing.T) {
	m := automationTestManager(t)
	legacy := m.state
	legacy.Page, legacy.Following = 11, 12
	legacy.Candidates, legacy.Cursor, legacy.DayCount = automationTestGames(2), 1, 3
	if err := m.saveLocked(legacy); err != nil {
		t.Fatal(err)
	}
	restored, err := newAutomation(m.app)
	if err != nil || restored.state.Page != 1 || restored.state.Following != 1 || restored.state.Cursor != 1 || len(restored.state.Candidates) != 2 || restored.state.DayCount != 3 || restored.state.DiscoveryWarning == "" {
		t.Fatalf("old query progress lost queued work or became unreadable: %+v %v", restored, err)
	}
	legacy.Page = 21
	if err := m.saveLocked(legacy); err != nil {
		t.Fatal(err)
	}
	if _, err := newAutomation(m.app); err == nil {
		t.Fatal("a new page without its required cursor was silently reset")
	}
}

func TestDiscoveryReadmeGameInstructionsDoNotOverrideDeclaredToolRole(t *testing.T) {
	cases := []struct {
		name, readme string
		want         bool
	}{
		{"navigation", "Navigation mesh toolset for several engines.\nIts modules can be used in open-world games.", false},
		{"automation", "**Vibe Coding 自动化框架**\n支持 Windows 应用和游戏、安卓模拟器及 ADB 设备。", false},
		{"counter", "A custom counter that displays your heart rate in-game.\nLaunch the game. The game is running.", false},
		{"updater", "Game updater for Windows.\nSupports multiple games in one launcher.\nStart game.exe", false},
		{"manager", "A mod-manager with a virtual file system.\nNo original game files lost.", false},
		{"heading", "# Supported games\n- Sample title\nGame objects have a position.", false},
		{"actual-game", "A playable adventure game.\nUses a graphics library and a framework for input.", true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			repo := searchRepository{FullName: "demo/" + tc.name, Name: tc.name, Description: "A related project", Topics: []string{"game"}, Readme: tc.readme}
			if got := isGameCandidate(repo, nil); got != tc.want {
				t.Fatalf("README role lost: got=%v want=%v", got, tc.want)
			}
		})
	}
}

func TestDiscoveryRateLimitStopsRemainingReadmeRequests(t *testing.T) {
	for _, status := range []int{403, 429} {
		t.Run(strconv.Itoa(status), func(t *testing.T) {
			g := newGitHub("")
			var calls atomic.Int32
			g.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
				calls.Add(1)
				return apiResponse(status, `{"message":"API rate limit exceeded"}`), nil
			})
			items := []searchRepository{{FullName: "demo/confirmed", Name: "confirmed", Description: "A puzzle game", Stars: 10}}
			for i := 0; i < 60; i++ {
				items = append(items, searchRepository{FullName: fmt.Sprintf("demo/unclear%d", i), Name: "unclear", Description: "An unclear remake", Stars: 10})
			}
			err := g.resolveGameEvidence(context.Background(), items)
			if err == nil || calls.Load() < 1 || calls.Load() > 4 || len(g.discoveryReadmes) != 0 {
				t.Fatalf("rate limit drained remaining queue or was cached: calls=%d cached=%d err=%v", calls.Load(), len(g.discoveryReadmes), err)
			}
			games, err := filterSearchGames(items, starBounds{}, true)
			if err != nil || len(games) != 1 || games[0].Repo != "demo/confirmed" {
				t.Fatalf("confirmed game lost to rate limit: %+v %v", games, err)
			}
		})
	}
}

func TestDiscoveryMalformedReadmeResponseCanRecoverWithoutNegativeCache(t *testing.T) {
	for _, invalid := range []string{
		`{"encoding":"utf-8","content":"A playable game","size":15}`,
		`{"encoding":"base64","content":"not valid base64$","size":15}`,
	} {
		g := newGitHub("")
		calls := 0
		g.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
			calls++
			if calls == 1 {
				return apiResponse(200, invalid), nil
			}
			return readmeResponse("A playable game."), nil
		})
		if evidence, err := g.readGameEvidence(context.Background(), "demo/unclear"); err == nil || evidence != "" || len(g.discoveryReadmes) != 0 {
			t.Fatalf("malformed response became cached non-game evidence: %q %v", evidence, err)
		}
		if evidence, err := g.readGameEvidence(context.Background(), "demo/unclear"); err != nil || evidence != "A playable game." || calls != 2 {
			t.Fatalf("healthy response could not recover: %q %v calls=%d", evidence, err, calls)
		}
	}
}
