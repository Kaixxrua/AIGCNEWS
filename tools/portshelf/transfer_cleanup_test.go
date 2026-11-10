package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func cleanupFixture(t *testing.T) (*transferManager, TransferJob, string) {
	t.Helper()
	m := automationTestManager(t).app.transfers
	content := "original verified game download"
	sum := sha256.Sum256([]byte(content))
	job := TransferJob{ID: randomID(), Repo: "demo/game", Name: "测试游戏", Arch: "amd64", Version: "v1",
		Status: "done", Stage: "done", Providers: []string{"baidu", "quark"}, SHA256: hex.EncodeToString(sum[:]),
		Description: "一款经典冒险游戏的开源移植。", SupportedSystems: []string{"Windows x64"},
		Asset: &Asset{ID: 123, Name: "game-windows-x64.zip", Size: int64(len(content)),
			URL: "https://github.com/demo/game/releases/download/v1/game-windows-x64.zip"},
		Outputs: map[string]TransferOutput{
			"baidu": {Status: "done", Session: "test-b", File: CloudFile{ID: "b-file"}, Share: CloudShare{URL: "https://pan.baidu.com/s/test", Code: "1234"}},
			"quark": {Status: "done", Session: "test-q", File: CloudFile{ID: "q-file"}, Share: CloudShare{URL: "https://pan.quark.cn/s/test", Code: "5678"}},
		}}
	job.DownloadPath = filepath.Join(m.downloadDir, job.ID, job.Asset.Name)
	if err := os.MkdirAll(filepath.Dir(job.DownloadPath), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(job.DownloadPath, []byte(content), 0600); err != nil {
		t.Fatal(err)
	}
	saveCleanupJobs(t, m, job)
	return m, job, content
}

func saveCleanupJobs(t *testing.T, m *transferManager, jobs ...TransferJob) {
	t.Helper()
	m.mu.Lock()
	defer m.mu.Unlock()
	if err := m.saveLocked(jobs); err != nil {
		t.Fatal(err)
	}
}

func waitLocalCleanup(t *testing.T, a *App, id string) TransferJob {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		job, _ := a.transfers.job(id)
		if job.LocalDeletedAt != "" {
			if _, err := os.Stat(job.DownloadPath); !errors.Is(err, os.ErrNotExist) {
				t.Fatal("cleanup receipt exists but the file remains")
			}
			return job
		}
		time.Sleep(5 * time.Millisecond)
	}
	job, _ := a.transfers.job(id)
	t.Fatalf("cleanup did not finish: %+v", job)
	return TransferJob{}
}

func TestCleanupRemovesOnlyVerifiedDownloadAndKeepsExportedMaterials(t *testing.T) {
	m, job, _ := cleanupFixture(t)
	sibling := filepath.Join(filepath.Dir(job.DownloadPath), "user-notes.txt")
	if err := os.WriteFile(sibling, []byte("keep this"), 0600); err != nil {
		t.Fatal(err)
	}
	m.cleanupLocalFiles()
	cleaned := waitLocalCleanup(t, m.app, job.ID)
	if cleaned.LocalCleanupPending || cleaned.LocalCleanupError != "" || cleaned.Description != job.Description || cleaned.SHA256 != job.SHA256 {
		t.Fatal("cleanup lost metadata or did not complete its receipt")
	}
	if data, err := os.ReadFile(sibling); err != nil || string(data) != "keep this" {
		t.Fatal("cleanup touched an unrelated file")
	}
	for _, format := range []string{"json", "csv", "markdown"} {
		w := httptest.NewRecorder()
		if err := exportTransfers(w, format, []TransferJob{cleaned}); err != nil {
			t.Fatal(err)
		}
		for _, value := range []string{job.Description, job.SHA256, job.Outputs["baidu"].Share.URL, job.Outputs["quark"].Share.URL, cleaned.LocalDeletedAt} {
			if !strings.Contains(w.Body.String(), value) {
				t.Fatalf("%s export lost %s", format, value)
			}
		}
		if strings.Contains(w.Body.String(), job.ID) {
			t.Fatalf("%s export still advertises a removed local path", format)
		}
	}
	restarted, err := newTransferManager(m.app)
	if err != nil {
		t.Fatal(err)
	}
	// A new user-created file at the former path does not belong to the old
	// cleanup operation, even if the app restarts or checks again.
	if err := os.WriteFile(job.DownloadPath, []byte("replacement user file"), 0600); err != nil {
		t.Fatal(err)
	}
	restarted.cleanupLocalFiles()
	if data, err := os.ReadFile(job.DownloadPath); err != nil || string(data) != "replacement user file" {
		t.Fatal("cleanup repeated on a file created after its receipt")
	}
}

