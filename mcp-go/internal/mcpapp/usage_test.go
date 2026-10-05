package mcpapp

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/alicebob/miniredis/v2"
	"github.com/redis/go-redis/v9"

	"aigcnews/mcp-go/internal/authn"
	"aigcnews/mcp-go/internal/ratelimit"
	"aigcnews/mcp-go/internal/usage"
)

// 每日用量汇总的 HTTP 接线：限流之后、分派之前记录；响应字节与未接线时一致。

func newUsageHandler(t *testing.T, auth Authenticator, limiter *ratelimit.Limiter) (*Handler, *miniredis.Miniredis, *redis.Client) {
	t.Helper()
	app, mr := newMetricsApp(t)
	client := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	t.Cleanup(func() { _ = client.Close() })
	handler := NewHandler(app, auth, limiter)
	handler.SetUsage(usage.NewRecorder(client))
	return handler, mr, client
}

func postFrom(t *testing.T, handler http.Handler, body, remoteAddr, forwardedFor string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(http.MethodPost, "http://example.test/api/mcp", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	if remoteAddr != "" {
		req.RemoteAddr = remoteAddr
	}
	if forwardedFor != "" {
		req.Header.Set("X-Forwarded-For", forwardedFor)
	}
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	return rec
}

// usageKey 找当天的 mcpusage 键（按后缀匹配，跨午夜运行也不误判）。
func usageKey(t *testing.T, mr *miniredis.Miniredis, suffix string) string {
	t.Helper()
	for _, key := range mr.Keys() {
		if strings.HasPrefix(key, "mcpusage:") && strings.HasSuffix(key, ":"+suffix) {
			return key
		}
	}
	t.Fatalf("no mcpusage key with suffix %q in %v", suffix, mr.Keys())
	return ""
}

const (
	initializeBody = `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"Cursor","version":"1.7"}}}`
	toolCallBody   = `{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"search_papers","arguments":{}}}`
)

func TestHandlerRecordsUsageForAuthenticatedUser(t *testing.T) {
	auth := &stubAuthenticator{identity: authn.Identity{UserID: 42, Role: "user", MembershipTier: authn.TierFree}, authenticated: true}
	handler, mr, client := newUsageHandler(t, auth, nil)
	for _, body := range []string{initializeBody, `{"jsonrpc":"2.0","method":"notifications/initialized"}`, toolCallBody, toolCallBody} {
		if rec := postFrom(t, handler, body, "", ""); rec.Code != http.StatusOK && rec.Code != http.StatusNoContent {
			t.Fatalf("status %d body %s", rec.Code, rec.Body)
		}
	}
	if got := mr.HGet(usageKey(t, mr, "calls"), "free|search_papers"); got != "2" {
		t.Errorf("calls[free|search_papers] = %q", got)
	}
	if got := mr.HGet(usageKey(t, mr, "client_names"), "free|cursor"); got != "1" {
		t.Errorf("client_names[free|cursor] = %q", got)
	}
	if n, _ := client.PFCount(context.Background(), usageKey(t, mr, "clients:free")).Result(); n != 1 {
		t.Errorf("clients:free = %d", n)
	}
}

func TestHandlerRecordsRateLimitedRequests(t *testing.T) {
	store := &countingRedis{}
	limiter := ratelimit.NewLimiter(store, "", func(l *ratelimit.Limits) {
		l.AuthenticatedToolCallPerMinute = 1
	})
	auth := &stubAuthenticator{identity: authn.Identity{UserID: 42, Role: "user"}, authenticated: true}
	handler, mr, _ := newUsageHandler(t, auth, limiter)
	if rec := postFrom(t, handler, toolCallBody, "", ""); rec.Code != http.StatusOK {
		t.Fatalf("first call status %d", rec.Code)
	}
	if rec := postFrom(t, handler, toolCallBody, "", ""); rec.Code != http.StatusTooManyRequests {
		t.Fatalf("second call status %d", rec.Code)
	}
	if got := mr.HGet(usageKey(t, mr, "limited"), "free|burst"); got != "1" {
		t.Errorf("limited[free|burst] = %q", got)
	}
	if got := mr.HGet(usageKey(t, mr, "calls"), "free|search_papers"); got != "1" {
		t.Errorf("only the dispatched call counts, calls = %q", got)
	}
}

func TestHandlerSkipsAdminUsage(t *testing.T) {
	auth := &stubAuthenticator{identity: authn.Identity{UserID: 1, Role: "admin"}, authenticated: true}
	handler, mr, _ := newUsageHandler(t, auth, nil)
	postFrom(t, handler, initializeBody, "", "")
	postFrom(t, handler, toolCallBody, "", "")
	for _, key := range mr.Keys() {
		if strings.HasPrefix(key, "mcpusage:") {
			t.Fatalf("admin traffic recorded: %s", key)
		}
	}
}

// 匿名去重按限流器同款可信代理规则取来源 IP：可信对端转发时认 XFF 首跳。
func TestHandlerAnonymousClientsUseTrustedClientIP(t *testing.T) {
	limiter := ratelimit.NewLimiter(&countingRedis{}, "192.0.2.1")
	handler, mr, client := newUsageHandler(t, nil, limiter)
	postFrom(t, handler, toolCallBody, "192.0.2.1:4100", "198.51.100.9")
	postFrom(t, handler, toolCallBody, "192.0.2.1:4101", "198.51.100.9")
	postFrom(t, handler, toolCallBody, "192.0.2.1:4102", "198.51.100.10")
	if n, _ := client.PFCount(context.Background(), usageKey(t, mr, "clients:anonymous")).Result(); n != 2 {
		t.Errorf("clients:anonymous = %d, want 2 (two forwarded IPs behind one proxy)", n)
	}
	for _, key := range mr.Keys() {
		if strings.Contains(key, "198.51.100") {
			t.Errorf("raw IP in key %s", key)
		}
	}
}

// 接线前后同一组请求的状态码、响应头（除随机会话 id）与响应体逐字节相同。
func TestHandlerUsageDoesNotChangeWireBytes(t *testing.T) {
	bodies := []string{
		initializeBody,
		`{"jsonrpc":"2.0","method":"notifications/initialized"}`,
		`{"jsonrpc":"2.0","id":3,"method":"tools/list"}`,
		toolCallBody,
		`{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"no_such_tool","arguments":{}}}`,
		`{"jsonrpc":"2.0","id":5,"method":"ping"}`,
		`{"jsonrpc":"2.0","id":6,"method":"nope"}`,
	}
	plainApp, _ := newMetricsApp(t)
	plain := NewHandler(plainApp, nil, nil)
	wired, mr, _ := newUsageHandler(t, nil, nil)
	for _, body := range bodies {
		want := postFrom(t, plain, body, "", "")
		got := postFrom(t, wired, body, "", "")
		if got.Code != want.Code || got.Body.String() != want.Body.String() {
			t.Fatalf("%s: wired %d %q, plain %d %q", body, got.Code, got.Body, want.Code, want.Body)
		}
		wantHeader, gotHeader := want.Header().Clone(), got.Header().Clone()
		wantHeader.Del("Mcp-Session-Id")
		gotHeader.Del("Mcp-Session-Id")
		if len(wantHeader) != len(gotHeader) {
			t.Fatalf("%s: headers differ %v vs %v", body, gotHeader, wantHeader)
		}
		for name := range wantHeader {
			if gotHeader.Get(name) != wantHeader.Get(name) {
				t.Fatalf("%s: header %s = %q, want %q", body, name, gotHeader.Get(name), wantHeader.Get(name))
			}
		}
	}
	if !mr.Exists(usageKey(t, mr, "calls")) {
		t.Fatal("wired handler did not record usage")
	}
}
