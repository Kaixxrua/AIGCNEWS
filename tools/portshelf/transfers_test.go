package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

type fakeCloudDrive struct {
	mu         sync.Mutex
	id         string
	uploads    int
	shares     int
	shareFails int
	checkError error
	content    string
}

func (d *fakeCloudDrive) Check(context.Context) (string, error) {
	return d.id + " test account", d.checkError
}
func (d *fakeCloudDrive) Upload(ctx context.Context, path, remote string, progress UploadProgress) (CloudFile, error) {
	d.mu.Lock()
	defer d.mu.Unlock()
	if ctx.Err() != nil {
		return CloudFile{}, ctx.Err()
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return CloudFile{}, err
	}
	if string(data) != d.content || !validDownloadName(remote) {
		return CloudFile{}, errors.New("wrong uploaded bytes/name")
	}
	d.uploads++
	progress(int64(len(data)), int64(len(data)))
	return CloudFile{ID: d.id + "-file", Name: remote, Path: "/PortShelf/" + remote}, nil
}
func (d *fakeCloudDrive) Share(ctx context.Context, file CloudFile, options ShareOptions) (CloudShare, error) {
	d.mu.Lock()
	defer d.mu.Unlock()
	d.shares++
	if d.shareFails > 0 {
		d.shareFails--
		return CloudShare{}, errors.New("temporary share failure")
	}
	host := "pan." + d.id + ".cn"
	if d.id == "baidu" {
		host = "pan.baidu.com"
	}
	return CloudShare{URL: "https://" + host + "/s/" + file.ID, Code: "1234"}, nil
}
func (d *fakeCloudDrive) counts() (int, int) {
	d.mu.Lock()
	defer d.mu.Unlock()
	return d.uploads, d.shares
}

func prepareTransferApp(t *testing.T) (*App, *atomic.Int64, string) {
	t.Helper()
	a := testApp(t)
	content := "known public Windows release bytes"
	sum := sha256.Sum256([]byte(content))
	digest := hex.EncodeToString(sum[:])
	release := Release{Tag: "v1.0", URL: "https://github.com/OpenRCT2/OpenRCT2/releases/tag/v1.0",
		Assets: []Asset{{ID: 321, Name: "game-windows-x64.zip", Size: int64(len(content)),
			URL: "https://github.com/OpenRCT2/OpenRCT2/releases/download/v1.0/game-windows-x64.zip", Digest: "sha256:" + digest}}}
	body, _ := json.Marshal(release)
	a.github.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		if !strings.HasSuffix(r.URL.Path, "/releases/latest") {
			t.Errorf("unexpected API request: %s", r.URL.Path)
		}
		return apiResponse(200, string(body)), nil
	})
	calls := &atomic.Int64{}
	a.transfers.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		calls.Add(1)
		if r.Header.Get("Authorization") != "" || r.Header.Get("Cookie") != "" {
			t.Error("credential attached to public download")
		}
		response := apiResponse(200, content)
		response.ContentLength = int64(len(content))
		return response, nil
	})
	return a, calls, content
}

func waitTransfer(t *testing.T, a *App, id string, statuses ...string) TransferJob {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		job, _ := a.transfers.job(id)
		for _, status := range statuses {
			if job.Status == status {
				a.transfers.mu.Lock()
				active := a.transfers.activeID
				a.transfers.mu.Unlock()
				if active != id {
					return job
				}
			}
		}
		time.Sleep(5 * time.Millisecond)
	}
	jobs, failure := a.transfers.snapshot()
	t.Fatalf("task did not finish: %+v store=%s", jobs, failure)
	return TransferJob{}
}

func enqueueTest(t *testing.T, a *App, providers ...string) string {
	t.Helper()
	added, _, err := a.transfers.enqueue(TransferRequest{Repos: []string{"OpenRCT2/OpenRCT2"}, Arch: "amd64", Providers: providers})
	if err != nil || len(added) != 1 {
		t.Fatalf("enqueue: %v %v", added, err)
	}
	return added[0]
}

