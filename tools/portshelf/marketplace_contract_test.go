package main

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"
)

// These assertions concern the official create/publish wire contract, including
// fields which are optional for physical goods but relevant to digital files.
func TestMarketplaceContractRequiredCreateFields(t *testing.T) {
	_, job := independentMarketplaceFixture(t, "queued")
	var body map[string]json.RawMessage
	if err := json.Unmarshal(job.Payload, &body); err != nil {
		t.Fatal(err)
	}
	for _, key := range []string{"item_biz_type", "sp_biz_type", "channel_cat_id", "price", "express_fee", "stock", "publish_shop"} {
		if raw, ok := body[key]; !ok || string(raw) == "null" {
			t.Errorf("required create field %s is absent", key)
		}
	}
	var shops []map[string]json.RawMessage
	if err := json.Unmarshal(body["publish_shop"], &shops); err != nil || len(shops) != 1 {
		t.Fatalf("expected exactly one configured shop: %v", err)
	}
	for _, key := range []string{"user_name", "province", "city", "district", "title", "content", "images"} {
		if raw, ok := shops[0][key]; !ok || string(raw) == "null" {
			t.Errorf("required shop field %s is absent", key)
		}
	}
	// Official ordinary goods allow omitting stuff_status; if provided, zero
	// accurately denotes no physical condition rather than claiming new goods.
	if raw, ok := body["stuff_status"]; ok && string(raw) != "0" {
		t.Error("digital source files must not be labelled with physical condition")
	}
}

func TestMarketplaceContractDigitalDeliveryUsesNoPostage(t *testing.T) {
	_, job := independentMarketplaceFixture(t, "queued")
	var body struct {
		PublishShop []struct {
			ExpressWay *int `json:"express_way"`
		} `json:"publish_shop"`
	}
	if err := json.Unmarshal(job.Payload, &body); err != nil {
		t.Fatal(err)
	}
	// Official express_way=5 is "无需邮寄". express_fee=0 alone means zero
	// cost; it does not select digital delivery.
	if len(body.PublishShop) != 1 || body.PublishShop[0].ExpressWay == nil || *body.PublishShop[0].ExpressWay != 5 {
		t.Error("digital cloud delivery did not explicitly select express_way=5")
	}
}

func TestMarketplaceContractEmptyPropertiesAreNotNull(t *testing.T) {
	m, job := independentMarketplaceFixture(t, "queued")
	transfer, ok := m.app.transfers.job(job.TransferID)
	if !ok {
		t.Fatal("missing test transfer")
	}
	config := job.Config
	config.Properties = nil
	payload, _, _, err := marketplacePayload(transfer, config, job.OuterID)
	if err != nil {
		t.Fatal(err)
	}
	var body map[string]json.RawMessage
	if err = json.Unmarshal(payload, &body); err != nil {
		t.Fatal(err)
	}
	if raw, ok := body["channel_pv"]; ok && string(raw) != "[]" {
		t.Fatalf("optional channel_pv must be omitted or an empty array, got %s", raw)
	}
}

func TestMarketplaceContractPersistedPayloadKeepsUTF8AndLiteralLinks(t *testing.T) {
	m, job := independentMarketplaceFixture(t, "queued")
	transfer, ok := m.app.transfers.job(job.TransferID)
	if !ok {
		t.Fatal("missing test transfer")
	}
	const exact = "这是一款开源游戏，项目 A&B 提供 <原版> 场景，资料 https://example.com/?a=1&b=2。"
	transfer.Description = exact
	payload, _, _, err := marketplacePayload(transfer, job.Config, job.OuterID)
	if err != nil {
		t.Fatal(err)
	}
	if err = m.change(job.ID, func(j *MarketplaceJob) { j.Payload = payload }); err != nil {
		t.Fatal(err)
	}
	var creates int
	m.api = independentMarketplaceClient(t, func(request *http.Request) (*http.Response, error) {
		if request.URL.Path == xgjShopsPath {
			return independentMarketplaceShops(m.now()), nil
		}
		if request.URL.Path != xgjCreatePath {
			t.Fatalf("unexpected API endpoint: %s", request.URL.Path)
		}
		creates++
		body, err := io.ReadAll(request.Body)
		if err != nil {
			t.Fatal(err)
		}
		if !strings.Contains(string(body), exact) || strings.Contains(string(body), `\u0026`) || strings.Contains(string(body), `\u003c`) || strings.Contains(string(body), `\u003e`) {
			t.Error("persisted RawMessage reintroduced Unicode/HTML escaping into the signed body")
		}
		return independentMarketplaceResponse(map[string]any{"product_id": 9007199254740993, "product_status": 21}), nil
	})
	if err = m.step(context.Background(), job.ID); err != nil || creates != 1 {
		t.Fatalf("test create did not run exactly once: creates=%d err=%v", creates, err)
	}
}

