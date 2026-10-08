package mcpapp

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"reflect"
	"strconv"
	"strings"
	"testing"

	"aigcnews/mcp-go/internal/authn"
	"aigcnews/mcp-go/internal/ratelimit"
)

const metadataChallenge = `resource_metadata="https://aigcnews.cn/.well-known/oauth-protected-resource/api/mcp/oauth"`

func entryRequest(method, path, body string, authorization ...string) *http.Request {
	req := httptest.NewRequest(method, "http://example.test"+path, strings.NewReader(body))
	for _, value := range authorization {
		req.Header.Add("Authorization", value)
	}
	return req
}

func serve(handler http.Handler, req *http.Request) *httptest.ResponseRecorder {
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	return rec
}

// 匿名请求回 401 质询：不解析（请求体是非法 JSON 也不回 -32700）、不计限流、不记指标，
// 也不带 MCP 协议头。
func TestOAuthEntryChallengesAnonymousRequests(t *testing.T) {
	app, mr := newMetricsApp(t)
	store := &countingRedis{}
	entry := NewHandler(app, &stubAuthenticator{}, ratelimit.NewLimiter(store, "")).OAuthEntry(OAuthResourceMetadataURL)
	for _, body := range []string{`{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}`, "{"} {
		rec := serve(entry, entryRequest(http.MethodPost, "/api/mcp/oauth", body))
		if rec.Code != http.StatusUnauthorized {
			t.Fatalf("status=%d body=%s", rec.Code, rec.Body)
		}
		if got := rec.Header().Values("WWW-Authenticate"); len(got) != 1 || got[0] != "Bearer "+metadataChallenge {
			t.Fatalf("www-authenticate=%q", got)
		}
		if rec.Body.String() != `{"detail":"此入口需要 MCP Token，请先完成 OAuth 授权"}` {
			t.Fatalf("body=%s", rec.Body)
		}
		if rec.Header().Get("Content-Type") != "application/json" ||
			rec.Header().Get("Content-Length") != strconv.Itoa(rec.Body.Len()) {
			t.Fatalf("headers=%v", rec.Header())
		}
		if rec.Header().Get("Mcp-Session-Id") != "" || rec.Header().Get("MCP-Protocol-Version") != "" {
			t.Fatalf("challenge leaked protocol headers: %v", rec.Header())
		}
	}
	if len(store.counts) != 0 {
		t.Fatalf("anonymous challenge consumed rate limit: %v", store.counts)
	}
	for _, key := range mr.Keys() {
		if strings.HasPrefix(key, "mcpmetrics:") {
			t.Fatalf("anonymous challenge created metrics key %q", key)
		}
	}
}

// 凭证有问题：正文沿用 authn 的 401，质询头补上 RFC 6750 错误码与 resource_metadata；
// 换了 scheme 等于没带 Bearer 凭证，按 RFC 6750 §3.1 不给错误码。/api/mcp 收到同样的
// 请求仍是裸 Bearer、正文一字不差。用真实的 authn.Authenticator：这几种失败都在查库之前判定。
func TestOAuthEntryChallengeCarriesBearerError(t *testing.T) {
	plain := NewHandler(newApp(), authn.Authenticator{}, nil)
	entry := plain.OAuthEntry(OAuthResourceMetadataURL)
	cases := []struct {
		name          string
		authorization []string
		challenge     string
		body          string
	}{
		{"non-bearer", []string{"Basic abc"}, "Bearer " + metadataChallenge,
			`{"detail":"Authorization 必须使用 Bearer Token"}`},
		{"malformed-bearer", []string{"Bearer "}, `Bearer error="invalid_token", ` + metadataChallenge,
			`{"detail":"MCP Token 无效、已过期或已撤销"}`},
		{"duplicate-header", []string{"Bearer a", "Bearer b"}, `Bearer error="invalid_request", ` + metadataChallenge,
			`{"detail":"Authorization must contain exactly one value"}`},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			rec := serve(entry, entryRequest(http.MethodPost, "/api/mcp/oauth", "{", tc.authorization...))
			if rec.Code != http.StatusUnauthorized || rec.Body.String() != tc.body {
				t.Fatalf("status=%d body=%s", rec.Code, rec.Body)
			}
			if got := rec.Header().Values("WWW-Authenticate"); len(got) != 1 || got[0] != tc.challenge {
				t.Fatalf("www-authenticate=%q, want %q", got, tc.challenge)
			}

			old := serve(plain, entryRequest(http.MethodPost, "/api/mcp", "{", tc.authorization...))
			if old.Code != http.StatusUnauthorized || old.Body.String() != tc.body {
				t.Fatalf("/api/mcp status=%d body=%s", old.Code, old.Body)
			}
			if got := old.Header().Values("WWW-Authenticate"); len(got) != 1 || got[0] != "Bearer" {
				t.Fatalf("/api/mcp www-authenticate=%q", got)
			}
		})
	}
}

