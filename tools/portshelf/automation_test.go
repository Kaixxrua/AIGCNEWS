package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func automationTestManager(t *testing.T) *automationManager {
	t.Helper()
	ctx, cancel := context.WithCancel(context.Background())
	t.Cleanup(cancel)
	a := &App{lib: testLibrary(t), github: newGitHub(""), aigc: newAIGC(), cloud: newCloudRegistry(), ctx: ctx, cancel: cancel, candidates: map[string]libraryEntry{}}
	var err error
	a.transfers, err = newTransferManager(a)
	if err != nil {
		t.Fatal(err)
	}
	m, err := newAutomation(a)
	if err != nil {
		t.Fatal(err)
	}
	a.automation = m
	m.apply = func(AutomationConfig, AutomationConfig) error { return nil }
	m.maintain = func(AutomationConfig) {}
	m.discover = func(context.Context, starBounds, int) (DiscoveryPage, error) {
		t.Error("unexpected discovery")
		return DiscoveryPage{}, errors.New("unexpected discovery")
	}
	m.latest = func(context.Context, string, string) (Release, error) {
		t.Error("unexpected release request")
		return Release{}, errors.New("unexpected release")
	}
	m.enqueue = func(string, AutomationConfig, Release) ([]string, []string, error) {
		t.Error("unexpected enqueue")
		return nil, nil, errors.New("unexpected enqueue")
	}
	return m
}

func automationTestEnable(t *testing.T, m *automationManager, limit int) AutomationConfig {
	t.Helper()
	config := m.configSnapshot()
	config.Enabled, config.RememberCredentials, config.StartOnLogin = true, false, false
	config.Providers, config.DailyLimit, config.Arch = []string{"quark"}, limit, "amd64"
	if err := m.configure(config); err != nil {
		t.Fatal(err)
	}
	return config
}

func automationTestGames(count int) []Game {
	games := make([]Game, count)
	for i := range games {
		stars := 1000 - i
		repo := fmt.Sprintf("portshelf/game%d", i)
		games[i] = Game{Repo: repo, Name: "Game", Stars: &stars, Description: "A source port of a game", Guide: "https://github.com/" + repo + "#readme"}
	}
	return games
}

func automationTestRelease(t *testing.T, repo, arch string) Release {
	t.Helper()
	release, err := prepareRelease(repo, Release{Tag: "v1", URL: "https://github.com/" + repo + "/releases/tag/v1", Assets: []Asset{{ID: 1, Name: "game-windows-x64.zip", Size: 100, URL: "https://github.com/" + repo + "/releases/download/v1/game-windows-x64.zip"}}}, arch)
	if err != nil {
		t.Fatal(err)
	}
	return release
}

func automationTestJob(repo string, config AutomationConfig, release Release) TransferJob {
	return TransferJob{ID: randomID(), Repo: repo, Name: "Game", Version: release.Tag, Arch: config.Arch, Providers: append([]string{}, config.Providers...),
		ShareOptions: ShareOptions{Days: config.ShareDays, Code: config.ShareCode, Private: config.PrivateShare}, Enrich: config.Enrich, Status: "queued", Stage: "download",
		Asset: automationAsset(release, config.Arch), SupportedSystems: append([]string{}, release.SupportedSystems...), Outputs: map[string]TransferOutput{}, CreatedAt: time.Now().UTC().Format(time.RFC3339)}
}

