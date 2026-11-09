package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

func testLibrary(t *testing.T) *Library {
	t.Helper()
	library, err := newLibrary(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	return library
}

func TestEmbeddedCatalogAndSnapshots(t *testing.T) {
	games, err := readCatalog()
	if err != nil {
		t.Fatal(err)
	}
	library := testLibrary(t)
	state := library.snapshot()
	if len(games) == 0 {
		t.Fatal("empty built-in catalog")
	}
	for _, game := range games {
		snapshot, ok := state.Snapshots[strings.ToLower(game.Repo)]
		if !ok || snapshot.Stars <= 0 || snapshot.StarsCheckedAt == "" || snapshot.ReleaseCheckedAt == "" || snapshot.Release == nil {
			t.Errorf("built-in project lacks real cached metadata: %s", game.Repo)
			continue
		}
		if _, err := prepareRelease(game.Repo, *snapshot.Release, "amd64"); err != nil {
			t.Errorf("invalid embedded release for %s: %v", game.Repo, err)
		}
	}
}

func TestLibraryPersistenceReplacementAndIndependentSnapshots(t *testing.T) {
	library := testLibrary(t)
	release := testRelease("owner/repo", "v1")
	initial := Snapshot{Stars: 1200, StarsCheckedAt: "2026-11-08T01:00:00Z", ReleaseCheckedAt: "2026-11-08T02:00:00Z", Release: &release}
	stars := 0
	if err := library.add(Game{Repo: "Owner/Repo", Name: "Game", Guide: "javascript:alert(1)", Stars: &stars}, initial); err != nil {
		t.Fatal(err)
	}
	stars = 777
	initial.Release.Assets[0].Name = "caller-mutated"
	view := library.snapshot()
	view.Games[0].Name = "view-mutated"
	*view.Games[0].Stars = 888
	view.Snapshots["owner/repo"].Release.Assets[0].Name = "view-mutated"
	if library.snapshot().Games[0].Name != "Game" || *library.snapshot().Games[0].Stars != 0 || library.snapshot().Snapshots["owner/repo"].Release.Assets[0].Name != "game-windows-x64.zip" {
		t.Fatal("library exposed internal mutable state")
	}
	updated := library.snapshot().Snapshots["owner/repo"]
	updated.Stars = 1300
	updated.StarsCheckedAt = "2026-11-09T01:00:00Z"
	if err := library.updateSnapshot("OWNER/REPO", updated); err != nil {
		t.Fatal(err)
	}
	if err := library.add(Game{Repo: "owner/repo", Name: "duplicate"}, updated); err != nil {
		t.Fatal(err)
	}
	reloaded, err := newLibrary(library.root)
	if err != nil {
		t.Fatal(err)
	}
	state := reloaded.snapshot()
	if len(state.Games) != 1 || state.Games[0].Guide != "https://github.com/Owner/Repo#readme" || state.Snapshots["owner/repo"].Stars != 1300 || state.Snapshots["owner/repo"].ReleaseCheckedAt != "2026-11-08T02:00:00Z" {
		t.Fatalf("persisted replacement lost state: %+v", state.Games)
	}
	if leftovers, _ := filepath.Glob(filepath.Join(library.root, ".library-*")); len(leftovers) != 0 {
		t.Fatalf("temporary cache files remain: %v", leftovers)
	}
}

func TestDiskOverridesSeedAndRejectsCorruptOrUnsafeState(t *testing.T) {
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "library.json"), []byte(`{"games":[],"snapshots":{"OpenRCT2/OpenRCT2":{"stars":42,"starsCheckedAt":"2026-11-09T01:00:00Z"}}}`), 0600); err != nil {
		t.Fatal(err)
	}
	library, err := newLibrary(root)
	if err != nil || library.snapshot().Snapshots["openrct2/openrct2"].Stars != 42 {
		t.Fatalf("disk did not override built-in snapshot: %v", err)
	}
	unsafe := testRelease("owner/repo", "v1")
	unsafe.Assets[0].URL = "https://evil.com/game.exe"
	for _, body := range []string{"{broken", `{"games":[{"repo":"../evil"}]}`, `{"snapshots":{"../evil":{"stars":1}}}`, jsonString(diskState{Snapshots: map[string]Snapshot{"owner/repo": {Release: &unsafe}}})} {
		if err := os.WriteFile(filepath.Join(root, "library.json"), []byte(body), 0600); err != nil {
			t.Fatal(err)
		}
		if _, err := newLibrary(root); err == nil {
			t.Fatalf("unsafe cache accepted: %s", body)
		}
	}
}

func TestSaveFailureDoesNotPublishMemory(t *testing.T) {
	library := testLibrary(t)
	before := len(library.snapshot().Games)
	if err := os.Mkdir(filepath.Join(library.root, "library.json"), 0700); err != nil {
		t.Fatal(err)
	}
	if err := library.add(Game{Repo: "owner/repo", Name: "Game"}, Snapshot{Stars: 10}); err == nil {
		t.Fatal("expected persistence failure")
	}
	if len(library.snapshot().Games) != before {
		t.Fatal("failed disk replacement published memory")
	}
}

func TestConcurrentLibraryWritesDoNotLoseProjects(t *testing.T) {
	library := testLibrary(t)
	const count = 16
	var wg sync.WaitGroup
	for i := 0; i < count; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			repo := fmt.Sprintf("owner/game%d", i)
			if err := library.add(Game{Repo: repo, Name: repo}, Snapshot{Stars: i}); err != nil {
				t.Errorf("add: %v", err)
			}
			if err := library.updateSnapshot(repo, Snapshot{Stars: 100 + i}); err != nil {
				t.Errorf("update: %v", err)
			}
			_ = library.snapshot()
		}(i)
	}
	wg.Wait()
	reloaded, err := newLibrary(library.root)
	if err != nil {
		t.Fatal(err)
	}
	state := reloaded.snapshot()
	if len(state.Games) != count {
		t.Fatalf("lost games: got %d", len(state.Games))
	}
	for i := 0; i < count; i++ {
		if state.Snapshots[fmt.Sprintf("owner/game%d", i)].Stars != 100+i {
			t.Errorf("lost update for game %d", i)
		}
	}
}

func TestSingleInstanceLockAndSessionURL(t *testing.T) {
	root := t.TempDir()
	unlock, err := lockLibrary(root)
	if err != nil {
		t.Fatal(err)
	}
	if other, err := lockLibrary(root); err == nil {
		other()
		t.Error("second instance acquired existing lock")
	}
	unlock()
	unlockAgain, err := lockLibrary(root)
	if err != nil {
		t.Fatal(err)
	}
	unlockAgain()
	token := randomID()
	if !validSessionURL("http://127.0.0.1:12345/#" + token) {
		t.Fatal("valid local session URL rejected")
	}
	for _, raw := range []string{"file:///tmp/evil.exe", "https://evil.com/#" + token, "http://127.0.0.1:12345@evil.com/#" + token, "http://127.0.0.1:12345/path#" + token, "http://127.0.0.1:70000/#" + token, "http://127.0.0.1:12345/?evil#" + token, "http://127.0.0.1:12345/#short"} {
		if validSessionURL(raw) {
			t.Errorf("unsafe stored session URL accepted: %s", raw)
		}
	}
}
