package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// Independent manager tests use the real signed client and a transport that
// accepts only the official origin. No test sends network traffic.
func independentMarketplaceClient(t *testing.T, fn func(*http.Request) (*http.Response, error)) *xgjClient {
	t.Helper()
	api := newXGJClient(xgjVaultTestCredentials())
	api.limiter = &xgjRateLimiter{}
	api.client.Transport = xgjTestTransport(func(r *http.Request) (*http.Response, error) {
		if r.URL.Scheme != "https" || r.URL.Host != "open.goofish.pro" || r.Method != http.MethodPost {
			t.Error("marketplace request escaped the fixed official origin")
			return nil, errors.New("unexpected test request")
		}
		return fn(r)
	})
	return api
}

func independentMarketplaceResponse(data any) *http.Response {
	b, _ := json.Marshal(map[string]any{"code": 0, "data": data})
	return &http.Response{StatusCode: 200, Header: make(http.Header), Body: io.NopCloser(bytes.NewReader(b))}
}

func independentMarketplaceShops(now time.Time) *http.Response {
	return independentMarketplaceResponse(map[string]any{"list": []map[string]any{{"authorize_id": 81, "user_name": "test-shop", "is_valid": true, "authorize_expires": now.Add(time.Hour).Unix(), "valid_end_time": now.Add(time.Hour).Unix()}}})
}

func independentMarketplaceFixture(t *testing.T, status string) (*marketplaceManager, MarketplaceJob) {
	t.Helper()
	app := newCredentialTestApp(t)
	m, err := newMarketplace(app)
	if err != nil {
		t.Fatal(err)
	}
	app.marketplace = m
	now := time.Now().UTC().Truncate(time.Second)
	m.now = func() time.Time { return now }
	m.restoreCredentials(xgjVaultTestCredentials())
	config := MarketplaceConfig{Enabled: true, ShopUserName: "test-shop", ItemBizType: 2, SpBizType: 22, CategoryID: "test-category", Properties: []MarketplaceProperty{}, Province: 110000, City: 110100, District: 110101, PriceFen: 100, Stock: 1}
	transfer := TransferJob{ID: randomID(), Repo: "test/game", Name: "测试游戏", GameNameZh: "测试游戏", Version: "v1", Arch: "amd64", Status: "done", Stage: "done", Providers: []string{"baidu", "quark"}, Description: "这是一款测试用的开源冒险游戏。", DetailsVersion: gameDetailsVersion,
		PosterURL: "https://aigcnews.cn/api/media/site/game-posters/" + strings.Repeat("a", 64) + ".jpg", DataNote: "需要自备原作文件。", Guide: "解压后运行。", SourceCommit: strings.Repeat("a", 40), SourceSHA256: strings.Repeat("b", 64), SourceSize: 100, BundleVersion: sourceBundleVersion, BundleSHA256: strings.Repeat("c", 64), BundleSize: 200}
	transfer.SourceURL = sourceArchiveURL(transfer.Repo, transfer.SourceCommit)
	transfer.SourcePath = filepath.Join(app.transfers.downloadDir, transfer.ID, "source.zip")
	transfer.BundlePath = filepath.Join(app.transfers.downloadDir, transfer.ID, "bundle.zip")
	transfer.Outputs = map[string]TransferOutput{
		"baidu": {Status: "done", Session: strings.Repeat("d", 48), File: CloudFile{ID: "test-baidu-file"}, PayloadSHA256: transfer.BundleSHA256, Share: CloudShare{URL: "https://pan.baidu.com/s/test", Code: "1234"}},
		"quark": {Status: "done", Session: strings.Repeat("e", 48), File: CloudFile{ID: "test-quark-file"}, PayloadSHA256: transfer.BundleSHA256, Share: CloudShare{URL: "https://pan.quark.cn/s/test", Code: "5678"}},
	}
	app.transfers.jobs = []TransferJob{transfer}
	outer := marketplaceOuterID(xgjVaultTestCredentials(), config, transfer)
	payload, title, content, err := marketplacePayload(transfer, config, outer)
	if err != nil {
		t.Fatal(err)
	}
	job := MarketplaceJob{ID: randomID(), TransferID: transfer.ID, Repo: transfer.Repo, Title: title, Content: content, PosterURL: transfer.PosterURL, Status: status, Config: config, ShopUserName: config.ShopUserName, PriceFen: config.PriceFen, OuterID: outer, AccountFingerprint: marketplaceFingerprint(xgjVaultTestCredentials()), BundleSHA256: transfer.BundleSHA256, Payload: payload, CreatedAt: now.Format(time.RFC3339), UpdatedAt: now.Format(time.RFC3339)}
	m.state.Config, m.state.Jobs = config, []MarketplaceJob{job}
	if err := m.saveLocked(m.state); err != nil {
		t.Fatal(err)
	}
	return m, job
}

