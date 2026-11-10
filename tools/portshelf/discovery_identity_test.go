package main

import (
	"context"
	"net/http"
	"strings"
	"testing"
)

func TestDiscoveryClassifiesTheProjectPurpose(t *testing.T) {
	cases := []struct {
		name, description, readme string
		topics                    []string
		want                      bool
	}{
		{"dungeon", "An open-source traditional roguelike dungeon crawler with randomized levels", "", []string{"game-development"}, true},
		{"space", "A replayable arcade shooter", "", []string{"tutorial", "game"}, true},
		{"warzone", "A realtime strategy game", "", []string{"cheats", "game"}, true},
		{"platform", "Awesome Platformer Game", "", nil, true},
		{"city", "An isometric city builder in JavaScript", "", nil, true},
		{"cards", "命令行斗地主和德州扑克", "", nil, true},
		{"namedgame", "A game developed using the SDL SDK", "", nil, true},
		{"title", "", "## Example Project\n## 1. 🎮 Introduction\nAn open-source puzzle game.\n## Building\nRequires a compiler and library.", nil, true},
		{"special-engine", "Open-source game engine used in the classic Example Quest game", "Requires the original game data.", nil, true},
		{"game-and-engine", "An RTS game and board game engine", "An RTS game and board game engine for its own battles.", nil, true},
		{"framework", "A reusable game engine for making games", "## Games made with it\nA playable first-person shooter game.", []string{"game"}, false},
		{"easy-engine", "An easy to use game engine", "# Engine\nAn easy to use game engine.\n## Examples\nPlay this shooter game.", []string{"game"}, false},
		{"own-engine", "TinyEngine is a modern game engine", "# TinyEngine\nTinyEngine is a modern game engine.\n## Sponsor\nA turn based strategy game.", []string{"game"}, false},
		{"postgres", "PostgreSQL reimplementation", "# Database\nA PostgreSQL reimplementation.\nFighting slow queries.\n## Sponsor\nPlay an exciting game.", nil, false},
		{"directory", "Open-source clones of popular games", "# Game database\nAdd new games or improve information. Games and their references are stored in YAML.", []string{"game"}, false},
		{"widget", "A touch input manager for the game engine", "Play the sample game to test this component.", []string{"game"}, false},
		{"overlay", "DirectX hook and game overlay solution", "Use this with your favorite game.", []string{"game"}, false},
		{"translate", "Real-time translation Android app for games and visual novels", "", []string{"game"}, false},
		{"ai", "AI for a multiplayer strategy game", "", []string{"game"}, false},
		{"renderer-port", "Example Quest source port with an updated Vulkan renderer and modern game engine features", "", nil, true},
		{"research-platform", "A platform for game research with AlphaZero reimplementation", "Play the game to evaluate the research agent.", []string{"game"}, false},
		{"solitaire", "A collection of solitaire/patience games", "# Solitaire\nA playable collection of solitaire games with many card sets.", []string{"game"}, true},
		{"late-about", "Source repository", "# Project\n## Community\nJoin our community for questions and discussion about this project and its future.\n## About the project\nThis is a cooperative platformer game.\n## Build\nUse a compiler.", nil, true},
		{"notice", "An extension of the original island project", "# NOTICE\nThe main branch has experimental features. Use the stable branch for a complete working version.\n# Island Plus\nIsland Plus is an open-source survival game with multiplayer support.", []string{"game"}, true},
		{"fan-demake", "A demake of Card Quest for a handheld", "# Card Quest\n### Disclaimer\nThis project is a non-profit fan demake of Card Quest for the handheld. The game is not affiliated with the original developer.", nil, true},
		{"own-rts-engine", "Real-time strategy game engine", "# Project\nThis repository contains our game engine.\n\nOur project is a real-time strategy game where you control an army.", []string{"game"}, true},
		{"showcase-engine", "A real-time strategy game engine", "# Engine\nA reusable real-time strategy game engine.\n## Engine Showcase\nExample Quest is the flagship game developed with it. Download the free demo.", []string{"game"}, false},
		{"engine-jam", "A cross-platform game engine", "# Engine\nA cross-platform game engine.\n\nVersion one is available! There will be a game jam to celebrate the release.", []string{"game"}, false},
		{"interpreter", "Language implementation", "# Runtime\nAn interpreter for a programming language.\nTry it online here, including a playable game example.", []string{"game"}, false},
		{"dependencies", "Source repository", "# Project\nThe used GUI library is no longer maintained.\n\nOur project is a turn-based space empire computer game.\nWe will replace the library in a later version.", nil, true},
		{"play-title", "A vintage knockoff", "# play play title\nUse the arrow keys to move around.", []string{"game"}, true},
		{"other-title", "Source repository", "# play unrelated game\nTry the third-party game.", nil, false},
		{"reference", "Unofficial Reference Book for the Example Game Engine", "Try making a playable game with this engine.", []string{"game", "example"}, false},
		{"native-recomp", "A console title recompiled to run natively on Windows", "# Recompiled title\nThe console title is recompiled to run natively on Windows with multiplayer support. You need your own copy of the game.", nil, true},
		{"tiles", "A fun game using the Example game engine", "# Tiles\nTile game with bookmarks, replay and extra levels.\n\nThis is a multiplatform implementation in Example game engine.", nil, true},
		{"classic-runtime", "A 2D RPG game engine", "# Runtime\nA from-scratch 2D RPG game engine.\n\nThe runtime was used to rebuild three classic RPGs, all fully playable in the browser.", nil, true},
		{"native-runtime", "A native porting toolkit for Example Quest with static recompilation", "# Native Runtime\nExample Quest as a native Windows program, built from your own copy of the game.\n\nThis repository includes the translator and runtime. An emulator normally translates a game while it runs.", nil, true},
		{"linked-projects", "An experimental voxel game engine", "# Engine\nAn experimental voxel game engine.\n\nSome projects using it:\n* Example Quest - a game inspired by a classic adventure.\n* Another Quest - a multiplayer voxel game.", []string{"game"}, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			repo := searchRepository{FullName: "sample/" + tc.name, Name: tc.name, Description: tc.description, Readme: tc.readme, Topics: tc.topics}
			if got := isGameCandidate(repo, nil); got != tc.want {
				t.Fatalf("game=%v want %v", got, tc.want)
			}
		})
	}
}

