package ratelimit

import (
	"context"
	"errors"
	"slices"
	"testing"
	"time"

	"aigcnews/mcp-go/internal/authn"
)

// 只读配额查询（QuotaStatus）与只过分钟桶的 EnforceBurst。

const (
	freeDailyKey   = KeyPrefix + QuotaDailyBucket + ":user:7"
	freeMonthlyKey = KeyPrefix + QuotaMonthlyBucket + ":user:7"
)

var freeUser = authn.Identity{UserID: 7, Role: "user", MembershipTier: authn.TierFree}

func TestQuotaStatusReadsWithoutConsuming(t *testing.T) {
	mr, rdb := newRedisPair(t)
	limiter := NewLimiter(rdb, "")
	ctx := context.Background()
	for range 3 {
		if exceeded := limiter.Enforce(ctx, "tools/call", freeUser, anonymousRequest()); exceeded != nil {
			t.Fatalf("setup call rejected: %+v", exceeded)
		}
	}
	mr.FastForward(time.Hour)
	keys := mr.Keys()
	dailyTTL, monthlyTTL := mr.TTL(freeDailyKey), mr.TTL(freeMonthlyKey)

	var status QuotaStatus
	for range 5 {
		status = limiter.QuotaStatus(ctx, freeUser, time.Now())
	}
	if !slices.Equal(mr.Keys(), keys) {
		t.Fatalf("QuotaStatus created or removed keys: %v -> %v", keys, mr.Keys())
	}
	for key, want := range map[string]string{freeDailyKey: "3", freeMonthlyKey: "3"} {
		if got, _ := mr.Get(key); got != want {
			t.Fatalf("%s = %q after status reads, want %q", key, got, want)
		}
	}
	if mr.TTL(freeDailyKey) != dailyTTL || mr.TTL(freeMonthlyKey) != monthlyTTL {
		t.Fatal("QuotaStatus must not refresh window TTLs")
	}

	if status.Tier != authn.TierFree || status.Exempt || !status.UsageKnown {
		t.Fatalf("status = %+v", status)
	}
	want := []QuotaWindow{
		{Scope: "daily", WindowSeconds: QuotaDailyWindowSeconds, Limit: 10, Used: 3, ResetsIn: QuotaDailyWindowSeconds - 3600},
		{Scope: "monthly", WindowSeconds: QuotaMonthlyWindowSeconds, Limit: 200, Used: 3, ResetsIn: QuotaMonthlyWindowSeconds - 3600},
	}
	if !slices.Equal(status.Windows, want) {
		t.Fatalf("windows = %+v, want %+v", status.Windows, want)
	}
}

func TestQuotaStatusUsesEffectiveTier(t *testing.T) {
	_, rdb := newRedisPair(t)
	limiter := NewLimiter(rdb, "")
	now := time.Date(2026, 10, 10, 12, 0, 0, 0, time.UTC)
	future, past := now.Add(24*time.Hour), now.Add(-time.Second)
	cases := []struct {
		name                string
		identity            authn.Identity
		tier                string
		dailyLimit, monthly int64
	}{
		{"member", authn.Identity{UserID: 7, MembershipTier: authn.TierMember, MembershipExpiresAt: &future}, authn.TierMember, 200, 4000},
		{"lifetime-member", authn.Identity{UserID: 7, MembershipTier: authn.TierMember}, authn.TierMember, 200, 4000},
		{"expired-member", authn.Identity{UserID: 7, MembershipTier: authn.TierMember, MembershipExpiresAt: &past}, authn.TierFree, 10, 200},
		{"unknown-tier", authn.Identity{UserID: 7, MembershipTier: "gold"}, authn.TierFree, 10, 200},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			status := limiter.QuotaStatus(context.Background(), tc.identity, now)
			if status.Tier != tc.tier || status.Windows[0].Limit != tc.dailyLimit || status.Windows[1].Limit != tc.monthly {
				t.Fatalf("status = %+v", status)
			}
		})
	}
}

// 键不存在 = 窗口未开始：用量 0、无重置时间，且查询不开窗。
func TestQuotaStatusMissingKeysMeansWindowNotStarted(t *testing.T) {
	mr, rdb := newRedisPair(t)
	status := NewLimiter(rdb, "").QuotaStatus(context.Background(), freeUser, time.Now())
	if !status.UsageKnown {
		t.Fatal("empty Redis is still a successful read")
	}
	for _, window := range status.Windows {
		if window.Used != 0 || window.ResetsIn != 0 {
			t.Fatalf("window = %+v, want unused and not started", window)
		}
	}
	if keys := mr.Keys(); len(keys) != 0 {
		t.Fatalf("status read created keys: %v", keys)
	}
}

// 无过期残键：计数照报，没有可报告的重置时间（下一次计数调用重新武装）。
func TestQuotaStatusResidualKeyWithoutTTL(t *testing.T) {
	mr, rdb := newRedisPair(t)
	if err := mr.Set(freeDailyKey, "4"); err != nil {
		t.Fatal(err)
	}
	status := NewLimiter(rdb, "").QuotaStatus(context.Background(), freeUser, time.Now())
	if daily := status.Windows[0]; !status.UsageKnown || daily.Used != 4 || daily.ResetsIn != 0 {
		t.Fatalf("status = %+v", status)
	}
	if mr.TTL(freeDailyKey) != 0 {
		t.Fatal("status read must not arm the residual key")
	}
}