func independentMarketplaceRestart(t *testing.T, previous *marketplaceManager, api *xgjClient) *marketplaceManager {
	t.Helper()
	m, err := newMarketplace(previous.app)
	if err != nil {
		t.Fatal(err)
	}
	m.now = previous.now
	m.restoreCredentials(xgjVaultTestCredentials())
	m.api = api
	previous.app.marketplace = m
	return m
}

func independentMarketplaceDiskJob(t *testing.T, m *marketplaceManager) MarketplaceJob {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(m.app.lib.root, "marketplace.json"))
	var state marketplaceState
	if err != nil || json.Unmarshal(data, &state) != nil || len(state.Jobs) != 1 {
		t.Fatalf("cannot read durable marketplace record: %v", err)
	}
	return state.Jobs[0]
}

func TestMarketplaceIndependentCreateRequiresDurableIntent(t *testing.T) {
	m, job := independentMarketplaceFixture(t, "queued")
	var creates int
	m.api = independentMarketplaceClient(t, func(r *http.Request) (*http.Response, error) {
		if r.URL.Path == xgjShopsPath {
			return independentMarketplaceShops(m.now()), nil
		}
		creates++
		return nil, errors.New("unexpected creation before durable intent")
	})
	m.write = func(string, string, []byte) error { return errors.New("simulated full disk") }
	if err := m.step(context.Background(), job.ID); err == nil {
		t.Fatal("failed intent write was ignored")
	}
	disk := independentMarketplaceDiskJob(t, m)
	if creates != 0 || disk.Status != "queued" || disk.CreateIssuedAt != "" {
		t.Fatal("remote creation ran before its durable intent or changed prior state")
	}
}

func TestMarketplaceIndependentCreateReceiptWriteFailureRestartsReadOnly(t *testing.T) {
	m, job := independentMarketplaceFixture(t, "queued")
	var creates, lists int
	failReceipt := false
	m.write = func(root, name string, data []byte) error {
		if failReceipt {
			return errors.New("simulated receipt write failure")
		}
		return automationWriteFile(root, name, data)
	}
	api := independentMarketplaceClient(t, func(r *http.Request) (*http.Response, error) {
		switch r.URL.Path {
		case xgjShopsPath:
			return independentMarketplaceShops(m.now()), nil
		case xgjCreatePath:
			creates++
			disk := independentMarketplaceDiskJob(t, m)
			if disk.Status != "creating" || disk.CreateIssuedAt == "" {
				t.Fatal("create request preceded its durable intent")
			}
			failReceipt = true
			return independentMarketplaceResponse(map[string]any{"product_id": 101, "product_status": 21}), nil
		case xgjProductsPath:
			lists++
			return independentMarketplaceResponse(map[string]any{"list": []map[string]any{{"product_id": 101, "outer_id": job.OuterID}}, "count": 1, "page_no": 1, "page_size": 100}), nil
		default:
			return nil, errors.New("unexpected test endpoint")
		}
	})
	m.api = api
	if err := m.step(context.Background(), job.ID); err == nil {
		t.Fatal("lost creation receipt did not report a persistence failure")
	}
	disk := independentMarketplaceDiskJob(t, m)
	if disk.Status != "creating" || disk.CreateIssuedAt == "" || disk.ProductID != "" || creates != 1 {
		t.Fatal("failed receipt replaced the durable ambiguous-create record")
	}
	restarted := independentMarketplaceRestart(t, m, api)
	if err := restarted.retry(job.ID); err != nil {
		t.Fatal(err)
	}
	if err := restarted.step(context.Background(), job.ID); err != nil {
		t.Fatal(err)
	}
	recovered, _ := restarted.job(job.ID)
	if recovered.Status != "created" || recovered.ProductID != "101" || creates != 1 || lists != 1 {
		t.Fatal("restart/retry repeated creation instead of reconciling the original request")
	}
}

