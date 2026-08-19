package probes

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"strconv"
	"strings"
	"testing"

	"aigcnews/mcp-go/internal/version"
)

// readyTrue / readyFalse 是测试注入的就绪探针。
func readyTrue(ctx context.Context) bool  { return true }
func readyFalse(ctx context.Context) bool { return false }

// do 执行一次请求并返回响应记录（不经过网络栈，与 Python 语料录制的
// TestClient 同层：无 Date 等服务器附加头）。
func do(t *testing.T, mux http.Handler, method, path string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(method, path, nil)
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)
	return rec
}

func requireExchange(t *testing.T, rec *httptest.ResponseRecorder, status int, body string) {
	t.Helper()
	if rec.Code != status {
		t.Fatalf("status = %d, want %d", rec.Code, status)
	}
	if got := rec.Body.String(); got != body {
		t.Fatalf("body = %q, want %q", got, body)
	}
	if got := rec.Header().Get("Content-Type"); got != "application/json" {
		t.Fatalf("content-type = %q, want application/json", got)
	}
	if got := rec.Header().Get("Content-Length"); got != strconv.Itoa(len(body)) {
		t.Fatalf("content-length = %q, want %d", got, len(body))
	}
}

func TestLive(t *testing.T) {
	mux := NewMux(version.Fallback, readyFalse)
	requireExchange(t, do(t, mux, "GET", "/api/live"), http.StatusOK, `{"status":"ok"}`)
}

func TestVersion(t *testing.T) {
	mux := NewMux(version.Fallback, readyFalse)
	requireExchange(t, do(t, mux, "GET", "/api/version"),
		http.StatusOK, `{"name":"aigc-radar","version":"1.2.0"}`)
}

func TestVersionQuoting(t *testing.T) {
	mux := NewMux("1.3.0-rc.1", readyFalse)
	requireExchange(t, do(t, mux, "GET", "/api/version"),
		http.StatusOK, `{"name":"aigc-radar","version":"1.3.0-rc.1"}`)
}

func TestReadyWhenReady(t *testing.T) {
	mux := NewMux(version.Fallback, readyTrue)
	requireExchange(t, do(t, mux, "GET", "/api/ready"), http.StatusOK,
		`{"status":"ready","runtime_ready":true,"active_backend":"postgres","scope":"application_runtime","checks":{"configuration":"ok","postgres":"ok"},"error_class":null}`)
}

func TestReadyWhenNotReady(t *testing.T) {
	mux := NewMux(version.Fallback, readyFalse)
	requireExchange(t, do(t, mux, "GET", "/api/ready"), http.StatusServiceUnavailable,
		`{"detail":{"status":"not_ready","runtime_ready":false}}`)
}

// 未绑定就绪探针对齐 Python 无 lifespan 形态（corpus 用例 mcp-ready-no-lifespan）。
func TestReadyNilReadiness(t *testing.T) {
	mux := NewMux(version.Fallback, nil)
	requireExchange(t, do(t, mux, "GET", "/api/ready"), http.StatusServiceUnavailable,
		`{"detail":{"status":"not_ready","runtime_ready":false}}`)
}

// FastAPI 实测：HEAD 不为 GET 路由隐式注册，与非 GET 方法同吃 405 JSON。
func TestMethodNotAllowed(t *testing.T) {
	mux := NewMux(version.Fallback, readyTrue)
	for _, method := range []string{"POST", "PUT", "DELETE", "HEAD"} {
		for _, path := range []string{"/api/live", "/api/version", "/api/ready"} {
			rec := do(t, mux, method, path)
			if rec.Code != http.StatusMethodNotAllowed {
				t.Fatalf("%s %s status = %d, want 405", method, path, rec.Code)
			}
			if got := rec.Header().Get("Allow"); got != "GET" {
				t.Fatalf("%s %s allow = %q, want GET", method, path, got)
			}
			if got := rec.Body.String(); method != "HEAD" && got != `{"detail":"Method Not Allowed"}` {
				t.Fatalf("%s %s body = %q", method, path, got)
			}
		}
	}
}