func TestTransferDownloadThenConnectBothDrivesAndResume(t *testing.T) {
	a, calls, content := prepareTransferApp(t)
	a.github.setToken("must-not-reach-download")
	id := enqueueTest(t, a, "baidu", "quark")
	job := waitTransfer(t, a, id, "waiting_auth")
	if job.SHA256 == "" || len(job.Outputs) != 2 {
		t.Fatalf("download did not checkpoint before auth: %+v", job)
	}
	b, err := os.ReadFile(job.DownloadPath)
	if err != nil || string(b) != content {
		t.Fatalf("download artifact: %q %v", b, err)
	}
	drives := map[string]*fakeCloudDrive{
		"baidu": {id: "baidu", content: content}, "quark": {id: "quark", content: content},
	}
	a.cloud.factory = func(provider string, c CloudCredentials) CloudDrive { return drives[provider] }
	for provider, body := range map[string]string{"baidu": `{"cookie":"BDUSS=never-persist-this"}`, "quark": `{"authCode":"never-persist-quark-code"}`} {
		w := call(a, "POST", "/api/cloud/"+provider, body)
		if w.Code != 200 || strings.Contains(w.Body.String(), "never-persist") {
			t.Fatalf("configure cloud: %d %s", w.Code, w.Body)
		}
	}
	if w := call(a, "POST", "/api/transfers/"+id+"/retry", `{}`); w.Code != 202 {
		t.Fatal(w.Body.String())
	}
	job = waitTransfer(t, a, id, "done")
	if calls.Load() != 1 || job.Outputs["baidu"].Share.URL == "" || job.Outputs["quark"].Share.URL == "" {
		t.Fatalf("resume repeated download or lost a share: calls=%d %+v", calls.Load(), job)
	}
	for _, d := range drives {
		uploads, shares := d.counts()
		if uploads != 1 || shares != 1 {
			t.Fatalf("unexpected remote work: %d %d", uploads, shares)
		}
	}
	for _, path := range []string{"transfers.json", "library.json"} {
		data, _ := os.ReadFile(filepath.Join(a.lib.root, path))
		if strings.Contains(string(data), "never-persist") {
			t.Fatal("cloud credential persisted")
		}
	}
	for _, route := range []string{"/api/cloud", "/api/transfers", "/api/transfers/export?format=json"} {
		w := call(a, "GET", route, "")
		if w.Code != 200 || strings.Contains(w.Body.String(), "never-persist") {
			t.Fatalf("read/export leaked credentials: %s", route)
		}
	}
}

func TestTransferShareRetrySkipsSuccessfulUploadAndOtherDrive(t *testing.T) {
	a, calls, content := prepareTransferApp(t)
	baidu := &fakeCloudDrive{id: "baidu", content: content, shareFails: 1}
	quark := &fakeCloudDrive{id: "quark", content: content}
	a.cloud.accounts = map[string]cloudAccount{
		"baidu": {drive: baidu, session: "b"}, "quark": {drive: quark, session: "q"},
	}
	id := enqueueTest(t, a, "baidu", "quark")
	partial := waitTransfer(t, a, id, "partial")
	if partial.Outputs["baidu"].File.ID == "" || partial.Outputs["quark"].Status != "done" {
		t.Fatalf("partial work lost: %+v", partial.Outputs)
	}
	if data, err := os.ReadFile(partial.DownloadPath); err != nil || string(data) != content || partial.LocalDeletedAt != "" {
		t.Fatal("one failed share must keep the local file")
	}
	if err := a.transfers.action(id, "retry"); err != nil {
		t.Fatal(err)
	}
	waitLocalCleanup(t, a, id)
	bUploads, bShares := baidu.counts()
	qUploads, qShares := quark.counts()
	if bUploads != 1 || bShares != 2 || qUploads != 1 || qShares != 1 || calls.Load() != 1 {
		t.Fatalf("retry repeated successful steps: %d %d %d %d downloads=%d", bUploads, bShares, qUploads, qShares, calls.Load())
	}
}