func TestMarketplaceIndependentAmbiguousCreateRetainsGuardAfterAttentionAndRetry(t *testing.T) {
	m, job := independentMarketplaceFixture(t, "queued")
	var creates, reads int
	m.api = independentMarketplaceClient(t, func(r *http.Request) (*http.Response, error) {
		if r.URL.Path == xgjShopsPath {
			return independentMarketplaceShops(m.now()), nil
		}
		if r.URL.Path == xgjCreatePath {
			creates++
			return nil, errors.New("simulated connection lost after server write")
		}
		reads++
		return &http.Response{StatusCode: 503, Header: make(http.Header), Body: io.NopCloser(strings.NewReader("unavailable"))}, nil
	})
	if err := m.step(context.Background(), job.ID); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 8; i++ {
		if err := m.step(context.Background(), job.ID); err != nil {
			t.Fatal(err)
		}
	}
	stopped, _ := m.job(job.ID)
	if stopped.Status != "attention" || stopped.CreateIssuedAt == "" || creates != 1 {
		t.Fatal("exhausted read failures forgot the submitted creation")
	}
	restarted := independentMarketplaceRestart(t, m, m.api)
	if err := restarted.retry(job.ID); err != nil {
		t.Fatal(err)
	}
	if err := restarted.step(context.Background(), job.ID); err != nil {
		t.Fatal(err)
	}
	again, _ := restarted.job(job.ID)
	if again.Status != "create_unknown" || again.CreateIssuedAt == "" || creates != 1 || reads < 8 {
		t.Fatal("manual retry after restart discarded the no-repeat guard")
	}
}

func TestMarketplaceIndependentReconcileRejectsPaginationMismatch(t *testing.T) {
	for _, response := range []struct {
		name string
		page int
		size int
	}{
		{"wrong-page", 2, 100},
		{"smaller-page", 1, 20},
	} {
		t.Run(response.name, func(t *testing.T) {
			m, job := independentMarketplaceFixture(t, "create_unknown")
			m.api = independentMarketplaceClient(t, func(r *http.Request) (*http.Response, error) {
				if r.URL.Path != xgjProductsPath {
					t.Error("reconciliation sent a write request")
				}
				return independentMarketplaceResponse(map[string]any{"list": []map[string]any{{"product_id": 101, "outer_id": job.OuterID}}, "count": 1, "page_no": response.page, "page_size": response.size}), nil
			})
			if err := m.step(context.Background(), job.ID); err != nil {
				t.Fatal(err)
			}
			current, _ := m.job(job.ID)
			if current.ProductID != "" || current.Status == "created" {
				t.Fatal("inconsistent pagination was treated as a complete remote duplicate check")
			}
		})
	}
}

func TestMarketplaceIndependentReconcileRejectsIncompleteResultCount(t *testing.T) {
	for _, count := range []int{100, 101} {
		t.Run(fmt.Sprint(count), func(t *testing.T) {
			m, job := independentMarketplaceFixture(t, "create_unknown")
			m.api = independentMarketplaceClient(t, func(r *http.Request) (*http.Response, error) {
				var request struct {
					Page int `json:"page_no"`
				}
				if json.NewDecoder(r.Body).Decode(&request) != nil || r.URL.Path != xgjProductsPath {
					t.Fatal("invalid test reconciliation request")
				}
				rows := []map[string]any{}
				if request.Page == 1 {
					rows = append(rows, map[string]any{"product_id": 101, "outer_id": job.OuterID})
				}
				return independentMarketplaceResponse(map[string]any{"list": rows, "count": count, "page_no": request.Page, "page_size": 100}), nil
			})
			if err := m.step(context.Background(), job.ID); err != nil {
				t.Fatal(err)
			}
			current, _ := m.job(job.ID)
			if current.ProductID != "" || current.Status == "created" {
				t.Fatal("partial product rows were treated as a complete remote duplicate check")
			}
		})
	}
}

