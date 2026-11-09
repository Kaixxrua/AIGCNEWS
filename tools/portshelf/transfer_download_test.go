package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestDownloadRedirectAndFilenameBoundaries(t *testing.T) {
	for _, raw := range []string{"http://github.com/o/r", "https://github.com.evil.test/a", "https://127.0.0.1/a",
		"https://github.com:443/a", "https://secret@github.com/a", "https://example.com/a", "https://github.com/a#fragment"} {
		target, _ := url.Parse(raw)
		if validDownloadTarget(target) {
			t.Fatalf("unsafe download target allowed: %s", raw)
		}
	}
	for _, raw := range []string{"https://github.com/o/r/releases/download/v1/x.zip", "https://release-assets.githubusercontent.com/a?signature=public"} {
		target, _ := url.Parse(raw)
		if !validDownloadTarget(target) {
			t.Fatalf("valid GitHub target rejected: %s", raw)
		}
	}
	for _, name := range []string{"../bad.exe", "/tmp/bad.exe", "CON", "nul.zip", "lpt1.exe", "C:ads", "archive.zip:stream", "foo\\bar", "bad\x00.zip", "trailing.zip.", " file.zip", strings.Repeat("a", 201)} {
		if validDownloadName(name) {
			t.Errorf("unsafe Windows filename: %q", name)
		}
	}
	for _, name := range []string{"release-win64.zip", "中文游戏-x64.exe", "My Game (Windows).7z"} {
		if !validDownloadName(name) {
			t.Errorf("valid filename rejected: %s", name)
		}
	}
}

func TestDownloadNeverForwardsCredentialOrFollowsForeignRedirect(t *testing.T) {
	a, _, content := prepareTransferApp(t)
	foreignRequested := false
	a.transfers.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		if r.URL.Host != "github.com" {
			foreignRequested = true
			return apiResponse(200, content), nil
		}
		response := apiResponse(302, "")
		response.Header.Set("Location", "https://evil.example/collect")
		return response, nil
	})
	job := waitTransfer(t, a, enqueueTest(t, a), "failed")
	if foreignRequested || job.DownloadPath != "" || strings.Contains(job.Error, "evil.example") {
		t.Fatalf("foreign redirect followed/exposed: %+v", job)
	}
}

func TestDownloadSizeAndUpstreamDigestMustMatch(t *testing.T) {
	for _, test := range []struct {
		name, body string
		length     int64
	}{
		{"truncated", "short", -1},
		{"oversized", strings.Repeat("X", 100), -1},
		{"wrong content length", "known public Windows release bytes", 999},
		{"wrong digest", "KNOWN PUBLIC WINDOWS RELEASE BYTES", -1},
	} {
		t.Run(test.name, func(t *testing.T) {
			a, _, _ := prepareTransferApp(t)
			a.transfers.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
				response := apiResponse(200, test.body)
				response.ContentLength = test.length
				return response, nil
			})
			job := waitTransfer(t, a, enqueueTest(t, a), "failed")
			if job.DownloadPath != "" || job.SHA256 != "" {
				t.Fatal("invalid bytes promoted to completed artifact")
			}
			if _, err := os.Stat(filepath.Join(a.transfers.downloadDir, job.ID, job.Asset.Name)); !errors.Is(err, os.ErrNotExist) {
				t.Fatal("invalid bytes saved as final artifact")
			}
		})
	}
}

