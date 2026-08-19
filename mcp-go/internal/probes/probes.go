// Package probes 提供 /api/live、/api/version、/api/ready 三个探活/版本端点，
// 响应与 Python（FastAPI/Starlette，mcp_main.py）逐字节对齐。
//
// 字节级事实来自 backend/tests/parity/corpus/surface.jsonl 的
// mcp-live / mcp-version / mcp-ready-no-lifespan 用例，以及对 mcp_main.app
// 的实测（404/405/307 形状）；本包 probes_test.go 直接消费语料文件做断言。
//
// 不用 http.ServeMux：ServeMux 会做路径清洗（/api//live → 301/307 重定向）
// 与方法模式自带的 405 空体，两者都与 Starlette 行为相悖。改为单一 Handler
// 手工分派，全表面可控。
//
// 已记录残余差异（均不在语料覆盖面内）：多值同名头、chunked 响应、
// 双层以上尾斜杠（Starlette 只剪一层，本实现同口径）。
package probes

import (
	"context"
	"net/http"
	"strconv"
	"strings"

	"aigcnews/mcp-go/internal/version"
)

// 响应体常量。键序/分隔符/内容逐字固定，任何改动都会触发语料回放红。
const (
	serverName    = version.ServerName
	liveBody      = `{"status":"ok"}`
	notFoundBody  = `{"detail":"Not Found"}`
	methodNotBody = `{"detail":"Method Not Allowed"}`
	// 未就绪时路由层收敛后的固定投射（mcp_main.py mcp_readiness 的
	// HTTPException detail；error_class 等明细只进日志，不回传）。
	notReadyBody = `{"detail":{"status":"not_ready","runtime_ready":false}}`
	// 就绪时 project_catalog_runtime_readiness 的完整返回（dict 插入序）。
	// 语料未钉此形状（录制不经 lifespan），由 Python 源码口径转写，
	// 切换前由 Phase 3 活体 diff 终验。
	readyBody = `{"status":"ready","runtime_ready":true,"active_backend":"postgres","scope":"application_runtime","checks":{"configuration":"ok","postgres":"ok"},"error_class":null}`
)

// Readiness 报告运行时就绪与否；等价 Python 侧 readiness 结果
// runtime_ready 字段的路由级读取。nil 视为未就绪（对齐 runtime 未绑定的 503）。
type Readiness func(ctx context.Context) bool

type handler struct {
	versionBody string
	readiness   Readiness
	mcp         http.Handler
}

// NewMux 装配探活路由（实为单一 Handler；保留 NewMux 命名以对齐
// “接线在启动期完成一次”的语义）。serverVersion 在启动时解析一次，之后不变。
// 可选的 mcp 处理器挂载 /api/mcp（PR 1.2 起）；缺省时该路径按未注册 404。
func NewMux(serverVersion string, readiness Readiness, mcp ...http.Handler) http.Handler {
	h := &handler{
		versionBody: `{"name":"` + serverName + `","version":` + strconv.Quote(serverVersion) + `}`,
		readiness:   readiness,
	}
	if len(mcp) > 0 {
		h.mcp = mcp[0]
	}
	return h
}

func (h *handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	// Starlette redirect_slashes 复刻：已注册路径恰好一个尾斜杠时
	// 307 到去斜杠形式（先于方法判定；双层尾斜杠不递归，落 404）。
	if strings.HasSuffix(r.URL.Path, "/") && r.URL.Path != "/" {
		trimmed := strings.TrimSuffix(r.URL.Path, "/")
		if h.isRegistered(trimmed) {
			w.Header().Set("Location", "http://"+r.Host+trimmed)
			w.Header().Set("Content-Length", "0")
			w.WriteHeader(http.StatusTemporaryRedirect)
			return
		}
	}
	switch r.URL.Path {
	case "/api/live":
		h.serveGet(w, r, func(context.Context) (int, string) { return http.StatusOK, liveBody })
	case "/api/version":
		h.serveGet(w, r, func(context.Context) (int, string) { return http.StatusOK, h.versionBody })
	case "/api/ready":
		h.serveGet(w, r, h.readyExchange)
	case "/api/mcp":
		if h.mcp == nil {
			writeJSON(w, http.StatusNotFound, notFoundBody)
			return
		}
		h.mcp.ServeHTTP(w, r)
	default:
		writeJSON(w, http.StatusNotFound, notFoundBody)
	}
}

func (h *handler) isRegistered(path string) bool {
	switch path {
	case "/api/live", "/api/version", "/api/ready":
		return true
	case "/api/mcp":
		return h.mcp != nil
	}
	return false
}

// serveGet 复刻 FastAPI 路由的方法闸：非 GET（含 HEAD——Starlette 不为
// GET 路由隐式注册 HEAD，实测 405）一律 JSON 405 + Allow: GET。
func (h *handler) serveGet(
	w http.ResponseWriter,
	r *http.Request,
	exchange func(context.Context) (int, string),
) {
	if r.Method != http.MethodGet {
		w.Header().Set("Allow", http.MethodGet)
		writeJSON(w, http.StatusMethodNotAllowed, methodNotBody)
		return
	}
	status, body := exchange(r.Context())
	writeJSON(w, status, body)
}

func (h *handler) readyExchange(ctx context.Context) (int, string) {
	if h.readiness != nil && h.readiness(ctx) {
		return http.StatusOK, readyBody
	}
	return http.StatusServiceUnavailable, notReadyBody
}

// writeJSON 按 Starlette JSONResponse 口径写出：显式 Content-Type
// （无 charset）与 Content-Length，body 为既有字节不再加工。
func writeJSON(w http.ResponseWriter, status int, body string) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Content-Length", strconv.Itoa(len(body)))
	w.WriteHeader(status)
	_, _ = w.Write([]byte(body))
}