func TestDiscoveryHTMLDoesNotConsumeReleaseTablesOrLaterIdentity(t *testing.T) {
	raw := "# Engine\n<p>Supported games:</p>\n| Game | Source code branch | Latest Release |\n| --- | --- | --- |\n| Adventure | main | [>>RELEASES<<](https://github.com/example/game/releases) |\n## About\nA dedicated runtime for the original game."
	text := discoveryReadmeText(raw)
	for _, want := range []string{"Supported games:", "Source code branch", ">>RELEASES<<", "## About", "dedicated runtime"} {
		if !strings.Contains(text, want) {
			t.Fatalf("HTML cleanup removed project evidence %q: %s", want, text)
		}
	}
	if strings.Contains(text, "https://") || strings.Contains(text, "<p>") {
		t.Fatalf("HTML or link target survived: %s", text)
	}
}

func TestDiscoveryDistinguishesPlayableRuntimeFromToolsAndFeatures(t *testing.T) {
	cases := []struct {
		name, description, readme string
		topics                    []string
		want                      bool
	}{
		{"board-battles", "A turn based strategy game and board game engine", "# Board Battles\n## About\nA strategy and board game engine with community maps.\n- Well-developed AI for single-player experiences\n- Active lobby for live multiplayer games", []string{"game"}, true},
		{"desktop-game", "Open-source Android/Desktop remake of a classic strategy title", "", []string{"game"}, true},
		{"desktop-demo", "A web-based desktop recreation", "# Desktop\nA web-based desktop remake.\nIncludes a notepad, paint program and calculator.\n## Try it out\nOpen the browser demo.", nil, false},
		{"fantasy-platform", "A fantasy console for creating retro games", "# Platform\nAn API platform for creating and playing games with a visual editor.", []string{"game"}, false},
		{"game-automation", "一款游戏自动化助手", "# 助手\n帮助玩家自动完成游戏任务。", []string{"game"}, false},
		{"decompilation-helper", "A decompilation workflow", "# Workflow\nYour AI agent decompiles the binary to generate source. Launch the game to compare results.", []string{"game"}, false},
		{"game-launcher", "Source repository", "# Launcher\nA customizable launcher for installing and running games. Launch the game from your library.", []string{"game"}, false},
		{"programming-book", "游戏编程笔记", "# 编程\n阅读此书可以学习如何制作一个冒险游戏。", []string{"game"}, false},
		{"metal-bird", "Bootable bird", "# Bird\nBird is a `clone` of the classic bird title written in assembly, running directly on bare metal.", []string{"game"}, true},
		{"world-runtime", "A title rewritten in Rust", "# Runtime\nVoxel World, rewritten in Rust. Your worlds and the same rules are available in one native program.", []string{"game-engine"}, true},
		{"portable-title", "Easily portable title", "# Runtime\nThe purpose is to make porting Sample Quest easier. To try it you need the original game's data.", []string{"game", "sample-quest"}, true},
		{"clone-command", "Source repository", "# Project\nInstall it with git clone example/repository and then run the demo.", []string{"game"}, false},
		{"mod-rewrite", "A transport network mod", "# Mod\nThis is a transport network mod. Version 4 is a complete rewrite from scratch.", []string{"game"}, false},
		{"wine-wrapper", "A modern compatibility wrapper", "# Wrapper\nA graphical wrapper for a compatibility runtime. It is built on the Game Porting Toolkit to run apps and games.", []string{"game", "game-porting-toolkit"}, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			repo := searchRepository{FullName: "sample/" + tc.name, Name: tc.name, Description: tc.description, Readme: tc.readme, Topics: tc.topics}
			if got := isGameCandidate(repo, nil); got != tc.want {
				t.Fatalf("game=%v want %v", got, tc.want)
			}
		})
	}
}

