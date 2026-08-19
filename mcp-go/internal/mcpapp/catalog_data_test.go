package mcpapp

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	"aigcnews/mcp-go/internal/jsonx"
	"aigcnews/mcp-go/internal/wire"
)

// catalogCorpusPath 相对包目录指向黄金语料；语料缺失（如裁剪后的
// 开源镜像）时整组用例 t.Skip，不阻断纯 Go 侧 CI。
const catalogCorpusPath = "../../../backend/tests/parity/corpus/protocol.jsonl"

// catalogCorpusCases 是 PR 1.4 静态清单数据层钉死的 11 个语料用例。
var catalogCorpusCases = []string{
	"tools-list",
	"tools-list-authenticated",
	"tools-list-id-null",
	"tools-list-id-float",
	"tools-list-id-bool",
	"tools-list-id-zero",
	"tools-list-without-params",
	"tools-list-unknown-session-header",
	"resources-list",
	"resources-templates-list",
	"prompts-list",
}

type parityExchange struct {
	Name    string `json:"name"`
	Request struct {
		Method  string            `json:"method"`
		Path    string            `json:"path"`
		Headers map[string]string `json:"headers"`
		Body    string            `json:"body"`
	} `json:"request"`
	Response struct {
		Status  int               `json:"status"`
		Headers map[string]string `json:"headers"`
		Body    string            `json:"body"`
	} `json:"response"`
}

func loadParityCorpus(t *testing.T) map[string]parityExchange {
	t.Helper()
	file, err := os.Open(catalogCorpusPath)
	if err != nil {
		t.Skipf("黄金语料不可用（%v），跳过字节级比对", err)
	}
	defer func() { _ = file.Close() }()
	exchanges := map[string]parityExchange{}
	scanner := bufio.NewScanner(file)
	scanner.Buffer(make([]byte, 1<<20), 1<<20)
	for scanner.Scan() {
		line := scanner.Bytes()
		if len(bytes.TrimSpace(line)) == 0 {
			continue
		}
		var exchange parityExchange
		if err := json.Unmarshal(line, &exchange); err != nil {
			t.Fatalf("语料行解析失败: %v", err)
		}
		exchanges[exchange.Name] = exchange
	}
	if err := scanner.Err(); err != nil {
		t.Fatalf("语料读取失败: %v", err)
	}
	return exchanges
}

// catalogResultForMethod 把静态清单方法投影到本 PR 交付的构造函数；
// 该映射即主会话 dispatch 接入时各分支的 result 形状。
func catalogResultForMethod(method string, authenticated bool) (jsonx.Object, error) {
	switch method {
	case "tools/list":
		return ToolsList(authenticated), nil
	case "resources/list":
		return ResourcesList(), nil
	case "resources/templates/list":
		return ResourceTemplatesList(), nil
	case "prompts/list":
		return PromptsList(), nil
	default:
		return nil, fmt.Errorf("未覆盖的方法 %q", method)
	}
}

// corpusAuthenticated 复刻 FastAPI 侧的匿名/认证判定语义：语料请求头携带
// Bearer 凭证即认证会话（仅 tools-list-authenticated 一例）。
func corpusAuthenticated(headers map[string]string) bool {
	for key, value := range headers {
		if strings.EqualFold(key, "authorization") {
			return strings.HasPrefix(strings.ToLower(value), "bearer ")
		}
	}
	return false
}

func firstByteDiff(got, want []byte) string {
	n := len(got)
	if len(want) < n {
		n = len(want)
	}
	for i := 0; i < n; i++ {
		if got[i] != want[i] {
			lo := i - 64
			if lo < 0 {
				lo = 0
			}
			hi := i + 64
			if hi > n {
				hi = n
			}
			return fmt.Sprintf("首处差异在字节 %d:\n got: %q\nwant: %q", i, got[lo:hi], want[lo:hi])
		}
	}
	return fmt.Sprintf("前缀一致但长度不同: got %d want %d", len(got), len(want))
}

