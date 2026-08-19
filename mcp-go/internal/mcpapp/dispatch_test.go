package mcpapp

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"regexp"
	"strings"
	"testing"
	"time"

	"aigcnews/mcp-go/internal/authn"
	"aigcnews/mcp-go/internal/ratelimit"
	"aigcnews/mcp-go/internal/wire"
)

func rpc(id any, method string, params string) wire.ValidatedRequest {
	var p map[string]any
	if params != "" {
		if err := json.Unmarshal([]byte(params), &p); err != nil {
			panic(err)
		}
	}
	if p == nil {
		p = map[string]any{}
	}
	return wire.ValidatedRequest{RequestID: id, Method: method, Params: p, HasID: id != nil}
}

func newApp() *App { return New("aigc-radar", "1.2.0", Handlers{}) }

func TestInitializeExactShapeAndSession(t *testing.T) {
	r := newApp().Dispatch(rpc(1, "initialize", `{}`))
	if r.Status != http.StatusOK {
		t.Fatalf("status %d", r.Status)
	}
	if !regexp.MustCompile(`^aigc-radar-[0-9a-f]{32}$`).MatchString(r.Headers.Get("Mcp-Session-Id")) {
		t.Fatalf("bad session %q", r.Headers.Get("Mcp-Session-Id"))
	}
	body := string(r.Body)
	for _, fragment := range []string{
		`"protocolVersion":"2025-06-18"`,
		`"capabilities":{"tools":{"listChanged":false},"resources":{"subscribe":false,"listChanged":false},"prompts":{"listChanged":false}}`,
		`"serverInfo":{"name":"aigc-radar","version":"1.2.0"}`,
		`"instructions":"When the user explicitly asks`,
	} {
		if !strings.Contains(body, fragment) {
			t.Errorf("initialize body 缺片段 %q:\n%s", fragment, body)
		}
	}
	// 顶层键序钉死：protocolVersion → capabilities → serverInfo → instructions。
	wantOrder := []string{`"protocolVersion"`, `"capabilities"`, `"serverInfo"`, `"instructions"`}
	cursor := 0
	for _, key := range wantOrder {
		next := strings.Index(body[cursor:], key)
		if next < 0 {
			t.Fatalf("键 %s 缺失或顺序错误:\n%s", key, body)
		}
		cursor += next + len(key)
	}
}

func TestNotificationsAlways204(t *testing.T) {
	for _, method := range []string{"notifications/initialized", "notifications/cancelled", "unknown", "tools/call", "tools/list"} {
		r := newApp().Dispatch(wire.ValidatedRequest{Method: method, HasID: false, Params: map[string]any{}})
		if r.Status != http.StatusNoContent || r.Body != nil {
			t.Fatalf("%s: %#v", method, r)
		}
		if r.Headers.Get("MCP-Protocol-Version") != wire.ProtocolVersion {
			t.Fatalf("%s: missing protocol header", method)
		}
	}
}

func TestUnknownMethodAndPing(t *testing.T) {
	for _, method := range []string{"unknown/method", "ping"} {
		r := newApp().Dispatch(rpc(9, method, `{}`))
		want := `{"jsonrpc":"2.0","id":9,"error":{"code":-32601,"message":"Method not found"}}`
		if string(r.Body) != want {
			t.Errorf("%s: %s", method, r.Body)
		}
	}
}

func TestToolsCallValidationUnknownAndCrash(t *testing.T) {
	a := New("aigc-radar", "1.2.0", Handlers{
		"crash": func(map[string]any) (any, error) { return nil, errors.New("boom") },
	})
	r := a.Dispatch(rpc(6, "tools/call", `{"arguments":{}}`))
	want := `{"jsonrpc":"2.0","id":6,"error":{"code":-32602,"message":"tools/call params.name is required"}}`
	if string(r.Body) != want {
		t.Fatalf("missing name: %s", r.Body)
	}

	r = a.Dispatch(rpc(1, "tools/call", `{"name":"not-a-tool","arguments":{}}`))
	// 语料 unknown-tool-call 逐字节形状：content 项 type 先于 text，
	// 内层 text 用 Python 默认分隔符（", " / ": "）。
	want = `{"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"{\"error\": \"Unknown tool: not-a-tool\"}"}],"isError":true}}`
	if string(r.Body) != want {
		t.Fatalf("unknown tool:\n got %s\nwant %s", r.Body, want)
	}

	r = a.Dispatch(rpc(1, "tools/call", `{"name":"crash","arguments":{}}`))
	want = `{"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"{\"error\": \"Tool execution failed.\"}"}],"isError":true}}`
	if string(r.Body) != want {
		t.Fatalf("handler crash:\n got %s\nwant %s", r.Body, want)
	}
}

func TestSuccessfulToolCallHasStructuredContent(t *testing.T) {
	a := New("aigc-radar", "1.2.0", Handlers{
		"ok": func(map[string]any) (any, error) {
			return map[string]any{"items": []any{}}, nil
		},
	})
	r := a.Dispatch(rpc(1, "tools/call", `{"name":"ok","arguments":{}}`))
	if !strings.Contains(string(r.Body), `"structuredContent":{"items":[]}`) ||
		!strings.Contains(string(r.Body), `"isError":false`) {
		t.Fatalf("success shape: %s", r.Body)
	}
}

// ── HTTP 接线：方法闸 / 认证先于解析 / panic 兜底 500 ────────────────────

type stubAuthenticator struct {
	failDetail string
	identity   authn.Identity
	seen       bool
}

func (s *stubAuthenticator) Authenticate(_ context.Context, authorization string) (authn.Identity, *authn.Response) {
	s.seen = true
	if s.failDetail != "" && strings.HasPrefix(authorization, "Bearer") {
		return authn.Identity{}, &authn.Response{
			Status:  http.StatusUnauthorized,
			Body:    []byte(`{"detail":"` + s.failDetail + `"}`),
			Headers: http.Header{},
		}
	}
	return s.identity, nil
}

