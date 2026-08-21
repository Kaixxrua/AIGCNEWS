// Package metrics 移植 MCP 工具调用计数的 Redis 聚合写者
// （backend/app/monitoring/mcp_redis_metrics.py + mcp_tools.py）。
//
// 只复刻 Go 切换期需要的一半：写路径。dashboard 的读路径
// （resolve_tool_call_metrics().snapshot()）仍由 Python 主进程承担，
// Go 不写本地 JSON shadow、只做 Redis 原子 Lua 聚合（模块注释明示的
// 过渡策略："Go 重写切换期 Python/Go 双写者并存时也靠它收敛（Go 侧
// 只写 Redis）"）。
//
// 语义逐字对齐 Python：
//   - 键布局 mcpmetrics:{total,since,tool_calls,tool_last,client_calls,
//     client_last}，同一份 Lua（INCR/SETNX/HINCRBY/HSET）；
//   - 时间戳 now = datetime.now(timezone.utc).isoformat() 的 Go 等价；
//   - fail-open：任何 Redis 错误只记日志，绝不影响 MCP 分派响应；
//   - bench 免计数：UA 命中 "mcp-latency-bench/" 前缀的 tools/call
//     完全不进本计数器（dashboard 的 mcp_total_calls 不含压测流量），
//     但不影响限流（限流在路由层先于分派）。
package metrics

import (
	"context"
	"log/slog"
	"strings"
	"time"

	"github.com/redis/go-redis/v9"
)

// 分桶常量逐字对齐 mcp_tools.py。
const (
	// MaxToolNameLength = MAX_TOOL_NAME_LENGTH（mcp_tools.py:19）。
	MaxToolNameLength = 64
	// UnknownToolName = UNKNOWN_TOOL_NAME（mcp_tools.py:18）。
	UnknownToolName = "__unknown__"
	// dshPluginClient = DSH_PLUGIN_CLIENT（mcp_tools.py:38）。
	dshPluginClient = "dsh-aigc-radar"
	// dshPluginUAPrefix 是 _CLIENT_UA_PREFIXES 唯一一项的前缀。
	dshPluginUAPrefix = "dsh-aigc-radar/"
	// BenchmarkUAPrefix = BENCHMARK_UA_PREFIX（mcp_tools.py:45）。
	BenchmarkUAPrefix = "mcp-latency-bench/"

	namespace = "mcpmetrics"
)

// recordScript 逐字复刻 _RECORD_SCRIPT（mcp_redis_metrics.py:54-64）：
// total 自增、since 先到先得、工具/客户端桶 HINCRBY+HSET，单次 EVAL 全原子。
// KEYS: total, since, tool_calls, tool_last, client_calls, client_last
// ARGV: tool, client（空串跳过客户端桶）, now_iso
var recordScript = redis.NewScript(`
redis.call('INCR', KEYS[1])
redis.call('SETNX', KEYS[2], ARGV[3])
redis.call('HINCRBY', KEYS[3], ARGV[1], 1)
redis.call('HSET', KEYS[4], ARGV[1], ARGV[3])
if ARGV[2] ~= '' then
  redis.call('HINCRBY', KEYS[5], ARGV[2], 1)
  redis.call('HSET', KEYS[6], ARGV[2], ARGV[3])
end
return 1
`)

// IsBenchmarkUserAgent 对齐 is_benchmark_user_agent：strip 后以前缀判定。
func IsBenchmarkUserAgent(userAgent string) bool {
	return strings.HasPrefix(strings.TrimSpace(userAgent), BenchmarkUAPrefix)
}

// BucketClientName 对齐 bucket_client_name：UA 前缀命中已知客户端才成桶，
// 其余一律空串（不计客户端桶，防随机 UA 无限膨胀基数）。
func BucketClientName(userAgent string) string {
	if strings.HasPrefix(strings.TrimSpace(userAgent), dshPluginUAPrefix) {
		return dshPluginClient
	}
	return ""
}

// BucketToolName 对齐 bucket_tool_name：仅 knownNames（注册表）内的名字
// 保留原名；其余（含超长、空串）截断判定后统一归入 __unknown__。
func BucketToolName(toolName string, knownNames map[string]struct{}) string {
	name := truncate(strings.TrimSpace(toolName), MaxToolNameLength)
	if name == "" {
		return UnknownToolName
	}
	if _, ok := knownNames[name]; ok {
		return name
	}
	return UnknownToolName
}

// truncate 等价 Python 的 name[:n]：按 rune 截断（Python str 切片按码点）。
func truncate(s string, n int) string {
	runes := []rune(s)
	if len(runes) <= n {
		return s
	}
	return string(runes[:n])
}

// Recorder 是 mcpmetrics:* 的 Redis 写者；nil *Recorder 等价未接线
// （对齐 Python app.state.mcp_tool_call_metrics 缺失语义），所有方法
// 安全 no-op。
type Recorder struct {
	client *redis.Client
}

// NewRecorder 接线；client 为 nil 时返回 nil（Record 恒 no-op）。
func NewRecorder(client *redis.Client) *Recorder {
	if client == nil {
		return nil
	}
	return &Recorder{client: client}
}

func (r *Recorder) keys() [6]string {
	return [6]string{
		namespace + ":total",
		namespace + ":since",
		namespace + ":tool_calls",
		namespace + ":tool_last",
		namespace + ":client_calls",
		namespace + ":client_last",
	}
}

// Record 写入一次工具调用计数。tool/client 应已过 Bucket* 归桶；bench
// 判定在调用方（命中即不调 Record）。fail-open：Redis 错误只记日志。
//
// now 对齐 datetime.now(timezone.utc).isoformat()：UTC、微秒精度、
// "+00:00" 偏移（无 "Z"，无纳秒）。
func (r *Recorder) Record(ctx context.Context, tool, client string) {
	if r == nil {
		return
	}
	now := time.Now().UTC().Format("2006-01-02T15:04:05.999999+00:00")
	keys := r.keys()
	k := []string{keys[0], keys[1], keys[2], keys[3], keys[4], keys[5]}
	if err := recordScript.Run(ctx, r.client, k, tool, client, now).Err(); err != nil {
		slog.Warn("mcp tool call metrics redis write failed", "err", err)
	}
}
