package main

import (
	"encoding/json"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestMarketplaceDeliveryPreviewUsesCurrentVerifiedBundleShares(t *testing.T) {
	m, j := independentMarketplaceFixture(t, "published")
	m.app.host = "127.0.0.1:12345"
	// No network client or remote writes are needed to prepare a draft.
	m.api = nil
	m.app.transfers.jobs[0].LocalDeletedAt = time.Now().UTC().Format(time.RFC3339)
	out := m.app.transfers.jobs[0].Outputs["baidu"]
	out.Share.URL = "https://pan.baidu.com/s/current-bundle"
	m.app.transfers.jobs[0].Outputs["baidu"] = out
	path := "/api/marketplace/jobs/" + j.ID + "/delivery-preview"
	r := request(m.app, "GET", path, "")
	r.Header.Del("Authorization")
	w := httptest.NewRecorder()
	m.app.handler().ServeHTTP(w, r)
	if w.Code != 401 {
		t.Fatal("private delivery links exposed without authentication")
	}
	w = call(m.app, "GET", path, "")
	var preview map[string]string
	if w.Code != 200 || json.Unmarshal(w.Body.Bytes(), &preview) != nil || preview["remoteStatus"] != "unverified" {
		t.Fatalf("draft incorrectly claims remote configuration: %s", w.Body.String())
	}
	for _, want := range []string{"测试游戏", "Windows x64", out.Share.URL, "1234", "https://pan.quark.cn/s/test", "5678", "版本：v1"} {
		if !strings.Contains(preview["content"], want) {
			t.Errorf("delivery draft missing %q", want)
		}
	}
	for _, unwanted := range []string{"github.com", "源码版本：", "项目：", "使用说明：", "Linux", "历史"} {
		if strings.Contains(preview["content"], unwanted) {
			t.Errorf("delivery draft includes %q", unwanted)
		}
	}
}

func TestMarketplaceDeliveryPreviewRejectsInvalidShareOrDifferentBundle(t *testing.T) {
	for _, mode := range []string{"bundle", "expired", "unfinished", "unsafe-url"} {
		t.Run(mode, func(t *testing.T) {
			m, j := independentMarketplaceFixture(t, "published")
			transfer := &m.app.transfers.jobs[0]
			out := transfer.Outputs["quark"]
			switch mode {
			case "bundle":
				transfer.BundleSHA256 = strings.Repeat("f", 64)
			case "expired":
				out.Share.ExpiresAt = time.Now().Add(-time.Hour).Format(time.RFC3339)
			case "unfinished":
				out.Status = "failed"
			case "unsafe-url":
				out.Share.URL = "https://unrelated.example/s/test"
			}
			transfer.Outputs["quark"] = out
			if content, err := m.deliveryPreview(j.ID); err == nil || content != "" {
				t.Fatal("unverified delivery material was exposed as a ready draft")
			}
		})
	}
}
