// 限流 429 的 HTTP 投影，逐字节对齐 Python /api/v1 的限流与配额投影。
package ratelimit

import (
	"fmt"
	"net/http"
	"strconv"

	"aigcnews/mcp-go/internal/authn"
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
			"已达匿名调用上限（每 24 小时 %d 次，按 IP 计）。请前往 https://aigcnews.cn/mcp 登录并创建 MCP token，获得每 24 小时与滚动 30 天配额；或前往 https://aigcnews.cn/membership 开通 VIP 享更高额度。Anonymous quota exhausted (%d calls per 24 hours per IP): sign in at https://aigcnews.cn/mcp to create an MCP token for per-24-hour and rolling-30-day quotas, or upgrade to VIP at https://aigcnews.cn/membership.",
			e.Limit, e.Limit,
		)
	case e.QuotaScope == "daily" && e.Tier == authn.TierMember:
		message = fmt.Sprintf(
			"VIP 每 24 小时额度已用完（%d 次），配额窗口将于约 %d 秒后重置。VIP per-24-hour quota exhausted (%d calls); the window resets in about %d seconds.",
			e.Limit, e.RetryAfter, e.Limit, e.RetryAfter,
		)
	case e.QuotaScope == "daily":
		message = fmt.Sprintf(
			"免费档每 24 小时额度已用完（%d 次）。请前往 https://aigcnews.cn/membership 开通 VIP，享更高的每 24 小时与滚动 30 天额度；或等待配额窗口重置（约 %d 秒后）。Free per-24-hour quota exhausted (%d calls): upgrade to VIP at https://aigcnews.cn/membership for higher per-24-hour and rolling-30-day quotas, or wait for the window to reset.",
			e.Limit, e.RetryAfter, e.Limit,
		)
	case e.Tier == authn.TierMember:
		message = fmt.Sprintf(
			"VIP 滚动 30 天额度已用完（%d 次），配额窗口将于约 %d 秒后重置。VIP rolling-30-day quota exhausted (%d calls); the window resets in about %d seconds.",
			e.Limit, e.RetryAfter, e.Limit, e.RetryAfter,
		)
	default:
		message = fmt.Sprintf(
			"免费档滚动 30 天额度已用完（%d 次）。请前往 https://aigcnews.cn/membership 开通 VIP 享更高额度，或等待配额窗口重置（约 %d 秒后）。Free rolling-30-day quota exhausted (%d calls): upgrade to VIP at https://aigcnews.cn/membership for a higher quota, or wait for the window to reset.",
			e.Limit, e.RetryAfter, e.Limit,
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
