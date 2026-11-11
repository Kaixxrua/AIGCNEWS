package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

type xgjTestTransport func(*http.Request) (*http.Response, error)

func (f xgjTestTransport) RoundTrip(request *http.Request) (*http.Response, error) {
	return f(request)
}

func xgjTestClient(fn xgjTestTransport) *xgjClient {
	client := newXGJClient(XGJCredentials{AppKey: "203413189371893", AppSecret: "test-secret-123"})
	client.client.Transport = fn
	client.limiter = &xgjRateLimiter{}
	client.now = func() time.Time { return time.Unix(1636087298, 0) }
	return client
}

func xgjTestResponse(body string) *http.Response {
	return &http.Response{StatusCode: 200, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(body))}
}

func xgjAssertError(t *testing.T, err error, kind string, ambiguous bool) *xgjError {
	t.Helper()
	var failure *xgjError
	if !errors.As(err, &failure) {
		t.Fatalf("expected xgjError, got %v", err)
	}
	if failure.Kind != kind || failure.Ambiguous != ambiguous {
		t.Fatalf("wrong error classification: kind=%s ambiguous=%v", failure.Kind, failure.Ambiguous)
	}
	return failure
}

func TestXGJOfficialSigningVector(t *testing.T) {
	// https://s.apifox.cn/3ac13d69-5a38-4536-ae9b-a54001854ef8/doc-2686716
	credentials := XGJCredentials{AppKey: "203413189371893", AppSecret: "o9wl81dncmvby3ijpq7eur456zhgtaxs"}
	got := xgjSign(credentials, []byte(`{"product_id":"219530767978565"}`), 1636087298)
	if got != "c26c8a48809141f3dd80bd9b9ddb41ea" {
		t.Fatalf("official signature vector mismatch: %s", got)
	}
}

func TestXGJCredentialsValidation(t *testing.T) {
	for _, credentials := range []XGJCredentials{
		{}, {AppKey: "203413189371893"}, {AppSecret: "secret"},
		{AppKey: "0", AppSecret: "secret"}, {AppKey: "01", AppSecret: "secret"},
		{AppKey: " 203413189371893", AppSecret: "secret"},
		{AppKey: "9223372036854775808", AppSecret: "secret"},
		{AppKey: "203413189371893", AppSecret: "secret\n"},
		{AppKey: "203413189371893", AppSecret: "se cret"},
		{AppKey: "203413189371893", AppSecret: "中文"},
		{AppKey: "203413189371893", AppSecret: strings.Repeat("s", 257)},
	} {
		if validXGJCredentials(credentials) {
			t.Error("accepted invalid credentials")
		}
	}
	if !validXGJCredentials(XGJCredentials{AppKey: "9223372036854775807", AppSecret: "valid-secret+!"}) {
		t.Error("rejected valid credentials")
	}
}

func TestXGJJSONUsesExactUTF8BodyAndInt64(t *testing.T) {
	const productID = int64(9007199254740993)
	var calls int
	client := xgjTestClient(func(request *http.Request) (*http.Response, error) {
		calls++
		body, err := io.ReadAll(request.Body)
		if err != nil {
			t.Fatal(err)
		}
		if request.URL.Scheme != "https" || request.URL.Host != "open.goofish.pro" || request.Method != http.MethodPost {
			t.Fatal("unexpected destination or method")
		}
		if request.URL.Path != xgjCreatePath || request.GetBody != nil {
			t.Fatal("wrong endpoint or replayable request body")
		}
		if !strings.Contains(string(body), "中文 <测试> & https://example.com/?a=1&b=2") || strings.Contains(string(body), `\u`) || strings.HasSuffix(string(body), "\n") {
			t.Fatalf("request body escaped or not compact: %s", body)
		}
		query := request.URL.Query()
		if query.Get("sign") != xgjSign(XGJCredentials{AppKey: "203413189371893", AppSecret: "test-secret-123"}, body, 1636087298) || query.Get("timestamp") != "1636087298" || query.Get("appid") != "203413189371893" || len(query) != 3 {
			t.Fatal("signature does not match actual transmitted body")
		}
		return xgjTestResponse(fmt.Sprintf(`{"code":0,"data":{"product_id":%d,"product_status":21}}`, productID)), nil
	})
	payload := XGJCreateRequest{ItemBizType: 2, SpBizType: 22, ChannelCatID: "category", Price: 100, Stock: 1, OuterID: "portshelf-test", PublishShop: []XGJPublishShop{{UserName: "shop", Province: 110000, City: 110100, District: 110101, Title: "中文 <测试> & https://example.com/?a=1&b=2", Content: "测试内容", Images: []string{"https://example.com/image.jpg"}}}}
	product, err := client.createProduct(context.Background(), payload)
	if err != nil || calls != 1 || product.ProductID != productID {
		t.Fatalf("create failed or lost integer precision: %+v %v calls=%d", product, err, calls)
	}
}

