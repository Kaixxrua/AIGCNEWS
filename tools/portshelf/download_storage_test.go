package main

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
)

func TestDownloadDirectoryResumesOldBinaryAndCleansFilesAcrossDisks(t *testing.T) {
	a, downloads, binary := prepareTransferApp(t)
	for _, id := range []string{"baidu", "quark"} {
		a.cloud.accounts[id] = cloudAccount{drive: &fakeCloudDrive{id: id, content: binary}, session: id}
	}
	var failSource atomic.Bool
	failSource.Store(true)
	transport := a.transfers.client.Transport
	a.transfers.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		if r.URL.Host == "codeload.github.com" && failSource.Load() {
			return nil, errors.New("source temporarily unavailable")
		}
		return transport.RoundTrip(r)
	})
	id := enqueueTest(t, a, "baidu", "quark")
	old := waitTransfer(t, a, id, "failed")
	if old.DownloadPath == "" || downloads.Load() != 1 {
		t.Fatal("fixture did not retain the downloaded binary")
	}
	credentialPath := filepath.Join(a.lib.root, "credentials.dpapi")
	if err := os.WriteFile(credentialPath, []byte("unchanged encrypted account fixture"), 0600); err != nil {
		t.Fatal(err)
	}
	directory := filepath.Join(t.TempDir(), "游戏 下载")
	body, _ := json.Marshal(map[string]string{"directory": directory})
	if response := call(a, "POST", "/api/transfers/directory", string(body)); response.Code != http.StatusOK {
		t.Fatal(response.Body.String())
	}
	if data, _ := os.ReadFile(credentialPath); string(data) != "unchanged encrypted account fixture" {
		t.Fatal("changing download directory changed saved credentials")
	}
	if current, _ := a.transfers.job(id); current.DownloadPath != old.DownloadPath || !a.transfers.verifyLocal(context.Background(), current) {
		t.Fatal("old task or its verified binary was lost")
	}
	reloaded, err := newTransferManager(a)
	if err != nil || reloaded.downloadDirectory() != directory || !reloaded.ownedDownloadPath(old.DownloadPath) {
		t.Fatal("directory/old path did not survive restart", err)
	}
	failSource.Store(false)
	if err := a.transfers.action(id, "retry"); err != nil {
		t.Fatal(err)
	}
	job := waitLocalCleanup(t, a, id)
	if downloads.Load() != 1 || job.DownloadPath != old.DownloadPath || filepath.Dir(job.SourcePath) != filepath.Join(directory, id) || filepath.Dir(job.BundlePath) != filepath.Join(directory, id) {
		t.Fatal("retry redownloaded the binary or used the wrong destination")
	}
	for _, file := range transferArtifacts(job) {
		if _, err := os.Stat(file.path); !errors.Is(err, os.ErrNotExist) {
			t.Fatal("dual-cloud cleanup failed across roots", file.path, err)
		}
	}
	for _, endpoint := range []string{"/api/cloud", "/api/transfers"} {
		var result struct {
			DownloadDir string `json:"downloadDir"`
		}
		response := call(a, "GET", endpoint, "")
		if json.Unmarshal(response.Body.Bytes(), &result) != nil || result.DownloadDir != directory {
			t.Fatal("UI received a stale download directory", endpoint)
		}
	}
}

func TestDownloadDirectoryUnavailableDoesNotFallBackOnRestart(t *testing.T) {
	a, downloads, _ := prepareTransferApp(t)
	directory := filepath.Join(t.TempDir(), "disk")
	if err := a.transfers.setDownloadDirectory(directory); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(directory); err != nil {
		t.Fatal(err)
	}
	reloaded, err := newTransferManager(a)
	if err != nil || reloaded.downloadDirectory() != directory {
		t.Fatal("unavailable disk blocked settings or reset the chosen path", err)
	}
	job := waitTransfer(t, a, enqueueTest(t, a), "failed")
	if downloads.Load() != 0 || job.DownloadPath != "" || !strings.Contains(job.Error, "下载目录不可用") {
		t.Fatal("unavailable destination downloaded to a different disk", job.Error)
	}
	if files, _ := os.ReadDir(a.transfers.downloadDir); len(files) != 0 {
		t.Fatal("unavailable destination fell back to the default disk")
	}
}