func TestDiscoveryReadmeSectionsKeepOnlyOwnEvidence(t *testing.T) {
	raw := "# Utility\nA utility.\n## 🎁 Sponsors\nA roguelike shooter.\n### Details\nPlay the game.\n## About\nOur project is a useful library.\n## Examples\n![a platformer game](https://example.test/image.png)\n```\nplayable game\n```\n## Installation\nInstall it."
	text := discoveryReadmeText(raw)
	for _, absent := range []string{"roguelike", "Play the game", "platformer", "playable"} {
		if strings.Contains(text, absent) {
			t.Fatalf("unrelated game evidence survived: %s", text)
		}
	}
	if !strings.Contains(text, "useful library") || !strings.Contains(text, "Install it") {
		t.Fatalf("section removal swallowed own project: %s", text)
	}
}

func TestStarsDiscoveryIncludesArchivedAndForkedGameProjects(t *testing.T) {
	g := newGitHub("")
	calls := 0
	g.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		q := r.URL.Query().Get("q")
		if !strings.Contains(q, "fork:true") || strings.Contains(q, "archived:") || !strings.Contains(q, "stars:10..1000000000") {
			t.Errorf("discovery scope narrowed: %s", q)
		}
		calls++
		return apiResponse(200, `{"total_count":1,"items":[{"full_name":"sample/archive-fork","name":"Archive Fork","description":"A classic source port","stargazers_count":10,"archived":true,"fork":true}]}`), nil
	})
	bounds, _ := parseStarBounds("10", "")
	page, cursor := 1, ""
	for {
		result, err := g.discoverNext(context.Background(), bounds, page, cursor)
		if err != nil || len(result.Items) != 1 {
			t.Fatalf("archived/fork game disappeared: %+v %v", result, err)
		}
		if !result.HasMore {
			break
		}
		page, cursor = result.NextPage, result.NextCursor
	}
	if calls != len(discoveryQueries) {
		t.Fatalf("queries=%d want %d", calls, len(discoveryQueries))
	}
}

func TestKeywordSearchPreservesExplicitScope(t *testing.T) {
	for _, tc := range []struct{ query, want string }{
		{"doom archived:true fork:only", "doom archived:true fork:only"},
		{"doom archived:false fork:false", "doom archived:false fork:false"},
		{"doom ARCHIVED:true fork:true", "doom ARCHIVED:true fork:true"},
		{`"description archived:true phrase" fork:only`, `"description archived:true phrase" fork:only archived:false`},
		{"doom fork:only", "doom fork:only archived:false"},
	} {
		t.Run(tc.query, func(t *testing.T) {
			g := newGitHub("")
			g.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
				if got := r.URL.Query().Get("q"); got != tc.want {
					t.Fatalf("query=%q want %q", got, tc.want)
				}
				return apiResponse(200, `{"items":[]}`), nil
			})
			if _, err := g.search(context.Background(), tc.query, starBounds{}); err != nil {
				t.Fatal(err)
			}
		})
	}
}