func TestXGJNoBodySignsAndSendsEmptyObject(t *testing.T) {
	client := xgjTestClient(func(request *http.Request) (*http.Response, error) {
		body, _ := io.ReadAll(request.Body)
		if string(body) != "{}" || request.ContentLength != 2 {
			t.Fatalf("unexpected no-argument body: %q", body)
		}
		return xgjTestResponse(`{"code":0,"data":{"list":[]}}`), nil
	})
	shops, err := client.listShops(context.Background())
	if err != nil || shops == nil || len(shops) != 0 {
		t.Fatalf("empty authorized shop list not preserved: %+v %v", shops, err)
	}
}

func TestXGJKnownEndpointsAndDestinationOnly(t *testing.T) {
	var requests int
	client := xgjTestClient(func(*http.Request) (*http.Response, error) {
		requests++
		return xgjTestResponse(`{"code":0,"data":{}}`), nil
	})
	for _, path := range []string{"https://evil.example/api", "/api/open/product/delete", xgjPublishPath + "?target=evil", "/api/open/product/../product/publish"} {
		xgjAssertError(t, client.call(context.Background(), path, nil, nil), "invalid_endpoint", false)
	}
	client.baseURL = "https://evil.example"
	xgjAssertError(t, client.call(context.Background(), xgjPublishPath, nil, nil), "invalid_endpoint", false)
	client.baseURL = xgjAPIOrigin
	client.credentials.AppSecret = ""
	xgjAssertError(t, client.call(context.Background(), xgjPublishPath, nil, nil), "credentials", false)
	if requests != 0 {
		t.Fatalf("invalid destination/credentials sent %d requests", requests)
	}
}

