package main

import (
	"archive/zip"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func readZIPMembers(t *testing.T, data []byte) map[string][]byte {
	t.Helper()
	reader, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		t.Fatal(err)
	}
	result := map[string][]byte{}
	for _, file := range reader.File {
		body, err := file.Open()
		if err != nil {
			t.Fatal(err)
		}
		data, err := io.ReadAll(body)
		body.Close()
		if err != nil {
			t.Fatal(err)
		}
		result[file.Name] = data
	}
	return result
}

func TestSourceBundleUploadsOriginalAssetAndPinnedSourceWithLicensesAndDetails(t *testing.T) {
	a, downloads, binary := prepareTransferApp(t)
	drive := &fakeCloudDrive{id: "quark", content: binary}
	a.cloud.accounts["quark"] = cloudAccount{drive: drive, session: "q"}
	item := readyFixture("OpenRCT2/OpenRCT2")
	item.GameNameZh, item.GameNameOriginal = "过山车大亨2", "RollerCoaster Tycoon 2"
	if err := a.lib.saveDescriptions([]Description{item}); err != nil {
		t.Fatal(err)
	}
	job := waitTransfer(t, a, enqueueTest(t, a, "quark"), "done")
	if !hasSourceBundle(job) || job.SourceCommit != testSourceCommit || job.SourceURL != sourceArchiveURL(job.Repo, testSourceCommit) || job.Outputs["quark"].PayloadSHA256 != job.BundleSHA256 || downloads.Load() != 1 {
		t.Fatalf("missing pinned package metadata: %+v", job)
	}
	drive.mu.Lock()
	uploaded := append([]byte{}, drive.uploaded...)
	remoteName := drive.remoteName
	drive.mu.Unlock()
	members := readZIPMembers(t, uploaded)
	if string(members["game/"+job.Asset.Name]) != binary || !bytes.Equal(members["source/"+sourceArchiveName(job)], testSourceZIP(t, job.Repo)) {
		t.Fatal("share did not contain byte-for-byte original game and exact source ZIP")
	}
	if string(members["licenses/LICENSE"]) != "Original upstream license. Preserve exactly.\n" {
		t.Fatal("license original text lost")
	}
	var manifest bundleManifest
	if json.Unmarshal(members["manifest.json"], &manifest) != nil || manifest.SourceCommit != testSourceCommit || manifest.AssetSHA256 != job.SHA256 || manifest.SourceSHA256 != job.SourceSHA256 || manifest.GameNameZh != item.GameNameZh || manifest.ProjectName != "OpenRCT2" {
		t.Fatal("manifest lost version/source/game identity")
	}
	for _, value := range []string{item.GameNameZh, "正版游戏数据", job.SourceCommit, job.SHA256, job.SourceSHA256} {
		if !bytes.Contains(members["使用说明.txt"], []byte(value)) {
			t.Fatalf("README missing %s", value)
		}
	}
	sum := sha256.Sum256(uploaded)
	if job.BundleSHA256 != hex.EncodeToString(sum[:]) || remoteName != bundleName(job) || job.LocalDeletedAt != "" {
		t.Fatal("uploaded digest/name mismatched or single-drive file deleted")
	}
	for _, target := range []string{job.DownloadPath, job.SourcePath, job.BundlePath} {
		if _, err := os.Stat(target); err != nil {
			t.Fatal("single-drive job lost managed file", err)
		}
	}
}