func TestCleanupKeepsDownloadsUntilBothCloudCopiesAndSharesAreReady(t *testing.T) {
	cases := map[string]func(*TransferJob){
		"local only":      func(j *TransferJob) { j.Providers = nil },
		"one drive":       func(j *TransferJob) { j.Providers = []string{"baidu"} },
		"duplicate drive": func(j *TransferJob) { j.Providers = []string{"baidu", "baidu"} },
		"queued":          func(j *TransferJob) { j.Status = "queued" },
		"running":         func(j *TransferJob) { j.Status = "running" },
		"waiting auth":    func(j *TransferJob) { j.Status = "waiting_auth" },
		"failed":          func(j *TransferJob) { j.Status = "failed" },
		"paused":          func(j *TransferJob) { j.Status = "paused"; j.LocalCleanupPending = true },
		"cancelled":       func(j *TransferJob) { j.Status = "cancelled"; j.LocalCleanupPending = true },
		"upload failed":   func(j *TransferJob) { o := j.Outputs["quark"]; o.Status = "failed"; j.Outputs["quark"] = o },
		"share failed":    func(j *TransferJob) { o := j.Outputs["quark"]; o.Status = "share_failed"; j.Outputs["quark"] = o },
		"missing file id": func(j *TransferJob) { o := j.Outputs["quark"]; o.File.ID = ""; j.Outputs["quark"] = o },
		"missing session": func(j *TransferJob) { o := j.Outputs["quark"]; o.Session = ""; j.Outputs["quark"] = o },
		"error":           func(j *TransferJob) { o := j.Outputs["quark"]; o.Error = "unfinished"; j.Outputs["quark"] = o },
		"needs attention": func(j *TransferJob) { o := j.Outputs["quark"]; o.NeedsAttention = true; j.Outputs["quark"] = o },
		"missing share":   func(j *TransferJob) { o := j.Outputs["quark"]; o.Share.URL = ""; j.Outputs["quark"] = o },
		"invalid share": func(j *TransferJob) {
			o := j.Outputs["quark"]
			o.Share.URL = "https://evil.test/s/test"
			j.Outputs["quark"] = o
		},
		"expired share": func(j *TransferJob) {
			o := j.Outputs["quark"]
			o.Share.ExpiresAt = time.Now().Add(-time.Hour).Format(time.RFC3339)
			j.Outputs["quark"] = o
		},
		"expiring share": func(j *TransferJob) {
			o := j.Outputs["quark"]
			o.Share.ExpiresAt = time.Now().Add(30 * time.Second).Format(time.RFC3339)
			j.Outputs["quark"] = o
		},
		"invalid expiry": func(j *TransferJob) {
			o := j.Outputs["quark"]
			o.Share.ExpiresAt = "not a time"
			j.Outputs["quark"] = o
		},
	}
	for name, change := range cases {
		t.Run(name, func(t *testing.T) {
			m, job, content := cleanupFixture(t)
			change(&job)
			saveCleanupJobs(t, m, job)
			m.cleanupLocalFiles()
			if data, err := os.ReadFile(job.DownloadPath); err != nil || string(data) != content {
				t.Fatal("unfinished/unsafe two-drive task lost its download")
			}
		})
	}
}