func TestXGJStrictEnvelopeAndEndpointData(t *testing.T) {
	tests := []struct {
		name string
		path string
		body string
	}{
		{"missing code", xgjPublishPath, `{"msg":"OK","data":{}}`},
		{"null code", xgjPublishPath, `{"code":null,"data":{}}`},
		{"string code", xgjPublishPath, `{"code":"0","data":{}}`},
		{"decimal code", xgjPublishPath, `{"code":0.0,"data":{}}`},
		{"missing data", xgjPublishPath, `{"code":0}`},
		{"null data", xgjPublishPath, `{"code":0,"data":null}`},
		{"scalar data", xgjPublishPath, `{"code":0,"data":"OK"}`},
		{"array data", xgjPublishPath, `{"code":0,"data":[]}`},
		{"duplicate code", xgjPublishPath, `{"code":403,"code":0,"data":{}}`},
		{"duplicate data", xgjPublishPath, `{"code":0,"data":{},"data":{}}`},
		{"trailing JSON", xgjPublishPath, `{"code":0,"data":{}}{}`},
		{"malformed JSON", xgjPublishPath, `{"code":0,"data":`},
		{"missing list", xgjShopsPath, `{"code":0,"data":{}}`},
		{"null list", xgjShopsPath, `{"code":0,"data":{"list":null}}`},
		{"invalid row", xgjShopsPath, `{"code":0,"data":{"list":[null]}}`},
		{"empty shop", xgjShopsPath, `{"code":0,"data":{"list":[{}]}}`},
		{"empty create", xgjCreatePath, `{"code":0,"data":{}}`},
		{"invalid product id", xgjCreatePath, `{"code":0,"data":{"product_id":0,"product_status":21}}`},
		{"string product id", xgjCreatePath, `{"code":0,"data":{"product_id":"9007199254740993","product_status":21}}`},
		{"missing created status", xgjCreatePath, `{"code":0,"data":{"product_id":9007199254740993}}`},
		{"missing publish status", xgjProductPath, `{"code":0,"data":{"product_id":1,"product_status":22,"publish_shop":[]}}`},
		{"missing shop statuses", xgjProductPath, `{"code":0,"data":{"product_id":1,"product_status":22,"publish_status":3}}`},
		{"duplicate shop status", xgjProductPath, `{"code":0,"data":{"product_id":1,"product_status":22,"publish_status":3,"publish_shop":[{"user_name":"shop","status":2,"status":1,"item_id":123}]}}`},
		{"null shop status", xgjProductPath, `{"code":0,"data":{"product_id":1,"product_status":22,"publish_status":3,"publish_shop":[{"user_name":"shop","status":null,"item_id":123}]}}`},
		{"string item id", xgjProductPath, `{"code":0,"data":{"product_id":1,"product_status":22,"publish_status":3,"publish_shop":[{"user_name":"shop","status":1,"item_id":"123"}]}}`},
		{"page missing count", xgjProductsPath, `{"code":0,"data":{"list":[],"page_no":1,"page_size":100}}`},
		{"page missing page", xgjProductsPath, `{"code":0,"data":{"list":[],"count":0,"page_size":100}}`},
		{"page invalid size", xgjProductsPath, `{"code":0,"data":{"list":[],"count":0,"page_no":1,"page_size":101}}`},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			client := xgjTestClient(func(*http.Request) (*http.Response, error) { return xgjTestResponse(test.body), nil })
			xgjAssertError(t, client.call(context.Background(), test.path, nil, nil), "invalid_response", true)
		})
	}
}

func TestXGJResultDecodePreservesNumbersAndRejectsWrongFieldType(t *testing.T) {
	client := xgjTestClient(func(*http.Request) (*http.Response, error) {
		return xgjTestResponse(`{"code":0,"data":{"product_id":9007199254740993,"product_status":21}}`), nil
	})
	var result map[string]any
	if err := client.call(context.Background(), xgjCreatePath, nil, &result); err != nil {
		t.Fatal(err)
	}
	number, ok := result["product_id"].(json.Number)
	if !ok || number.String() != "9007199254740993" {
		t.Fatalf("integer decoded through float: %#v", result)
	}
	client.client.Transport = xgjTestTransport(func(*http.Request) (*http.Response, error) {
		return xgjTestResponse(`{"code":0,"data":{"list":[{"authorize_id":123,"user_name":"shop","is_valid":"true"}]}}`), nil
	})
	_, err := client.listShops(context.Background())
	xgjAssertError(t, err, "invalid_response", true)
}

func TestXGJDetailPreservesShopIdentityAndMissingStatus(t *testing.T) {
	client := xgjTestClient(func(request *http.Request) (*http.Response, error) {
		body, _ := io.ReadAll(request.Body)
		if string(body) != `{"product_id":9007199254740993}` {
			t.Fatalf("large product ID changed on wire: %s", body)
		}
		return xgjTestResponse(`{"code":0,"data":{"product_id":9007199254740993,"product_status":22,"publish_status":3,"outer_id":"ours","publish_shop":[{"user_name":"other","item_id":9007199254740994,"status":1},{"user_name":"target","item_id":0}]}}`), nil
	})
	detail, err := client.productDetail(context.Background(), 9007199254740993)
	if err != nil || detail.PublishStatus == nil || *detail.PublishStatus != 3 || len(detail.PublishShop) != 2 || detail.PublishShop[0].ItemID != 9007199254740994 || detail.PublishShop[1].Status != nil {
		t.Fatalf("per-shop identity or absent status lost: %+v %v", detail, err)
	}
	client.client.Transport = xgjTestTransport(func(*http.Request) (*http.Response, error) {
		return xgjTestResponse(`{"code":0,"data":{"product_id":2,"product_status":22,"publish_status":3,"publish_shop":[]}}`), nil
	})
	_, err = client.productDetail(context.Background(), 1)
	xgjAssertError(t, err, "invalid_response", true)
}