func TestDownloadRefusesSymlinkDirectoryAndChangedCompletedFile(t *testing.T) {
	a, _, _ := prepareTransferApp(t)
	job := waitTransfer(t, a, enqueueTest(t, a), "done")
	if err := os.WriteFile(job.DownloadPath, []byte("tampered"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, _, err := a.transfers.download(context.Background(), job, func(int64, int64) {}); err == nil {
		t.Fatal("changed completed file reused")
	}
	other := cloneTransfer(job)
	other.ID, other.DownloadPath, other.SHA256 = randomID(), "", ""
	outside := t.TempDir()
	if err := os.Symlink(outside, filepath.Join(a.transfers.downloadDir, other.ID)); err != nil {
		t.Skipf("symlink unavailable: %v", err)
	}
	if _, _, err := a.transfers.download(context.Background(), other, func(int64, int64) {}); err == nil {
		t.Fatal("symlink task directory accepted")
	}
	entries, _ := os.ReadDir(outside)
	if len(entries) != 0 {
		t.Fatal("download escaped its directory")
	}
}

func TestExpiredShareIsNotReusableAndRemoteNameIsPortable(t *testing.T) {
	for _, raw := range []string{"http://pan.quark.cn/s/id", "https://pan.quark.cn.evil.test/s/id", "https://pan.quark.cn:443/s/id", "https://pan.quark.cn/s/a/b", "https://pan.quark.cn/s/../x", "https://pan.quark.cn/s/id#fragment"} {
		if validCloudShare("quark", raw) {
			t.Fatal("unsafe share URL accepted: " + raw)
		}
	}
	if usableCloudShare("quark", CloudShare{URL: "https://pan.quark.cn/s/id", ExpiresAt: time.Now().Add(-time.Hour).Format(time.RFC3339)}) {
		t.Fatal("expired share reused")
	}
	if !usableCloudShare("baidu", CloudShare{URL: "https://pan.baidu.com/s/1id", Code: "abc1"}) {
		t.Fatal("permanent share rejected")
	}
	job := TransferJob{Repo: "owner/repo", Version: "v/1:2 ?*", Asset: &Asset{Name: "game-windows-x64.zip"}}
	if name := transferRemoteName(job); !validDownloadName(name) {
		t.Fatal("generated remote filename is invalid: " + name)
	}
}

func TestTaskDoesNotSelectWrongArchitectureOrSourceArchive(t *testing.T) {
	a, calls, content := prepareTransferApp(t)
	sum := sha256.Sum256([]byte(content))
	body := `{"tag_name":"v1","html_url":"https://github.com/OpenRCT2/OpenRCT2/releases/tag/v1","assets":[
		{"id":1,"name":"game-windows-arm64.zip","size":33,"browser_download_url":"https://github.com/OpenRCT2/OpenRCT2/releases/download/v1/game-windows-arm64.zip"},
		{"id":2,"name":"game-windows-source.zip","size":33,"browser_download_url":"https://github.com/OpenRCT2/OpenRCT2/releases/download/v1/game-windows-source.zip"}]}`
	a.github.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) { return apiResponse(200, body), nil })
	job := waitTransfer(t, a, enqueueTest(t, a), "failed")
	if calls.Load() != 0 || !strings.Contains(job.Error, "架构") {
		t.Fatalf("wrong artifact downloaded: %+v", job)
	}
	// A previously downloaded file is verified against its saved SHA, not just size.
	path := filepath.Join(a.transfers.downloadDir, job.ID, "same-size.zip")
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(strings.Repeat("x", len(content))), 0600); err != nil {
		t.Fatal(err)
	}
	job.DownloadPath, job.SHA256 = path, hex.EncodeToString(sum[:])
	job.Asset = &Asset{Size: int64(len(content))}
	if a.transfers.verifyLocal(context.Background(), job) {
		t.Fatal("size alone accepted as identity")
	}
}

func TestTransferUncheckpointedDownloadWithoutUpstreamDigest(t *testing.T) {
	for _, changed := range []bool{false, true} {
		t.Run(fmt.Sprint(changed), func(t *testing.T) {
			a, calls, content := prepareTransferApp(t)
			finished := waitTransfer(t, a, enqueueTest(t, a), "done")
			if changed {
				if err := os.WriteFile(finished.DownloadPath, []byte(strings.Repeat("x", len(content))), 0600); err != nil {
					t.Fatal(err)
				}
			}
			job := finished
			job.DownloadPath, job.SHA256, job.Asset.Digest = "", "", ""
			path, digest, err := a.transfers.download(context.Background(), job, func(int64, int64) {})
			if changed {
				if err == nil {
					t.Fatal("modified orphan file accepted")
				}
				data, _ := os.ReadFile(finished.DownloadPath)
				if string(data) != strings.Repeat("x", len(content)) {
					t.Fatal("existing file overwritten")
				}
			} else if err != nil || path != finished.DownloadPath || digest != finished.SHA256 {
				t.Fatalf("complete file not recovered: path=%s digest=%s err=%v", path, digest, err)
			}
			if calls.Load() != 2 {
				t.Fatal("file without an expected checksum was accepted without upstream comparison")
			}
		})
	}
}