func TestTransferNewTaskForSameReleaseReusesVerifiedArtifactAndLinks(t *testing.T) {
	a, calls, content := prepareTransferApp(t)
	drive := &fakeCloudDrive{id: "quark", content: content}
	a.cloud.accounts["quark"] = cloudAccount{drive: drive, session: "q"}
	first := waitTransfer(t, a, enqueueTest(t, a, "quark"), "done")
	second := waitTransfer(t, a, enqueueTest(t, a, "quark"), "done")
	uploads, shares := drive.counts()
	if calls.Load() != 1 || uploads != 1 || shares != 1 || first.DownloadPath != second.DownloadPath {
		t.Fatalf("identical release duplicated: downloads=%d uploads=%d shares=%d", calls.Load(), uploads, shares)
	}
}

func TestTransferRestartPausesWorkKeepsFilesButNotCredentials(t *testing.T) {
	a, _, _ := prepareTransferApp(t)
	id := enqueueTest(t, a, "baidu")
	first := waitTransfer(t, a, id, "waiting_auth")
	a.cancel()
	other, err := newApp(a.lib)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(other.cancel)
	job, ok := other.transfers.job(id)
	if !ok || job.Status != "paused" || job.DownloadPath != first.DownloadPath {
		t.Fatalf("restart state: %+v", job)
	}
	for _, status := range other.cloud.statuses() {
		if status.Configured {
			t.Fatal("credential restored unexpectedly")
		}
	}
	called := false
	other.transfers.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		called = true
		return nil, errors.New("must reuse")
	})
	path, _, err := other.transfers.download(context.Background(), job, func(int64, int64) {})
	if called || err != nil || path != first.DownloadPath {
		t.Fatalf("restart failed to reuse verified file: %v", err)
	}
}

func TestTransferCancellationKeepsStatusAndQueueContinues(t *testing.T) {
	a, _, _ := prepareTransferApp(t)
	started := make(chan struct{})
	a.transfers.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		close(started)
		<-r.Context().Done()
		return nil, r.Context().Err()
	})
	id := enqueueTest(t, a)
	select {
	case <-started:
	case <-time.After(time.Second):
		t.Fatal("download never started")
	}
	if err := a.transfers.action(id, "cancel"); err != nil {
		t.Fatal(err)
	}
	job := waitTransfer(t, a, id, "cancelled")
	if job.DownloadPath != "" {
		t.Fatal("partial file presented as completed download")
	}
}

func TestTransferValidationAndQueueSaveFailureDoNotStartIO(t *testing.T) {
	a, calls, _ := prepareTransferApp(t)
	for _, body := range []string{
		`{"repos":[],"arch":"amd64"}`,
		`{"repos":["unknown/repo"],"arch":"amd64"}`,
		`{"repos":["OpenRCT2/OpenRCT2"],"arch":"linux"}`,
		`{"repos":["OpenRCT2/OpenRCT2"],"arch":"amd64","providers":["evil"]}`,
		`{"repos":["OpenRCT2/OpenRCT2"],"arch":"amd64","providers":["baidu","baidu"]}`,
		`{"repos":["OpenRCT2/OpenRCT2"],"arch":"amd64","providers":["baidu"],"privateShare":false}`,
		`{"repos":["OpenRCT2/OpenRCT2"],"arch":"amd64","shareCode":"123"}`,
		`{"repos":["OpenRCT2/OpenRCT2"],"arch":"amd64","shareDays":999}`,
		`{"repos":["OpenRCT2/OpenRCT2"],"arch":"amd64","downloadPath":"/tmp/arbitrary"}`,
	} {
		if w := call(a, "POST", "/api/transfers", body); w.Code != 400 {
			t.Errorf("invalid request accepted: %s: %d", body, w.Code)
		}
	}
	if err := os.Mkdir(filepath.Join(a.lib.root, "transfers.json"), 0700); err != nil {
		t.Fatal(err)
	}
	_, _, err := a.transfers.enqueue(TransferRequest{Repos: []string{"OpenRCT2/OpenRCT2"}, Arch: "amd64"})
	jobs, _ := a.transfers.snapshot()
	if err == nil || len(jobs) != 0 || calls.Load() != 0 {
		t.Fatal("failed state save still published work")
	}
}

