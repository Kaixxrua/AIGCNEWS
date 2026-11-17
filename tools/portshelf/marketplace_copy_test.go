package main

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"reflect"
	"strings"
	"testing"
)

func marketplaceCopyFixture(t *testing.T) (*marketplaceManager, MarketplaceJob) {
	t.Helper()
	m, j := independentMarketplaceFixture(t, "published")
	err := m.change(j.ID, func(j *MarketplaceJob) {
		j.ProductID, j.ItemID = "9007199254740993", "9007199254740995"
		j.Title, j.Content = "旧商品文案", "项目：test/game\n源码版本：旧版本"
		j.Payload, _ = marketplaceCopyPayload(j.Payload, j.ShopUserName, j.Title, j.Content)
	})
	if err != nil {
		t.Fatal(err)
	}
	j, _ = m.job(j.ID)
	return m, j
}

func marketplaceCopyProduct(j MarketplaceJob, title, content string, status int) map[string]any {
	return map[string]any{"product_id": int64(9007199254740993), "outer_id": j.OuterID,
		"product_status": status, "publish_status": 3,
		"publish_shop": []map[string]any{{"user_name": j.ShopUserName, "item_id": int64(9007199254740995), "status": 1, "title": title, "content": content}}}
}

func TestMarketplaceBuyerCopyDescribesDeliveredPlatformWithoutProvenance(t *testing.T) {
	m, j := independentMarketplaceFixture(t, "queued")
	transfer, _ := m.app.transfers.job(j.TransferID)
	transfer.Name, transfer.GameNameZh = "CommunityGame", "测试游戏"
	transfer.SupportedSystems = []string{"Windows", "macOS", "Linux", "Android"}
	transfer.Arch = "arm64"
	title, content, err := marketplaceBuyerCopy(transfer, j.Config)
	if err != nil || !strings.Contains(title, "CommunityGame") || !strings.Contains(title, "测试游戏") || !strings.Contains(content, "Windows ARM64") {
		t.Fatalf("buyer identity/platform missing: %s / %s / %v", title, content, err)
	}
	for _, unwanted := range []string{"项目：", "运行要求：", "使用说明：", "源码版本：", "项目来源：", "上游许可", "github.com", transfer.SourceCommit, "macOS", "Android", "Linux"} {
		if strings.Contains(content, unwanted) {
			t.Errorf("buyer copy includes unwanted %q", unwanted)
		}
	}
	if transfer.SourceURL == "" || transfer.Guide == "" || transfer.SourceCommit == "" {
		t.Fatal("copy generation removed the original package instructions")
	}
}

func TestMarketplaceCopyEditsOnlyExistingProductText(t *testing.T) {
	for _, status := range []int{22, 31} {
		t.Run(map[int]string{22: "on-sale", 31: "manually-offline"}[status], func(t *testing.T) {
			m, j := marketplaceCopyFixture(t)
			title, content, edits := j.Title, j.Content, 0
			m.api = independentMarketplaceClient(t, func(r *http.Request) (*http.Response, error) {
				switch r.URL.Path {
				case xgjShopsPath:
					return independentMarketplaceShops(m.now()), nil
				case xgjProductPath:
					return independentMarketplaceResponse(marketplaceCopyProduct(j, title, content, status)), nil
				case xgjEditPath:
					edits++
					if independentMarketplaceDiskJob(t, m).CopyUpdate == nil {
						t.Fatal("edit sent before durable intent")
					}
					var body map[string]json.RawMessage
					if json.NewDecoder(r.Body).Decode(&body) != nil || len(body) != 3 || string(body["product_id"]) != j.ProductID {
						t.Fatal("edit sent extra fields or changed the product ID")
					}
					var shops []map[string]string
					if json.Unmarshal(body["publish_shop"], &shops) != nil || len(shops) != 1 || len(shops[0]) != 3 || shops[0]["user_name"] != j.ShopUserName {
						t.Fatal("edit changed a non-text shop field")
					}
					title, content = shops[0]["title"], shops[0]["content"]
					return independentMarketplaceResponse(map[string]any{"product_id": int64(9007199254740993)}), nil
				default:
					t.Fatalf("copy update attempted creation/publication: %s", r.URL.Path)
					return nil, errors.New("unexpected endpoint")
				}
			})
			if err := m.refreshCopy(context.Background(), j.ID); err != nil {
				t.Fatal(err)
			}
			saved := independentMarketplaceDiskJob(t, m)
			if saved.Title != title || saved.Content != content || saved.CopyUpdate != nil || saved.CopyUpdatedAt == "" || saved.ProductID != j.ProductID || saved.ItemID != j.ItemID || !reflect.DeepEqual(saved.Config, j.Config) || !reflect.DeepEqual(saved.Baidu, j.Baidu) || !reflect.DeepEqual(saved.Quark, j.Quark) {
				t.Fatal("verified copy lost non-text job data")
			}
			var old, next map[string]json.RawMessage
			_ = json.Unmarshal(j.Payload, &old)
			_ = json.Unmarshal(saved.Payload, &next)
			for _, key := range []string{"price", "stock", "outer_id", "channel_cat_id", "channel_pv"} {
				if string(old[key]) != string(next[key]) {
					t.Fatalf("copy update changed %s", key)
				}
			}
			if status == 31 && saved.Status != "attention" {
				t.Fatal("manually offline product still shown as on sale")
			}
			if err := m.refreshCopy(context.Background(), j.ID); err != nil || edits != 1 {
				t.Fatalf("already updated copy was resent: %d / %v", edits, err)
			}
		})
	}
}