func TestSourceTagResolutionFollowsAnnotatedTagsAndRejectsBranchFallback(t *testing.T) {
	const annotatedSHA = "1111111111111111111111111111111111111111"
	for _, kind := range []string{"lightweight", "annotated", "missing", "wrong tag", "tree", "invalid sha", "cycle"} {
		t.Run(kind, func(t *testing.T) {
			g := newGitHub("source-test-token")
			calls := 0
			g.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
				calls++
				if r.URL.Host != "api.github.com" || r.Header.Get("Authorization") != "Bearer source-test-token" || strings.Contains(r.URL.Path, "/commits/") {
					t.Error("source tag lookup was not fixed GitHub API")
				}
				if kind == "missing" {
					return apiResponse(404, `{}`), nil
				}
				if strings.Contains(r.URL.Path, "/git/tags/") {
					object := map[string]string{"type": "commit", "sha": testSourceCommit}
					if kind == "cycle" {
						object = map[string]string{"type": "tag", "sha": annotatedSHA}
					}
					data, _ := json.Marshal(map[string]any{"sha": annotatedSHA, "object": object})
					return apiResponse(200, string(data)), nil
				}
				if r.URL.Path != "/repos/demo/game/git/ref/tags/release/v1" {
					t.Errorf("release tag changed: %s", r.URL.Path)
				}
				ref, sha, objectType := "refs/tags/release/v1", testSourceCommit, "commit"
				switch kind {
				case "annotated", "cycle":
					sha, objectType = annotatedSHA, "tag"
				case "wrong tag":
					ref = "refs/heads/main"
				case "tree":
					objectType = "tree"
				case "invalid sha":
					sha = "main"
				}
				data, _ := json.Marshal(map[string]any{"ref": ref, "object": map[string]string{"type": objectType, "sha": sha}})
				return apiResponse(200, string(data)), nil
			})
			commit, err := g.releaseCommit(context.Background(), "demo/game", "release/v1")
			if kind == "lightweight" || kind == "annotated" {
				if err != nil || commit != testSourceCommit {
					t.Fatalf("exact tag commit not resolved: %s %v", commit, err)
				}
			} else if err == nil || commit != "" {
				t.Fatal("unverified source accepted")
			}
			if calls > 9 {
				t.Fatal("unbounded annotated tag traversal")
			}
		})
	}
}

func TestSourceFailureKeepsGameAndRetriesWithoutUploadingBinaryAlone(t *testing.T) {
	for _, failure := range []string{"missing tag", "bad ZIP", "truncated ZIP", "CRC", "wrong commit", "size mismatch", "oversized", "foreign redirect"} {
		t.Run(failure, func(t *testing.T) {
			a, downloads, binary := prepareTransferApp(t)
			drives := automationIntegrationDrives(a, binary)
			apiTransport, publicTransport := a.github.client.Transport, a.transfers.client.Transport
			bad := atomic.Bool{}
			bad.Store(true)
			if failure == "missing tag" {
				a.github.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
					if bad.Load() && strings.Contains(r.URL.Path, "/git/ref/tags/") {
						return apiResponse(404, `{}`), nil
					}
					return apiTransport.RoundTrip(r)
				})
			}
			a.transfers.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
				if r.URL.Host == "evil.example" {
					t.Error("followed foreign source redirect")
					return nil, errors.New("foreign")
				}
				if r.URL.Host != "codeload.github.com" || !bad.Load() || failure == "missing tag" {
					return publicTransport.RoundTrip(r)
				}
				archive := testSourceZIP(t, "OpenRCT2/OpenRCT2")
				response := apiResponse(200, string(archive))
				response.ContentLength = int64(len(archive))
				switch failure {
				case "bad ZIP":
					response = apiResponse(200, "not zip")
					response.ContentLength = 7
				case "truncated ZIP":
					response = apiResponse(200, string(archive[:len(archive)-10]))
					response.ContentLength = -1
				case "CRC":
					central := bytes.Index(archive, []byte{0x50, 0x4b, 0x01, 0x02})
					archive[central+16] ^= 0x1f
					response = apiResponse(200, string(archive))
					response.ContentLength = int64(len(archive))
				case "wrong commit":
					archive = bytes.ReplaceAll(archive, []byte(testSourceCommit), []byte(strings.Repeat("9", 40)))
					response = apiResponse(200, string(archive))
					response.ContentLength = int64(len(archive))
				case "size mismatch":
					response.ContentLength++
				case "oversized":
					response.ContentLength = maxSourceBytes + 1
				case "foreign redirect":
					response = apiResponse(302, "")
					response.Header.Set("Location", "https://evil.example/source.zip")
				}
				return response, nil
			})
			id := enqueueTest(t, a, "baidu", "quark")
			failed := waitTransfer(t, a, id, "failed")
			if failed.BundleVersion != 0 || failed.LocalDeletedAt != "" || failed.Error == "" {
				t.Fatal("source failure was hidden")
			}
			if data, err := os.ReadFile(failed.DownloadPath); err != nil || string(data) != binary {
				t.Fatal("source failure lost original game download")
			}
			for _, drive := range drives {
				if uploads, shares := drive.counts(); uploads != 0 || shares != 0 {
					t.Fatal("uploaded binary without corresponding source")
				}
			}
			bad.Store(false)
			if err := a.transfers.action(id, "retry"); err != nil {
				t.Fatal(err)
			}
			cleaned := waitLocalCleanup(t, a, id)
			if downloads.Load() != 1 || !hasSourceBundle(cleaned) || len(cleaned.LocalRemovedFiles) != 3 {
				t.Fatal("retry did not reuse binary or complete bundle cleanup")
			}
			for _, target := range []string{cleaned.DownloadPath, cleaned.SourcePath, cleaned.BundlePath} {
				if _, err := os.Stat(target); !errors.Is(err, os.ErrNotExist) {
					t.Fatal("completed two-drive job retained managed file", target)
				}
			}
		})
	}
}