func TestCleanupRejectsModifiedOrUnownedFiles(t *testing.T) {
	cases := map[string]func(*testing.T, *transferManager, *TransferJob, string) string{
		"modified bytes": func(t *testing.T, m *transferManager, j *TransferJob, content string) string {
			if err := os.WriteFile(j.DownloadPath, []byte(strings.Repeat("x", len(content))), 0600); err != nil {
				t.Fatal(err)
			}
			return j.DownloadPath
		},
		"wrong size": func(t *testing.T, m *transferManager, j *TransferJob, content string) string {
			j.Asset.Size++
			return j.DownloadPath
		},
		"outside directory": func(t *testing.T, m *transferManager, j *TransferJob, content string) string {
			j.DownloadPath = filepath.Join(t.TempDir(), j.Asset.Name)
			if err := os.WriteFile(j.DownloadPath, []byte(content), 0600); err != nil {
				t.Fatal(err)
			}
			return j.DownloadPath
		},
		"wrong name": func(t *testing.T, m *transferManager, j *TransferJob, content string) string {
			j.Asset.Name = "different.zip"
			return j.DownloadPath
		},
		"file symlink": func(t *testing.T, m *transferManager, j *TransferJob, content string) string {
			target := filepath.Join(t.TempDir(), j.Asset.Name)
			if err := os.Rename(j.DownloadPath, target); err != nil {
				t.Fatal(err)
			}
			if err := os.Symlink(target, j.DownloadPath); err != nil {
				t.Skip(err)
			}
			return target
		},
		"directory symlink": func(t *testing.T, m *transferManager, j *TransferJob, content string) string {
			parent := filepath.Dir(j.DownloadPath)
			target := filepath.Join(t.TempDir(), "moved")
			if err := os.Rename(parent, target); err != nil {
				t.Fatal(err)
			}
			if err := os.Symlink(target, parent); err != nil {
				t.Skip(err)
			}
			return filepath.Join(target, j.Asset.Name)
		},
		"root symlink": func(t *testing.T, m *transferManager, j *TransferJob, content string) string {
			target := filepath.Join(t.TempDir(), "moved-downloads")
			if err := os.Rename(m.downloadDir, target); err != nil {
				t.Fatal(err)
			}
			if err := os.Symlink(target, m.downloadDir); err != nil {
				t.Skip(err)
			}
			return filepath.Join(target, j.ID, j.Asset.Name)
		},
	}
	for name, change := range cases {
		t.Run(name, func(t *testing.T) {
			m, job, content := cleanupFixture(t)
			target := change(t, m, &job, content)
			saveCleanupJobs(t, m, job)
			m.cleanupLocalFiles()
			current, _ := m.job(job.ID)
			if _, err := os.Stat(target); err != nil || current.LocalDeletedAt != "" || current.LocalCleanupError == "" {
				t.Fatal("modified/unsafe file was removed or its preservation was not explained")
			}
		})
	}
}

func TestCleanupDoesNotWaitForChineseDescriptionAfterBothDrivesFinish(t *testing.T) {
	m, job, _ := cleanupFixture(t)
	job.Status, job.Description, job.Enrich = "partial", "", true
	job.NextRetryAt = time.Now().Add(time.Minute).Format(time.RFC3339)
	job.Warnings = []string{"中文简介服务暂不可用"}
	saveCleanupJobs(t, m, job)
	m.cleanupLocalFiles()
	cleaned := waitLocalCleanup(t, m.app, job.ID)
	if cleaned.Status != "partial" || cleaned.NextRetryAt != job.NextRetryAt || len(cleaned.Warnings) != 1 {
		t.Fatal("cleanup lost the outstanding description retry")
	}
}

