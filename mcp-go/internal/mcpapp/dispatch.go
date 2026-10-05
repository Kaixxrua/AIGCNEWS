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
	"aigcnews/mcp-go/internal/metrics"
	"aigcnews/mcp-go/internal/ratelimit"
	"aigcnews/mcp-go/internal/usage"
	"aigcnews/mcp-go/internal/wire"
)

// ToolHandler 执行一个已注册工具。返回值必须是可直接 JSON 编码的有序结构
// （jsonx.Object/[]any/标量），将进入 content 文本与 structuredContent
// 双层编码；保序责任在处理器，dispatch 不做 map 重排。
type ToolHandler func(arguments map[string]any) (any, error)

// IdentityToolHandler 是需要用户身份的工具处理器（PR 2.5 起：
// search_my_project_favorites 等 *my* 族）。匿名请求拿到零值
// authn.Identity{}（UserID=0），对齐 Python user_id<=0 分支；
// 认证/scope 判定文案由处理器内产生，dispatch 不特判工具名
// （Python application.py 的 dispatcher 短路与处理器内分支同文案）。
type IdentityToolHandler func(identity authn.Identity, arguments map[string]any) (any, error)

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
	identityTools map[string]IdentityToolHandler
	resources     *ResourceService
	sessionID     func() string

	// metrics 是 dashboard 工具调用计数写者；nil 表示未接线（回放多数
	// 用例与 Redis 未接线场景，对齐 Python app.state 缺失语义），
	// tools/call 不记录。
	metrics *metrics.Recorder
	// knownToolNames 对齐 Python MCP_TOOL_REGISTRY：注册表内工具名按原名
	// 单独统计，其余归入 __unknown__（防基数膨胀）。
	knownToolNames map[string]struct{}

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

// SetMetrics 接线 dashboard 工具调用计数（可选）。knownToolNames 应等于
// 当前注册表（含身份感知工具）的全部名字。
func (a *App) SetMetrics(recorder *metrics.Recorder, knownToolNames map[string]struct{}) {
	a.metrics = recorder
	a.knownToolNames = knownToolNames
}

func (a *App) SetResources(resources *ResourceService) { a.resources = resources }

// RegisterIdentityTool 注册身份感知工具（与 tools 注册表并行，名冲突以
// 身份表优先——现行目录无重名工具，双表仅为最小侵入演进）。
func (a *App) RegisterIdentityTool(name string, handler IdentityToolHandler) {
	if a.identityTools == nil {
		a.identityTools = map[string]IdentityToolHandler{}
	}
	a.identityTools[name] = handler
}

// Dispatch 消费已校验请求并产出框架无关响应。
func (a *App) Dispatch(req wire.ValidatedRequest) wire.Response {
	return a.dispatch(req, authn.Identity{}, false, "")
}

// DispatchWithIdentity dispatches a request after the HTTP authentication layer
// has established whether an identity was supplied. The explicit authenticated
// bit is intentional: a valid identity may contain zero-valued fields in tests,
// and catalog visibility must not infer authentication from UserID.
func (a *App) DispatchWithIdentity(req wire.ValidatedRequest, identity authn.Identity, authenticated bool) wire.Response {
	return a.DispatchWithIdentityUA(req, identity, authenticated, "")
}

// DispatchWithIdentityUA 与 DispatchWithIdentity 相同，额外携带调用方
// User-Agent（HTTP 层在分派前读取），供 dashboard 工具调用计数按
// bench/客户端分桶；回放与测试经 Dispatch* 直入时为空串，不参与计数。
func (a *App) DispatchWithIdentityUA(req wire.ValidatedRequest, identity authn.Identity, authenticated bool, userAgent string) wire.Response {
	return a.dispatch(req, identity, authenticated, userAgent)
}