// TestCatalogDataByteParity 对 11 个静态清单用例做逐字节比对：
// 请求经 wire.ParseRequest 走真实解析路径（含 id null/float/bool/zero 回显
// 形状与 bool id 兼容怪癖），结果经 wire.Result 200 信封 + Write 投影，
// body、status、响应头集合三项均须与语料一致。
func TestCatalogDataByteParity(t *testing.T) {
	corpus := loadParityCorpus(t)
	for _, name := range catalogCorpusCases {
		t.Run(name, func(t *testing.T) {
			exchange, ok := corpus[name]
			if !ok {
				t.Fatalf("语料缺少用例 %s", name)
			}
			if exchange.Request.Method != http.MethodPost {
				t.Fatalf("语料请求方法假设破裂: %q", exchange.Request.Method)
			}
			req := httptest.NewRequest(
				http.MethodPost,
				"http://parity.test"+exchange.Request.Path,
				strings.NewReader(exchange.Request.Body),
			)
			for key, value := range exchange.Request.Headers {
				req.Header.Set(key, value)
			}
			validated, parseErr := wire.ParseRequest(req)
			if parseErr != nil {
				t.Fatalf("语料请求应通过解析，得到 %+v", parseErr)
			}
			authenticated := corpusAuthenticated(exchange.Request.Headers)
			if want := name == "tools-list-authenticated"; authenticated != want {
				t.Fatalf("认证判定与用例预期不符: got %v want %v", authenticated, want)
			}
			result, err := catalogResultForMethod(validated.Method, authenticated)
			if err != nil {
				t.Fatal(err)
			}
			response := wire.Result(validated.RequestID, result)

			recorder := httptest.NewRecorder()
			response.Write(recorder)

			if recorder.Code != exchange.Response.Status {
				t.Fatalf("status got %d want %d", recorder.Code, exchange.Response.Status)
			}
			if exchange.Response.Status != http.StatusOK {
				t.Fatalf("语料响应状态假设破裂: %d", exchange.Response.Status)
			}
			if got, want := recorder.Body.Bytes(), []byte(exchange.Response.Body); !bytes.Equal(got, want) {
				t.Fatalf("body 漂移:\n%s", firstByteDiff(got, want))
			}
			gotHeaders := map[string]string{}
			for key, values := range recorder.Header() {
				gotHeaders[strings.ToLower(key)] = strings.Join(values, ",")
			}
			if len(gotHeaders) != len(exchange.Response.Headers) {
				t.Fatalf("响应头数量 got %v want %v", gotHeaders, exchange.Response.Headers)
			}
			for key, want := range exchange.Response.Headers {
				got, ok := gotHeaders[strings.ToLower(key)]
				if !ok || got != want {
					t.Fatalf("响应头 %s got %q want %q（全部: %v）", key, got, want, gotHeaders)
				}
			}
		})
	}
}

// TestToolsListAuthenticationFork 不依赖语料的形状自检：认证分叉点只能是
// 追加 search_my_project_favorites，公开段两态逐字节一致。
func TestToolsListAuthenticationFork(t *testing.T) {
	anonymous := ToolsList(false)
	authenticated := ToolsList(true)
	if len(anonymous) != 1 || anonymous[0].Key != "tools" {
		t.Fatalf("result 顶层形状漂移: %v", anonymous)
	}
	anonTools, ok := anonymous[0].Value.([]any)
	if !ok || len(anonTools) != 8 {
		t.Fatalf("匿名工具数漂移: %v", anonymous[0].Value)
	}
	authTools, ok := authenticated[0].Value.([]any)
	if !ok || len(authTools) != 9 {
		t.Fatalf("认证工具数漂移: %v", authenticated[0].Value)
	}
	for i := range anonTools {
		if !bytes.Equal(jsonx.MustMarshalCompact(anonTools[i]), jsonx.MustMarshalCompact(authTools[i])) {
			t.Fatalf("公开段第 %d 项两态不一致", i)
		}
	}
	last, ok := authTools[8].(jsonx.Object)
	if !ok || len(last) == 0 || last[0].Key != "name" || last[0].Value != "search_my_project_favorites" {
		t.Fatalf("认证追加项漂移: %v", authTools[8])
	}
}