func TestMarketplaceCopyUncertainEditReconcilesAfterRestart(t *testing.T) {
	m, j := marketplaceCopyFixture(t)
	newTitle, newContent, edits, visible := "", "", 0, false
	api := independentMarketplaceClient(t, func(r *http.Request) (*http.Response, error) {
		switch r.URL.Path {
		case xgjShopsPath:
			return independentMarketplaceShops(m.now()), nil
		case xgjProductPath:
			title, content := j.Title, j.Content
			if visible {
				title, content = newTitle, newContent
			}
			return independentMarketplaceResponse(marketplaceCopyProduct(j, title, content, 22)), nil
		case xgjEditPath:
			edits++
			pending := independentMarketplaceDiskJob(t, m).CopyUpdate
			newTitle, newContent = pending.Title, pending.Content
			return nil, io.ErrUnexpectedEOF
		default:
			t.Fatal("unexpected endpoint")
			return nil, errors.New("unexpected endpoint")
		}
	})
	m.api = api
	if err := m.refreshCopy(context.Background(), j.ID); err == nil || independentMarketplaceDiskJob(t, m).CopyUpdate == nil {
		t.Fatal("uncertain edit incorrectly marked complete")
	}
	m = independentMarketplaceRestart(t, m, api)
	if err := m.refreshCopy(context.Background(), j.ID); err == nil || edits != 1 {
		t.Fatal("pending remote edit was resent")
	}
	visible = true
	if err := m.refreshCopy(context.Background(), j.ID); err != nil || edits != 1 || independentMarketplaceDiskJob(t, m).CopyUpdate != nil {
		t.Fatalf("read-back failed to reconcile: %v", err)
	}
}

func TestMarketplaceCopyRejectsMismatchAndFailedIntentWrite(t *testing.T) {
	for _, mode := range []string{"account", "product", "outer", "shop", "manual-copy", "disk"} {
		t.Run(mode, func(t *testing.T) {
			m, j := marketplaceCopyFixture(t)
			if mode == "account" {
				m.creds.AppKey = "9999999"
			}
			if mode == "disk" {
				m.write = func(string, string, []byte) error { return errors.New("disk full") }
			}
			m.api = independentMarketplaceClient(t, func(r *http.Request) (*http.Response, error) {
				if r.URL.Path == xgjShopsPath {
					return independentMarketplaceShops(m.now()), nil
				}
				if r.URL.Path != xgjProductPath {
					t.Fatal("edit sent despite mismatch or failed intent")
				}
				p := marketplaceCopyProduct(j, j.Title, j.Content, 22)
				switch mode {
				case "product":
					p["product_id"] = 123
				case "outer":
					p["outer_id"] = "other-product"
				case "shop":
					p["publish_shop"] = []any{}
				case "manual-copy":
					p = marketplaceCopyProduct(j, "卖家手动修改", j.Content, 22)
				}
				return independentMarketplaceResponse(p), nil
			})
			if err := m.refreshCopy(context.Background(), j.ID); err == nil {
				t.Fatal("unsafe copy update was accepted")
			}
		})
	}
}