func TestTransferExportCSVNeutralizesFormulaAndOmitsAuth(t *testing.T) {
	a, _, _ := prepareTransferApp(t)
	job := waitTransfer(t, a, enqueueTest(t, a), "done")
	if err := a.transfers.modify(job.ID, func(j *TransferJob) {
		j.Name, j.Description = "=HYPERLINK(\"evil\")", "\t=1+1"
	}, true); err != nil {
		t.Fatal(err)
	}
	csv := call(a, "GET", "/api/transfers/export?format=csv", "")
	if csv.Code != 200 || !strings.Contains(csv.Body.String(), "'=HYPERLINK") || !strings.Contains(csv.Body.String(), "'\t=1+1") {
		t.Fatalf("unsafe CSV: %s", csv.Body.String())
	}
	for _, format := range []string{"json", "markdown"} {
		w := call(a, "GET", "/api/transfers/export?format="+format, "")
		if w.Code != 200 || !strings.Contains(w.Header().Get("Content-Disposition"), "attachment") {
			t.Fatalf("missing usable export: %s", format)
		}
	}
	if w := call(a, "POST", "/api/transfers/clear", `{}`); w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	jobs, _ := a.transfers.snapshot()
	if len(jobs) != 0 {
		t.Fatal("completed task did not clear")
	}
	if _, err := os.Stat(job.DownloadPath); err != nil {
		t.Fatal("clearing task history deleted downloaded file")
	}
}

func TestCloudCredentialRoutesValidateAndClearMemory(t *testing.T) {
	a := testApp(t)
	for _, c := range []CloudCredentials{{Cookie: "bad\r\nvalue"}, {AccessToken: strings.Repeat("x", 12001)}, {AuthCode: "非ASCII"}} {
		if validCloudCredentials(c) {
			t.Fatal("invalid credential accepted")
		}
	}
	for _, tc := range []struct{ id, body string }{
		{"other", `{"cookie":"x"}`}, {"baidu", `{"accessToken":"x"}`}, {"quark", `{"cookie":"x"}`},
		{"quark", `{"accessToken":"x","authCode":"y"}`},
	} {
		if w := call(a, "POST", "/api/cloud/"+tc.id, tc.body); w.Code < 400 {
			t.Fatal("wrong credential mode accepted")
		}
	}
	a.cloud.accounts["baidu"] = cloudAccount{drive: &fakeCloudDrive{id: "baidu"}, session: "b"}
	if w := call(a, "POST", "/api/cloud/baidu", `{}`); w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	if _, found := a.cloud.get("baidu"); found {
		t.Fatal("cleared credential still accessible")
	}
	a.cloud.factory = func(string, CloudCredentials) CloudDrive {
		return &fakeCloudDrive{checkError: errors.New("login rejected")}
	}
	if w := call(a, "POST", "/api/cloud/baidu", `{"cookie":"BDUSS=test"}`); w.Code != 502 {
		t.Fatal("failed login accepted")
	}
	if _, found := a.cloud.get("baidu"); found {
		t.Fatal("failed login changed account")
	}
}

func TestTransferStateRejectsArbitraryFileAndShareURL(t *testing.T) {
	for _, mutate := range []func(*TransferJob){
		func(j *TransferJob) { j.DownloadPath = "/etc/passwd" },
		func(j *TransferJob) {
			j.Outputs["quark"] = TransferOutput{Share: CloudShare{URL: "https://evil.example/s/leak"}}
		},
		func(j *TransferJob) { j.Asset.URL = "http://127.0.0.1/private" },
	} {
		t.Run("unsafe saved state", func(t *testing.T) {
			a, _, _ := prepareTransferApp(t)
			job := waitTransfer(t, a, enqueueTest(t, a), "done")
			a.cancel()
			mutate(&job)
			data, _ := json.Marshal([]TransferJob{job})
			if err := os.WriteFile(filepath.Join(a.lib.root, "transfers.json"), data, 0600); err != nil {
				t.Fatal(err)
			}
			if other, err := newApp(a.lib); err == nil {
				other.cancel()
				t.Fatal("unsafe saved transfer accepted")
			}
		})
	}
}

