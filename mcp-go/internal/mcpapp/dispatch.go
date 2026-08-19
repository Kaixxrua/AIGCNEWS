// Package mcpapp 实现无状态 MCP JSON-RPC 应用分派与 /api/mcp HTTP 接线。
//
// 字节级行为以 backend/tests/parity/corpus/protocol.jsonl 为准绳：
//   - 无 id 通知一律 204 空体，仅 MCP-Protocol-Version 头；
//   - 协议错误均为 200 JSON-RPC 信封；
//   - initialize 铸造装饰性 Mcp-Session-Id（aigc-radar-<32 位小写 hex>），
//     后续请求永不回验、响应头永不重发；
//   - 非 POST → Starlette 口径 JSON 405 + Allow: POST；
//   - 未捕获 panic → 500 text/plain "Internal Server Error"（对齐
//     Starlette ServerErrorMiddleware，net/http 默认行为是断连空响应，
//     必须显式兜底）。
package mcpapp

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"net/http"
	"strconv"

	"aigcnews/mcp-go/internal/authn"
	"aigcnews/mcp-go/internal/jsonx"
	"aigcnews/mcp-go/internal/wire"
)

// ToolHandler 执行一个已注册工具，返回的数据将进入 content 文本与
// structuredContent 双层编码（PR 1.2 仅用于未知工具/崩溃语料面）。
type ToolHandler func(arguments map[string]any) (map[string]any, error)

// ToolRegistry 按名查找工具处理器。
type ToolRegistry interface {
	Lookup(name string) (ToolHandler, bool)
}

// Handlers 是最简单的静态注册表实现。
type Handlers map[string]ToolHandler

func (h Handlers) Lookup(name string) (ToolHandler, bool) {
	f, ok := h[name]
	return f, ok
}

// App 是无状态协议分派器；依赖在启动期装配一次。
type App struct {
	serverName    string
	serverVersion string
	tools         ToolRegistry
	sessionID     func() string

	// PanicOnMethods 是回放/测试专用注入缝（对应 recorder.py 的
	// profile="dispatch_crash"）：命中的方法在分派时 panic，以钉住
	// 500 投射。生产装配不得设置。
	PanicOnMethods map[string]bool
}

// New 装配分派器；tools 为 nil 时全部 tools/call 走未知工具分支。
func New(serverName, serverVersion string, tools ToolRegistry) *App {
	return &App{
		serverName:    serverName,
		serverVersion: serverVersion,
		tools:         tools,
		sessionID:     newSessionID,
	}
}

// Dispatch 消费已校验请求并产出框架无关响应。
func (a *App) Dispatch(req wire.ValidatedRequest) wire.Response {
	// JSON-RPC 约定：无 id 的消息是通知，一律 204 空体（任何方法同口径）。
	if !req.HasID {
		return wire.Notification()
	}
	if a.PanicOnMethods[req.Method] {
		panic("parity probe")
	}
	switch req.Method {
	case "initialize":
		return a.initialize(req)
	case "tools/call":
		return a.call(req)
	default:
		// tools/list、resources/*、prompts/* 自 PR 1.4 起接入；此前与未知
		// 方法同口径（ping 也是 Method not found，刻意非标准但已冻结）。
		return wire.Error(req.RequestID, wire.MethodNotFound, "Method not found")
	}
}

func (a *App) initialize(req wire.ValidatedRequest) wire.Response {
	// 键序逐字对齐 Python dict 插入序（corpus initialize 用例钉死）。
	result := jsonx.Object{
		{Key: "protocolVersion", Value: wire.ProtocolVersion},
		{Key: "capabilities", Value: jsonx.Object{
			{Key: "tools", Value: jsonx.Object{{Key: "listChanged", Value: false}}},
			{Key: "resources", Value: jsonx.Object{
				{Key: "subscribe", Value: false},
				{Key: "listChanged", Value: false},
			}},
			{Key: "prompts", Value: jsonx.Object{{Key: "listChanged", Value: false}}},
		}},
		{Key: "serverInfo", Value: jsonx.Object{
			{Key: "name", Value: a.serverName},
			{Key: "version", Value: a.serverVersion},
		}},
		{Key: "instructions", Value: hostInstructions},
	}
	return wire.WithSession(wire.Result(req.RequestID, result), a.sessionID())
}

func (a *App) call(req wire.ValidatedRequest) wire.Response {
	name, ok := req.Params["name"].(string)
	if !ok || name == "" {
		return wire.Error(req.RequestID, wire.InvalidParams, "tools/call params.name is required")
	}
	args, _ := req.Params["arguments"].(map[string]any)
	var handler ToolHandler
	found := false
	if a.tools != nil {
		handler, found = a.tools.Lookup(name)
	}
	if !found {
		return wire.Result(req.RequestID, toolResult(
			jsonx.Object{{Key: "error", Value: "Unknown tool: " + name}}, true))
	}
	data, err := handler(args)
	if err != nil {
		// 处理器失败在结果层收敛，不泄漏内部细节（语料钉死固定文案）。
		return wire.Result(req.RequestID, toolResult(
			jsonx.Object{{Key: "error", Value: "Tool execution failed."}}, true))
	}
	return wire.Result(req.RequestID, toolResult(data, false))
}