func TestDownloadDirectorySettingsRejectUnsafePathsAndPersistBeforeSwitch(t *testing.T) {
	m := automationTestManager(t).app.transfers
	initial := m.downloadDirectory()
	file := filepath.Join(t.TempDir(), "file")
	if err := os.WriteFile(file, []byte("unrelated"), 0600); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(t.TempDir(), "link")
	if err := os.Symlink(t.TempDir(), link); err != nil {
		t.Fatal(err)
	}
	for _, invalid := range []string{"", "relative/folder", "../folder", initial + "\x00", file, link, filepath.Join(link, "nested")} {
		if err := m.setDownloadDirectory(invalid); err == nil || m.downloadDirectory() != initial {
			t.Fatalf("invalid destination accepted: %q", invalid)
		}
	}
	if err := os.Mkdir(filepath.Join(m.app.lib.root, "download-settings.json"), 0700); err != nil {
		t.Fatal(err)
	}
	newDirectory := t.TempDir()
	if err := m.setDownloadDirectory(newDirectory); err == nil || m.downloadDirectory() != initial || m.ownedDownloadPath(filepath.Join(newDirectory, randomID(), "game.zip")) {
		t.Fatal("failed settings commit changed active or trusted directories")
	}
}

func TestDownloadDirectoryChangeDuringDownloadKeepsInFlightPath(t *testing.T) {
	a, _, content := prepareTransferApp(t)
	started, release := make(chan struct{}), make(chan struct{})
	a.transfers.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		close(started)
		select {
		case <-release:
		case <-r.Context().Done():
			return nil, r.Context().Err()
		}
		response := apiResponse(200, content)
		response.ContentLength = int64(len(content))
		return response, nil
	})
	id := enqueueTest(t, a)
	<-started
	directory := t.TempDir()
	if err := a.transfers.setDownloadDirectory(directory); err != nil {
		close(release)
		t.Fatal(err)
	}
	close(release)
	job := waitTransfer(t, a, id, "done")
	if filepath.Dir(job.DownloadPath) != filepath.Join(a.transfers.downloadDir, id) || !a.transfers.verifyLocal(context.Background(), job) {
		t.Fatal("in-flight bytes were recorded under a different directory")
	}
	if reloaded, err := newTransferManager(a); err != nil || !reloaded.verifyLocal(context.Background(), job) {
		t.Fatal("in-flight receipt did not survive restart", err)
	}
}

func TestDownloadDirectoryEndpointRequiresLocalSession(t *testing.T) {
	a := testApp(t)
	directory := filepath.Join(t.TempDir(), "must-not-create")
	body, _ := json.Marshal(map[string]string{"directory": directory})
	for _, foreign := range []bool{false, true} {
		r := request(a, "POST", "/api/transfers/directory", string(body))
		if foreign {
			r.Header.Set("Origin", "https://unrelated.example")
		} else {
			r.Header.Del("Authorization")
		}
		response := httptest.NewRecorder()
		a.handler().ServeHTTP(response, r)
		if response.Code != http.StatusForbidden && response.Code != http.StatusUnauthorized {
			t.Fatal("unauthorized folder change succeeded")
		}
	}
	if _, err := os.Stat(directory); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("unauthorized request created a directory")
	}
}

func TestDownloadDirectoryNewFilesAndRestart(t *testing.T) {
	a, _, content := prepareTransferApp(t)
	a.cloud.accounts["quark"] = cloudAccount{drive: &fakeCloudDrive{id: "quark", content: content}, session: "q"}
	directory := filepath.Join(t.TempDir(), "download files")
	if err := a.transfers.setDownloadDirectory(directory); err != nil {
		t.Fatal(err)
	}
	job := waitTransfer(t, a, enqueueTest(t, a, "quark"), "done")
	reloaded, err := newTransferManager(a)
	if err != nil {
		t.Fatal(err)
	}
	for _, file := range transferArtifacts(job) {
		if filepath.Dir(file.path) != filepath.Join(directory, job.ID) || !reloaded.verifyManaged(context.Background(), file.path, file.digest, file.size) {
			t.Fatal("new binary/source/bundle did not use the saved directory", file.key)
		}
	}
	if entries, _ := os.ReadDir(a.transfers.downloadDir); len(entries) != 0 {
		t.Fatal("new task left files in the default directory")
	}
}

func TestDownloadDirectoryReplacedRootCannotReadOrDelete(t *testing.T) {
	m, job, content := cleanupFixture(t)
	directory := filepath.Join(t.TempDir(), "selected")
	if err := m.setDownloadDirectory(directory); err != nil {
		t.Fatal(err)
	}
	outside := t.TempDir()
	if err := os.Mkdir(filepath.Join(outside, job.ID), 0700); err != nil {
		t.Fatal(err)
	}
	sentinel := filepath.Join(outside, job.ID, job.Asset.Name)
	if err := os.WriteFile(sentinel, []byte(content), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(directory); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, directory); err != nil {
		t.Fatal(err)
	}
	job.DownloadPath = filepath.Join(directory, job.ID, job.Asset.Name)
	saveCleanupJobs(t, m, job)
	if m.verifyLocal(context.Background(), job) {
		t.Fatal("followed a replaced root when verifying a file")
	}
	m.cleanupLocalFiles()
	if data, err := os.ReadFile(sentinel); err != nil || string(data) != content {
		t.Fatal("cleanup escaped the chosen root")
	}
}
