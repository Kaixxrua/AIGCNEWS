// Package replay 是黄金语料的 Go 回放门禁：直接消费
// backend/tests/parity/corpus/protocol.jsonl，按 corpus_manifest.json 的
// 归一化规则逐字节比对 /api/mcp 的响应。
//
// 本包只含测试代码，不进生产二进制。用例纳入范围随 PR 里程碑推进：
//
//   - PR 1.2（本包当前）：信封/解析/认证/通知/错误面 + 无注册表时的
//     tools/call 错误面；
//   - PR 1.3：rate-limited-429（限流层落地后解除跳过）；
//   - PR 1.4：tools/list* / resources-list / resources-templates-list /
//     prompts-list（静态清单落地后解除跳过）。
//
// 跳过即声明：deferredSkips 表里的每个名字都必须出现在语料中且被跳过，
// 语料新增用例会立即以"未裁决"失败暴露，不允许静默漏测。
package replay

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"sort"
	"strings"
	"testing"

	"aigcnews/mcp-go/internal/authn"
	"aigcnews/mcp-go/internal/jsonx"
	"aigcnews/mcp-go/internal/mcpapp"
	"aigcnews/mcp-go/internal/version"
)

type corpusCase struct {
	Name   string `json:"name"`
	Replay string `json:"replay"`
	Body   struct {
		Method  string            `json:"method"`
		Path    string            `json:"path"`
		Headers map[string]string `json:"headers"`
		Body    string            `json:"body"`
		BodyB64 string            `json:"body_b64"`
	} `json:"request"`
	Response struct {
		Status  int               `json:"status"`
		Headers map[string]string `json:"headers"`
		Body    string            `json:"body"`
	} `json:"response"`
}

// deferredSkips 记录显式推迟的用例及归属里程碑；键不在语料中出现也算失败。
var deferredSkips = map[string]string{
	"rate-limited-429":                  "PR 1.3 限流层",
	"tools-list":                        "PR 1.4 静态清单",
	"tools-list-authenticated":          "PR 1.4 静态清单",
	"tools-list-id-null":                "PR 1.4 静态清单",
	"tools-list-id-float":               "PR 1.4 静态清单",
	"tools-list-id-bool":                "PR 1.4 静态清单",
	"tools-list-id-zero":                "PR 1.4 静态清单",
	"tools-list-without-params":         "PR 1.4 静态清单",
	"tools-list-unknown-session-header": "PR 1.4 静态清单",
	"resources-list":                    "PR 1.4 静态清单",
	"resources-templates-list":          "PR 1.4 静态清单",
	"prompts-list":                      "PR 1.4 静态清单",
}

// sessionIDPattern 与 corpus_manifest.json normalizations 一致。
var sessionIDPattern = regexp.MustCompile(`^aigc-radar-[0-9a-f]{32}$`)

func corpusPath(t *testing.T, name string) string {
	t.Helper()
	_, thisFile, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("无法定位 replay 包路径")
	}
	// internal/replay → mcp-go → 仓库根 → backend/tests/parity/corpus
	root := filepath.Dir(filepath.Dir(filepath.Dir(filepath.Dir(thisFile))))
	return filepath.Join(root, "backend", "tests", "parity", "corpus", name)
}

func loadProtocolCases(t *testing.T) []corpusCase {
	t.Helper()
	raw, err := os.ReadFile(corpusPath(t, "protocol.jsonl"))
	if err != nil {
		t.Skipf("parity corpus 不可读（%v），跳过回放", err)
	}
	var cases []corpusCase
	for line := range strings.Lines(string(raw)) {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		var c corpusCase
		if err := json.Unmarshal([]byte(line), &c); err != nil {
			t.Fatalf("语料行解析失败: %v", err)
		}
		cases = append(cases, c)
	}
	return cases
}

// fixtureToken 对齐 fixtures.json tokens 段（recorder._TOKENS 的导出）。
type fixtureToken struct {
	UserID int `json:"user_id"`
	Scopes any `json:"scopes"`
}

// fixtureAuthenticator 复刻 recorder._StubTokenRepository + OptionalMcpUser
// 的判定链：按 SHA-256 反查固定 token 表，scopes 非字符串列表即权限无效。
type fixtureAuthenticator struct {
	tokens map[string]fixtureToken
}

func (f fixtureAuthenticator) Authenticate(_ context.Context, authorization string) (authn.Identity, *authn.Response) {
	if authorization == "" {
		return authn.Identity{}, nil
	}
	if !strings.HasPrefix(strings.ToLower(authorization), "bearer ") {
		return authn.Identity{}, fixtureUnauthorized("Authorization 必须使用 Bearer Token")
	}
	digest := sha256.Sum256([]byte(authorization[len("Bearer "):]))
	entry, ok := f.tokens[hex.EncodeToString(digest[:])]
	if !ok {
		return authn.Identity{}, fixtureUnauthorized("MCP Token 无效、已过期或已撤销")
	}
	scopes, ok := entry.Scopes.([]any)
	if !ok {
		return authn.Identity{}, fixtureUnauthorized("MCP Token 权限无效")
	}
	identity := authn.Identity{UserID: entry.UserID}
	for _, scope := range scopes {
		s, ok := scope.(string)
		if !ok {
			return authn.Identity{}, fixtureUnauthorized("MCP Token 权限无效")
		}
		identity.Scopes = append(identity.Scopes, s)
	}
	return identity, nil
}