func TestXGJLookupAndReconciliationWireContracts(t *testing.T) {
	tests := []struct {
		path string
		body string
		call func(*xgjClient) error
	}{
		{xgjAddressesPath, `{"type":0}`, func(c *xgjClient) error { _, err := c.listAddresses(context.Background(), 0); return err }},
		{xgjCategoriesPath, `{"item_biz_type":2,"sp_biz_type":22}`, func(c *xgjClient) error { _, err := c.listCategories(context.Background(), 2, 22); return err }},
		{xgjPropertiesPath, `{"item_biz_type":2,"sp_biz_type":22,"channel_cat_id":"category","sub_property_id":"child"}`, func(c *xgjClient) error {
			_, err := c.listProperties(context.Background(), 2, 22, "category", "child")
			return err
		}},
		{xgjProductsPath, `{"page_no":2,"page_size":100,"update_time":[100,200]}`, func(c *xgjClient) error { _, err := c.listProducts(context.Background(), 2, 100, 100, 200); return err }},
	}
	for _, test := range tests {
		t.Run(test.path, func(t *testing.T) {
			client := xgjTestClient(func(request *http.Request) (*http.Response, error) {
				body, _ := io.ReadAll(request.Body)
				if request.URL.Path != test.path || string(body) != test.body {
					t.Fatalf("wrong endpoint or request body: %s %s", request.URL.Path, body)
				}
				if test.path == xgjProductsPath {
					return xgjTestResponse(`{"code":0,"data":{"list":[],"count":0,"page_no":2,"page_size":100}}`), nil
				}
				return xgjTestResponse(`{"code":0,"data":{"list":[]}}`), nil
			})
			if err := test.call(client); err != nil {
				t.Fatal(err)
			}
		})
	}
}

func TestXGJReconciliationRejectsWrongPageOrIncompleteCount(t *testing.T) {
	for _, data := range []string{
		`{"list":[],"count":0,"page_no":1,"page_size":100}`,
		`{"list":[],"count":0,"page_no":2,"page_size":50}`,
		`{"list":[{"product_id":123}],"count":0,"page_no":2,"page_size":100}`,
	} {
		client := xgjTestClient(func(*http.Request) (*http.Response, error) {
			return xgjTestResponse(`{"code":0,"data":` + data + `}`), nil
		})
		_, err := client.listProducts(context.Background(), 2, 100, 0, 0)
		xgjAssertError(t, err, "invalid_response", true)
	}
}