func TestMarketplaceIndependentPublishTimeoutAndRestartNeverRepublishes(t *testing.T) {
	m, job := independentMarketplaceFixture(t, "created")
	if err := m.change(job.ID, func(j *MarketplaceJob) { j.ProductID = "101" }); err != nil {
		t.Fatal(err)
	}
	var publishes int
	confirmed := false
	api := independentMarketplaceClient(t, func(r *http.Request) (*http.Response, error) {
		switch r.URL.Path {
		case xgjShopsPath:
			return independentMarketplaceShops(m.now()), nil
		case xgjProductPath:
			status, publish := 21, 2
			var shops []map[string]any
			if confirmed {
				status, publish = 22, 3
				shops = []map[string]any{{"user_name": job.ShopUserName, "status": 1, "item_id": 501}}
			} else {
				shops = []map[string]any{{"user_name": job.ShopUserName, "status": 1, "item_id": 0}}
			}
			return independentMarketplaceResponse(map[string]any{"product_id": 101, "outer_id": job.OuterID, "product_status": status, "publish_status": publish, "publish_shop": shops}), nil
		case xgjPublishPath:
			publishes++
			disk := independentMarketplaceDiskJob(t, m)
			if disk.Status != "publishing" || disk.PublishIssuedAt == "" {
				t.Fatal("publish preceded its durable intent")
			}
			return nil, errors.New("simulated timeout after publish")
		default:
			return nil, errors.New("unexpected request")
		}
	})
	m.api = api
	if err := m.step(context.Background(), job.ID); err != nil {
		t.Fatal(err)
	}
	restarted := independentMarketplaceRestart(t, m, api)
	if err := restarted.retry(job.ID); err != nil {
		t.Fatal(err)
	}
	if err := restarted.step(context.Background(), job.ID); err != nil {
		t.Fatal(err)
	}
	waiting, _ := restarted.job(job.ID)
	if waiting.Status != "confirming" || publishes != 1 {
		t.Fatal("unconfirmed publish was submitted again after restart/retry")
	}
	confirmed = true
	if err := restarted.step(context.Background(), job.ID); err != nil {
		t.Fatal(err)
	}
	completed, _ := restarted.job(job.ID)
	if completed.Status != "published" || completed.ItemID != "501" || publishes != 1 {
		t.Fatal("specific shop confirmation was not recorded without republishing")
	}
}

func TestMarketplaceIndependentRejectsWrongShopAndPseudoSuccess(t *testing.T) {
	for _, test := range []struct {
		name  string
		shops []map[string]any
	}{
		{"wrong-shop", []map[string]any{{"user_name": "another-shop", "status": 1, "item_id": 501}}},
		{"missing-item", []map[string]any{{"user_name": "test-shop", "status": 1, "item_id": 0}}},
		{"missing-status", []map[string]any{{"user_name": "test-shop", "item_id": 501}}},
		{"not-selected", []map[string]any{{"user_name": "test-shop", "status": 0, "item_id": 501}}},
		{"duplicate-shop", []map[string]any{{"user_name": "test-shop", "status": 1, "item_id": 501}, {"user_name": "test-shop", "status": 1, "item_id": 502}}},
	} {
		t.Run(test.name, func(t *testing.T) {
			m, job := independentMarketplaceFixture(t, "confirming")
			if err := m.change(job.ID, func(j *MarketplaceJob) { j.ProductID, j.PublishIssuedAt = "101", m.nowString() }); err != nil {
				t.Fatal(err)
			}
			m.api = independentMarketplaceClient(t, func(r *http.Request) (*http.Response, error) {
				if r.URL.Path != xgjProductPath {
					t.Error("pseudo-success triggered another publication request")
				}
				return independentMarketplaceResponse(map[string]any{"product_id": 101, "outer_id": job.OuterID, "product_status": 22, "publish_status": 3, "publish_shop": test.shops}), nil
			})
			if err := m.step(context.Background(), job.ID); err != nil {
				t.Fatal(err)
			}
			current, _ := m.job(job.ID)
			if current.Status == "published" || current.ItemID != "" || current.ItemURL != "" {
				t.Fatal("incorrect or incomplete shop evidence was reported as successful publication")
			}
		})
	}
}