func TestCleanupWaitsForOtherTasksUsingTheSameFile(t *testing.T) {
	m, first, _ := cleanupFixture(t)
	second := cloneTransfer(first)
	second.ID, second.Status = randomID(), "queued"
	saveCleanupJobs(t, m, first, second)
	m.cleanupLocalFiles()
	if _, err := os.Stat(first.DownloadPath); err != nil {
		t.Fatal("a queued task's shared file was deleted")
	}
	if err := m.modify(second.ID, func(j *TransferJob) { j.Status = "done" }, true); err != nil {
		t.Fatal(err)
	}
	m.cleanupLocalFiles()
	for _, id := range []string{first.ID, second.ID} {
		waitLocalCleanup(t, m.app, id)
	}
}

func TestCleanupPersistsIntentBeforeDeletionAndRecoversAfterRestart(t *testing.T) {
	m, job, _ := cleanupFixture(t)
	statePath := filepath.Join(m.app.lib.root, "transfers.json")
	backup := statePath + ".test-backup"
	if err := os.Rename(statePath, backup); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(statePath, 0700); err != nil {
		t.Fatal(err)
	}
	m.cleanupLocalFiles()
	if _, err := os.Stat(job.DownloadPath); err != nil {
		t.Fatal("file deleted without a persisted cleanup intent")
	}
	if _, failure := m.snapshot(); failure == "" {
		t.Fatal("state write failure was hidden")
	}
	if err := os.Remove(statePath); err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(backup, statePath); err != nil {
		t.Fatal(err)
	}
	restarted, err := newTransferManager(m.app)
	if err != nil {
		t.Fatal(err)
	}
	restarted.cleanupLocalFiles()
	current, _ := restarted.job(job.ID)
	if current.LocalDeletedAt == "" {
		t.Fatal("cleanup did not recover after restoring persistence")
	}

	// Simulate process termination after deleting the file but before saving
	// the final receipt. Links may expire while the process is stopped.
	job.LocalCleanupPending = true
	output := job.Outputs["baidu"]
	output.Share.ExpiresAt = time.Now().Add(-time.Hour).Format(time.RFC3339)
	job.Outputs["baidu"] = output
	saveCleanupJobs(t, restarted, job)
	recovered, err := newTransferManager(m.app)
	if err != nil {
		t.Fatal(err)
	}
	recovered.cleanupLocalFiles()
	current, _ = recovered.job(job.ID)
	if current.LocalDeletedAt == "" || current.LocalCleanupPending || current.Outputs["baidu"].Share.URL == "" {
		t.Fatal("restart failed to finish the cleanup receipt and retain cloud metadata")
	}
}

func TestNewTasksReuseCleanedRemoteFilesForExpiredOrChangedShares(t *testing.T) {
	a, downloads, content := prepareTransferApp(t)
	drives := automationIntegrationDrives(a, content)
	first := waitLocalCleanup(t, a, enqueueTest(t, a, "baidu", "quark"))
	if err := a.transfers.modify(first.ID, func(j *TransferJob) {
		for provider, output := range j.Outputs {
			output.Share.ExpiresAt = time.Now().Add(-time.Hour).Format(time.RFC3339)
			j.Outputs[provider] = output
		}
	}, true); err != nil {
		t.Fatal(err)
	}
	second := waitTransfer(t, a, enqueueTest(t, a, "baidu", "quark"), "done")
	added, _, err := a.transfers.enqueue(TransferRequest{Repos: []string{first.Repo}, Arch: "amd64", Providers: []string{"baidu", "quark"}, ShareDays: 7})
	if err != nil || len(added) != 1 {
		t.Fatalf("changed share options not queued: %v %v", added, err)
	}
	third := waitTransfer(t, a, added[0], "done")
	if second.LocalDeletedAt != first.LocalDeletedAt || third.LocalDeletedAt != first.LocalDeletedAt || downloads.Load() != 1 {
		t.Fatal("renewal tasks downloaded an already uploaded release again")
	}
	for provider, drive := range drives {
		if uploads, shares := drive.counts(); uploads != 1 || shares != 3 {
			t.Fatalf("%s did not reuse the existing file for new shares: %d %d", provider, uploads, shares)
		}
	}
}

