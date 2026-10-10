package mcpapp

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/redis/go-redis/v9"

	"aigcnews/mcp-go/internal/authn"
	"aigcnews/mcp-go/internal/jsonx"
	"aigcnews/mcp-go/internal/ratelimit"
)

type quotaReaderStub struct {
	status ratelimit.QuotaStatus
	calls  int
	seen   authn.Identity
}

func (r *quotaReaderStub) QuotaStatus(_ context.Context, identity authn.Identity, _ time.Time) ratelimit.QuotaStatus {
	r.calls++
	r.seen = identity
	return r.status
}

func (r *quotaReaderStub) TierQuotaLimits(tier string) (int64, int64) {
	if tier == authn.TierMember {
		return 200, 4000
	}
	return 10, 200
}

func quotaWindows(dailyLimit, dailyUsed, dailyResets, monthlyLimit, monthlyUsed, monthlyResets int64) []ratelimit.QuotaWindow {
	return []ratelimit.QuotaWindow{
		{Scope: "daily", WindowSeconds: ratelimit.QuotaDailyWindowSeconds, Limit: dailyLimit, Used: dailyUsed, ResetsIn: dailyResets},
		{Scope: "monthly", WindowSeconds: ratelimit.QuotaMonthlyWindowSeconds, Limit: monthlyLimit, Used: monthlyUsed, ResetsIn: monthlyResets},
	}
}

func TestQuotaGatesRunBeforeAnyRead(t *testing.T) {
	cases := []struct {
		name     string
		identity authn.Identity
		args     map[string]any
		want     string
	}{
		{"anonymous", authn.Identity{}, map[string]any{"x": 1}, "Authentication is required for this tool."},
		{"extra-args", authn.Identity{UserID: 7}, map[string]any{"window": "24h", "all": true},
			"all: Extra inputs are not permitted; window: Extra inputs are not permitted"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			reader := &quotaReaderStub{}
			_, err := NewQuotaService(reader, "https://aigcnews.cn").Get(tc.identity, tc.args)
			if inputErr, ok := err.(ToolInputError); !ok || inputErr.Message != tc.want {
				t.Fatalf("err = %#v, want %q", err, tc.want)
			}
			if reader.calls != 0 {
				t.Fatal("gates must run before reading quota")
			}
		})
	}
}

