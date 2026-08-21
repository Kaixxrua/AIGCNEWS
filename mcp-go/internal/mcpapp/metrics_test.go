package mcpapp

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/alicebob/miniredis/v2"
	"github.com/redis/go-redis/v9"

	"aigcnews/mcp-go/internal/authn"
	"aigcnews/mcp-go/internal/metrics"
)

// tools/call 计数的分派层行为：对齐 application.py 的 bench 免计数 +
// 注册表归桶 + 客户端分桶。响应字节不受计数影响（parity 不破）。

func newMetricsApp(t *testing.T) (*App, *miniredis.Miniredis) {
	t.Helper()
	mr := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	t.Cleanup(func() { _ = client.Close() })
	app := New("aigc-radar", "1.2.0", Handlers{
		"search_papers": func(map[string]any) (any, error) {
			return map[string]any{"ok": true}, nil
		},
	})
	app.SetMetrics(metrics.NewRecorder(client), map[string]struct{}{
		"search_papers": {},
	})
	return app, mr
}

func callTool(t *testing.T, app *App, name, ua string) {
	t.Helper()
	app.DispatchWithIdentityUA(
		rpc(1, "tools/call", `{"name":"`+name+`","arguments":{}}`),
		authn.Identity{}, false, ua,
	)
}

func TestToolCallRecordsKnownToolAndClient(t *testing.T) {
	app, mr := newMetricsApp(t)
	callTool(t, app, "search_papers", "dsh-aigc-radar/2.1")
	if got, _ := mr.Get("mcpmetrics:total"); got != "1" {
		t.Fatalf("total = %q, want 1", got)
	}
	if got := mr.HGet("mcpmetrics:tool_calls", "search_papers"); got != "1" {
		t.Errorf("tool_calls[search_papers] = %q", got)
	}
	if got := mr.HGet("mcpmetrics:client_calls", "dsh-aigc-radar"); got != "1" {
		t.Errorf("client_calls[dsh-aigc-radar] = %q", got)
	}
}

func TestToolCallBenchmarkUAExcluded(t *testing.T) {
	app, mr := newMetricsApp(t)
	callTool(t, app, "search_papers", "mcp-latency-bench/1.0")
	if mr.Exists("mcpmetrics:total") {
		v, _ := mr.Get("mcpmetrics:total")
		t.Errorf("bench traffic must not be counted, total=%q", v)
	}
}

func TestToolCallUnknownToolBucketed(t *testing.T) {
	app, mr := newMetricsApp(t)
	callTool(t, app, "no_such_tool", "curl/8.0")
	if got := mr.HGet("mcpmetrics:tool_calls", "__unknown__"); got != "1" {
		t.Errorf("tool_calls[__unknown__] = %q", got)
	}
	// 未知 UA 不进客户端桶。
	if mr.Exists("mcpmetrics:client_calls") {
		fields, _ := mr.HKeys("mcpmetrics:client_calls")
		t.Errorf("unknown UA must not create client bucket: %v", fields)
	}
}

func TestToolCallMissingNameNotCounted(t *testing.T) {
	app, mr := newMetricsApp(t)
	app.DispatchWithIdentityUA(rpc(1, "tools/call", `{"arguments":{}}`), authn.Identity{}, false, "")
	if mr.Exists("mcpmetrics:total") {
		t.Error("params.name missing must not be counted")
	}
}

func TestToolCallUnwiredMetricsIsNoOp(t *testing.T) {
	app := New("aigc-radar", "1.2.0", Handlers{
		"search_papers": func(map[string]any) (any, error) { return map[string]any{"ok": true}, nil },
	})
	// 未 SetMetrics：分派正常、不 panic。
	resp := app.DispatchWithIdentityUA(rpc(1, "tools/call", `{"name":"search_papers","arguments":{}}`), authn.Identity{}, false, "")
	if resp.Status != http.StatusOK {
		t.Fatalf("status %d", resp.Status)
	}
}

// HTTP 端到端：Handler.ServeHTTP 在分派前读 UA，bench UA 不计数但响应正常。
func TestHandlerBenchUANotCountedButServed(t *testing.T) {
	app, mr := newMetricsApp(t)
	h := NewHandler(app, nil, nil)
	req := httptest.NewRequest(http.MethodPost, "/api/mcp",
		strings.NewReader(`{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"search_papers","arguments":{}}}`))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("User-Agent", "mcp-latency-bench/1.0")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status %d body %q", rec.Code, rec.Body.String())
	}
	if mr.Exists("mcpmetrics:total") {
		t.Error("bench UA via HTTP must not be counted")
	}
}

// 非 bench 的真实客户端经 HTTP 正常计数。
func TestHandlerRealClientCounted(t *testing.T) {
	app, mr := newMetricsApp(t)
	h := NewHandler(app, nil, nil)
	req := httptest.NewRequest(http.MethodPost, "/api/mcp",
		strings.NewReader(`{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"search_papers","arguments":{}}}`))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("User-Agent", "dsh-aigc-radar/2.1")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status %d body %q", rec.Code, rec.Body.String())
	}
	if got, _ := mr.Get("mcpmetrics:total"); got != "1" {
		t.Errorf("total = %q, want 1", got)
	}
}