func TestXGJErrorClassificationAndRedaction(t *testing.T) {
	const sentinel = "test-secret-123 https://open.goofish.pro/path?appid=203413189371893&sign=SECRET_SIGNATURE"
	tests := []struct {
		name      string
		status    int
		body      string
		kind      string
		ambiguous bool
	}{
		{"unauthorized", 200, `{"code":403,"msg":"未授权 ` + sentinel + `"}`, "unauthorized", false},
		{"application offline", 200, `{"code":1001,"msg":"应用已下线 ` + sentinel + `"}`, "application_unavailable", false},
		{"rejected parameter", 200, `{"code":400,"msg":"参数错误 ` + sentinel + `"}`, "rejected", false},
		{"API server failure", 200, `{"code":500,"msg":"` + sentinel + `"}`, "server", true},
		{"internal timeout", 200, `{"code":1002,"msg":"请求处理超时 ` + sentinel + `"}`, "server", true},
		{"HTTP permission", 401, sentinel, "unauthorized", false},
		{"HTTP throttled", 429, sentinel, "rate_limited", false},
		{"HTTP gateway", 502, sentinel, "http", true},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			client := xgjTestClient(func(*http.Request) (*http.Response, error) {
				response := xgjTestResponse(test.body)
				response.StatusCode = test.status
				return response, nil
			})
			err := client.call(context.Background(), xgjCreatePath, nil, nil)
			xgjAssertError(t, err, test.kind, test.ambiguous)
			if strings.Contains(err.Error(), "test-secret") || strings.Contains(err.Error(), "https:") || strings.Contains(err.Error(), "SECRET_SIGNATURE") || strings.Contains(err.Error(), "203413189371893") {
				t.Fatal("provider error leaked a credential or URL")
			}
		})
	}
	client := xgjTestClient(func(request *http.Request) (*http.Response, error) {
		return nil, fmt.Errorf("failed request %s %s", request.URL, sentinel)
	})
	err := client.call(context.Background(), xgjCreatePath, nil, nil)
	xgjAssertError(t, err, "transport", true)
	if errors.Unwrap(err) != nil || strings.Contains(fmt.Sprintf("%+v", err), "https:") || strings.Contains(fmt.Sprintf("%+v", err), "secret") {
		t.Fatal("transport error leaked its signed URL through wrapping")
	}
}

func TestXGJRedirectNeverForwardsSignedRequest(t *testing.T) {
	var calls int
	client := xgjTestClient(func(request *http.Request) (*http.Response, error) {
		calls++
		response := xgjTestResponse("")
		response.StatusCode = http.StatusTemporaryRedirect
		response.Header.Set("Location", "https://other.example/steal")
		return response, nil
	})
	// A caller replacing the client must not accidentally restore redirects.
	client.client.CheckRedirect = nil
	err := client.publishProduct(context.Background(), 123, "shop")
	xgjAssertError(t, err, "redirect", true)
	if calls != 1 {
		t.Fatalf("redirect caused %d calls", calls)
	}
}

func TestXGJCreateAndPublishNeverRetry(t *testing.T) {
	for _, path := range []string{xgjCreatePath, xgjPublishPath} {
		for _, fault := range []string{"network", "timeout", "malformed", "server"} {
			t.Run(path+fault, func(t *testing.T) {
				var calls int
				client := xgjTestClient(func(*http.Request) (*http.Response, error) {
					calls++
					switch fault {
					case "network":
						return nil, errors.New("connection reset after upstream write")
					case "timeout":
						return nil, context.DeadlineExceeded
					case "server":
						return xgjTestResponse(`{"code":500,"msg":"Internal Server Error"}`), nil
					default:
						return xgjTestResponse(`{"code":0`), nil
					}
				})
				err := client.call(context.Background(), path, nil, nil)
				var failure *xgjError
				if !errors.As(err, &failure) || !failure.Ambiguous || calls != 1 {
					t.Fatalf("unsafe write retry or error: calls=%d error=%v", calls, err)
				}
			})
		}
	}
}

func TestXGJPublishAcknowledgmentDoesNotFetchOrClaimPublished(t *testing.T) {
	var calls int
	client := xgjTestClient(func(request *http.Request) (*http.Response, error) {
		calls++
		body, _ := io.ReadAll(request.Body)
		if request.URL.Path != xgjPublishPath || string(body) != `{"product_id":9007199254740993,"user_name":["shop"]}` {
			t.Fatalf("unexpected publish request: %s %s", request.URL.Path, body)
		}
		return xgjTestResponse(`{"code":0,"data":{}}`), nil
	})
	if err := client.publishProduct(context.Background(), 9007199254740993, "shop"); err != nil || calls != 1 {
		t.Fatalf("publish acknowledgment failed: %v calls=%d", err, calls)
	}
}

func TestXGJResponseSizeLimit(t *testing.T) {
	client := xgjTestClient(func(*http.Request) (*http.Response, error) {
		return xgjTestResponse(`{"code":0,"data":{},"padding":"` + strings.Repeat("x", xgjResponseLimit) + `"}`), nil
	})
	xgjAssertError(t, client.call(context.Background(), xgjPublishPath, nil, nil), "invalid_response", true)
}