func TestSourcePublicOriginAndRedirectCredentials(t *testing.T) {
	for _, raw := range []string{"http://codeload.github.com/demo/game/zip/" + testSourceCommit, "https://user@codeload.github.com/demo/game/zip/" + testSourceCommit, "https://codeload.github.com:443/demo/game/zip/" + testSourceCommit, "https://codeload.github.com/demo/game/zip/main", "https://codeload.github.com/demo/game/zip/" + testSourceCommit + "?token=secret", "https://codeload.github.com.evil.test/demo/game/zip/" + testSourceCommit, "https://127.0.0.1/demo/game/zip/" + testSourceCommit} {
		target, _ := url.Parse(raw)
		if validSourceTarget(target) {
			t.Fatalf("unsafe source origin accepted: %s", raw)
		}
	}
	request, _ := http.NewRequest("GET", sourceArchiveURL("demo/game", testSourceCommit), nil)
	request.Header.Set("Authorization", "secret")
	request.Header.Set("Cookie", "secret")
	client := newDownloadClient()
	if err := client.CheckRedirect(request, nil); err != nil || request.Header.Get("Authorization") != "" || request.Header.Get("Cookie") != "" {
		t.Fatal("source redirect leaked a credential or rejected official archive")
	}
}

func TestLegacySingleFileShareIsPreservedButNewTaskUploadsSourceBundle(t *testing.T) {
	a, downloads, binary := prepareTransferApp(t)
	old := waitTransfer(t, a, enqueueTest(t, a), "done")
	if err := a.transfers.modify(old.ID, func(j *TransferJob) {
		j.Providers = []string{"quark"}
		j.Outputs["quark"] = TransferOutput{Status: "done", Session: "q", File: CloudFile{ID: "legacy-binary"}, Share: CloudShare{URL: "https://pan.quark.cn/s/legacy-binary"}}
	}, true); err != nil {
		t.Fatal(err)
	}
	drive := &fakeCloudDrive{id: "quark", content: binary}
	a.cloud.accounts["quark"] = cloudAccount{drive: drive, session: "q"}
	fresh := waitTransfer(t, a, enqueueTest(t, a, "quark"), "done")
	unchanged, _ := a.transfers.job(old.ID)
	if unchanged.BundleVersion != 0 || unchanged.Outputs["quark"].Share.URL != "https://pan.quark.cn/s/legacy-binary" || fresh.Outputs["quark"].File.ID == "legacy-binary" || fresh.BundleVersion != 1 || downloads.Load() != 1 {
		t.Fatal("legacy share reused as a source bundle or changed without user action")
	}
	if err := a.transfers.action(old.ID, "retry"); err != nil {
		t.Fatal(err)
	}
	upgraded := waitTransfer(t, a, old.ID, "done")
	if upgraded.LegacyOutputs["quark"].File.ID != "legacy-binary" || upgraded.Outputs["quark"].PayloadSHA256 != upgraded.BundleSHA256 {
		t.Fatal("explicit legacy retry lost old link or skipped new bundle upload")
	}
	if uploads, _ := drive.counts(); uploads != 2 {
		t.Fatal("legacy binary remote result treated as bundle")
	}
}

