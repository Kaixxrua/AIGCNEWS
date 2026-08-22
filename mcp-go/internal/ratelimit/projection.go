// 限流 429 的 HTTP 投影，逐字节对齐 Python 的 mcp_rate_limited_projection
// 与 mcp_quota_exceeded_projection（inbound/rate_limit.py）。
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
			"已达今日匿名调用上限（%d 次/天，按 IP 计）。请前往 https://aigcnews.cn/mcp 登录并创建 MCP token 获得月度配额，或前往 https://aigcnews.cn/membership 开通 VIP 享更高额度。Anonymous daily quota exhausted (%d calls/day per IP): sign in at https://aigcnews.cn/mcp to create an MCP token for a monthly quota, or upgrade to VIP at https://aigcnews.cn/membership.",
			e.Limit, e.Limit,
		)
	case e.QuotaScope == "daily" && e.Tier == authn.TierMember:
		message = fmt.Sprintf(
			"今日 VIP 额度已用完（%d 次/天），配额窗口将于约 %d 秒后重置。VIP daily quota exhausted (%d calls/day); the window resets in about %d seconds.",
			e.Limit, e.RetryAfter, e.Limit, e.RetryAfter,
		)
	case e.QuotaScope == "daily":
		message = fmt.Sprintf(
			"已达今日免费调用上限（%d 次/天）。请前往 https://aigcnews.cn/membership 开通 VIP 享更高日度与月度额度，或等待配额窗口重置（约 %d 秒后）。Free daily quota exhausted (%d calls/day): upgrade to VIP at https://aigcnews.cn/membership for higher daily and monthly quotas, or wait for the window to reset.",
			e.Limit, e.RetryAfter, e.Limit,
		)
	case e.Tier == authn.TierMember:
		message = fmt.Sprintf(
			"本月 VIP 额度已用完（%d 次/月），配额窗口将于约 %d 秒后重置。VIP monthly quota exhausted (%d calls/month); the window resets in about %d seconds.",
			e.Limit, e.RetryAfter, e.Limit, e.RetryAfter,
		)
	default:
		message = fmt.Sprintf(
			"本月免费额度已用完（%d 次/月）。请前往 https://aigcnews.cn/membership 开通 VIP 享更高额度，或等待配额窗口重置（约 %d 秒后）。Free monthly quota exhausted (%d calls/month): upgrade to VIP at https://aigcnews.cn/membership for a higher quota, or wait for the window to reset.",
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