func TestAutomationDailyQuotaAndCandidateCursorSurviveRestart(t *testing.T) {
	m := automationTestManager(t)
	now := time.Date(2026, 11, 10, 9, 0, 0, 0, time.UTC)
	m.now = func() time.Time { return now }
	automationTestEnable(t, m, 2)
	var discoverCalls, releaseCalls int
	m.discover = func(_ context.Context, bounds starBounds, page int) (DiscoveryPage, error) {
		discoverCalls++
		if page != 1 || bounds.min == nil || *bounds.min != 10 {
			t.Fatalf("wrong Stars/page: %+v %d", bounds, page)
		}
		return DiscoveryPage{Items: automationTestGames(3), HasMore: true, NextPage: 2}, nil
	}
	m.latest = func(_ context.Context, repo, arch string) (Release, error) {
		releaseCalls++
		return automationTestRelease(t, repo, arch), nil
	}
	enqueue := func(repo string, config AutomationConfig, release Release) ([]string, []string, error) {
		data, err := os.ReadFile(filepath.Join(m.app.lib.root, "automation.json"))
		var persisted automationState
		if err != nil || json.Unmarshal(data, &persisted) != nil || persisted.DayCount < 1 {
			t.Fatal("daily quota was not durably reserved before enqueue")
		}
		job := automationTestJob(repo, config, release)
		m.app.transfers.mu.Lock()
		err = m.app.transfers.saveLocked(append(m.app.transfers.jobs, job))
		m.app.transfers.mu.Unlock()
		return []string{job.ID}, nil, err
	}
	m.enqueue = enqueue
	m.runOnce()
	if discoverCalls != 1 || releaseCalls != 2 || m.state.Cursor != 2 || m.state.DayCount != 2 || m.state.Page != 1 || len(m.app.lib.snapshot().Games) != 3 {
		t.Fatalf("wrong first round: state=%+v discovery=%d releases=%d", m.state, discoverCalls, releaseCalls)
	}
	restored, err := newAutomation(m.app)
	if err != nil {
		t.Fatal(err)
	}
	restored.now, restored.latest, restored.enqueue = m.now, m.latest, enqueue
	restored.discover = func(context.Context, starBounds, int) (DiscoveryPage, error) {
		t.Fatal("unprocessed page was lost")
		return DiscoveryPage{}, nil
	}
	restored.runOnce()
	if releaseCalls != 2 || restored.state.DayCount != 2 || restored.state.Cursor != 2 {
		t.Fatal("restart bypassed today's quota or discarded cursor")
	}
	now = now.Add(24 * time.Hour)
	restored.runOnce()
	if releaseCalls != 3 || restored.state.DayCount != 1 || restored.state.Page != 2 || len(restored.state.Candidates) != 0 || restored.state.LastError != "" {
		t.Fatalf("next day did not resume remaining candidate: %+v", restored.state)
	}
}

func TestAutomationBoundsReleaseRequestsAndSkipsUnsupported(t *testing.T) {
	m := automationTestManager(t)
	automationTestEnable(t, m, 100)
	m.discover = func(context.Context, starBounds, int) (DiscoveryPage, error) {
		return DiscoveryPage{Items: automationTestGames(100)}, nil
	}
	requests := 0
	m.latest = func(_ context.Context, repo, arch string) (Release, error) {
		requests++
		if requests%2 == 0 {
			return Release{}, &githubError{Status: 404, Message: "no formal release"}
		}
		release, err := prepareRelease(repo, Release{Tag: "v1", URL: "https://github.com/" + repo + "/releases/tag/v1", Assets: []Asset{{ID: 1, Name: "linux-x64.tar.gz", Size: 20, URL: "https://github.com/" + repo + "/releases/download/v1/linux-x64.tar.gz"}}}, arch)
		return release, err
	}
	m.runOnce()
	if requests != automationReleaseBudget || m.state.Cursor != automationReleaseBudget || m.state.Unsupported != automationReleaseBudget || m.state.DayCount != 0 || m.state.LastError != "" {
		t.Fatalf("release budget/unsupported handling failed: requests=%d state=%+v", requests, m.state)
	}
	// The same successfully checked unsupported result is cached across rounds.
	game := automationTestGames(1)[0]
	_, unsupported, fetched, err := m.release(context.Background(), game, "amd64")
	if err != nil || !unsupported || fetched || requests != automationReleaseBudget {
		t.Fatalf("unsupported cache missed: unsupported=%v fetched=%v err=%v", unsupported, fetched, err)
	}
}

func TestAutomationTransientFailureAndEnqueueRefund(t *testing.T) {
	m := automationTestManager(t)
	config := automationTestEnable(t, m, 1)
	discoveryCalls, releaseCalls := 0, 0
	m.discover = func(context.Context, starBounds, int) (DiscoveryPage, error) {
		discoveryCalls++
		return DiscoveryPage{Items: automationTestGames(1)}, nil
	}
	m.latest = func(_ context.Context, repo, arch string) (Release, error) {
		releaseCalls++
		if releaseCalls == 1 {
			return Release{}, &githubError{Status: 429, Message: "GitHub temporarily rate limited"}
		}
		return automationTestRelease(t, repo, arch), nil
	}
	m.runOnce()
	if m.state.Cursor != 0 || m.state.DayCount != 0 || !strings.Contains(m.state.LastError, "rate limited") {
		t.Fatalf("lost failed candidate: %+v", m.state)
	}
	next, _ := time.Parse(time.RFC3339, m.state.NextRun)
	if time.Until(next) < 59*time.Minute {
		t.Fatal("rate limit did not back off")
	}
	m.enqueue = func(string, AutomationConfig, Release) ([]string, []string, error) {
		return nil, nil, errors.New("temporary queue write failure")
	}
	m.runOnce()
	if discoveryCalls != 1 || releaseCalls != 2 || m.state.DayCount != 0 || m.state.Cursor != 0 || !strings.Contains(m.state.LastError, "queue write") {
		t.Fatalf("queue failure lost quota or cursor: %+v", m.state)
	}
	// A crash after enqueue, before cursor advancement, must not create a second job.
	release := automationTestRelease(t, "portshelf/game0", "amd64")
	job := automationTestJob("portshelf/game0", config, release)
	m.app.transfers.mu.Lock()
	m.app.transfers.jobs = []TransferJob{job}
	m.app.transfers.mu.Unlock()
	m.enqueue = func(string, AutomationConfig, Release) ([]string, []string, error) {
		t.Fatal("created duplicate recovered task")
		return nil, nil, nil
	}
	m.runOnce()
	if m.state.LastError != "" || m.state.DayCount != 0 || len(m.state.Candidates) != 0 || releaseCalls != 2 {
		t.Fatalf("recovery was not idempotent: %+v", m.state)
	}
}

