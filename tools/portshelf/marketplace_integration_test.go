package main

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func waitMarketplace(t *testing.T, m *marketplaceManager, status string) MarketplaceJob {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		m.mu.Lock()
		jobs := cloneMarketplaceState(m.state).Jobs
		m.mu.Unlock()
		for _, j := range jobs {
			if j.Status == status {
				return j
			}
		}
		time.Sleep(5 * time.Millisecond)
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	t.Fatalf("marketplace did not reach %s: %+v", status, m.state.Jobs)
	return MarketplaceJob{}
}

func TestMarketplaceIntegrationDiscoveryThroughPublicationAndRestart(t *testing.T) {
	root := t.TempDir()
	a := automationIntegrationApp(t, root)
	sources := &automationIntegrationSources{content: "verified Windows test release"}
	sources.install(t, a)
	drives := automationIntegrationDrives(a, sources.content)
	poster := "https://aigcnews.cn/api/media/site/game-posters/" + strings.Repeat("a", 64) + ".jpg"
	a.aigc.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		sources.descriptions.Add(1)
		if r.Method != http.MethodGet || r.URL.Query().Get("repos") != "integration/port-game" {
			t.Error("unexpected metadata request")
		}
		data, _ := json.Marshal(DescriptionsResponse{Items: []Description{{Repo: "integration/port-game", Status: "ready", Source: "aigcnews", DescriptionZh: "经典平台动作游戏的开源移植，保留原作关卡与玩法。", GameNameZh: "测试平台游戏", GameNameOriginal: "Test Platform Game", DetailsVersion: gameDetailsVersion, PosterURL: poster, PosterSourceURL: "https://example.com/game", PosterKind: "cover"}}})
		return apiResponse(200, string(data)), nil
	})
	m, err := newMarketplace(a)
	if err != nil {
		t.Fatal(err)
	}
	a.marketplace = m
	creds := xgjVaultTestCredentials()
	m.restoreCredentials(creds)
	m.state.Config = MarketplaceConfig{Enabled: true, ShopUserName: "test-shop", ItemBizType: 2, SpBizType: 22, CategoryID: "test-category", Properties: []MarketplaceProperty{}, Province: 110000, City: 110100, District: 110101, PriceFen: 199, Stock: 3}
	var creates, publishes, details atomic.Int32
	var outer atomic.Value
	api := independentMarketplaceClient(t, func(r *http.Request) (*http.Response, error) {
		switch r.URL.Path {
		case xgjShopsPath:
			return independentMarketplaceShops(time.Now()), nil
		case xgjCreatePath:
			creates.Add(1)
			var request XGJCreateRequest
			body, _ := io.ReadAll(r.Body)
			if json.Unmarshal(body, &request) != nil || request.Price != 199 || request.Stock != 3 || len(request.PublishShop) != 1 || request.PublishShop[0].UserName != "test-shop" || len(request.PublishShop[0].Images) != 1 || request.PublishShop[0].Images[0] != poster || !strings.Contains(request.PublishShop[0].Title, "测试平台游戏") {
				t.Error("automatic listing lost the configured price, stock, shop, identity or verified picture")
			}
			if strings.Contains(string(body), "pan.baidu.com") || strings.Contains(string(body), "pan.quark.cn") || strings.Contains(string(body), creds.AppSecret) {
				t.Error("private delivery material leaked into public listing")
			}
			jobs, _ := a.transfers.snapshot()
			if len(jobs) != 1 || marketplaceTransferReady(jobs[0]) != nil {
				t.Error("creation preceded both verified shares and matching source bundle")
			}
			outer.Store(request.OuterID)
			return independentMarketplaceResponse(map[string]any{"product_id": int64(9007199254740993), "product_status": 21}), nil
		case xgjProductPath:
			details.Add(1)
			productStatus, publishStatus, itemID := 21, 2, int64(0)
			if publishes.Load() > 0 {
				productStatus, publishStatus, itemID = 22, 3, 9007199254740995
			}
			return independentMarketplaceResponse(map[string]any{"product_id": int64(9007199254740993), "product_status": productStatus, "publish_status": publishStatus, "outer_id": outer.Load(), "publish_shop": []map[string]any{{"user_name": "test-shop", "status": 1, "item_id": itemID}}}), nil
		case xgjPublishPath:
			publishes.Add(1)
			var request struct {
				ID    int64    `json:"product_id"`
				Shops []string `json:"user_name"`
			}
			if json.NewDecoder(r.Body).Decode(&request) != nil || request.ID != 9007199254740993 || len(request.Shops) != 1 || request.Shops[0] != "test-shop" {
				t.Error("publish did not use the exact product and configured shop")
			}
			return independentMarketplaceResponse(map[string]any{}), nil
		default:
			t.Errorf("unexpected marketplace endpoint %s", r.URL.Path)
			return nil, errors.New("unexpected marketplace endpoint")
		}
	})
	m.api = api
	config := a.automation.configSnapshot()
	config.Enabled, config.Arch, config.DailyLimit = true, "amd64", 1
	config.RememberCredentials, config.StartOnLogin = false, false
	if err := a.automation.configure(config); err != nil {
		t.Fatal(err)
	}
	go m.loop()
	stop := startAutomationIntegration(t, a)
	t.Cleanup(func() {
		stop()
		select {
		case <-m.done:
		case <-time.After(3 * time.Second):
			t.Error("marketplace did not stop")
		}
	})
	job := waitMarketplace(t, m, "confirming")
	// Advance only the persisted poll deadline; keep the real scheduler,
	// signed HTTP client, transfer worker, bundle and both-drive chain.
	if err := m.change(job.ID, func(j *MarketplaceJob) { j.NextRunAt = "" }); err != nil {
		t.Fatal(err)
	}
	m.notify()
	job = waitMarketplace(t, m, "published")
	row := waitAutomationMaterial(t, a)
	stop()
	<-m.done
	if creates.Load() != 1 || publishes.Load() != 1 || details.Load() != 2 || job.ProductID != "9007199254740993" || job.ItemID != "9007199254740995" || !strings.Contains(job.ItemURL, job.ItemID) || job.Baidu.URL == "" || job.Quark.URL == "" {
		t.Fatalf("incorrect final publication receipt: %+v", job)
	}
	if sources.searches.Load() != 1 || sources.releases.Load() != 1 || sources.downloads.Load() != 1 || row.LocalDeletedAt == "" {
		t.Fatal("discovery/download was repeated or local source files were retained")
	}
	for provider, drive := range drives {
		if uploads, shares := drive.counts(); uploads != 1 || shares != 1 {
			t.Fatalf("%s duplicated transfer: uploads=%d shares=%d", provider, uploads, shares)
		}
	}
	transfers, _ := a.transfers.snapshot()
	for _, artifact := range transferArtifacts(transfers[0]) {
		if _, err := os.Stat(artifact.path); !errors.Is(err, os.ErrNotExist) {
			t.Fatal("published task retained a local bundle or source file")
		}
	}
	data, _ := os.ReadFile(filepath.Join(root, "marketplace.json"))
	if strings.Contains(string(data), creds.AppKey) || strings.Contains(string(data), creds.AppSecret) {
		t.Fatal("marketplace journal contains account credentials")
	}
	restartedApp := automationIntegrationApp(t, root)
	restarted, err := newMarketplace(restartedApp)
	if err != nil {
		t.Fatal(err)
	}
	restartedApp.marketplace = restarted
	restarted.restoreCredentials(creds)
	restarted.api = api
	if added, err := restarted.collect(); err != nil || added != 0 {
		t.Fatalf("restart duplicated the already published release: added=%d err=%v", added, err)
	}
	if err := restarted.step(context.Background(), job.ID); err != nil || creates.Load() != 1 || publishes.Load() != 1 || sources.downloads.Load() != 1 {
		t.Fatal("restart repeated a completed side effect")
	}
}

func TestMarketplaceRoutesUnconfiguredAndSessionGuard(t *testing.T) {
	a := testApp(t)
	for _, path := range []string{"/api/marketplace/run", "/api/marketplace/enqueue"} {
		if response := call(a, "POST", path, `{}`); response.Code != 409 {
			t.Fatalf("unconfigured publication accepted: %s %s", path, response.Body.String())
		}
	}
	if response := call(a, "GET", "/api/marketplace", ""); response.Code != 200 || !strings.Contains(response.Body.String(), `"connected":false`) || !strings.Contains(response.Body.String(), `"enabled":false`) || !strings.Contains(response.Body.String(), `"priceFen":0`) {
		t.Fatal("unset price/account did not remain visibly disabled")
	}
	config := MarketplaceConfig{ItemBizType: 2, Enabled: true}
	data, _ := json.Marshal(config)
	if response := call(a, "POST", "/api/marketplace/config", string(data)); response.Code != 400 {
		t.Fatal("enabled an incomplete publication rule")
	}
	config.Enabled = false
	data, _ = json.Marshal(config)
	if response := call(a, "POST", "/api/marketplace/config", string(data)); response.Code != 200 {
		t.Fatal("could not save an unfinished disabled draft")
	}
}