func TestXGJCancellationBeforeAndAfterSend(t *testing.T) {
	var calls int
	client := xgjTestClient(func(request *http.Request) (*http.Response, error) {
		calls++
		<-request.Context().Done()
		return nil, request.Context().Err()
	})
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	err := client.call(ctx, xgjCreatePath, nil, nil)
	xgjAssertError(t, err, "cancelled", false)
	if !errors.Is(err, context.Canceled) || calls != 0 {
		t.Fatal("cancelled request was sent or cancellation identity lost")
	}
	ctx, cancel = context.WithTimeout(context.Background(), 20*time.Millisecond)
	defer cancel()
	err = client.call(ctx, xgjCreatePath, nil, nil)
	xgjAssertError(t, err, "timeout", true)
	if !errors.Is(err, context.DeadlineExceeded) || calls != 1 {
		t.Fatal("cancellation after send was not marked ambiguous")
	}
}

func TestXGJRateLimitSharedAcrossClientsAndCancellable(t *testing.T) {
	if newXGJClient(XGJCredentials{}).limiter != newXGJClient(XGJCredentials{}).limiter || xgjSharedLimiter.interval < 500*time.Millisecond {
		t.Fatal("default clients do not share <=2 per second limiter")
	}
	limiter := &xgjRateLimiter{interval: xgjRequestInterval}
	if err := limiter.wait(context.Background()); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
	defer cancel()
	start := time.Now()
	if err := limiter.wait(ctx); !errors.Is(err, context.DeadlineExceeded) || time.Since(start) > 300*time.Millisecond {
		t.Fatalf("rate limit wait was not promptly cancelled: %v", err)
	}
	var mu sync.Mutex
	var times []time.Time
	limiter = &xgjRateLimiter{interval: xgjRequestInterval}
	var calls atomic.Int32
	transport := xgjTestTransport(func(*http.Request) (*http.Response, error) {
		mu.Lock()
		times = append(times, time.Now())
		mu.Unlock()
		calls.Add(1)
		return xgjTestResponse(`{"code":0,"data":{"list":[]}}`), nil
	})
	var group sync.WaitGroup
	for i := 0; i < 3; i++ {
		client := xgjTestClient(transport)
		client.limiter = limiter
		group.Add(1)
		go func() {
			defer group.Done()
			if _, err := client.listShops(context.Background()); err != nil {
				t.Error(err)
			}
		}()
	}
	group.Wait()
	if calls.Load() != 3 || times[1].Sub(times[0]) < 490*time.Millisecond || times[2].Sub(times[1]) < 490*time.Millisecond {
		t.Fatalf("concurrent clients exceeded rate limit: %v", times)
	}
}

func TestXGJInvalidQueriesAndPayloadNeverSend(t *testing.T) {
	var calls int
	client := xgjTestClient(func(*http.Request) (*http.Response, error) {
		calls++
		return xgjTestResponse(`{"code":0,"data":{}}`), nil
	})
	_, err := client.listProducts(context.Background(), 101, 100, 0, 0)
	xgjAssertError(t, err, "invalid_request", false)
	_, err = client.listProducts(context.Background(), 1, 100, 200, 100)
	xgjAssertError(t, err, "invalid_request", false)
	_, err = client.productDetail(context.Background(), 0)
	xgjAssertError(t, err, "invalid_request", false)
	xgjAssertError(t, client.publishProduct(context.Background(), 1, " "), "invalid_request", false)
	xgjAssertError(t, client.call(context.Background(), xgjCreatePath, map[string]any{"bad": make(chan int)}, nil), "invalid_request", false)
	xgjAssertError(t, client.call(context.Background(), xgjCreatePath, map[string]string{"oversize": strings.Repeat("x", xgjRequestLimit+1)}, nil), "invalid_request", false)
	if calls != 0 {
		t.Fatal("invalid request reached transport")
	}
}