func TestQuotaStatusAdminIsExempt(t *testing.T) {
	mr, rdb := newRedisPair(t)
	if err := mr.Set(KeyPrefix+QuotaDailyBucket+":user:1", "9"); err != nil {
		t.Fatal(err)
	}
	status := NewLimiter(rdb, "").QuotaStatus(context.Background(), authn.Identity{UserID: 1, Role: "admin"}, time.Now())
	if !status.Exempt || status.UsageKnown {
		t.Fatalf("admin status = %+v, want exempt without usage", status)
	}
}

// getErrRedis 实现 Reader，按注入点让 GET 或 TTL 失败。
type getErrRedis struct {
	errRedis
	getErr error
}

func (r getErrRedis) Get(context.Context, string) (int64, error) { return 3, r.getErr }

func TestQuotaStatusReportsLimitsWhenUsageUnavailable(t *testing.T) {
	boom := errors.New("redis boom")
	cases := []struct {
		name    string
		limiter *Limiter
	}{
		{"nil-limiter", nil},
		{"no-redis", NewLimiter(nil, "")},
		{"counter-without-get", NewLimiter(errRedis{}, "")},
		{"get-error", NewLimiter(getErrRedis{getErr: boom}, "")},
		{"ttl-error", NewLimiter(getErrRedis{errRedis: errRedis{ttlErr: boom}}, "")},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			status := tc.limiter.QuotaStatus(context.Background(), freeUser, time.Now())
			if status.UsageKnown || status.Tier != authn.TierFree {
				t.Fatalf("status = %+v, want limits only", status)
			}
			if status.Windows[0].Limit != 10 || status.Windows[1].Limit != 200 ||
				status.Windows[0].Used != 0 || status.Windows[1].Used != 0 {
				t.Fatalf("windows = %+v", status.Windows)
			}
		})
	}
}

func TestQuotaStatusNonIntegerCounterIsUnavailable(t *testing.T) {
	mr, rdb := newRedisPair(t)
	if err := mr.Set(freeDailyKey, "not-a-number"); err != nil {
		t.Fatal(err)
	}
	if status := NewLimiter(rdb, "").QuotaStatus(context.Background(), freeUser, time.Now()); status.UsageKnown {
		t.Fatalf("status = %+v, want usage unavailable", status)
	}
}

func TestTierQuotaLimitsNilSafe(t *testing.T) {
	var limiter *Limiter
	if daily, monthly := limiter.TierQuotaLimits(authn.TierMember); daily != 200 || monthly != 4000 {
		t.Fatalf("member limits = %d/%d", daily, monthly)
	}
	if daily, monthly := limiter.TierQuotaLimits("unknown"); daily != 10 || monthly != 200 {
		t.Fatalf("fallback limits = %d/%d", daily, monthly)
	}
}

// EnforceBurst 只计分钟桶：配额已用尽也放行，且不再给配额桶计数。
func TestEnforceBurstSkipsQuotaBuckets(t *testing.T) {
	mr, rdb := newRedisPair(t)
	limiter := NewLimiter(rdb, "", func(l *Limits) { l.AuthenticatedToolCallPerMinute = 2 })
	ctx := context.Background()
	if err := mr.Set(freeDailyKey, "10"); err != nil {
		t.Fatal(err)
	}
	mr.SetTTL(freeDailyKey, time.Hour)
	if exceeded := limiter.Enforce(ctx, "tools/call", freeUser, anonymousRequest()); exceeded == nil || !exceeded.Quota {
		t.Fatalf("exhausted daily quota must reject a counted call, got %+v", exceeded)
	}
	if exceeded := limiter.EnforceBurst(ctx, "tools/call", freeUser, anonymousRequest()); exceeded != nil {
		t.Fatalf("burst-only call must pass an exhausted quota, got %+v", exceeded)
	}
	if got, _ := mr.Get(freeDailyKey); got != "11" {
		t.Fatalf("daily = %q, want 11 (only the counted call increments it)", got)
	}
	if mr.Exists(freeMonthlyKey) {
		t.Fatal("burst-only call must not touch the 30-day bucket")
	}
	exceeded := limiter.EnforceBurst(ctx, "tools/call", freeUser, anonymousRequest())
	if exceeded == nil || exceeded.Quota || exceeded.RetryAfter != WindowSeconds {
		t.Fatalf("third call in the minute must hit the burst bucket, got %+v", exceeded)
	}
}

func TestEnforceBurstDisabledWithoutRedis(t *testing.T) {
	var limiter *Limiter
	if exceeded := limiter.EnforceBurst(context.Background(), "tools/call", freeUser, anonymousRequest()); exceeded != nil {
		t.Fatalf("nil limiter must allow, got %+v", exceeded)
	}
	if exceeded := NewLimiter(nil, "").EnforceBurst(context.Background(), "tools/call", freeUser, anonymousRequest()); exceeded != nil {
		t.Fatalf("nil redis must allow, got %+v", exceeded)
	}
}
