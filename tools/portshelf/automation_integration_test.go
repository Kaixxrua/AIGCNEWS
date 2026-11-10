package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func automationIntegrationApp(t *testing.T, root string) *App {
	t.Helper()
	lib, err := newLibrary(root)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	t.Cleanup(cancel)
	ready := make(chan struct{})
	close(ready)
	a := &App{lib: lib, github: newGitHub(""), aigc: newAIGC(), cloud: newCloudRegistry(), ctx: ctx, cancel: cancel,
		credentialsReady: ready, candidates: map[string]libraryEntry{}}
	a.transfers, err = newTransferManager(a)
	if err != nil {
		t.Fatal(err)
	}
	a.automation, err = newAutomation(a)
	if err != nil {
		t.Fatal(err)
	}
	// OS credential storage/startup is tested separately; this chain exercises
	// real scheduler, queue, worker, file verification, enrichment and exports.
	a.automation.apply = func(AutomationConfig, AutomationConfig) error { return nil }
	return a
}

func startAutomationIntegration(t *testing.T, a *App) func() {
	t.Helper()
	go a.transfers.loop()
	go a.automation.loop()
	cancel := a.cancel
	var once sync.Once
	stop := func() {
		once.Do(func() {
			cancel()
			for _, done := range []<-chan struct{}{a.transfers.done, a.automation.done} {
				select {
				case <-done:
				case <-time.After(3 * time.Second):
					t.Error("integration worker did not stop")
				}
			}
		})
	}
	a.cancel = stop
	t.Cleanup(stop)
	return stop
}

type automationIntegrationSources struct {
	searches, releases, downloads, descriptions atomic.Int32
	downloadStarted                             chan struct{}
	releaseDownload                             <-chan struct{}
	content                                     string
}

func (s *automationIntegrationSources) install(t *testing.T, a *App) {
	t.Helper()
	const repo = "integration/port-game"
	digest := sha256.Sum256([]byte(s.content))
	release := Release{Tag: "v1", URL: "https://github.com/" + repo + "/releases/tag/v1", Assets: []Asset{
		{ID: 11, Name: "game-windows-x64.zip", Size: int64(len(s.content)), URL: "https://github.com/" + repo + "/releases/download/v1/game-windows-x64.zip", Digest: "sha256:" + hex.EncodeToString(digest[:])},
		{ID: 12, Name: "game-macos-arm64.dmg", Size: 10, URL: "https://github.com/" + repo + "/releases/download/v1/game-macos-arm64.dmg"},
		{ID: 13, Name: "game-linux-x86_64.AppImage", Size: 10, URL: "https://github.com/" + repo + "/releases/download/v1/game-linux-x86_64.AppImage"},
	}}
	encodedRelease, _ := json.Marshal(release)
	a.github.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		switch r.URL.Path {
		case "/search/repositories":
			s.searches.Add(1)
			if !strings.Contains(r.URL.Query().Get("q"), "stars:>=10") || r.URL.Query().Get("per_page") != "100" {
				t.Error("scheduler did not use Stars discovery")
			}
			return apiResponse(200, `{"total_count":1,"incomplete_results":false,"items":[{"full_name":"integration/port-game","name":"Port Game","description":"A source port of a classic game","topics":["game","source-port"],"stargazers_count":11,"private":false}]}`), nil
		case "/repos/" + repo + "/releases/latest":
			s.releases.Add(1)
			return apiResponse(200, string(encodedRelease)), nil
		default:
			t.Errorf("unexpected GitHub request: %s", r.URL.Path)
			return nil, errors.New("unexpected GitHub request")
		}
	})
	a.transfers.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		s.downloads.Add(1)
		if r.URL.String() != release.Assets[0].URL || r.Header.Get("Authorization") != "" || r.Header.Get("Cookie") != "" {
			t.Error("download was not the pinned official asset or leaked credentials")
		}
		if s.downloadStarted != nil {
			select {
			case s.downloadStarted <- struct{}{}:
			default:
			}
		}
		if s.releaseDownload != nil {
			select {
			case <-s.releaseDownload:
			case <-r.Context().Done():
				return nil, r.Context().Err()
			}
		}
		response := apiResponse(200, s.content)
		response.ContentLength = int64(len(s.content))
		return response, nil
	})
	a.aigc.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		s.descriptions.Add(1)
		if r.Method != http.MethodGet || r.URL.Query().Get("repos") != repo {
			t.Error("unexpected Chinese description request")
		}
		return apiResponse(200, `{"items":[{"repo":"integration/port-game","status":"ready","descriptionZh":"经典平台动作游戏的开源移植，保留原作关卡与玩法。","source":"aigcnews"}]}`), nil
	})
}