func TestTransferMissingChineseDescriptionDoesNotBlockDownload(t *testing.T) {
	a, calls, _ := prepareTransferApp(t)
	a.catalog[0].Description = "English only"
	repo := a.catalog[0].Repo
	a.github.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		return apiResponse(404, `{}`), nil
	})
	// Directly exercise enrichment on a pinned task, without a real model call.
	a.transfers.mu.Lock()
	job := TransferJob{ID: randomID(), Repo: repo, Status: "running", Warnings: []string{}, Outputs: map[string]TransferOutput{}}
	a.transfers.jobs = append(a.transfers.jobs, job)
	a.transfers.mu.Unlock()
	a.aigc.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		if r.Method != "GET" {
			t.Error("generation requested without an AIGC token")
		}
		return &http.Response{StatusCode: 503, Body: io.NopCloser(strings.NewReader("{}")), Header: http.Header{}}, nil
	})
	if err := a.transfers.enrich(context.Background(), job); err != nil {
		t.Fatal(err)
	}
	after, _ := a.transfers.job(job.ID)
	if len(after.Warnings) != 1 || after.Description != "" || calls.Load() != 0 {
		t.Fatalf("missing description misrepresented: %+v", after)
	}
}

func TestTransferAccountChangeRequiresNewUpload(t *testing.T) {
	a, _, content := prepareTransferApp(t)
	old := &fakeCloudDrive{id: "quark", content: content}
	a.cloud.accounts["quark"] = cloudAccount{drive: old, session: "old"}
	waitTransfer(t, a, enqueueTest(t, a, "quark"), "done")
	next := &fakeCloudDrive{id: "quark", content: content}
	a.cloud.factory = func(string, CloudCredentials) CloudDrive { return next }
	if w := call(a, "POST", "/api/cloud/quark", `{"accessToken":"new-account"}`); w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	result := waitTransfer(t, a, enqueueTest(t, a, "quark"), "done")
	count, _ := next.counts()
	current, _ := a.cloud.get("quark")
	if count != 1 || result.Outputs["quark"].Session != current.session {
		t.Fatalf("new-account upload count=%d, task output still uses old account=%t", count, result.Outputs["quark"].Session == "old")
	}
}

type gatedCloudDrive struct {
	*fakeCloudDrive
	checkStarted  chan struct{}
	checkRelease  chan struct{}
	uploadStarted chan struct{}
	uploadRelease chan struct{}
}

func (d *gatedCloudDrive) Check(ctx context.Context) (string, error) {
	if d.checkStarted != nil {
		close(d.checkStarted)
		select {
		case <-d.checkRelease:
		case <-ctx.Done():
			return "", ctx.Err()
		}
	}
	return d.fakeCloudDrive.Check(ctx)
}
func (d *gatedCloudDrive) Upload(ctx context.Context, p, n string, progress UploadProgress) (CloudFile, error) {
	if d.uploadStarted != nil {
		close(d.uploadStarted)
		select {
		case <-d.uploadRelease:
		case <-ctx.Done():
			return CloudFile{}, ctx.Err()
		}
	}
	return d.fakeCloudDrive.Upload(ctx, p, n, progress)
}
func TestTransferAccountCheckCannotSwapDuringActiveUpload(t *testing.T) {
	a, _, content := prepareTransferApp(t)
	old := &gatedCloudDrive{fakeCloudDrive: &fakeCloudDrive{id: "baidu", content: content}, uploadStarted: make(chan struct{}), uploadRelease: make(chan struct{})}
	next := &gatedCloudDrive{fakeCloudDrive: &fakeCloudDrive{id: "baidu", content: content}, checkStarted: make(chan struct{}), checkRelease: make(chan struct{})}
	a.cloud.accounts["baidu"] = cloudAccount{drive: old, session: "old"}
	a.cloud.factory = func(string, CloudCredentials) CloudDrive { return next }
	response := make(chan int, 1)
	go func() { response <- call(a, "POST", "/api/cloud/baidu", `{"cookie":"new-account"}`).Code }()
	select {
	case <-next.checkStarted:
	case <-time.After(time.Second):
		t.Fatal("check did not start")
	}
	id := enqueueTest(t, a, "baidu")
	select {
	case <-old.uploadStarted:
	case <-time.After(time.Second):
		t.Fatal("upload did not start")
	}
	close(next.checkRelease)
	status := <-response
	current, _ := a.cloud.get("baidu")
	switched := current.drive == next
	close(old.uploadRelease)
	waitTransfer(t, a, id, "done")
	if status != 409 || switched {
		t.Fatalf("credential request HTTP=%d; replaced registry while old account upload active=%t", status, switched)
	}
}