func TestQuotaProjection(t *testing.T) {
	expires := time.Date(2026, 11, 1, 8, 0, 0, 0, time.FixedZone("UTC+8", 8*60*60))
	free := authn.Identity{UserID: 7, Role: "user", MembershipTier: authn.TierFree}
	vip := authn.Identity{UserID: 7, Role: "user", MembershipTier: authn.TierMember, MembershipExpiresAt: &expires}
	cases := []struct {
		name     string
		identity authn.Identity
		status   ratelimit.QuotaStatus
		want     string
	}{
		{
			name:     "free-in-use",
			identity: free,
			status: ratelimit.QuotaStatus{Tier: authn.TierFree, UsageKnown: true,
				Windows: quotaWindows(10, 3, 5*3600+120, 200, 12, 23*86400+4*3600+5)},
			want: `{"plan":"free","membership_expires_at":null,"quota_applies":true,"windows":[` +
				`{"window":"24h","limit":10,"used":3,"remaining":7,"resets_in_seconds":18120},` +
				`{"window":"30d","limit":200,"used":12,"remaining":188,"resets_in_seconds":2001605}],` +
				`"counts_toward_quota":false,"summary":"Free plan. 24-hour window: 7 of 10 tool calls left, resets in 5h 2m. ` +
				`30-day window: 188 of 200 left, resets in 23d 4h. VIP raises the limits to 200 per 24 hours and 4,000 per 30 days: ` +
				`https://aigcnews.cn/membership. Checking quota does not use any.","manage_url":"https://aigcnews.cn/membership"}`,
		},
		{
			// 被拒的尝试也计数：used 封顶为 limit。
			name:     "vip-daily-exhausted",
			identity: vip,
			status: ratelimit.QuotaStatus{Tier: authn.TierMember, UsageKnown: true,
				Windows: quotaWindows(200, 205, 59, 4000, 1200, 2*86400)},
			want: `{"plan":"vip","membership_expires_at":"2026-11-01T00:00:00Z","quota_applies":true,"windows":[` +
				`{"window":"24h","limit":200,"used":200,"remaining":0,"resets_in_seconds":59},` +
				`{"window":"30d","limit":4000,"used":1200,"remaining":2800,"resets_in_seconds":172800}],` +
				`"counts_toward_quota":false,"summary":"VIP plan. 24-hour window: 0 of 200 tool calls left, resets in under a minute. ` +
				`30-day window: 2,800 of 4,000 left, resets in 2d. Tool calls are paused until the 24-hour window resets. ` +
				`Checking quota does not use any.","manage_url":"https://aigcnews.cn/membership"}`,
		},
		{
			name:     "free-monthly-exhausted",
			identity: free,
			status: ratelimit.QuotaStatus{Tier: authn.TierFree, UsageKnown: true,
				Windows: quotaWindows(10, 10, 3600, 200, 200, 3*86400+60)},
			want: `{"plan":"free","membership_expires_at":null,"quota_applies":true,"windows":[` +
				`{"window":"24h","limit":10,"used":10,"remaining":0,"resets_in_seconds":3600},` +
				`{"window":"30d","limit":200,"used":200,"remaining":0,"resets_in_seconds":259260}],` +
				`"counts_toward_quota":false,"summary":"Free plan. 24-hour window: 0 of 10 tool calls left, resets in 1h. ` +
				`30-day window: 0 of 200 left, resets in 3d. Tool calls are paused until the 30-day window resets. ` +
				`VIP raises the limits to 200 per 24 hours and 4,000 per 30 days: https://aigcnews.cn/membership. ` +
				`Checking quota does not use any.","manage_url":"https://aigcnews.cn/membership"}`,
		},
		{
			name:     "windows-not-started",
			identity: free,
			status:   ratelimit.QuotaStatus{Tier: authn.TierFree, UsageKnown: true, Windows: quotaWindows(10, 0, 0, 200, 0, 0)},
			want: `{"plan":"free","membership_expires_at":null,"quota_applies":true,"windows":[` +
				`{"window":"24h","limit":10,"used":0,"remaining":10,"resets_in_seconds":null},` +
				`{"window":"30d","limit":200,"used":0,"remaining":200,"resets_in_seconds":null}],` +
				`"counts_toward_quota":false,"summary":"Free plan. 24-hour window: 10 of 10 tool calls left; it starts with your next tool call. ` +
				`30-day window: 200 of 200 left; it starts with your next tool call. VIP raises the limits to 200 per 24 hours and ` +
				`4,000 per 30 days: https://aigcnews.cn/membership. Checking quota does not use any.","manage_url":"https://aigcnews.cn/membership"}`,
		},
		{
			name:     "usage-unavailable",
			identity: free,
			status:   ratelimit.QuotaStatus{Tier: authn.TierFree, Windows: quotaWindows(10, 0, 0, 200, 0, 0)},
			want: `{"plan":"free","membership_expires_at":null,"quota_applies":true,"windows":[` +
				`{"window":"24h","limit":10,"used":null,"remaining":null,"resets_in_seconds":null},` +
				`{"window":"30d","limit":200,"used":null,"remaining":null,"resets_in_seconds":null}],` +
				`"counts_toward_quota":false,"summary":"Free plan: up to 10 tool calls per 24 hours and 200 per 30 days. ` +
				`Live usage is temporarily unavailable; try again shortly. VIP raises the limits to 200 per 24 hours and ` +
				`4,000 per 30 days: https://aigcnews.cn/membership. Checking quota does not use any.","manage_url":"https://aigcnews.cn/membership"}`,
		},
		{
			name:     "admin-exempt",
			identity: authn.Identity{UserID: 1, Role: "admin", MembershipTier: authn.TierMember},
			status:   ratelimit.QuotaStatus{Tier: authn.TierMember, Exempt: true, Windows: quotaWindows(200, 0, 0, 4000, 0, 0)},
			want: `{"plan":"vip","membership_expires_at":null,"quota_applies":false,"windows":[],"counts_toward_quota":false,` +
				`"summary":"VIP plan; this admin account is exempt from the 24-hour and 30-day tool-call quotas. ` +
				`Only the per-minute burst limit applies.","manage_url":"https://aigcnews.cn/membership"}`,
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			reader := &quotaReaderStub{status: tc.status}
			result, err := NewQuotaService(reader, "https://aigcnews.cn").Get(tc.identity, nil)
			if err != nil {
				t.Fatal(err)
			}
			if got := string(jsonx.MustMarshalCompact(result)); got != tc.want {
				t.Fatalf("result\n got %s\nwant %s", got, tc.want)
			}
			if reader.calls != 1 || reader.seen.UserID != tc.identity.UserID {
				t.Fatalf("reader calls=%d identity=%+v", reader.calls, reader.seen)
			}
		})
	}
}