func TestMarketplaceContractShopExpiryChecks(t *testing.T) {
	for _, test := range []struct {
		name  string
		valid bool
		auth  time.Duration
		plan  time.Duration
		zero  bool
		want  bool
	}{
		{"current", true, time.Hour, time.Hour, false, true},
		{"expired authorization", true, -time.Hour, time.Hour, false, false},
		{"expired subscription", true, time.Hour, -time.Hour, false, false},
		{"invalid subscription", false, time.Hour, time.Hour, false, false},
		{"undefined zero expiry", true, 0, 0, true, false},
	} {
		t.Run(test.name, func(t *testing.T) {
			m, _ := independentMarketplaceFixture(t, "queued")
			authorizeExpires, validEnd := m.now().Add(test.auth).Unix(), m.now().Add(test.plan).Unix()
			if test.zero {
				authorizeExpires, validEnd = 0, 0
			}
			api := independentMarketplaceClient(t, func(*http.Request) (*http.Response, error) {
				return independentMarketplaceResponse(map[string]any{"list": []map[string]any{{"authorize_id": 81, "user_name": "test-shop", "is_valid": test.valid, "authorize_expires": authorizeExpires, "valid_end_time": validEnd}}}), nil
			})
			err := m.checkShop(context.Background(), api, "test-shop")
			if (err == nil) != test.want {
				t.Fatalf("incorrect authorization/subscription preflight: %v", err)
			}
		})
	}
}

func TestMarketplaceContractRequiredDependentAttributes(t *testing.T) {
	platform := MarketplaceProperty{PropertyID: "platform", PropertyName: "平台", ValueID: "windows", ValueName: "Windows"}
	architecture := MarketplaceProperty{PropertyID: "architecture", PropertyName: "架构", ValueID: "x64", ValueName: "64 位"}
	wrongArchitecture := architecture
	wrongArchitecture.ValueID = "different-value"
	extra := MarketplaceProperty{PropertyID: "unrelated", PropertyName: "无关属性", ValueID: "other", ValueName: "其他"}
	for _, test := range []struct {
		name       string
		properties []MarketplaceProperty
		want       bool
	}{
		{"verified parent and child", []MarketplaceProperty{platform, architecture}, true},
		{"missing required parent", []MarketplaceProperty{}, false},
		{"missing required child", []MarketplaceProperty{platform}, false},
		{"wrong child value", []MarketplaceProperty{platform, wrongArchitecture}, false},
		{"unrelated extra property", []MarketplaceProperty{platform, architecture, extra}, false},
	} {
		t.Run(test.name, func(t *testing.T) {
			m, job := independentMarketplaceFixture(t, "queued")
			config := job.Config
			config.Properties = test.properties
			queriedChild := false
			api := independentMarketplaceClient(t, func(request *http.Request) (*http.Response, error) {
				switch request.URL.Path {
				case xgjShopsPath:
					return independentMarketplaceShops(m.now()), nil
				case xgjCategoriesPath:
					return independentMarketplaceResponse(map[string]any{"list": []map[string]any{{"sp_biz_type": 22, "channel_cat_id": "test-category", "channel_cat_name": "测试类目"}}}), nil
				case xgjPropertiesPath:
					var query struct {
						ItemBizType   int    `json:"item_biz_type"`
						SpBizType     int    `json:"sp_biz_type"`
						ChannelCatID  string `json:"channel_cat_id"`
						SubPropertyID string `json:"sub_property_id"`
					}
					if err := json.NewDecoder(request.Body).Decode(&query); err != nil {
						t.Fatal(err)
					}
					if query.ItemBizType != 2 || query.SpBizType != 22 || query.ChannelCatID != "test-category" {
						t.Error("attribute lookup did not retain selected business type and category")
					}
					if query.SubPropertyID == "" {
						return independentMarketplaceResponse(map[string]any{"list": []map[string]any{{"property_id": "platform", "property_name": "平台", "required": 1, "items": []map[string]any{{"value_id": "windows", "value_name": "Windows", "sub_property_id": "windows-architecture-query"}}}}}), nil
					}
					if query.SubPropertyID != "windows-architecture-query" {
						t.Fatal("child lookup used a parent property/value ID instead of sub_property_id")
					}
					queriedChild = true
					return independentMarketplaceResponse(map[string]any{"list": []map[string]any{{"property_id": "architecture", "property_name": "架构", "required": 1, "items": []map[string]any{{"value_id": "x64", "value_name": "64 位"}}}}}), nil
				default:
					t.Fatalf("configuration validation attempted a write: %s", request.URL.Path)
					return nil, nil
				}
			})
			err := m.validateRemoteConfig(context.Background(), api, config)
			if (err == nil) != test.want {
				t.Fatalf("wrong conditional attribute validation result: %v", err)
			}
			if test.want && !queriedChild {
				t.Error("dependent required attribute was never checked")
			}
		})
	}
}

func TestMarketplaceContractDraftIsNotPublishable(t *testing.T) {
	m, job := independentMarketplaceFixture(t, "created")
	if err := m.change(job.ID, func(j *MarketplaceJob) { j.ProductID = "101" }); err != nil {
		t.Fatal(err)
	}
	var publishCalls int
	m.api = independentMarketplaceClient(t, func(request *http.Request) (*http.Response, error) {
		switch request.URL.Path {
		case xgjProductPath:
			// Official publish_status=1 is draft (edit/delete only), unlike 2
			// which allows publication. An existing product ID is insufficient.
			return independentMarketplaceResponse(map[string]any{"product_id": 101, "product_status": 21, "publish_status": 1, "outer_id": job.OuterID, "publish_shop": []map[string]any{{"user_name": "test-shop", "status": 1, "item_id": 0}}}), nil
		case xgjShopsPath:
			return independentMarketplaceShops(m.now()), nil
		case xgjPublishPath:
			publishCalls++
			return independentMarketplaceResponse(map[string]any{}), nil
		default:
			t.Fatalf("unexpected request while reading draft: %s", request.URL.Path)
			return nil, nil
		}
	})
	if err := m.step(context.Background(), job.ID); err != nil {
		t.Fatal(err)
	}
	if publishCalls != 0 {
		t.Error("publish was submitted for a draft which permits only edit/delete")
	}
}