func (a *App) dispatch(req wire.ValidatedRequest, identity authn.Identity, authenticated bool, userAgent string) wire.Response {
	// JSON-RPC 约定：无 id 的消息是通知，一律 204 空体（任何方法同口径）。
	if !req.HasID {
		return wire.Notification()
	}
	if a.PanicOnMethods != nil && a.PanicOnMethods[req.Method] {
		panic("parity probe")
	}
	switch req.Method {
	case "initialize":
		return a.initialize(req)
	case "tools/list":
		return wire.Result(req.RequestID, a.toolsList(authenticated))
	case "resources/list":
		return wire.Result(req.RequestID, ResourcesList())
	case "resources/templates/list":
		return wire.Result(req.RequestID, ResourceTemplatesList())
	case "resources/read":
		if a.resources == nil {
			return wire.Error(req.RequestID, wire.InternalError, "Resource read failed")
		}
		uri, ok := req.Params["uri"].(string)
		if !ok {
			return wire.Error(req.RequestID, wire.InvalidParams, "resources/read params.uri is required.")
		}
		result, err := a.resources.ReadResource(uri)
		if err != nil {
			if inputErr, ok := err.(ResourceInputError); ok {
				return wire.Error(req.RequestID, wire.InvalidParams, inputErr.Error())
			}
			return wire.Error(req.RequestID, wire.InternalError, "Resource read failed")
		}
		return wire.Result(req.RequestID, result)
	case "prompts/list":
		return wire.Result(req.RequestID, PromptsList())
	case "prompts/get":
		result, err := GetPrompt(req.Params["name"], req.Params["arguments"])
		if err != nil {
			if inputErr, ok := err.(PromptInputError); ok {
				return wire.Error(req.RequestID, wire.InvalidParams, inputErr.Error())
			}
			return wire.Error(req.RequestID, wire.InternalError, "Prompt rendering failed")
		}
		return wire.Result(req.RequestID, result)
	case "tools/call":
		a.recordToolCall(req, userAgent)
		return a.call(req, identity)
	default:
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
		{Key: "instructions", Value: a.instructions()},
	}
	return wire.WithSession(wire.Result(req.RequestID, result), a.sessionID())
}

func (a *App) call(req wire.ValidatedRequest, identity authn.Identity) wire.Response {
	name, ok := req.Params["name"].(string)
	if !ok || name == "" {
		return wire.Error(req.RequestID, wire.InvalidParams, "tools/call params.name is required")
	}
	args, _ := req.Params["arguments"].(map[string]any)
	// 身份感知表优先；匿名请求 identity 为零值（UserID=0），
	// 由处理器投射 "Authentication is required for this tool."。
	if handler, found := a.identityTools[name]; found {
		data, err := handler(identity, args)
		return toolCallResult(req, data, err)
	}
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
	return toolCallResult(req, data, err)
}

// recordToolCall 对齐 application.py tools/call 的鉴权前置计数：仅当计数器
// 已接线、name 为合法非空字符串、且 UA 非压测前缀时记录；bench 前缀
// （mcp-latency-bench/）整体免计数但仍受限流约束（限流在路由层先于分派）。
// 计数时机先于工具执行，与 Python 一致（失败调用同样计入）。
func (a *App) recordToolCall(req wire.ValidatedRequest, userAgent string) {
	if a.metrics == nil {
		return
	}
	name, ok := req.Params["name"].(string)
	if !ok || name == "" {
		return
	}
	if metrics.IsBenchmarkUserAgent(userAgent) {
		return
	}
	a.metrics.Record(
		context.Background(),
		metrics.BucketToolName(name, a.knownToolNames),
		metrics.BucketClientName(userAgent),
	)
}

// toolCallResult 把处理器产出/错误折叠成统一包络：ToolInputError 文案直出，
// 其余错误一律 "Tool execution failed."（isError 均无 structuredContent）。
func toolCallResult(req wire.ValidatedRequest, data any, err error) wire.Response {
	if err != nil {
		message := "Tool execution failed."
		if inputErr, ok := err.(ToolInputError); ok {
			message = inputErr.Error()
		}
		return wire.Result(req.RequestID, toolResult(
			jsonx.Object{{Key: "error", Value: message}}, true))
	}
	return wire.Result(req.RequestID, toolResult(data, false))
}

// maxToolResultChars 复刻 responses.py 的 MAX_TOOL_RESULT_CHARS
// （catalog.py 的 100_000）：按 rune 计数，超长则整体替换为
// truncated/reason/preview 包络。
const maxToolResultChars = 100_000