func TestMarketplaceIndependentPublishRequiresExactlyOneSelectedShop(t *testing.T) {
	for _, test := range []struct {
		name  string
		shops []map[string]any
	}{
		{"empty", []map[string]any{}},
		{"wrong-shop", []map[string]any{{"user_name": "another-shop", "status": 1, "item_id": 0}}},
		{"duplicate-shop", []map[string]any{{"user_name": "test-shop", "status": 1, "item_id": 0}, {"user_name": "test-shop", "status": 1, "item_id": 0}}},
	} {
		t.Run(test.name, func(t *testing.T) {
			m, job := independentMarketplaceFixture(t, "created")
			if err := m.change(job.ID, func(j *MarketplaceJob) { j.ProductID = "101" }); err != nil {
				t.Fatal(err)
			}
			publishes := 0
			m.api = independentMarketplaceClient(t, func(r *http.Request) (*http.Response, error) {
				switch r.URL.Path {
				case xgjShopsPath:
					return independentMarketplaceShops(m.now()), nil
				case xgjProductPath:
					return independentMarketplaceResponse(map[string]any{"product_id": 101, "outer_id": job.OuterID, "product_status": 21, "publish_status": 2, "publish_shop": test.shops}), nil
				case xgjPublishPath:
					publishes++
					return independentMarketplaceResponse(map[string]any{}), nil
				default:
					return nil, errors.New("unexpected request")
				}
			})
			if err := m.step(context.Background(), job.ID); err != nil {
				t.Fatal(err)
			}
			if publishes != 0 {
				t.Fatal("publish was issued without one unambiguous selected shop in the remote product")
			}
		})
	}
}

func TestMarketplaceIndependentPublishRechecksCurrentCloudShares(t *testing.T) {
	m, job := independentMarketplaceFixture(t, "created")
	if err := m.change(job.ID, func(j *MarketplaceJob) { j.ProductID = "101" }); err != nil {
		t.Fatal(err)
	}
	transfer := &m.app.transfers.jobs[0]
	output := transfer.Outputs["quark"]
	output.Share.ExpiresAt = time.Now().Add(-time.Hour).UTC().Format(time.RFC3339)
	transfer.Outputs["quark"] = output
	publishes := 0
	m.api = independentMarketplaceClient(t, func(r *http.Request) (*http.Response, error) {
		switch r.URL.Path {
		case xgjShopsPath:
			return independentMarketplaceShops(m.now()), nil
		case xgjProductPath:
			return independentMarketplaceResponse(map[string]any{"product_id": 101, "outer_id": job.OuterID, "product_status": 21, "publish_status": 2, "publish_shop": []map[string]any{{"user_name": "test-shop", "status": 1, "item_id": 0}}}), nil
		case xgjPublishPath:
			publishes++
			return independentMarketplaceResponse(map[string]any{}), nil
		default:
			return nil, errors.New("unexpected request")
		}
	})
	if err := m.step(context.Background(), job.ID); err != nil {
		t.Fatal(err)
	}
	if publishes != 0 {
		t.Fatal("an expired delivery share was published after remote creation")
	}
}

func TestMarketplaceIndependentQueueRejectsIncompleteCloudReceipts(t *testing.T) {
	for _, test := range []struct {
		name   string
		mutate func(*TransferOutput)
	}{
		{"missing-file", func(o *TransferOutput) { o.File.ID = "" }},
		{"missing-session", func(o *TransferOutput) { o.Session = "" }},
		{"error", func(o *TransferOutput) { o.Error = "share failed" }},
		{"attention", func(o *TransferOutput) { o.NeedsAttention = true }},
		{"wrong-bundle", func(o *TransferOutput) { o.PayloadSHA256 = strings.Repeat("f", 64) }},
		{"expired", func(o *TransferOutput) { o.Share.ExpiresAt = time.Now().Add(-time.Hour).UTC().Format(time.RFC3339) }},
	} {
		t.Run(test.name, func(t *testing.T) {
			m, job := independentMarketplaceFixture(t, "queued")
			output := m.app.transfers.jobs[0].Outputs["baidu"]
			test.mutate(&output)
			m.app.transfers.jobs[0].Outputs["baidu"] = output
			requests := 0
			m.api = independentMarketplaceClient(t, func(*http.Request) (*http.Response, error) {
				requests++
				return nil, errors.New("incomplete sharing receipt reached marketplace")
			})
			if err := m.step(context.Background(), job.ID); err != nil {
				t.Fatal(err)
			}
			current, _ := m.job(job.ID)
			if requests != 0 || current.CreateIssuedAt != "" || current.Status == "creating" {
				t.Fatal("incomplete cloud receipt was allowed to reach remote creation")
			}
		})
	}
}