func TestCleanedDownloadSupportsDescriptionAndShareRetriesWithoutRedownloading(t *testing.T) {
	a, downloads, content := prepareTransferApp(t)
	drives := automationIntegrationDrives(a, content)
	id := enqueueTest(t, a, "baidu", "quark")
	cleaned := waitLocalCleanup(t, a, id)
	if w := call(a, "POST", "/api/transfers/open", `{"id":"`+id+`"}`); w.Code != http.StatusGone {
		t.Fatalf("removed local file still offered as available: %d", w.Code)
	}
	a.aigc.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		return apiResponse(200, `{"items":[{"repo":"OpenRCT2/OpenRCT2","status":"ready","descriptionZh":"重现经典游乐园经营玩法的开源游戏。","source":"aigcnews"}]}`), nil
	})
	if err := a.transfers.modify(id, func(j *TransferJob) {
		j.Enrich, j.Description = true, ""
	}, true); err != nil {
		t.Fatal(err)
	}
	if err := a.transfers.action(id, "retry"); err != nil {
		t.Fatal(err)
	}
	enriched := waitTransfer(t, a, id, "done")
	if enriched.Description == "" || enriched.LocalDeletedAt != cleaned.LocalDeletedAt || downloads.Load() != 1 {
		t.Fatal("description retry lost metadata or downloaded the deleted file again")
	}
	if err := a.transfers.modify(id, func(j *TransferJob) {
		o := j.Outputs["baidu"]
		o.Share.ExpiresAt = time.Now().Add(-time.Hour).Format(time.RFC3339)
		j.Outputs["baidu"] = o
	}, true); err != nil {
		t.Fatal(err)
	}
	if err := a.transfers.action(id, "retry"); err != nil {
		t.Fatal(err)
	}
	renewed := waitTransfer(t, a, id, "done")
	if !usableCloudShare("baidu", renewed.Outputs["baidu"].Share) || downloads.Load() != 1 {
		t.Fatal("share renewal did not reuse the remote file")
	}
	for provider, drive := range drives {
		uploads, shares := drive.counts()
		expectedShares := 1
		if provider == "baidu" {
			expectedShares = 2
		}
		if uploads != 1 || shares != expectedShares {
			t.Fatalf("repeated %s cloud work: %d %d", provider, uploads, shares)
		}
	}
	// A newly queued identical release also reuses verified remote results.
	second := waitTransfer(t, a, enqueueTest(t, a, "baidu", "quark"), "done")
	if second.LocalDeletedAt != cleaned.LocalDeletedAt || downloads.Load() != 1 {
		t.Fatal("a duplicate release unnecessarily downloaded the cleaned artifact")
	}
	w := call(a, "GET", "/api/transfers/export?format=json", "")
	var rows []transferMaterial
	if w.Code != 200 || json.Unmarshal(w.Body.Bytes(), &rows) != nil || len(rows) != 2 || rows[0].DownloadPath != "" || rows[0].Baidu.URL == "" {
		t.Fatal("API lost materials after cleanup/retry")
	}
	// A new account really needs another upload; download again in that case.
	a.cloud.mu.Lock()
	account := a.cloud.accounts["baidu"]
	account.session = "different-account"
	a.cloud.accounts["baidu"] = account
	a.cloud.mu.Unlock()
	if err := a.transfers.action(id, "retry"); err != nil {
		t.Fatal(err)
	}
	waitTransfer(t, a, id, "done")
	waitLocalCleanup(t, a, id)
	uploads, _ := drives["baidu"].counts()
	if downloads.Load() != 2 || uploads != 2 {
		t.Fatal("new account did not get a fresh download and upload")
	}
}