// toolResult 复刻 responses._tool_response：内层 text 用 Python 默认
// 分隔符（", " / ": "）的 json.dumps，外层信封紧凑；成功才带
// structuredContent。顶层键序 content/isError/structuredContent 与
// Python 插入序一致（亦恰好是按字母序）。
//
// 内层 text 超过 100000 字符（rune 口径）时替换为截断包络并重新编码；
// structuredContent 也随之变为截断包络（Python 行为：safe_data 被替换）。
func toolResult(data any, isError bool) jsonx.Object {
	text := pythonDumps(data)
	if runes := []rune(text); len(runes) > maxToolResultChars {
		data = jsonx.Object{
			{Key: "truncated", Value: true},
			{Key: "reason", Value: "Tool result exceeded 100000 characters."},
			{Key: "preview", Value: string(runes[:maxToolResultChars])},
		}
		text = pythonDumps(data)
	}
	result := jsonx.Object{
		{Key: "content", Value: []any{jsonx.Object{
			{Key: "type", Value: "text"},
			{Key: "text", Value: text},
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
	Authenticate(ctx context.Context, authorization string) (authn.Identity, bool, *authn.Response)
}

// Handler 把认证、解析、限流、分派接成 http.Handler。顺序对齐 FastAPI
// routes_mcp.py：路由方法闸（405）→ 依赖认证（401）→ 请求体解析
// （协议错误）→ 限流（429，解析之后分派之前）→ 分派。
type Handler struct {
	app     *App
	auth    Authenticator
	limiter *ratelimit.Limiter
	usage   *usage.Recorder
}

// NewHandler 接线；limiter 为 nil 时不限流（回放多数用例与 Redis 未接线
// 场景，对齐 Python app.state.redis 缺失语义）。
func NewHandler(app *App, auth Authenticator, limiter *ratelimit.Limiter) *Handler {
	return &Handler{app: app, auth: auth, limiter: limiter}
}

// SetUsage 接线每日用量汇总（可选）；未接线时不记录。
func (h *Handler) SetUsage(recorder *usage.Recorder) { h.usage = recorder }

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
	var (
		identity      authn.Identity
		authenticated bool
	)
	if h.auth != nil {
		authorizations := r.Header.Values("Authorization")
		if len(authorizations) > 1 {
			unauthorizedHeaderResponse().Write(w)
			return
		}
		authorization := ""
		if len(authorizations) == 1 {
			authorization = authorizations[0]
		}
		id, ok, authFailure := h.auth.Authenticate(r.Context(), authorization)
		if authFailure != nil {
			authFailure.Write(w)
			return
		}
		identity = id
		authenticated = ok
	}
	req, parseErr := wire.ParseRequest(r)
	if parseErr != nil {
		wire.Error(parseErr.RequestID, parseErr.Code, parseErr.Message).Write(w)
		return
	}
	// 限流缝：enforce_mcp_rate_limit 的调用点在 parse 之后、dispatch 之前；
	// 身份（user_id/role/生效档位）与可信代理 XFF 链全部由限流器消费。
	if exceeded := h.limiter.Enforce(r.Context(), req.Method, identity, r); exceeded != nil {
		h.recordUsage(r, req, identity, usage.LimitKind(exceeded.Quota, exceeded.QuotaScope))
		exceeded.Projection(req.RequestID).Write(w)
		return
	}
	h.recordUsage(r, req, identity, "")
	// PR 1.4 起 tools/list 私有工具按 is_authenticated 分叉，身份经参数传入分派。
	// User-Agent 在分派前读取（对齐 application.py），供 dashboard 计数
	// 按 bench/客户端分桶；不参与协议行为。
	h.app.DispatchWithIdentityUA(req, identity, authenticated, r.Header.Get("User-Agent")).Write(w)
}

// recordUsage 写每日用量汇总（被限流时 limited 为限流类别）。只读请求，
// 不改变任何响应字节；未接线时直接返回。
func (h *Handler) recordUsage(r *http.Request, req wire.ValidatedRequest, identity authn.Identity, limited string) {
	if h.usage == nil {
		return
	}
	event := usage.Event{
		Identity:  identity,
		ClientIP:  h.limiter.ClientIP(r),
		UserAgent: r.Header.Get("User-Agent"),
		Method:    req.Method,
		Limited:   limited,
	}
	switch req.Method {
	case "tools/call":
		name, _ := req.Params["name"].(string)
		event.Tool = metrics.BucketToolName(name, h.app.knownToolNames)
	case "initialize":
		if info, ok := req.Params["clientInfo"].(map[string]any); ok {
			event.ClientName, _ = info["name"].(string)
		}
	}
	h.usage.Record(r.Context(), event)
}

// writeInternalServerError 对齐 ServerErrorMiddleware：纯文本定长 500。
func unauthorizedHeaderResponse() *authn.Response {
	return &authn.Response{
		Status:  http.StatusUnauthorized,
		Body:    []byte(`{"detail":"Authorization must contain exactly one value"}`),
		Headers: http.Header{"WWW-Authenticate": []string{"Bearer"}},
	}
}

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