func TestMarketplaceIndependentCredentialTransactionRollsBackAllProviders(t *testing.T) {
	for _, disconnect := range []bool{false, true} {
		t.Run(fmt.Sprintf("disconnect=%v", disconnect), func(t *testing.T) {
			m, _ := independentMarketplaceFixture(t, "queued")
			original := vaultTestCredentials()
			installUpgradeMemoryAccounts(t, m.app, original)
			oldCreds, oldAPI := m.credentialsSnapshot(), m.api
			m.app.credentials.persist()
			vaultPath := filepath.Join(m.app.lib.root, credentialVaultFile)
			before, err := os.ReadFile(vaultPath)
			if err != nil {
				t.Fatal(err)
			}
			protect := m.app.credentials.vault.protect
			m.app.credentials.vault.protect = func([]byte) ([]byte, error) { return nil, errors.New("simulated encryption failure") }
			next := XGJCredentials{AppKey: "203413189371894", AppSecret: "new-test-secret"}
			api := newXGJClient(next)
			if disconnect {
				next, api = XGJCredentials{}, nil
			}
			if err := m.setCredentials(next, api, nil); err == nil {
				t.Fatal("failed credential transaction reported success")
			}
			m.app.credentials.vault.protect = protect
			after, err := os.ReadFile(vaultPath)
			if err != nil || !bytes.Equal(before, after) || m.credentialsSnapshot() != oldCreds || m.api != oldAPI {
				t.Fatal("failed credential transaction changed memory or opaque vault")
			}
			saved, err := m.app.credentials.vault.load()
			if err != nil || saved.Xianguanjia == nil || *saved.Xianguanjia != oldCreds || saved.GitHubToken != original.GitHubToken || saved.AIGCToken != original.AIGCToken || !reflect.DeepEqual(saved.Clouds, original.Clouds) {
				t.Fatal("rollback lost another provider's authorization")
			}
		})
	}
}

func TestMarketplaceIndependentDifferentAccountCannotResumeOldJob(t *testing.T) {
	m, job := independentMarketplaceFixture(t, "created")
	if err := m.change(job.ID, func(j *MarketplaceJob) { j.ProductID = "101" }); err != nil {
		t.Fatal(err)
	}
	var calls int
	api := independentMarketplaceClient(t, func(*http.Request) (*http.Response, error) { calls++; return nil, errors.New("wrong-account request") })
	if err := m.setCredentials(XGJCredentials{AppKey: "203413189371894", AppSecret: "other-test-secret"}, api, nil); err != nil {
		t.Fatal(err)
	}
	if err := m.step(context.Background(), job.ID); err != nil {
		t.Fatal(err)
	}
	current, _ := m.job(job.ID)
	if calls != 0 || current.Status != "attention" || current.ProductID != "101" {
		t.Fatal("changing application used the new account for an old job")
	}
}

func TestMarketplaceIndependentPauseCancelsActiveCreateWithoutLockCycle(t *testing.T) {
	m, job := independentMarketplaceFixture(t, "queued")
	started := make(chan struct{})
	var creates atomic.Int64
	m.api = independentMarketplaceClient(t, func(r *http.Request) (*http.Response, error) {
		if r.URL.Path == xgjShopsPath {
			return independentMarketplaceShops(m.now()), nil
		}
		if r.URL.Path != xgjCreatePath {
			return nil, errors.New("unexpected request while pausing")
		}
		if creates.Add(1) == 1 {
			close(started)
		}
		<-r.Context().Done()
		return nil, r.Context().Err()
	})
	go m.loop()
	t.Cleanup(func() {
		m.app.cancel()
		select {
		case <-m.done:
		case <-time.After(3 * time.Second):
			t.Error("marketplace loop did not stop")
		}
	})
	select {
	case <-started:
	case <-time.After(3 * time.Second):
		t.Fatal("test create never started")
	}
	var workers sync.WaitGroup
	workers.Add(1)
	go func() {
		defer workers.Done()
		for i := 0; i < 10; i++ {
			m.app.credentials.persist()
			_ = m.status()
		}
	}()
	paused := make(chan error, 1)
	config := job.Config
	config.Enabled = false
	go func() { paused <- m.configure(context.Background(), config) }()
	select {
	case err := <-paused:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("pause deadlocked with active creation and credential persistence")
	}
	done := make(chan struct{})
	go func() { workers.Wait(); close(done) }()
	select {
	case <-done:
	case <-time.After(3 * time.Second):
		t.Fatal("credential persistence deadlocked after pause")
	}
	current, _ := m.job(job.ID)
	m.mu.Lock()
	enabled := m.state.Config.Enabled
	m.mu.Unlock()
	if enabled || current.CreateIssuedAt == "" || current.Status != "create_unknown" || creates.Load() != 1 {
		t.Fatal("pause lost the ambiguous creation or allowed another create")
	}
}