func TestNotFound(t *testing.T) {
	mux := NewMux(version.Fallback, readyTrue)
	requireExchange(t, do(t, mux, "GET", "/api/nope"), http.StatusNotFound,
		`{"detail":"Not Found"}`)
	// /api/mcp 未挂载时同样按未注册 404。
	requireExchange(t, do(t, mux, "POST", "/api/mcp"), http.StatusNotFound,
		`{"detail":"Not Found"}`)
}

type echoHandler struct{ body string }

func (h echoHandler) ServeHTTP(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Content-Length", strconv.Itoa(len(h.body)))
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte(h.body))
}

func TestMCPMountAndTrailingSlash(t *testing.T) {
	mux := NewMux(version.Fallback, readyTrue, echoHandler{body: `{"ok":true}`})
	requireExchange(t, do(t, mux, "POST", "/api/mcp"), http.StatusOK, `{"ok":true}`)

	// /api/mcp 是已注册路径：单层尾斜杠同样 307 到去斜杠形式。
	req := httptest.NewRequest("POST", "http://example.test/api/mcp/", nil)
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)
	if rec.Code != http.StatusTemporaryRedirect ||
		rec.Header().Get("Location") != "http://example.test/api/mcp" {
		t.Fatalf("redirect = %d %q", rec.Code, rec.Header().Get("Location"))
	}
}

// Starlette redirect_slashes 实测：单层尾斜杠 307 到去斜杠绝对 URL，空体；
// 双层尾斜杠不递归，落 404。
func TestTrailingSlashRedirect(t *testing.T) {
	mux := NewMux(version.Fallback, readyTrue)
	req := httptest.NewRequest("POST", "http://example.test/api/live/", nil)
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)
	if rec.Code != http.StatusTemporaryRedirect {
		t.Fatalf("status = %d, want 307", rec.Code)
	}
	if got := rec.Header().Get("Location"); got != "http://example.test/api/live" {
		t.Fatalf("location = %q", got)
	}
	if got := rec.Body.String(); got != "" {
		t.Fatalf("body = %q, want empty", got)
	}
	requireExchange(t, do(t, mux, "GET", "/api//live"), http.StatusNotFound,
		`{"detail":"Not Found"}`)
}

// ── 语料对齐：直接消费 surface.jsonl 的探活用例逐字节比对 ────────────────

type corpusCase struct {
	Name    string `json:"name"`
	Request struct {
		Method string `json:"method"`
		Path   string `json:"path"`
	} `json:"request"`
	Response struct {
		Status  int               `json:"status"`
		Headers map[string]string `json:"headers"`
		Body    string            `json:"body"`
	} `json:"response"`
}

// TestCorpusProbeCases 以黄金语料为准绳回放三个探活用例。
// 语料未随仓库检出（如裁剪过的构建上下文）时跳过而非失败。
func TestCorpusProbeCases(t *testing.T) {
	const corpusPath = "../../../backend/tests/parity/corpus/surface.jsonl"
	raw, err := os.ReadFile(corpusPath)
	if err != nil {
		t.Skipf("parity corpus 不可读（%v），跳过语料对齐", err)
	}
	want := map[string]bool{
		"mcp-live":              false,
		"mcp-version":           false,
		"mcp-ready-no-lifespan": false,
	}
	mux := NewMux(version.Fallback, nil)
	for line := range strings.Lines(string(raw)) {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		var c corpusCase
		if err := json.Unmarshal([]byte(line), &c); err != nil {
			t.Fatalf("语料行解析失败: %v", err)
		}
		if _, ok := want[c.Name]; !ok {
			continue
		}
		want[c.Name] = true
		rec := do(t, mux, c.Request.Method, c.Request.Path)
		if rec.Code != c.Response.Status {
			t.Errorf("%s: status = %d, want %d", c.Name, rec.Code, c.Response.Status)
		}
		if got := rec.Body.String(); got != c.Response.Body {
			t.Errorf("%s: body = %q, want %q", c.Name, got, c.Response.Body)
		}
		for name, value := range c.Response.Headers {
			if got := rec.Header().Get(name); got != value {
				t.Errorf("%s: header %s = %q, want %q", c.Name, name, got, value)
			}
		}
	}
	for name, seen := range want {
		if !seen {
			t.Errorf("语料用例 %s 未在 %s 中找到", name, corpusPath)
		}
	}
}