func automationIntegrationDrives(a *App, content string) map[string]*fakeCloudDrive {
	drives := map[string]*fakeCloudDrive{}
	for _, provider := range []string{"baidu", "quark"} {
		drive := &fakeCloudDrive{id: provider, content: content}
		drives[provider] = drive
		a.cloud.accounts[provider] = cloudAccount{drive: drive, account: "test account", session: randomID()}
	}
	return drives
}

func waitAutomationJob(t *testing.T, a *App) TransferJob {
	t.Helper()
	deadline := time.Now().Add(4 * time.Second)
	for time.Now().Before(deadline) {
		jobs, _ := a.transfers.snapshot()
		if len(jobs) > 0 {
			return jobs[0]
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatalf("automatic task was not queued: %+v", a.automation.status())
	return TransferJob{}
}

func waitAutomationMaterial(t *testing.T, a *App) transferMaterial {
	t.Helper()
	deadline := time.Now().Add(4 * time.Second)
	for time.Now().Before(deadline) {
		data, err := os.ReadFile(filepath.Join(a.lib.root, "exports", "最新游戏清单.json"))
		var rows []transferMaterial
		if err == nil && json.Unmarshal(data, &rows) == nil && len(rows) == 1 && rows[0].Status == "done" && rows[0].Baidu.URL != "" && rows[0].Quark.URL != "" && rows[0].LocalDeletedAt != "" {
			return rows[0]
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatalf("automatic final export did not arrive: %+v", a.automation.status())
	return transferMaterial{}
}

func TestAutomationIntegrationDiscoveryToBothDrivesExportAndRestartQuota(t *testing.T) {
	root := t.TempDir()
	a := automationIntegrationApp(t, root)
	sources := &automationIntegrationSources{content: "verified open-source Windows release test bytes"}
	sources.install(t, a)
	drives := automationIntegrationDrives(a, sources.content)
	config := a.automation.configSnapshot()
	config.Enabled, config.Arch, config.DailyLimit = true, "amd64", 1
	config.RememberCredentials, config.StartOnLogin = false, false
	if err := a.automation.configure(config); err != nil {
		t.Fatal(err)
	}
	stop := startAutomationIntegration(t, a)
	job := waitAutomationJob(t, a)
	job = waitTransfer(t, a, job.ID, "done")
	row := waitAutomationMaterial(t, a)
	if !job.Automatic || job.Version != "v1" || job.Asset == nil || job.Asset.ID != 11 || job.ResolvedAt == "" || job.Description == "" || job.Attempts != 1 || len(job.SupportedSystems) != 3 {
		t.Fatalf("pinned/enriched metadata was lost: %+v", job)
	}
	if row.Description != job.Description || len(row.SupportedSystems) != 3 || row.SHA256 != job.SHA256 || row.DownloadPath != "" {
		t.Fatal("export did not preserve final game materials")
	}
	for provider, drive := range drives {
		if uploads, shares := drive.counts(); uploads != 1 || shares != 1 {
			t.Fatalf("%s repeated work: uploads=%d shares=%d", provider, uploads, shares)
		}
	}
	if sources.searches.Load() != 1 || sources.releases.Load() != 1 || sources.downloads.Load() != 1 || sources.descriptions.Load() != 1 {
		t.Fatalf("unexpected source request counts: search=%d release=%d download=%d descriptions=%d", sources.searches.Load(), sources.releases.Load(), sources.downloads.Load(), sources.descriptions.Load())
	}
	if _, err := os.Stat(job.DownloadPath); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("successful two-drive download was not cleaned")
	}
	stop()
	// Recreate real library/queue/scheduler from disk. Today's slot remains used;
	// even an explicit immediate check must not perform another discovery.
	restarted := automationIntegrationApp(t, root)
	sources.install(t, restarted)
	for provider, account := range a.cloud.accounts {
		restarted.cloud.accounts[provider] = account
	}
	if err := restarted.automation.requestRun(); err != nil {
		t.Fatal(err)
	}
	stopRestarted := startAutomationIntegration(t, restarted)
	deadline := time.Now().Add(time.Second)
	for {
		restarted.automation.mu.Lock()
		pending, running, count := restarted.automation.requested, restarted.automation.running, restarted.automation.state.DayCount
		restarted.automation.mu.Unlock()
		if !pending && !running {
			if count != 1 {
				t.Fatalf("restart reset daily quota: %d", count)
			}
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("restart check did not finish")
		}
		time.Sleep(5 * time.Millisecond)
	}
	stopRestarted()
	jobs, _ := restarted.transfers.snapshot()
	if len(jobs) != 1 || jobs[0].ID != job.ID || jobs[0].LocalDeletedAt != row.LocalDeletedAt || sources.searches.Load() != 1 || sources.releases.Load() != 1 || sources.downloads.Load() != 1 {
		t.Fatal("restart duplicated an already handled release or bypassed quota")
	}
}

func TestAutomationIntegrationPausePersistRestartAndResume(t *testing.T) {
	root := t.TempDir()
	a := automationIntegrationApp(t, root)
	releaseDownload := make(chan struct{})
	sources := &automationIntegrationSources{content: "paused and resumed release bytes", downloadStarted: make(chan struct{}, 2), releaseDownload: releaseDownload}
	sources.install(t, a)
	drives := automationIntegrationDrives(a, sources.content)
	config := a.automation.configSnapshot()
	config.Enabled, config.Arch, config.DailyLimit = true, "amd64", 1
	config.RememberCredentials, config.StartOnLogin = false, false
	if err := a.automation.configure(config); err != nil {
		t.Fatal(err)
	}
	stop := startAutomationIntegration(t, a)
	select {
	case <-sources.downloadStarted:
	case <-time.After(3 * time.Second):
		t.Fatal("automatic download did not start")
	}
	job := waitAutomationJob(t, a)
	config.Enabled = false
	if err := a.automation.configure(config); err != nil {
		t.Fatal(err)
	}
	job = waitTransfer(t, a, job.ID, "paused")
	if job.Status == "cancelled" || job.NextRetryAt != "" {
		t.Fatal("pausing became permanent cancellation or retained retry")
	}
	stop()
	restarted := automationIntegrationApp(t, root)
	sources.install(t, restarted)
	for provider, account := range a.cloud.accounts {
		restarted.cloud.accounts[provider] = account
	}
	stopRestarted := startAutomationIntegration(t, restarted)
	if restarted.automation.configSnapshot().Enabled {
		t.Fatal("disabled config was not persisted")
	}
	if err := restarted.automation.requestRun(); err == nil {
		t.Fatal("disabled restart accepted an automatic run")
	}
	time.Sleep(30 * time.Millisecond)
	if sources.downloads.Load() != 1 {
		t.Fatal("disabled restart resumed download")
	}
	close(releaseDownload)
	config.Enabled = true
	if err := restarted.automation.configure(config); err != nil {
		t.Fatal(err)
	}
	job = waitTransfer(t, restarted, job.ID, "done")
	_ = waitAutomationMaterial(t, restarted)
	stopRestarted()
	jobs, _ := restarted.transfers.snapshot()
	if len(jobs) != 1 || job.Attempts != 2 || sources.downloads.Load() != 2 || sources.searches.Load() != 1 || sources.releases.Load() != 1 {
		t.Fatalf("resume duplicated task or re-resolved pinned release: jobs=%d attempts=%d downloads=%d searches=%d releases=%d", len(jobs), job.Attempts, sources.downloads.Load(), sources.searches.Load(), sources.releases.Load())
	}
	for provider, drive := range drives {
		if uploads, shares := drive.counts(); uploads != 1 || shares != 1 {
			t.Fatalf("%s duplicated cloud work after resume", provider)
		}
	}
}

func TestAutomationIntegrationRealPinnedQueueVersionAndCancellationDedup(t *testing.T) {
	m := automationTestManager(t)
	config := automationTestEnable(t, m, 10)
	game := automationTestGames(1)[0]
	if err := m.app.lib.add(game, Snapshot{}); err != nil {
		t.Fatal(err)
	}
	release := automationTestRelease(t, game.Repo, config.Arch)
	added, _, err := m.app.transfers.enqueueAutomatic(game.Repo, config, release)
	if err != nil || len(added) != 1 {
		t.Fatalf("initial enqueue: %v %v", added, err)
	}
	id := added[0]
	first, _ := m.app.transfers.job(id)
	if !first.Automatic || first.ResolvedAt == "" || first.Asset == nil || len(first.SupportedSystems) == 0 {
		t.Fatal("real enqueue lost resolved metadata")
	}
	if added, skipped, err := m.app.transfers.enqueueAutomatic(game.Repo, config, release); err != nil || len(added) != 0 || len(skipped) != 1 {
		t.Fatalf("same-version queued dedup: added=%v skipped=%v error=%v", added, skipped, err)
	}
	if err := m.app.transfers.modify(id, func(job *TransferJob) { job.Status = "failed" }, true); err != nil {
		t.Fatal(err)
	}
	second := automationTestRelease(t, game.Repo, config.Arch)
	second.Tag, second.URL = "v2", "https://github.com/"+game.Repo+"/releases/tag/v2"
	second.Assets[0].ID, second.Assets[0].URL = 2, "https://github.com/"+game.Repo+"/releases/download/v2/game-windows-x64.zip"
	if added, _, err := m.app.transfers.enqueueAutomatic(game.Repo, config, second); err != nil || len(added) != 1 {
		t.Fatalf("failed v1 blocked new v2: added=%v err=%v", added, err)
	}
	if err := m.app.transfers.action(id, "cancel"); err != nil {
		t.Fatal(err)
	}
	if added, skipped, err := m.app.transfers.enqueueAutomatic(game.Repo, config, release); err != nil || len(added) != 0 || len(skipped) != 1 {
		t.Fatalf("cancelled v1 was recreated: added=%v skipped=%v err=%v", added, skipped, err)
	}
	jobs, _ := m.app.transfers.snapshot()
	if len(jobs) != 2 || jobs[0].Version != "v1" || jobs[1].Version != "v2" {
		t.Fatalf("unexpected version history: %+v", jobs)
	}
}

func TestAutomationConfigurationDelegatesDurableCommitToTransaction(t *testing.T) {
	m := automationTestManager(t)
	m.apply = nil
	config := m.configSnapshot()
	config.Enabled, config.RememberCredentials, config.StartOnLogin = true, false, false
	called := false
	m.applyTransaction = func(previous, next AutomationConfig, persist func() error) error {
		called = true
		if previous.Enabled || !next.Enabled || m.configSnapshot().Enabled {
			t.Fatal("configuration published before transaction")
		}
		return persist()
	}
	if err := m.configure(config); err != nil || !called || !m.configSnapshot().Enabled {
		t.Fatalf("transaction was bypassed: called=%v err=%v", called, err)
	}
}
