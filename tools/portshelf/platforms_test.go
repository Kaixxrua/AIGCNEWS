package main

import (
	"reflect"
	"testing"
)

func TestSupportedSystemsRequireDistributableReleaseEvidence(t *testing.T) {
	assets := []Asset{}
	for _, name := range []string{"game-windows-x64.zip", "game-win-arm64.zip", "game-macos-universal.dmg", "game-linux-x86_64.AppImage", "game-android-arm64.apk", "game-ios.ipa", "game-freebsd-amd64.tar.xz",
		"game-windows-x86-symbols.zip", "game-linux-source.tar.gz", "game-windows-x86.exe.sha256", "game-macos-debug.zip", "game-server-windows-x86.zip", "game-win32-sdk.zip", "game-linux-amd64.zip.asc", "unknown.zip"} {
		assets = append(assets, Asset{Name: name, Size: 100})
	}
	want := []string{"Windows x64", "Windows ARM64", "macOS Universal", "Linux x64", "Android ARM64", "iOS", "FreeBSD x64"}
	if got := supportedSystems(assets); !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v want %v", got, want)
	}
	if got := supportedSystems([]Asset{{Name: "unknown.zip", Size: 100, Windows: true, Arch: "amd64"}, {Name: "game-linux-x64.zip", Size: 0}}); len(got) != 0 {
		t.Fatalf("trusted a supplied platform claim/empty attachment: %v", got)
	}
	if systemDescription(nil) != "支持系统待核实" {
		t.Fatal("unknown was presented as supported")
	}
}

func TestPrepareReleaseRecomputesSystemsAndSnapshotClonesThem(t *testing.T) {
	release := Release{Tag: "v1", URL: "https://github.com/game/port/releases/tag/v1", SupportedSystems: []string{"invented OS"}, Assets: []Asset{
		{Name: "game-windows-x64.zip", Size: 100, URL: "https://github.com/game/port/releases/download/v1/game-windows-x64.zip"},
		{Name: "game-linux-x64.AppImage", Size: 100, URL: "https://github.com/game/port/releases/download/v1/game-linux-x64.AppImage"},
	}}
	prepared, err := prepareRelease("game/port", release, "amd64")
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(prepared.SupportedSystems, []string{"Windows x64", "Linux x64"}) {
		t.Fatalf("unverified systems survived: %v", prepared.SupportedSystems)
	}
	source := Snapshot{Release: &prepared}
	copy := cloneSnapshot(source)
	copy.Release.SupportedSystems[0] = "changed"
	if source.Release.SupportedSystems[0] != "Windows x64" {
		t.Fatal("snapshot exposed mutable systems slice")
	}
}
