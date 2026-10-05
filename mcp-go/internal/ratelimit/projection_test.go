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
	exceeded := &Exceeded{Quota: true, QuotaScope: "daily", Tier: "free", Limit: 30, RetryAfter: 43200, IdentityKind: "ip"}
	resp := exceeded.Projection(float64(9))
	want := `{"jsonrpc":"2.0","id":9,"error":{"code":-32000,"message":"已达匿名调用上限（每 24 小时 30 次，按 IP 计）。请前往 https://aigcnews.cn/mcp?ref=mcp-429-anon 登录并创建 MCP token，获得每 24 小时与滚动 30 天配额；或前往 https://aigcnews.cn/membership?ref=mcp-429-anon 开通 VIP 享更高额度。Anonymous quota exhausted (30 calls per 24 hours per IP): sign in at https://aigcnews.cn/mcp?ref=mcp-429-anon to create an MCP token for per-24-hour and rolling-30-day quotas, or upgrade to VIP at https://aigcnews.cn/membership?ref=mcp-429-anon.","data":{"quota_scope":"daily","tier":"free","limit":30,"retry_after":43200,"identity_kind":"ip"}}}`
	if string(resp.Body) != want {
		t.Fatalf("body mismatch:\n got %s\nwant %s", resp.Body, want)
	}
	assertCommonHeaders(t, resp, "43200")
}

// 登录免费档日 pacing 投影：identity_kind=user，文案指向 membership
// （「按 IP 计」的匿名文案不能落在登录用户头上）。
func TestQuotaProjectionFreeDailyBytes(t *testing.T) {
	exceeded := &Exceeded{Quota: true, QuotaScope: "daily", Tier: "free", Limit: 60, RetryAfter: 43200, IdentityKind: "user"}
	resp := exceeded.Projection(float64(9))
	want := `{"jsonrpc":"2.0","id":9,"error":{"code":-32000,"message":"免费档每 24 小时额度已用完（60 次）。请前往 https://aigcnews.cn/membership?ref=mcp-429-daily 开通 VIP，享更高的每 24 小时与滚动 30 天额度；或等待配额窗口重置（约 43200 秒后）。Free per-24-hour quota exhausted (60 calls): upgrade to VIP at https://aigcnews.cn/membership?ref=mcp-429-daily for higher per-24-hour and rolling-30-day quotas, or wait for the window to reset.","data":{"quota_scope":"daily","tier":"free","limit":60,"retry_after":43200,"identity_kind":"user"}}}`
	if string(resp.Body) != want {
		t.Fatalf("body mismatch:\n got %s\nwant %s", resp.Body, want)
	}
	assertCommonHeaders(t, resp, "43200")
}

// 会员档日 pacing 投影：告知窗口重置，不做升级引导。
func TestQuotaProjectionMemberDailyBytes(t *testing.T) {
	exceeded := &Exceeded{Quota: true, QuotaScope: "daily", Tier: "member", Limit: 400, RetryAfter: 3600, IdentityKind: "user"}
	resp := exceeded.Projection(float64(9))
	want := `{"jsonrpc":"2.0","id":9,"error":{"code":-32000,"message":"VIP 每 24 小时额度已用完（400 次），配额窗口将于约 3600 秒后重置。VIP per-24-hour quota exhausted (400 calls); the window resets in about 3600 seconds.","data":{"quota_scope":"daily","tier":"member","limit":400,"retry_after":3600,"identity_kind":"user"}}}`
	if string(resp.Body) != want {
		t.Fatalf("body mismatch:\n got %s\nwant %s", resp.Body, want)
	}
	assertCommonHeaders(t, resp, "3600")
}

func TestQuotaProjectionMemberMonthlyBytes(t *testing.T) {
	exceeded := &Exceeded{Quota: true, QuotaScope: "monthly", Tier: "member", Limit: 8000, RetryAfter: 86400, IdentityKind: "user"}
	resp := exceeded.Projection(float64(9))
	want := `{"jsonrpc":"2.0","id":9,"error":{"code":-32000,"message":"VIP 滚动 30 天额度已用完（8000 次），配额窗口将于约 86400 秒后重置。VIP rolling-30-day quota exhausted (8000 calls); the window resets in about 86400 seconds.","data":{"quota_scope":"monthly","tier":"member","limit":8000,"retry_after":86400,"identity_kind":"user"}}}`
	if string(resp.Body) != want {
		t.Fatalf("body mismatch:\n got %s\nwant %s", resp.Body, want)
	}
	assertCommonHeaders(t, resp, "86400")
}

func TestQuotaProjectionFreeMonthlyBytes(t *testing.T) {
	exceeded := &Exceeded{Quota: true, QuotaScope: "monthly", Tier: "free", Limit: 1200, RetryAfter: 86400, IdentityKind: "user"}
	resp := exceeded.Projection(float64(9))
	want := `{"jsonrpc":"2.0","id":9,"error":{"code":-32000,"message":"免费档滚动 30 天额度已用完（1200 次）。请前往 https://aigcnews.cn/membership?ref=mcp-429-monthly 开通 VIP 享更高额度，或等待配额窗口重置（约 86400 秒后）。Free rolling-30-day quota exhausted (1200 calls): upgrade to VIP at https://aigcnews.cn/membership?ref=mcp-429-monthly for a higher quota, or wait for the window to reset.","data":{"quota_scope":"monthly","tier":"free","limit":1200,"retry_after":86400,"identity_kind":"user"}}}`
	if string(resp.Body) != want {
		t.Fatalf("body mismatch:\n got %s\nwant %s", resp.Body, want)
	}
	assertCommonHeaders(t, resp, "86400")
}