func TestSourceBundleCleanupCrashReceiptAndOtherTaskReferences(t *testing.T) {
	a, _, binary := prepareTransferApp(t)
	drives := automationIntegrationDrives(a, binary)
	drives["baidu"].shareFails = 1
	job := waitTransfer(t, a, enqueueTest(t, a, "baidu", "quark"), "partial")
	a.cancel()
	// No worker now: share completion and partial removal simulate a process
	// stopping between individual filesystem removal and its state checkpoint.
	job.Outputs["baidu"] = job.Outputs["quark"]
	output := job.Outputs["baidu"]
	output.Share.URL = "https://pan.baidu.com/s/complete"
	job.Outputs["baidu"] = output
	job.Status, job.LocalCleanupPending = "done", true
	job.LocalCleanupIntents = map[string]string{"binary": job.SHA256}
	if err := os.Remove(job.DownloadPath); err != nil {
		t.Fatal(err)
	}
	m, err := newTransferManager(a)
	if err != nil {
		t.Fatal(err)
	}
	// Use a live context for the isolated cleanup worker.
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	a.ctx = ctx
	a.transfers = m
	saveCleanupJobs(t, m, job)
	m.cleanupLocalFiles()
	cleaned, _ := m.job(job.ID)
	if cleaned.LocalDeletedAt == "" || len(cleaned.LocalRemovedFiles) != 3 {
		t.Fatal("restart did not complete per-file cleanup receipts")
	}
	for _, artifact := range transferArtifacts(job) {
		if _, err := os.Stat(artifact.path); !errors.Is(err, os.ErrNotExist) {
			t.Fatal("remaining source/bundle not cleaned")
		}
	}
	if err := os.WriteFile(job.SourcePath, []byte("new user file"), 0600); err != nil {
		t.Fatal(err)
	}
	m.cleanupLocalFiles()
	if data, err := os.ReadFile(job.SourcePath); err != nil || string(data) != "new user file" {
		t.Fatal("cleanup repeated on replacement source file")
	}
}