func TestQuotaManageURLFollowsPublicBase(t *testing.T) {
	reader := &quotaReaderStub{status: ratelimit.QuotaStatus{Tier: authn.TierMember, UsageKnown: true,
		Windows: quotaWindows(200, 1, 60, 4000, 1, 60)}}
	for base, want := range map[string]string{"": "https://aigcnews.cn/membership", "https://aigcradar.online": "https://aigcradar.online/membership"} {
		result, err := NewQuotaService(reader, base).Get(authn.Identity{UserID: 7}, map[string]any{})
		if err != nil {
			t.Fatal(err)
		}
		if got := result.(jsonx.Object)[6]; got.Key != "manage_url" || got.Value != want {
			t.Fatalf("base %q: %v", base, got)
		}
	}
}

func TestQuotaFormatting(t *testing.T) {
	for n, want := range map[int64]string{0: "0", 999: "999", 1000: "1,000", 4000: "4,000", 1234567: "1,234,567"} {
		if got := groupDigits(n); got != want {
			t.Errorf("groupDigits(%d) = %q, want %q", n, got, want)
		}
	}
	for seconds, want := range map[int64]string{
		0: "under a minute", 59: "under a minute", 60: "1m", 3599: "59m", 3600: "1h", 3660: "1h 1m",
		86400: "1d", 90000: "1d 1h", 2592000: "30d",
	} {
		if got := formatQuotaDuration(seconds); got != want {
			t.Errorf("formatQuotaDuration(%d) = %q, want %q", seconds, got, want)
		}
	}
}

// 线上形状（Red：MCP wire）：只在认证会话的 tools/list 末尾出现，只读、无参数。
func TestQuotaToolIsListedLastForAuthenticatedSessionsOnly(t *testing.T) {
	for _, authenticated := range []bool{false, true} {
		body := string(jsonx.MustMarshalCompact(ToolsList(authenticated)))
		if strings.Contains(body, `"name":"get_my_quota"`) != authenticated {
			t.Fatalf("authenticated=%v listing mismatch", authenticated)
		}
	}
	var listed struct {
		Tools []struct {
			Name        string         `json:"name"`
			Annotations map[string]any `json:"annotations"`
			InputSchema map[string]any `json:"inputSchema"`
		} `json:"tools"`
	}
	if err := json.Unmarshal(jsonx.MustMarshalCompact(ToolsList(true)), &listed); err != nil {
		t.Fatal(err)
	}
	last := listed.Tools[len(listed.Tools)-1]
	if last.Name != QuotaToolName || last.Annotations["readOnlyHint"] != true || last.Annotations["destructiveHint"] != false ||
		last.Annotations["openWorldHint"] != false {
		t.Fatalf("quota tool listing=%+v", last)
	}
	properties, ok := last.InputSchema["properties"].(map[string]any)
	if !ok || len(properties) != 0 || last.InputSchema["additionalProperties"] != false {
		t.Fatalf("quota tool must take no arguments: %+v", last.InputSchema)
	}
}

// ── HTTP 接线：额度查询只过分钟桶，额度用尽仍可调用 ─────────────────────────

const (
	quotaCallBody  = `{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"get_my_quota","arguments":{}}}`
	quotaDailyKey  = "ratelimit:mcp.quota.daily:user:42"
	quotaMonthKey  = "ratelimit:mcp.quota.monthly:user:42"
	quotaBurstKey  = "ratelimit:mcp.tool_call:user:42"
	quotaTestUser  = 42
	quotaTestLimit = "10"
)