func TestAutomationHistorySuppressesCancelledFailedAndFinishedAssets(t *testing.T) {
	m := automationTestManager(t)
	config := automationTestEnable(t, m, 10)
	repo := "portshelf/game0"
	release := automationTestRelease(t, repo, "amd64")
	base := automationTestJob(repo, config, release)
	for _, status := range []string{"queued", "running", "cancelled", "failed", "partial", "paused", "waiting_auth"} {
		job := cloneTransfer(base)
		job.Status = status
		m.app.transfers.jobs = []TransferJob{job}
		if m.needsTransfer(repo, config, release) {
			t.Errorf("recreated same-version %s task", status)
		}
	}
	completed := cloneTransfer(base)
	completed.Status = "done"
	completed.Outputs["quark"] = TransferOutput{Status: "done", Share: CloudShare{URL: "https://pan.quark.cn/s/fid", Code: "1234"}}
	m.app.transfers.jobs = []TransferJob{completed}
	if m.needsTransfer(strings.ToUpper(repo), config, release) {
		t.Fatal("recreated a valid completed share")
	}
	output := completed.Outputs["quark"]
	output.Share.ExpiresAt = time.Now().Add(-time.Hour).UTC().Format(time.RFC3339)
	completed.Outputs["quark"] = output
	m.app.transfers.jobs = []TransferJob{completed}
	if !m.needsTransfer(repo, config, release) {
		t.Fatal("expired share was never renewed")
	}
	blocked := cloneTransfer(base)
	blocked.Status = "cancelled"
	m.app.transfers.jobs = []TransferJob{completed, blocked}
	if m.needsTransfer(repo, config, release) {
		t.Fatal("expired old share bypassed later cancellation")
	}
	newRelease := release
	newRelease.Tag = "v2"
	if !m.needsTransfer(repo, config, newRelease) {
		t.Fatal("new version was suppressed")
	}
	newRelease = release
	newRelease.Assets = append([]Asset{}, release.Assets...)
	newRelease.Assets[0].ID++
	if !m.needsTransfer(repo, config, newRelease) {
		t.Fatal("replaced upstream asset was suppressed")
	}
	changedProfile := cloneAutomationConfig(config)
	changedProfile.ShareDays = 7
	if !m.needsTransfer(repo, changedProfile, release) {
		t.Fatal("changed cloud sharing profile was suppressed")
	}
}

func TestAutomationConfigRollbackAndResetPreserveDailyQuota(t *testing.T) {
	m := automationTestManager(t)
	if m.configSnapshot().MinStars != 10 || m.configSnapshot().Enabled {
		t.Fatal("wrong safe defaults")
	}
	original := m.configSnapshot()
	var applied []AutomationConfig
	m.apply = func(_ AutomationConfig, next AutomationConfig) error {
		applied = append(applied, cloneAutomationConfig(next))
		return nil
	}
	if err := os.Mkdir(filepath.Join(m.app.lib.root, "automation.json"), 0700); err != nil {
		t.Fatal(err)
	}
	next := cloneAutomationConfig(original)
	next.Enabled = true
	if err := m.configure(next); err == nil || len(applied) != 2 || !reflect.DeepEqual(m.configSnapshot(), original) || !reflect.DeepEqual(applied[1], original) {
		t.Fatalf("failed persistence changed config or omitted system rollback: err=%v apply=%v", err, applied)
	}
	if err := os.Remove(filepath.Join(m.app.lib.root, "automation.json")); err != nil {
		t.Fatal(err)
	}
	config := automationTestEnable(t, m, 10)
	m.mu.Lock()
	nextState := m.state
	nextState.Day, nextState.DayCount, nextState.Page = time.Now().Format("2006-01-02"), 3, 5
	nextState.Candidates, nextState.Cursor = automationTestGames(3), 1
	if err := m.saveLocked(nextState); err != nil {
		t.Fatal(err)
	}
	m.mu.Unlock()
	config.MinStars = 20
	max := 100
	config.MaxStars = &max
	if err := m.configure(config); err != nil {
		t.Fatal(err)
	}
	config.Providers[0], *config.MaxStars = "changed", 2
	if m.state.Page != 1 || len(m.state.Candidates) != 0 || m.state.DayCount != 3 || m.configSnapshot().Providers[0] != "quark" || *m.configSnapshot().MaxStars != 100 {
		t.Fatalf("selection reset lost quota or shared mutable fields: %+v", m.state)
	}
	copy := m.configSnapshot()
	copy.Providers[0], *copy.MaxStars = "mutated", 1
	if m.configSnapshot().Providers[0] != "quark" || *m.configSnapshot().MaxStars != 100 {
		t.Fatal("snapshot aliases live config")
	}
}