// 鉴权查询本身出错（500）不是质询，原样返回、不加 WWW-Authenticate。
func TestOAuthEntryLeavesServerErrorsAlone(t *testing.T) {
	entry := NewHandler(newApp(), authn.Authenticator{}, nil).OAuthEntry(OAuthResourceMetadataURL)
	rec := serve(entry, entryRequest(http.MethodPost, "/api/mcp/oauth", "{", "Bearer secret"))
	if rec.Code != http.StatusInternalServerError || rec.Body.String() != "Internal Server Error" {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body)
	}
	if got := rec.Header().Get("WWW-Authenticate"); got != "" {
		t.Fatalf("server error carried a challenge: %q", got)
	}
}

// 带有效令牌时与 /api/mcp 逐字节相同：状态、全部响应头、正文。
func TestOAuthEntryMatchesPlainEntryWhenAuthenticated(t *testing.T) {
	plain := NewHandler(newApp(), &stubAuthenticator{authenticated: true}, nil)
	entry := plain.OAuthEntry(OAuthResourceMetadataURL)
	for _, body := range []string{
		`{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}`,
		`{"jsonrpc":"2.0","id":2,"method":"ping"}`,
		"{",
	} {
		want := serve(plain, entryRequest(http.MethodPost, "/api/mcp", body, "Bearer token"))
		got := serve(entry, entryRequest(http.MethodPost, "/api/mcp/oauth", body, "Bearer token"))
		if got.Code != want.Code || got.Body.String() != want.Body.String() || !reflect.DeepEqual(got.Header(), want.Header()) {
			t.Fatalf("body %q differs:\noauth %d %v %s\nplain %d %v %s",
				body, got.Code, got.Header(), got.Body, want.Code, want.Header(), want.Body)
		}
	}
	if !strings.Contains(serve(entry, entryRequest(http.MethodPost, "/api/mcp/oauth",
		`{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}`, "Bearer token")).Body.String(),
		"search_my_project_favorites") {
		t.Fatal("authenticated OAuth entry must list private tools")
	}
}

// 方法闸先于认证，与 /api/mcp 相同：GET 回 405，不回质询。
func TestOAuthEntryMethodGate(t *testing.T) {
	entry := NewHandler(newApp(), &stubAuthenticator{}, nil).OAuthEntry(OAuthResourceMetadataURL)
	rec := serve(entry, entryRequest(http.MethodGet, "/api/mcp/oauth", ""))
	if rec.Code != http.StatusMethodNotAllowed || rec.Header().Get("Allow") != http.MethodPost {
		t.Fatalf("status=%d allow=%q", rec.Code, rec.Header().Get("Allow"))
	}
	if got := rec.Header().Get("WWW-Authenticate"); got != "" {
		t.Fatalf("405 carried a challenge: %q", got)
	}
}

// OAuthEntry 返回副本：/api/mcp 照旧收匿名请求。
func TestOAuthEntryLeavesPlainHandlerAnonymous(t *testing.T) {
	plain := NewHandler(newApp(), &stubAuthenticator{}, nil)
	_ = plain.OAuthEntry(OAuthResourceMetadataURL)
	rec := post(t, plain, `{"jsonrpc":"2.0","id":9,"method":"ping"}`)
	if rec.Code != http.StatusOK || rec.Header().Get("WWW-Authenticate") != "" {
		t.Fatalf("status=%d headers=%v body=%s", rec.Code, rec.Header(), rec.Body)
	}
}

// 质询里的地址必须指向前端发布包里的元数据文件，文件声明的 resource 就是本入口
// （Python 侧 test_mcp_oauth_metadata_contract.py 反向钉住同一组字面量）。
func TestOAuthResourceMetadataMatchesPublishedFile(t *testing.T) {
	const wellKnown = "https://aigcnews.cn/.well-known/oauth-protected-resource"
	resourcePath, ok := strings.CutPrefix(OAuthResourceMetadataURL, wellKnown)
	if !ok || resourcePath != "/api/mcp/oauth" {
		t.Fatalf("metadata url %q", OAuthResourceMetadataURL)
	}
	raw, err := os.ReadFile("../../../frontend/public/.well-known/oauth-protected-resource" + resourcePath)
	if err != nil {
		t.Skipf("前端元数据文件不可读（%v），跳过对钉", err)
	}
	var metadata struct {
		Resource             string   `json:"resource"`
		AuthorizationServers []string `json:"authorization_servers"`
	}
	if err := json.Unmarshal(raw, &metadata); err != nil {
		t.Fatal(err)
	}
	if metadata.Resource != "https://aigcnews.cn"+resourcePath {
		t.Fatalf("resource=%q", metadata.Resource)
	}
	if !reflect.DeepEqual(metadata.AuthorizationServers, []string{"https://aigcnews.cn"}) {
		t.Fatalf("authorization_servers=%v", metadata.AuthorizationServers)
	}
}