func fixtureUnauthorized(detail string) *authn.Response {
	headers := http.Header{}
	headers.Set("WWW-Authenticate", "Bearer")
	return &authn.Response{
		Status:  http.StatusUnauthorized,
		Body:    jsonx.MustMarshalCompact(jsonx.Object{{Key: "detail", Value: detail}}),
		Headers: headers,
	}
}

func loadFixtureAuthenticator(t *testing.T) fixtureAuthenticator {
	t.Helper()
	raw, err := os.ReadFile(corpusPath(t, "fixtures.json"))
	if err != nil {
		t.Skipf("fixtures 不可读（%v），跳过回放", err)
	}
	var fixtures struct {
		Tokens map[string]fixtureToken `json:"tokens"`
	}
	if err := json.Unmarshal(raw, &fixtures); err != nil {
		t.Fatalf("fixtures 解析失败: %v", err)
	}
	byDigest := map[string]fixtureToken{}
	for token, entry := range fixtures.Tokens {
		digest := sha256.Sum256([]byte(token))
		byDigest[hex.EncodeToString(digest[:])] = entry
	}
	return fixtureAuthenticator{tokens: byDigest}
}

func newReplayHandler(t *testing.T, caseName string) http.Handler {
	t.Helper()
	// 对齐 recorder profile 语义：
	// tool_handler_crash → search_papers 处理器抛错；
	// dispatch_crash → 分派阶段 panic（internal-error-500 用例）。
	registry := mcpapp.Handlers{
		"search_papers": func(map[string]any) (map[string]any, error) {
			return nil, errParityProbe
		},
	}
	app := mcpapp.New(version.ServerName, version.Fallback, registry)
	if caseName == "internal-error-500" {
		app.PanicOnMethods = map[string]bool{"tools/list": true}
	}
	return mcpapp.NewHandler(app, loadFixtureAuthenticator(t))
}

var errParityProbe = errors.New("parity probe")

// TestProtocolCorpus 逐案回放 protocol.jsonl 的 PR 1.2 范围用例。
func TestProtocolCorpus(t *testing.T) {
	cases := loadProtocolCases(t)
	seen := map[string]bool{}
	skipped := map[string]bool{}
	for _, c := range cases {
		c := c
		if reason, deferred := deferredSkips[c.Name]; deferred {
			skipped[c.Name] = true
			t.Logf("SKIP %s（%s）", c.Name, reason)
			continue
		}
		seen[c.Name] = true
		t.Run(c.Name, func(t *testing.T) {
			replayCase(t, c)
		})
	}
	for name := range deferredSkips {
		if !skipped[name] {
			t.Errorf("推迟用例 %s 未在语料中出现——里程碑到期或语料已删，须更新 deferredSkips", name)
		}
	}
	var names []string
	for name := range seen {
		names = append(names, name)
	}
	sort.Strings(names)
	t.Logf("回放通过 %d 例: %s", len(names), strings.Join(names, ", "))
}

func replayCase(t *testing.T, c corpusCase) {
	t.Helper()
	handler := newReplayHandler(t, c.Name)

	var body []byte
	switch {
	case c.Body.BodyB64 != "":
		decoded, err := base64.StdEncoding.DecodeString(c.Body.BodyB64)
		if err != nil {
			t.Fatalf("body_b64 解码失败: %v", err)
		}
		body = decoded
	default:
		body = []byte(c.Body.Body)
	}
	req := httptest.NewRequest(c.Body.Method, "http://parity.test"+c.Body.Path, bytes.NewReader(body))
	for name, value := range c.Body.Headers {
		req.Header.Set(name, value)
	}
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != c.Response.Status {
		t.Errorf("status = %d, want %d\nbody: %s", rec.Code, c.Response.Status, rec.Body.String())
	}
	if got := rec.Body.String(); got != c.Response.Body {
		t.Errorf("body 不一致:\n got %q\nwant %q", got, c.Response.Body)
	}

	got := map[string]string{}
	for name, values := range rec.Header() {
		lower := strings.ToLower(name)
		value := values[0]
		if lower == "mcp-session-id" && sessionIDPattern.MatchString(value) {
			value = "<mcp-session-id>"
		}
		got[lower] = value
	}
	if len(got) != len(c.Response.Headers) {
		t.Errorf("响应头数量 = %d，want %d:\n got %v\nwant %v",
			len(got), len(c.Response.Headers), got, c.Response.Headers)
	}
	for name, want := range c.Response.Headers {
		if value, ok := got[name]; !ok || value != want {
			t.Errorf("header %s = %q, want %q", name, value, want)
		}
	}
}