func newQuotaHandler(t *testing.T, register bool, identity authn.Identity, authenticated bool) (*Handler, *miniredis.Miniredis) {
	t.Helper()
	mr := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	t.Cleanup(func() { _ = client.Close() })
	limiter := ratelimit.NewLimiter(ratelimit.GoRedis{Client: client}, "")
	app := newApp()
	if register {
		app.RegisterIdentityTool(QuotaToolName, NewQuotaService(limiter, "https://aigcnews.cn").Get)
	}
	auth := &stubAuthenticator{identity: identity, authenticated: authenticated}
	return NewHandler(app, auth, limiter), mr
}

func TestHandlerQuotaToolBypassesExhaustedQuota(t *testing.T) {
	user := authn.Identity{UserID: quotaTestUser, Role: "user", MembershipTier: authn.TierFree}
	handler, mr := newQuotaHandler(t, true, user, true)
	if err := mr.Set(quotaDailyKey, quotaTestLimit); err != nil {
		t.Fatal(err)
	}
	mr.SetTTL(quotaDailyKey, 2*time.Hour)

	// 普通工具调用被 24 小时配额拒绝（并照常计数）。
	if rec := postFrom(t, handler, toolCallBody, "", ""); rec.Code != http.StatusTooManyRequests {
		t.Fatalf("counted call status %d body %s", rec.Code, rec.Body)
	}
	rec := postFrom(t, handler, quotaCallBody, "", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("quota call status %d body %s", rec.Code, rec.Body)
	}
	var envelope struct {
		Result struct {
			IsError           bool `json:"isError"`
			StructuredContent struct {
				Plan    string `json:"plan"`
				Windows []struct {
					Window          string `json:"window"`
					Remaining       *int64 `json:"remaining"`
					ResetsInSeconds *int64 `json:"resets_in_seconds"`
				} `json:"windows"`
			} `json:"structuredContent"`
		} `json:"result"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &envelope); err != nil {
		t.Fatal(err)
	}
	content := envelope.Result.StructuredContent
	if envelope.Result.IsError || content.Plan != "free" || len(content.Windows) != 2 {
		t.Fatalf("quota result = %s", rec.Body)
	}
	daily := content.Windows[0]
	if daily.Window != "24h" || daily.Remaining == nil || *daily.Remaining != 0 ||
		daily.ResetsInSeconds == nil || *daily.ResetsInSeconds != 7200 {
		t.Fatalf("daily window = %s", rec.Body)
	}
	if got, _ := mr.Get(quotaDailyKey); got != "11" {
		t.Fatalf("daily = %q, want 11 (only the rejected counted call increments it)", got)
	}
	if mr.Exists(quotaMonthKey) {
		t.Fatal("quota call must not open the 30-day window")
	}
	if got, _ := mr.Get(quotaBurstKey); got != "2" {
		t.Fatalf("burst = %q, want 2 (the quota call still counts against the per-minute bucket)", got)
	}
}

// 未注册时不豁免：借名调用照常过完整限流。
func TestHandlerQuotaExemptionRequiresRegisteredTool(t *testing.T) {
	user := authn.Identity{UserID: quotaTestUser, Role: "user", MembershipTier: authn.TierFree}
	handler, mr := newQuotaHandler(t, false, user, true)
	if err := mr.Set(quotaDailyKey, quotaTestLimit); err != nil {
		t.Fatal(err)
	}
	mr.SetTTL(quotaDailyKey, time.Hour)
	if rec := postFrom(t, handler, quotaCallBody, "", ""); rec.Code != http.StatusTooManyRequests {
		t.Fatalf("unregistered quota tool status %d body %s", rec.Code, rec.Body)
	}
}

// 匿名调用得到认证提示，不开匿名 24 小时配额窗口。
func TestHandlerQuotaToolAnonymous(t *testing.T) {
	handler, mr := newQuotaHandler(t, true, authn.Identity{}, false)
	rec := postFrom(t, handler, quotaCallBody, "192.0.2.7:4000", "")
	want := `{"jsonrpc":"2.0","id":5,"result":{"content":[{"type":"text","text":"{\"error\": \"Authentication is required for this tool.\"}"}],"isError":true}}`
	if rec.Code != http.StatusOK || rec.Body.String() != want {
		t.Fatalf("status %d body %s", rec.Code, rec.Body)
	}
	if mr.Exists("ratelimit:mcp.quota.daily:ip:192.0.2.7") {
		t.Fatal("anonymous quota call must not consume the anonymous daily quota")
	}
}