func TestSourceBundleRefusesChangedSourceAndKeepsUnrelatedFiles(t *testing.T) {
	a, downloads, binary := prepareTransferApp(t)
	drives := automationIntegrationDrives(a, binary)
	drives["quark"].shareFails = 1
	job := waitTransfer(t, a, enqueueTest(t, a, "baidu", "quark"), "partial")
	unrelated := filepath.Join(filepath.Dir(job.SourcePath), "personal.txt")
	if err := os.WriteFile(unrelated, []byte("keep"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(job.SourcePath, bytes.Repeat([]byte("x"), int(job.SourceSize)), 0600); err != nil {
		t.Fatal(err)
	}
	if err := a.transfers.action(job.ID, "retry"); err != nil {
		t.Fatal(err)
	}
	waitTransfer(t, a, job.ID, "done")
	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) {
		current, _ := a.transfers.job(job.ID)
		if current.LocalCleanupError != "" {
			if current.LocalDeletedAt != "" {
				t.Fatal("modified source marked as removed")
			}
			if data, err := os.ReadFile(job.SourcePath); err != nil || len(data) != int(job.SourceSize) {
				t.Fatal("modified source removed")
			}
			if data, err := os.ReadFile(unrelated); err != nil || string(data) != "keep" {
				t.Fatal("unrelated file changed")
			}
			a.aigc.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
				item := readyFixture(job.Repo)
				item.GameNameZh = "过山车大亨2"
				encoded, _ := json.Marshal(DescriptionsResponse{Items: []Description{item}})
				return apiResponse(200, string(encoded)), nil
			})
			if err := a.transfers.modify(job.ID, func(j *TransferJob) { j.Enrich = true; j.Description = "" }, true); err != nil {
				t.Fatal(err)
			}
			if err := a.transfers.action(job.ID, "retry"); err != nil {
				t.Fatal(err)
			}
			enriched := waitTransfer(t, a, job.ID, "done")
			if downloads.Load() != 1 || enriched.Description == "" || enriched.GameNameZh == "" {
				t.Fatal("metadata retry redownloaded files after partial cleanup")
			}
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatal("modified source preservation not reported")
}

func TestSourceArchiveCanonicalCaseAndSafeLicenseCopies(t *testing.T) {
	m := automationTestManager(t).app.transfers
	canonical := testSourceZIP(t, "OpenRCT2/OpenRCT2")
	file, err := os.CreateTemp(t.TempDir(), "source-*")
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	if _, err := file.Write(canonical); err != nil {
		t.Fatal(err)
	}
	licenses, err := validateSourceZIP(context.Background(), file, int64(len(canonical)), "openrct2/openrct2", testSourceCommit)
	if err != nil || len(licenses) != 1 || string(licenses["LICENSE"]) != "Original upstream license. Preserve exactly.\n" {
		t.Fatal("canonical repository case rejected or license bytes changed", err)
	}
	if _, err := validateSourceZIP(context.Background(), file, int64(len(canonical)), "openrct2/openrct2", strings.ToUpper(testSourceCommit)); err == nil {
		t.Fatal("commit case/identity changed")
	}
	var buffer bytes.Buffer
	writer := zip.NewWriter(&buffer)
	prefix := "game-" + testSourceCommit + "/"
	for _, name := range []string{"LICENSE", "LICENSE:stream", "LICENSE.", "COPYING-link"} {
		header := &zip.FileHeader{Name: prefix + name, Method: zip.Store}
		if name == "COPYING-link" {
			header.SetMode(os.ModeSymlink | 0777)
		}
		member, err := writer.CreateHeader(header)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := member.Write([]byte("original license bytes")); err != nil {
			t.Fatal(err)
		}
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(m.downloadDir, randomID())
	if err := os.Mkdir(target, 0700); err != nil {
		t.Fatal(err)
	}
	archive, err := os.Create(filepath.Join(target, "source.zip"))
	if err != nil {
		t.Fatal(err)
	}
	defer archive.Close()
	if _, err := archive.Write(buffer.Bytes()); err != nil {
		t.Fatal(err)
	}
	copies, err := validateSourceZIP(context.Background(), archive, int64(buffer.Len()), "demo/game", testSourceCommit)
	if err != nil || len(copies) != 1 || string(copies["LICENSE"]) != "original license bytes" {
		t.Fatalf("unsafe top-level license copy accepted: %v %v", copies, err)
	}
	members := readZIPMembers(t, buffer.Bytes())
	if len(members) != 4 {
		t.Fatal("original source entries should remain intact")
	}
}

func TestTransferDetailsPreserveCompletedIdentityOnLegacyFallback(t *testing.T) {
	job := TransferJob{Repo: "demo/game", Description: "以前的中文简介。", GameNameZh: "原有游戏名", GameNameOriginal: "Original Game", PosterURL: "https://raw.githubusercontent.com/demo/game/main/cover.png", PosterSourceURL: "https://github.com/demo/game", PosterKind: "cover", DetailsVersion: gameDetailsVersion}
	item := readyFixture(job.Repo)
	item.DetailsVersion = 0
	item.GameNameZh = "错误覆盖"
	item.PosterURL = "https://evil.example/cover.jpg"
	applyTransferDetails(&job, item)
	if job.GameNameZh != "原有游戏名" || job.DetailsVersion != gameDetailsVersion || !validGamePoster(job.Repo, job.PosterURL) {
		t.Fatal("legacy fallback erased completed or accepted unsafe identity")
	}
}

func TestLocalOnlyTaskAfterCleanedBundleDownloadsOnlyOriginalAsset(t *testing.T) {
	a, downloads, binary := prepareTransferApp(t)
	automationIntegrationDrives(a, binary)
	waitLocalCleanup(t, a, enqueueTest(t, a, "baidu", "quark"))
	local := waitTransfer(t, a, enqueueTest(t, a), "done")
	if local.BundleVersion != 0 || local.BundlePath != "" || local.SourcePath != "" || local.LocalDeletedAt != "" || downloads.Load() != 2 {
		t.Fatal("local-only task inherited a deleted sharing package")
	}
	if data, err := os.ReadFile(local.DownloadPath); err != nil || string(data) != binary {
		t.Fatal("local-only original asset unavailable")
	}
}

func TestSourceArchiveExpandedByteLimit(t *testing.T) {
	var buffer bytes.Buffer
	writer := zip.NewWriter(&buffer)
	header := &zip.FileHeader{Name: "game-" + testSourceCommit + "/huge.bin", Method: zip.Store, UncompressedSize64: maxSourceExpandedBytes + 1, CompressedSize64: 0}
	if _, err := writer.CreateRaw(header); err != nil {
		t.Fatal(err)
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	file, err := os.CreateTemp(t.TempDir(), "source-*")
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	if _, err := file.Write(buffer.Bytes()); err != nil {
		t.Fatal(err)
	}
	if _, err := validateSourceZIP(context.Background(), file, int64(buffer.Len()), "demo/game", testSourceCommit); err == nil || !strings.Contains(err.Error(), "8 GiB") {
		t.Fatal("expanded source bound not enforced", err)
	}
}
