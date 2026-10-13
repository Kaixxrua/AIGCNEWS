// 限流 429 的 HTTP 投影，逐字节对齐 Python /api/v1 的限流与配额投影
// （唯一差异是登录链接的来源标记：这里是 ref=mcp-429-*，/api/v1 是 ref=api-429-*）。
package ratelimit

import (
	"fmt"
	"net/http"
	"strconv"

	"aigcnews/mcp-go/internal/jsonx"
	"aigcnews/mcp-go/internal/wire"
)

// Exceeded 携带一次限流判定：Quota=false 为分钟级突发桶（对齐
// RateLimitExceededError 的投影面），Quota=true 为 tools/call 分层
// 配额桶（字段对齐 McpQuotaExceededError）。
type Exceeded struct {
	Quota      bool
	QuotaScope string // "daily" | "monthly"（Quota=true 时有效）
	Tier       string
	Limit      int64
	RetryAfter int64
	// IdentityKind 区分匿名日配额（"ip"）与登录日配额（"user"）——
	// 两者同 QuotaScope="daily" 同 Tier="free"，投影文案必须分开
	// （按 IP 计的提示不能落在登录用户头上）。
	IdentityKind string
}

// Projection 产出 429 + JSON-RPC 错误信封。突发桶 message 由
// WindowSeconds 插值；配额桶 error.data 的键序（quota_scope/tier/
// limit/retry_after/identity_kind）与 message 五变体文案逐字复制
// Python，额度数字一律走插值不在文案里硬编码（档位调整时文案不漂移）。
// 升级链接带 ref=mcp-429-{anon,daily,monthly}：网站据此记录从哪类 429
// 提示点进来的（前端 visitBeacon 上报，后端只收这几个值）。
func (e *Exceeded) Projection(requestID any) wire.Response {
	if !e.Quota {
		message := fmt.Sprintf(
			"Rate limit exceeded; slow down and retry after %d seconds.",
			WindowSeconds,
		)
		return wire.ErrorResponse(
			http.StatusTooManyRequests, requestID, RateLimitedCode, message,
			nil, retryAfterHeader(WindowSeconds),
		)
	}

	var message string
	switch {
	case e.QuotaScope == "daily" && e.IdentityKind == "ip":
		message = fmt.Sprintf(
			"已达匿名调用上限（每 24 小时 %d 次，按 IP 计）。请前往 https://aigcnews.cn/mcp?ref=mcp-429-anon 登录并创建 MCP token，免费使用账号配额。Anonymous quota exhausted (%d calls per 24 hours per IP): sign in at https://aigcnews.cn/mcp?ref=mcp-429-anon to create an MCP token and use the free account quotas.",
			e.Limit, e.Limit,
		)
	case e.QuotaScope == "daily":
		message = fmt.Sprintf(
			"账号每 24 小时额度已用完（%d 次），配额窗口将于约 %d 秒后重置。Account per-24-hour quota exhausted (%d calls); the window resets in about %d seconds.",
			e.Limit, e.RetryAfter, e.Limit, e.RetryAfter,
		)
	default:
		message = fmt.Sprintf(
			"账号滚动 30 天额度已用完（%d 次），配额窗口将于约 %d 秒后重置。Account rolling-30-day quota exhausted (%d calls); the window resets in about %d seconds.",
			e.Limit, e.RetryAfter, e.Limit, e.RetryAfter,
		)
	}
	data := jsonx.Object{
		{Key: "quota_scope", Value: e.QuotaScope},
		{Key: "tier", Value: e.Tier},
		{Key: "limit", Value: e.Limit},
		{Key: "retry_after", Value: e.RetryAfter},
		{Key: "identity_kind", Value: e.IdentityKind},
	}
	return wire.ErrorResponse(
		http.StatusTooManyRequests, requestID, RateLimitedCode, message,
		data, retryAfterHeader(e.RetryAfter),
	)
}

// retryAfterHeader 对齐 Python 投影的 {"Retry-After": str(n)}。
func retryAfterHeader(n int64) http.Header {
	header := http.Header{}
	header.Set("Retry-After", strconv.FormatInt(n, 10))
	return header
}