func TestAutomationWaitsForCredentialsAndDisabledCannotRun(t *testing.T) {
	m := automationTestManager(t)
	ready := make(chan struct{})
	m.app.credentialsReady = ready
	var scans atomic.Int32
	started := make(chan struct{}, 1)
	m.discover = func(context.Context, starBounds, int) (DiscoveryPage, error) {
		scans.Add(1)
		started <- struct{}{}
		return DiscoveryPage{}, nil
	}
	automationTestEnable(t, m, 1)
	go m.loop()
	select {
	case <-started:
		t.Fatal("scanned before credential restoration finished")
	case <-time.After(30 * time.Millisecond):
	}
	close(ready)
	select {
	case <-started:
	case <-time.After(time.Second):
		t.Fatal("did not run after credentials became ready")
	}
	config := m.configSnapshot()
	config.Enabled = false
	if err := m.configure(config); err != nil {
		t.Fatal(err)
	}
	if err := m.requestRun(); err == nil {
		t.Fatal("disabled automation accepted forced run")
	}
	m.app.cancel()
	select {
	case <-m.done:
	case <-time.After(time.Second):
		t.Fatal("scheduler did not exit on app cancellation")
	}
	if scans.Load() != 1 {
		t.Fatalf("unexpected duplicate scans: %d", scans.Load())
	}
}

func TestAutomationExportsRefreshOnlyOnMaterialChangeAndRecoverFailure(t *testing.T) {
	m := automationTestManager(t)
	config := m.configSnapshot()
	job := automationTestJob("portshelf/game0", config, automationTestRelease(t, "portshelf/game0", "amd64"))
	job.Status, job.Name, job.Description, job.SHA256 = "done", "=unsafe-sheet-formula", "第一版中文游戏说明", strings.Repeat("a", 64)
	job.DownloadPath = filepath.Join(m.app.transfers.downloadDir, job.ID, job.Asset.Name)
	job.Outputs["quark"] = TransferOutput{Status: "done", Session: "private-account-session", Share: CloudShare{URL: "https://pan.quark.cn/s/fid", Code: "1234"}}
	m.app.transfers.jobs = []TransferJob{job}
	now := time.Now().UTC()
	m.now = func() time.Time { return now }
	directory := filepath.Join(m.app.lib.root, "exports")
	if err := os.WriteFile(directory, []byte("unrelated local file"), 0600); err != nil {
		t.Fatal(err)
	}
	m.exportLatest()
	if m.state.ExportError == "" || m.state.ExportDigest != "" {
		t.Fatal("export failure was not visible/retryable")
	}
	if data, _ := os.ReadFile(directory); string(data) != "unrelated local file" {
		t.Fatal("export overwrote unrelated local file")
	}
	if err := os.Remove(directory); err != nil {
		t.Fatal(err)
	}
	m.exportLatest()
	if m.state.ExportError != "" || m.state.ExportDigest == "" || !automationExportsExist(directory) {
		t.Fatal("exports did not recover")
	}
	firstTime := m.state.ExportedAt
	data, err := os.ReadFile(filepath.Join(directory, "最新游戏清单.json"))
	var rows []transferMaterial
	if err != nil || json.Unmarshal(data, &rows) != nil || len(rows) != 1 || rows[0].Description != job.Description || len(rows[0].SupportedSystems) == 0 || !reflect.DeepEqual(rows[0].SupportedSystems, job.SupportedSystems) || strings.Contains(string(data), "private-account-session") {
		t.Fatalf("bad JSON export: %v", err)
	}
	csv, _ := os.ReadFile(filepath.Join(directory, "最新游戏清单.csv"))
	if !strings.Contains(string(csv), "'=unsafe-sheet-formula") || !strings.Contains(string(csv), "支持系统（据发布附件）") {
		t.Fatal("automatic CSV bypassed formula escaping")
	}
	now = now.Add(time.Hour)
	m.exportLatest()
	if m.state.ExportedAt != firstTime {
		t.Fatal("unchanged material was rewritten")
	}
	job.Description = "更新后的中文说明"
	m.app.transfers.jobs[0] = job
	m.exportLatest()
	if m.state.ExportedAt == firstTime {
		t.Fatal("changed material did not refresh")
	}
	markdown, _ := os.ReadFile(filepath.Join(directory, "最新游戏清单.md"))
	if !strings.Contains(string(markdown), job.Description) || !strings.Contains(string(markdown), "https://pan.quark.cn/s/fid") || !strings.Contains(string(markdown), "支持系统（据发布附件）："+systemDescription(job.SupportedSystems)) {
		t.Fatal("Markdown export missed latest material/share")
	}
	job.Status = "cancelled"
	m.app.transfers.jobs[0] = job
	m.exportLatest()
	data, _ = os.ReadFile(filepath.Join(directory, "最新游戏清单.json"))
	if json.Unmarshal(data, &rows) != nil || len(rows) != 1 || rows[0].Status != "cancelled" {
		t.Fatal("stopping a task removed its already downloaded material")
	}
}

