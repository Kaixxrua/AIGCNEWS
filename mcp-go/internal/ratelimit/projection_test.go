package ratelimit

import (
	"net/http"
	"testing"

	"aigcnews/mcp-go/internal/wire"
)

// assertCommonHeaders 断言 429 投影的公共头：Retry-After、协议版本，
// 且不带 mcp-session-id（投影不建立会话）。
func assertCommonHeaders(t *testing.T, resp wire.Response, wantRetryAfter string) {
	t.Helper()
	if resp.Status != http.StatusTooManyRequests {
		t.Fatalf("status = %d, want 429", resp.Status)
	}
	if got := resp.Headers.Get("Retry-After"); got != wantRetryAfter {
		t.Fatalf("Retry-After = %q, want %q", got, wantRetryAfter)
	}
	if got := resp.Headers.Get("MCP-Protocol-Version"); got != wire.ProtocolVersion {
		t.Fatalf("MCP-Protocol-Version = %q, want %q", got, wire.ProtocolVersion)
	}
	if _, ok := resp.Headers["Mcp-Session-Id"]; ok {
		t.Fatal("projection must not carry mcp-session-id")
	}
}

func TestBurstProjectionBytes(t *testing.T) {
	exceeded := &Exceeded{Quota: false, RetryAfter: WindowSeconds}
	resp := exceeded.Projection(float64(2))
	want := `{"jsonrpc":"2.0","id":2,"error":{"code":-32000,"message":"Rate limit exceeded; slow down and retry after 60 seconds."}}`
	if string(resp.Body) != want {
		t.Fatalf("body mismatch:\n got %s\nwant %s", resp.Body, want)
	}
	if len(resp.Body) != 119 {
		t.Fatalf("body length = %d, want 119", len(resp.Body))
	}
	assertCommonHeaders(t, resp, "60")
}

func TestQuotaProjectionDailyBytes(t *testing.T) {
	exceeded := &Exceeded{Quota: true, QuotaScope: "daily", Tier: "free", Limit: 100, RetryAfter: 43200}
	resp := exceeded.Projection(float64(9))
	want := `{"jsonrpc":"2.0","id":9,"error":{"code":-32000,"message":"已达今日匿名调用上限（100 次/天，按 IP 计）。请前往 https://aigcnews.cn/mcp 登录并创建 MCP token 获得月度配额，或前往 https://aigcnews.cn/membership 开通 VIP 享更高额度。Anonymous daily quota exhausted (100 calls/day per IP): sign in at https://aigcnews.cn/mcp to create an MCP token for a monthly quota, or upgrade to VIP at https://aigcnews.cn/membership.","data":{"quota_scope":"daily","tier":"free","limit":100,"retry_after":43200}}}`
	if string(resp.Body) != want {
		t.Fatalf("body mismatch:\n got %s\nwant %s", resp.Body, want)
	}
	assertCommonHeaders(t, resp, "43200")
}

func TestQuotaProjectionMemberMonthlyBytes(t *testing.T) {
	exceeded := &Exceeded{Quota: true, QuotaScope: "monthly", Tier: "member", Limit: 20000, RetryAfter: 86400}
	resp := exceeded.Projection(float64(9))
	want := `{"jsonrpc":"2.0","id":9,"error":{"code":-32000,"message":"本月 VIP 额度已用完（20000 次/月），配额窗口将于约 86400 秒后重置。VIP monthly quota exhausted (20000 calls/month); the window resets in about 86400 seconds.","data":{"quota_scope":"monthly","tier":"member","limit":20000,"retry_after":86400}}}`
	if string(resp.Body) != want {
		t.Fatalf("body mismatch:\n got %s\nwant %s", resp.Body, want)
	}
	assertCommonHeaders(t, resp, "86400")
}

func TestQuotaProjectionFreeMonthlyBytes(t *testing.T) {
	exceeded := &Exceeded{Quota: true, QuotaScope: "monthly", Tier: "free", Limit: 2000, RetryAfter: 86400}
	resp := exceeded.Projection(float64(9))
	want := `{"jsonrpc":"2.0","id":9,"error":{"code":-32000,"message":"本月免费额度已用完（2000 次/月）。请前往 https://aigcnews.cn/membership 开通 VIP 享更高额度，或等待配额窗口重置（约 86400 秒后）。Free monthly quota exhausted (2000 calls/month): upgrade to VIP at https://aigcnews.cn/membership for a higher quota, or wait for the window to reset.","data":{"quota_scope":"monthly","tier":"free","limit":2000,"retry_after":86400}}}`
	if string(resp.Body) != want {
		t.Fatalf("body mismatch:\n got %s\nwant %s", resp.Body, want)
	}
	assertCommonHeaders(t, resp, "86400")
}