func TestTransferCompleteDownloadBeforeCheckpointCanRecover(t *testing.T) {
	a, _, _ := prepareTransferApp(t)
	finished := waitTransfer(t, a, enqueueTest(t, a), "done")
	// Simulates a process exit or state-write failure after atomic file rename,
	// before the download-path/hash checkpoint is published.
	unfinished := finished
	unfinished.DownloadPath = ""
	unfinished.SHA256 = ""
	_, _, err := a.transfers.download(context.Background(), unfinished, func(int64, int64) {})
	if err != nil {
		t.Fatalf("complete file with matching upstream SHA-256 cannot resume: %v", err)
	}
}

func TestTransferRequestedProviderDoesNotInheritOtherProviderOutputs(t *testing.T) {
	a, _, content := prepareTransferApp(t)
	a.cloud.accounts["baidu"] = cloudAccount{drive: &fakeCloudDrive{id: "baidu", content: content}, session: "b"}
	a.cloud.accounts["quark"] = cloudAccount{drive: &fakeCloudDrive{id: "quark", content: content}, session: "q"}
	waitTransfer(t, a, enqueueTest(t, a, "baidu", "quark"), "done")
	second := waitTransfer(t, a, enqueueTest(t, a, "quark"), "done")
	if _, exists := second.Outputs["baidu"]; exists {
		t.Fatal("quark-only task inherited and exports unrequested Baidu share")
	}
}

func TestTransferFailedPinnedTaskCanBeReplaced(t *testing.T) {
	a, _, content := prepareTransferApp(t)
	a.cloud.accounts["baidu"] = cloudAccount{drive: &fakeCloudDrive{id: "baidu", content: content, shareFails: 1}, session: "b"}
	first := waitTransfer(t, a, enqueueTest(t, a, "baidu"), "partial")
	if err := os.WriteFile(first.DownloadPath, []byte(strings.Repeat("x", len(content))), 0600); err != nil {
		t.Fatal(err)
	}
	if err := a.transfers.action(first.ID, "retry"); err != nil {
		t.Fatal(err)
	}
	failed := waitTransfer(t, a, first.ID, "failed")
	if !strings.Contains(failed.Error, "新建任务") {
		t.Fatal(failed.Error)
	}
	if err := a.transfers.action(first.ID, "cancel"); err != nil {
		t.Fatal(err)
	}
	added, skipped, err := a.transfers.enqueue(TransferRequest{Repos: []string{"OpenRCT2/OpenRCT2"}, Arch: "amd64", Providers: []string{"baidu"}})
	if err != nil || len(added) != 1 {
		t.Fatalf("cancelled failure cannot be replaced: added=%v skipped=%v error=%v", added, skipped, err)
	}
	replacement := waitTransfer(t, a, added[0], "done")
	if replacement.DownloadPath == first.DownloadPath {
		t.Fatal("replacement overwrote existing file")
	}
}