func post(t *testing.T, handler http.Handler, body string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(http.MethodPost, "http://example.test/api/mcp", strings.NewReader(body))
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	return rec
}

func TestHandlerMethodGate(t *testing.T) {
	handler := NewHandler(newApp(), nil, nil)
	for _, method := range []string{http.MethodGet, http.MethodPut, http.MethodDelete, http.MethodHead} {
		req := httptest.NewRequest(method, "http://example.test/api/mcp", nil)
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		if rec.Code != http.StatusMethodNotAllowed {
			t.Fatalf("%s: status=%d", method, rec.Code)
		}
		if rec.Header().Get("Allow") != http.MethodPost {
			t.Fatalf("%s: allow=%q", method, rec.Header().Get("Allow"))
		}
		if method != http.MethodHead && rec.Body.String() != `{"detail":"Method Not Allowed"}` {
			t.Fatalf("%s: body=%q", method, rec.Body.String())
		}
	}
}

func TestHandlerAuthPrecedesParsing(t *testing.T) {
	auth := &stubAuthenticator{failDetail: "MCP Token 无效、已过期或已撤销"}
	handler := NewHandler(newApp(), auth, nil)
	// 请求体是非法 JSON：若解析先于认证会回 -32700，401 证明顺序正确。
	req := httptest.NewRequest(http.MethodPost, "http://example.test/api/mcp", strings.NewReader("{"))
	req.Header.Set("Authorization", "Bearer whatever")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if !auth.seen {
		t.Fatal("authenticator not consulted")
	}
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body)
	}
	if rec.Header().Get("MCP-Protocol-Version") != "" {
		t.Fatal("401 泄漏了协议头")
	}
}

func TestHandlerAnonymousPassesThrough(t *testing.T) {
	handler := NewHandler(newApp(), &stubAuthenticator{}, nil)
	rec := post(t, handler, `{"jsonrpc":"2.0","id":9,"method":"ping"}`)
	want := `{"jsonrpc":"2.0","id":9,"error":{"code":-32601,"message":"Method not found"}}`
	if rec.Code != http.StatusOK || rec.Body.String() != want {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body)
	}
}

func TestHandlerParseErrorProjection(t *testing.T) {
	handler := NewHandler(newApp(), nil, nil)
	rec := post(t, handler, "{")
	want := `{"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":"Parse error"}}`
	if rec.Code != http.StatusOK || rec.Body.String() != want {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body)
	}
}

// countingRedis 钉住 Handler 将认证身份传给 limiter，且限流发生在解析之后：
// user 维度分钟桶限额为 1，第一次通过、第二次同请求投影 429。
type countingRedis struct {
	counts map[string]int64
}

func (r *countingRedis) Incr(_ context.Context, key string) (int64, error) {
	if r.counts == nil {
		r.counts = map[string]int64{}
	}
	r.counts[key]++
	return r.counts[key], nil
}

func (r *countingRedis) TTL(context.Context, string) (time.Duration, error) {
	return 50 * time.Second, nil
}

func (r *countingRedis) Expire(context.Context, string, time.Duration) (bool, error) {
	return true, nil
}

func TestHandlerRateLimitAfterParseUsesAuthenticatedIdentity(t *testing.T) {
	store := &countingRedis{}
	limiter := ratelimit.NewLimiter(store, "", func(l *ratelimit.Limits) {
		l.AuthenticatedProtocolPerMinute = 1
	})
	auth := &stubAuthenticator{identity: authn.Identity{UserID: 42, Role: "user"}}
	handler := NewHandler(newApp(), auth, limiter)
	body := `{"jsonrpc":"2.0","id":9,"method":"ping"}`
	if rec := post(t, handler, body); rec.Code != http.StatusOK {
		t.Fatalf("first request status=%d body=%s", rec.Code, rec.Body)
	}
	rec := post(t, handler, body)
	if rec.Code != http.StatusTooManyRequests {
		t.Fatalf("second request status=%d body=%s", rec.Code, rec.Body)
	}
	if store.counts["ratelimit:mcp.protocol:user:42"] != 2 {
		t.Fatalf("authenticated bucket counts=%v", store.counts)
	}
}

func TestHandlerParseErrorDoesNotConsumeRateLimit(t *testing.T) {
	store := &countingRedis{}
	limiter := ratelimit.NewLimiter(store, "")
	handler := NewHandler(newApp(), nil, limiter)
	rec := post(t, handler, "{")
	if rec.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body)
	}
	if len(store.counts) != 0 {
		t.Fatalf("parse failure consumed rate limit: %v", store.counts)
	}
}

// dispatch panic 必须收敛为 ServerErrorMiddleware 口径的 500 纯文本；
// net/http 默认是断连空响应，不兜底就是线格式漂移。
func TestHandlerPanicBecomes500(t *testing.T) {
	app := newApp()
	app.PanicOnMethods = map[string]bool{"tools/list": true}
	handler := NewHandler(app, nil, nil)
	rec := post(t, handler, `{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}`)
	if rec.Code != http.StatusInternalServerError {
		t.Fatalf("status=%d", rec.Code)
	}
	if rec.Body.String() != "Internal Server Error" {
		t.Fatalf("body=%q", rec.Body.String())
	}
	if rec.Header().Get("Content-Type") != "text/plain; charset=utf-8" {
		t.Fatalf("content-type=%q", rec.Header().Get("Content-Type"))
	}
	if rec.Header().Get("Content-Length") != "21" {
		t.Fatalf("content-length=%q", rec.Header().Get("Content-Length"))
	}
}