// toolResult 复刻 responses._tool_response：内层 text 用 Python 默认
// 分隔符（", " / ": "）的 json.dumps，外层信封紧凑；成功才带
// structuredContent。顶层键序 content/isError/structuredContent 与
// Python 插入序一致（亦恰好是按字母序）。
func toolResult(data any, isError bool) jsonx.Object {
	result := jsonx.Object{
		{Key: "content", Value: []any{jsonx.Object{
			{Key: "type", Value: "text"},
			{Key: "text", Value: pythonDumps(data)},
		}}},
		{Key: "isError", Value: isError},
	}
	if !isError {
		result = append(result, jsonx.Pair{Key: "structuredContent", Value: data})
	}
	return result
}

// pythonDumps 以 Python json.dumps(ensure_ascii=False) 默认分隔符编码。
// jsonx.Object 保序；map 键序对齐 Python 3.7+ 插入序的惟一可行近似是
// 调用方一律用 Object（Phase 2 约束）。
func pythonDumps(value any) string {
	var buf []byte
	writePythonJSON(&buf, value)
	return string(buf)
}

func writePythonJSON(buf *[]byte, value any) {
	switch v := value.(type) {
	case jsonx.Object:
		*buf = append(*buf, '{')
		for i, pair := range v {
			if i > 0 {
				*buf = append(*buf, ',', ' ')
			}
			writePythonJSON(buf, pair.Key)
			*buf = append(*buf, ':', ' ')
			writePythonJSON(buf, pair.Value)
		}
		*buf = append(*buf, '}')
	case []any:
		*buf = append(*buf, '[')
		for i, item := range v {
			if i > 0 {
				*buf = append(*buf, ',', ' ')
			}
			writePythonJSON(buf, item)
		}
		*buf = append(*buf, ']')
	default:
		*buf = append(*buf, jsonx.MustMarshalCompact(v)...)
	}
}

func newSessionID() string {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		panic(fmt.Sprintf("mcpapp: 会话 id 随机源失败: %v", err))
	}
	return "aigc-radar-" + hex.EncodeToString(b[:])
}

// Authenticator 是 /api/mcp 的可选 Bearer 认证边界（authn.Authenticator
// 即其实现；回放用 fixture 假实现）。
type Authenticator interface {
	Authenticate(ctx context.Context, authorization string) (authn.Identity, *authn.Response)
}

// Handler 把认证、解析、分派接成 http.Handler。顺序对齐 FastAPI：
// 路由方法闸（405）→ 依赖认证（401）→ 请求体解析（协议错误）→ 分派；
// 限流缝在 PR 1.3 落在解析之后、分派之前。
type Handler struct {
	app  *App
	auth Authenticator
}

func NewHandler(app *App, auth Authenticator) *Handler {
	return &Handler{app: app, auth: auth}
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	defer func() {
		if recovered := recover(); recovered != nil {
			writeInternalServerError(w)
		}
	}()
	if r.Method != http.MethodPost {
		w.Header().Set("Allow", http.MethodPost)
		writeJSON(w, http.StatusMethodNotAllowed, `{"detail":"Method Not Allowed"}`)
		return
	}
	if h.auth != nil {
		_, authFailure := h.auth.Authenticate(r.Context(), r.Header.Get("Authorization"))
		if authFailure != nil {
			authFailure.Write(w)
			return
		}
		// PR 1.2 分派不消费身份；PR 1.4 起 tools/list 私有工具按
		// is_authenticated 分叉，身份经参数传入。
	}
	req, parseErr := wire.ParseRequest(r)
	if parseErr != nil {
		wire.Error(parseErr.RequestID, parseErr.Code, parseErr.Message).Write(w)
		return
	}
	h.app.Dispatch(req).Write(w)
}

// writeInternalServerError 对齐 ServerErrorMiddleware：纯文本定长 500。
func writeInternalServerError(w http.ResponseWriter) {
	body := "Internal Server Error"
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	w.Header().Set("Content-Length", strconv.Itoa(len(body)))
	w.WriteHeader(http.StatusInternalServerError)
	_, _ = w.Write([]byte(body))
}

func writeJSON(w http.ResponseWriter, status int, body string) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Content-Length", strconv.Itoa(len(body)))
	w.WriteHeader(status)
	_, _ = w.Write([]byte(body))
}