func TestAutomationRejectsCorruptStateWithoutResettingQuota(t *testing.T) {
	m := automationTestManager(t)
	for _, body := range []string{"null", "{}", `{"version":1}`, strings.Repeat("x", automationMaxBytes+1)} {
		if err := os.WriteFile(filepath.Join(m.app.lib.root, "automation.json"), []byte(body), 0600); err != nil {
			t.Fatal(err)
		}
		if _, err := newAutomation(m.app); err == nil {
			t.Fatal("corrupt state silently reset daily quota/config")
		}
	}
}

func TestAutomationExportRejectsSymlinkDirectory(t *testing.T) {
	m := automationTestManager(t)
	outside := t.TempDir()
	if err := os.Symlink(outside, filepath.Join(m.app.lib.root, "exports")); err != nil {
		t.Skip("symlinks unavailable")
	}
	m.exportLatest()
	files, _ := os.ReadDir(outside)
	if len(files) != 0 || m.state.ExportError == "" {
		t.Fatal("export wrote through a directory symlink")
	}
}

func TestAutomationRoutesValidateAndPersistConfig(t *testing.T) {
	m := automationTestManager(t)
	mux := http.NewServeMux()
	m.app.registerAutomationRoutes(mux)
	request := func(method, path, body string) *httptest.ResponseRecorder {
		r := httptest.NewRequest(method, path, strings.NewReader(body))
		r.Header.Set("Content-Type", "application/json")
		w := httptest.NewRecorder()
		mux.ServeHTTP(w, r)
		return w
	}
	if w := request("POST", "/api/automation/run", "{}"); w.Code != http.StatusConflict {
		t.Fatalf("disabled run: %d", w.Code)
	}
	if w := request("POST", "/api/automation", `{"enabled":true,"unexpected":"field"}`); w.Code != http.StatusBadRequest {
		t.Fatalf("unknown fields: %d", w.Code)
	}
	config := m.configSnapshot()
	config.Enabled, config.RememberCredentials, config.StartOnLogin = true, false, false
	body, _ := json.Marshal(config)
	if w := request("POST", "/api/automation", string(body)); w.Code != http.StatusOK {
		t.Fatalf("save config: %d %s", w.Code, w.Body.String())
	}
	if w := request("POST", "/api/automation/run", "{}"); w.Code != http.StatusAccepted {
		t.Fatalf("run request: %d %s", w.Code, w.Body.String())
	}
	if w := request("POST", "/api/automation/run", "{}"); w.Code != http.StatusConflict {
		t.Fatalf("duplicate run: %d", w.Code)
	}
	if w := request("GET", "/api/automation", ""); w.Code != http.StatusOK || !strings.Contains(w.Body.String(), `"minStars":10`) || !strings.Contains(w.Body.String(), `"credentialStorageSupported"`) {
		t.Fatalf("status: %d %s", w.Code, w.Body.String())
	}
	for _, invalid := range []AutomationConfig{
		{IntervalHours: 0}, {IntervalHours: 169}, {IntervalHours: 6, DailyLimit: 101},
	} {
		if _, err := validateAutomationConfig(invalid); err == nil {
			t.Fatal("accepted out-of-range settings")
		}
	}
}
