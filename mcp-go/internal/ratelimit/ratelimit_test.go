package ratelimit

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strconv"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/redis/go-redis/v9"

	"aigcnews/mcp-go/internal/authn"
)

// newRedisPair 起 miniredis 并接出真实 go-redis client 的适配器。
func newRedisPair(t *testing.T) (*miniredis.Miniredis, Redis) {
	t.Helper()
	mr := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	t.Cleanup(func() { _ = client.Close() })
	return mr, GoRedis{Client: client}
}

// anonymousRequest 构造直连对端为公网 IP 的请求（不进可信代理分支，
// ClientIP 归因为 192.0.2.1）。
func anonymousRequest() *http.Request {
	r := httptest.NewRequest(http.MethodPost, "/api/mcp", nil)
	r.RemoteAddr = "192.0.2.1:1234"
	return r
}

func TestEnforceDisabledWithoutRedis(t *testing.T) {
	limiter := NewLimiter(nil, "")
	if exceeded := limiter.Enforce(context.Background(), "tools/call", authn.Identity{}, anonymousRequest()); exceeded != nil {
		t.Fatalf("nil redis must disable the limiter, got %+v", exceeded)
	}
}

func TestEnforceAnonymousProtocolBurstBucket(t *testing.T) {
	mr, rdb := newRedisPair(t)
	limiter := NewLimiter(rdb, "127.0.0.1,::1")
	ctx := context.Background()
	for i := int64(1); i <= 60; i++ {
		if exceeded := limiter.Enforce(ctx, "initialize", authn.Identity{}, anonymousRequest()); exceeded != nil {
			t.Fatalf("hit %d should pass, got %+v", i, exceeded)
		}
	}
	exceeded := limiter.Enforce(ctx, "initialize", authn.Identity{}, anonymousRequest())
	if exceeded == nil {
		t.Fatal("61st hit should be rejected")
	}
	if exceeded.Quota {
		t.Fatal("burst bucket must report Quota=false")
	}
	if exceeded.RetryAfter != WindowSeconds {
		t.Fatalf("RetryAfter = %d, want %d", exceeded.RetryAfter, WindowSeconds)
	}
	// 键与计数断言：键形 ratelimit:<bucket>:<identity>。
	key := "ratelimit:mcp.protocol:ip:192.0.2.1"
	if value, err := mr.Get(key); err != nil || value != "61" {
		t.Fatalf("key %s = %q, %v; want %q", key, value, err, "61")
	}
	if ttl := mr.TTL(key); ttl != WindowSeconds*time.Second {
		t.Fatalf("key %s TTL = %v, want %v", key, ttl, WindowSeconds*time.Second)
	}
	// 非 tools/call 不产生配额键。
	if mr.Exists("ratelimit:mcp.quota.daily:ip:192.0.2.1") {
		t.Fatal("protocol methods must not consume quota")
	}
}

// 默认额度与 REST 侧 backend/app/services/api_access/quota.py 同值即同池；
// Python 侧 SharedPoolContract 直接解析本文件的 defaultLimits() 反向核对，
// 任一侧单独改额度都会显红。
func TestDefaultLimitsMatchSharedPool(t *testing.T) {
	want := Limits{
		AnonymousProtocolPerMinute:     60,
		AnonymousToolCallPerMinute:     30,
		AuthenticatedProtocolPerMinute: 240,
		AuthenticatedToolCallPerMinute: 120,
		AnonymousDailyToolCallQuota:    5,
		FreeDailyToolCallQuota:         10,
		FreeMonthlyToolCallQuota:       400,
		MemberDailyToolCallQuota:       200,
		MemberMonthlyToolCallQuota:     8000,
	}
	if got := defaultLimits(); got != want {
		t.Fatalf("defaultLimits() = %+v, want %+v", got, want)
	}
}

func TestEnforceToolCallBurstBucketLimits(t *testing.T) {
	cases := []struct {
		name     string
		identity authn.Identity
		limit    int64
		key      string
		quotaKey string
	}{
		{"anonymous-30", authn.Identity{}, 30,
			"ratelimit:mcp.tool_call:ip:192.0.2.1", "ratelimit:mcp.quota.daily:ip:192.0.2.1"},
		{"authenticated-120", authn.Identity{UserID: 5, Role: "user"}, 120,
			"ratelimit:mcp.tool_call:user:5", "ratelimit:mcp.quota.monthly:user:5"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			mr, rdb := newRedisPair(t)
			// 拉高配额桶（含登录档日 pacing 桶），让分钟桶成为唯一约束面。
			limiter := NewLimiter(rdb, "", func(l *Limits) {
				l.AnonymousDailyToolCallQuota = 100000
				l.FreeDailyToolCallQuota = 100000
				l.FreeMonthlyToolCallQuota = 100000
			})
			ctx := context.Background()
			for i := int64(1); i <= tc.limit; i++ {
				if exceeded := limiter.Enforce(ctx, "tools/call", tc.identity, anonymousRequest()); exceeded != nil {
					t.Fatalf("hit %d should pass, got %+v", i, exceeded)
				}
			}
			exceeded := limiter.Enforce(ctx, "tools/call", tc.identity, anonymousRequest())
			if exceeded == nil || exceeded.Quota {
				t.Fatalf("hit %d should hit burst bucket, got %+v", tc.limit+1, exceeded)
			}
			wantCount := strconv.FormatInt(tc.limit+1, 10)
			if value, err := mr.Get(tc.key); err != nil || value != wantCount {
				t.Fatalf("key %s = %q, %v; want %q", tc.key, value, err, wantCount)
			}
			// 被分钟桶 429 的请求不消耗配额：配额键停在 limit。
			if value, err := mr.Get(tc.quotaKey); err != nil || value != strconv.FormatInt(tc.limit, 10) {
				t.Fatalf("quota key %s = %q, %v; want %d (burst-rejected hit must not consume quota)",
					tc.quotaKey, value, err, tc.limit)
			}
		})
	}
}

func TestAnonymousAndAuthenticatedBucketsAreIsolated(t *testing.T) {
	mr, rdb := newRedisPair(t)
	limiter := NewLimiter(rdb, "", func(l *Limits) {
		l.AnonymousToolCallPerMinute = 1
		l.AuthenticatedToolCallPerMinute = 1
		l.AnonymousDailyToolCallQuota = 1
		l.FreeDailyToolCallQuota = 1
		l.FreeMonthlyToolCallQuota = 100
	})
	anonymous := authn.Identity{}
	authenticated := authn.Identity{UserID: 7, Role: "user", MembershipTier: authn.TierFree}
	ctx := context.Background()
	if exceeded := limiter.Enforce(ctx, "tools/call", anonymous, anonymousRequest()); exceeded != nil {
		t.Fatalf("anonymous first call should pass: %+v", exceeded)
	}
	if exceeded := limiter.Enforce(ctx, "tools/call", authenticated, anonymousRequest()); exceeded != nil {
		t.Fatalf("authenticated first call should pass despite same IP: %+v", exceeded)
	}
	if value, err := mr.Get("ratelimit:mcp.tool_call:ip:192.0.2.1"); err != nil || value != "1" {
		t.Fatalf("anonymous burst bucket = %q, %v", value, err)
	}
	if value, err := mr.Get("ratelimit:mcp.tool_call:user:7"); err != nil || value != "1" {
		t.Fatalf("authenticated burst bucket = %q, %v", value, err)
	}
	if value, err := mr.Get("ratelimit:mcp.quota.daily:ip:192.0.2.1"); err != nil || value != "1" {
		t.Fatalf("anonymous quota bucket = %q, %v", value, err)
	}
	if value, err := mr.Get("ratelimit:mcp.quota.daily:user:7"); err != nil || value != "1" {
		t.Fatalf("authenticated quota bucket = %q, %v", value, err)
	}
}

func TestEnforceAnonymousDailyQuota(t *testing.T) {
	mr, rdb := newRedisPair(t)
	// 拉高分钟桶，让日配额成为约束面。
	limiter := NewLimiter(rdb, "", func(l *Limits) {
		l.AnonymousToolCallPerMinute = 1000
	})
	ctx := context.Background()
	for i := int64(1); i <= 5; i++ {
		if exceeded := limiter.Enforce(ctx, "tools/call", authn.Identity{}, anonymousRequest()); exceeded != nil {
			t.Fatalf("call %d should pass, got %+v", i, exceeded)
		}
	}
	exceeded := limiter.Enforce(ctx, "tools/call", authn.Identity{}, anonymousRequest())
	if exceeded == nil {
		t.Fatal("6th call should be rejected")
	}
	if !exceeded.Quota || exceeded.QuotaScope != "daily" {
		t.Fatalf("6th call should hit daily quota, got %+v", exceeded)
	}
	if exceeded.Tier != authn.TierFree || exceeded.Limit != 5 {
		t.Fatalf("daily quota should report tier=free limit=5, got %+v", exceeded)
	}
	if exceeded.IdentityKind != "ip" {
		t.Fatalf("anonymous daily quota should report identity_kind=ip, got %+v", exceeded)
	}
	// miniredis 模拟时钟不自动流逝，TTL 恰为整窗。
	if exceeded.RetryAfter != QuotaDailyWindowSeconds {
		t.Fatalf("RetryAfter = %d, want %d", exceeded.RetryAfter, QuotaDailyWindowSeconds)
	}
	key := "ratelimit:mcp.quota.daily:ip:192.0.2.1"
	if value, err := mr.Get(key); err != nil || value != "6" {
		t.Fatalf("key %s = %q, %v; want %q", key, value, err, "6")
	}
}

// 登录档日 pacing：先日桶后月桶，日桶超限后请求被拒且不再消耗月配额。
func TestEnforceDailyPacingQuotaByTier(t *testing.T) {
	future := time.Now().Add(24 * time.Hour)
	past := time.Now().Add(-24 * time.Hour)
	cases := []struct {
		name      string
		identity  authn.Identity
		wantLimit int64
		wantTier  string
	}{
		{"free", authn.Identity{UserID: 7, Role: "user", MembershipTier: authn.TierFree}, 2, authn.TierFree},
		{"member", authn.Identity{UserID: 8, Role: "user", MembershipTier: authn.TierMember, MembershipExpiresAt: &future}, 4, authn.TierMember},
		// member 已过期回落 free 档（resolve_effective_tier 语义）。
		{"member-expired", authn.Identity{UserID: 10, Role: "user", MembershipTier: authn.TierMember, MembershipExpiresAt: &past}, 2, authn.TierFree},
		// 未知档 fail-closed 按 free。
		{"tier-unknown", authn.Identity{UserID: 11, Role: "user", MembershipTier: "gold"}, 2, authn.TierFree},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			mr, rdb := newRedisPair(t)
			limiter := NewLimiter(rdb, "", func(l *Limits) {
				l.AuthenticatedToolCallPerMinute = 1000 // 拉高分钟桶
				l.FreeDailyToolCallQuota = 2
				l.MemberDailyToolCallQuota = 4
				l.FreeMonthlyToolCallQuota = 100000 // 拉高月桶，让日桶成为约束面
				l.MemberMonthlyToolCallQuota = 100000
			})
			ctx := context.Background()
			for i := int64(1); i <= tc.wantLimit; i++ {
				if exceeded := limiter.Enforce(ctx, "tools/call", tc.identity, anonymousRequest()); exceeded != nil {
					t.Fatalf("call %d should pass, got %+v", i, exceeded)
				}
			}
			exceeded := limiter.Enforce(ctx, "tools/call", tc.identity, anonymousRequest())
			if exceeded == nil {
				t.Fatal("quota+1 call should be rejected")
			}
			if !exceeded.Quota || exceeded.QuotaScope != "daily" {
				t.Fatalf("should hit daily pacing quota, got %+v", exceeded)
			}
			if exceeded.Tier != tc.wantTier || exceeded.Limit != tc.wantLimit {
				t.Fatalf("tier/limit = %s/%d, want %s/%d", exceeded.Tier, exceeded.Limit, tc.wantTier, tc.wantLimit)
			}
			if exceeded.IdentityKind != "user" {
				t.Fatalf("authenticated daily quota should report identity_kind=user, got %+v", exceeded)
			}
			if exceeded.RetryAfter != QuotaDailyWindowSeconds {
				t.Fatalf("RetryAfter = %d, want %d", exceeded.RetryAfter, QuotaDailyWindowSeconds)
			}
			// 被日桶拒绝的请求不消耗月配额：月度键停在日限额。
			monthlyKey := "ratelimit:" + QuotaMonthlyBucket + ":user:" + strconv.Itoa(tc.identity.UserID)
			if value, err := mr.Get(monthlyKey); err != nil || value != strconv.FormatInt(tc.wantLimit, 10) {
				t.Fatalf("monthly key %s = %q, %v; want %d (daily-rejected hit must not consume monthly quota)",
					monthlyKey, value, err, tc.wantLimit)
			}
		})
	}
}

func TestEnforceMonthlyQuotaByTier(t *testing.T) {
	future := time.Now().Add(24 * time.Hour)
	past := time.Now().Add(-24 * time.Hour)
	cases := []struct {
		name      string
		identity  authn.Identity
		wantLimit int64
		wantTier  string
	}{
		{"free", authn.Identity{UserID: 7, Role: "user", MembershipTier: authn.TierFree}, 3, authn.TierFree},
		{"member", authn.Identity{UserID: 8, Role: "user", MembershipTier: authn.TierMember, MembershipExpiresAt: &future}, 5, authn.TierMember},
		// member 已过期回落 free 档（resolve_effective_tier 语义）。
		{"member-expired", authn.Identity{UserID: 10, Role: "user", MembershipTier: authn.TierMember, MembershipExpiresAt: &past}, 3, authn.TierFree},
		// 未知档 fail-closed 按 free。
		{"tier-unknown", authn.Identity{UserID: 11, Role: "user", MembershipTier: "gold"}, 3, authn.TierFree},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			_, rdb := newRedisPair(t)
			limiter := NewLimiter(rdb, "", func(l *Limits) {
				l.AuthenticatedToolCallPerMinute = 1000 // 拉高分钟桶
				l.FreeMonthlyToolCallQuota = 3
				l.MemberMonthlyToolCallQuota = 5
			})
			ctx := context.Background()
			for i := int64(1); i <= tc.wantLimit; i++ {
				if exceeded := limiter.Enforce(ctx, "tools/call", tc.identity, anonymousRequest()); exceeded != nil {
					t.Fatalf("call %d should pass, got %+v", i, exceeded)
				}
			}
			exceeded := limiter.Enforce(ctx, "tools/call", tc.identity, anonymousRequest())
			if exceeded == nil {
				t.Fatal("quota+1 call should be rejected")
			}
			if !exceeded.Quota || exceeded.QuotaScope != "monthly" {
				t.Fatalf("should hit monthly quota, got %+v", exceeded)
			}
			if exceeded.Tier != tc.wantTier || exceeded.Limit != tc.wantLimit {
				t.Fatalf("tier/limit = %s/%d, want %s/%d", exceeded.Tier, exceeded.Limit, tc.wantTier, tc.wantLimit)
			}
			if exceeded.RetryAfter != QuotaMonthlyWindowSeconds {
				t.Fatalf("RetryAfter = %d, want %d", exceeded.RetryAfter, QuotaMonthlyWindowSeconds)
			}
		})
	}
}

func TestEnforceAdminExemptsQuotaButNotBurst(t *testing.T) {
	mr, rdb := newRedisPair(t)
	limiter := NewLimiter(rdb, "", func(l *Limits) {
		l.AuthenticatedToolCallPerMinute = 3
		l.FreeMonthlyToolCallQuota = 1
	})
	admin := authn.Identity{UserID: 9, Role: "admin", MembershipTier: authn.TierFree}
	ctx := context.Background()
	for i := int64(1); i <= 3; i++ {
		if exceeded := limiter.Enforce(ctx, "tools/call", admin, anonymousRequest()); exceeded != nil {
			t.Fatalf("admin hit %d should pass, got %+v", i, exceeded)
		}
	}
	// admin 不消耗配额：日/月配额键都不存在。
	if mr.Exists("ratelimit:mcp.quota.daily:user:9") {
		t.Fatal("admin must not consume daily quota")
	}
	if mr.Exists("ratelimit:mcp.quota.monthly:user:9") {
		t.Fatal("admin must not consume quota")
	}
	// 但分钟桶不豁免：第 4 次超限。
	exceeded := limiter.Enforce(ctx, "tools/call", admin, anonymousRequest())
	if exceeded == nil || exceeded.Quota {
		t.Fatalf("admin 4th hit should hit burst bucket, got %+v", exceeded)
	}
}

func TestHitSelfHealsMissingTTL(t *testing.T) {
	mr, rdb := newRedisPair(t)
	limiter := NewLimiter(rdb, "")
	key := "ratelimit:mcp.protocol:ip:192.0.2.1"
	// 复现 2026-08-14 事故形态：count>1 但键丢 TTL。
	if err := mr.Set(key, "5"); err != nil {
		t.Fatal(err)
	}
	if mr.TTL(key) != 0 {
		t.Fatalf("precondition: key must have no TTL, got %v", mr.TTL(key))
	}
	if exceeded := limiter.Enforce(context.Background(), "initialize", authn.Identity{}, anonymousRequest()); exceeded != nil {
		t.Fatalf("self-heal hit should pass, got %+v", exceeded)
	}
	if ttl := mr.TTL(key); ttl != WindowSeconds*time.Second {
		t.Fatalf("key should be re-armed with %v, got %v", WindowSeconds*time.Second, ttl)
	}
	if value, err := mr.Get(key); err != nil || value != "6" {
		t.Fatalf("key %s = %q, %v; want %q", key, value, err, "6")
	}
}

func TestEnforceFailsOpenOnRedisOutage(t *testing.T) {
	mr, rdb := newRedisPair(t)
	limiter := NewLimiter(rdb, "")
	// 关掉 miniredis 使 INCR 报连接错误：分钟桶与配额桶均 fail-open。
	mr.Close()
	if exceeded := limiter.Enforce(context.Background(), "tools/call", authn.Identity{}, anonymousRequest()); exceeded != nil {
		t.Fatalf("redis outage must fail open, got %+v", exceeded)
	}
}

// errRedis 按注入点报错，覆盖 hit 原语各阶段的 fail-open 分支。
type errRedis struct {
	incrValue int64
	incrErr   error
	ttlErr    error
	expireErr error
}

func (r errRedis) Incr(context.Context, string) (int64, error) {
	return r.incrValue, r.incrErr
}

func (r errRedis) TTL(context.Context, string) (time.Duration, error) {
	return time.Duration(-1), r.ttlErr
}

func (r errRedis) Expire(context.Context, string, time.Duration) (bool, error) {
	return false, r.expireErr
}

func TestEnforceFailsOpenPerStage(t *testing.T) {
	redisErr := errors.New("redis boom")
	cases := []struct {
		name  string
		redis Redis
	}{
		{"incr-error", errRedis{incrErr: redisErr}},
		// count>1 走 TTL 分支，TTL 报错 → 放行。
		{"ttl-error", errRedis{incrValue: 2, ttlErr: redisErr}},
		// count==1 走 EXPIRE 分支，EXPIRE 报错 → 放行。
		{"expire-error", errRedis{incrValue: 1, expireErr: redisErr}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			limiter := NewLimiter(tc.redis, "")
			if exceeded := limiter.Enforce(context.Background(), "tools/call", authn.Identity{}, anonymousRequest()); exceeded != nil {
				t.Fatalf("redis error must fail open, got %+v", exceeded)
			}
		})
	}
}

// burstFailRedis 分钟桶 INCR 报错、配额桶正常：钉住 Python 的"分钟桶故障
// 不阻断配额判定"（except Exception 之后顺序执行 _enforce_tool_call_quota，
// 配额键照常计数、超限照常 429）。
type burstFailRedis struct {
	incrCalls int
}

func (r *burstFailRedis) Incr(context.Context, string) (int64, error) {
	r.incrCalls++
	if r.incrCalls == 1 {
		return 0, errors.New("burst incr boom")
	}
	return 2, nil // 配额桶超限（override 限 1）
}

func (r *burstFailRedis) TTL(context.Context, string) (time.Duration, error) {
	return 50 * time.Second, nil
}

func (r *burstFailRedis) Expire(context.Context, string, time.Duration) (bool, error) {
	return true, nil
}

func TestEnforceBurstErrorStillChecksQuota(t *testing.T) {
	limiter := NewLimiter(&burstFailRedis{}, "", func(l *Limits) {
		l.AnonymousDailyToolCallQuota = 1
	})
	exceeded := limiter.Enforce(context.Background(), "tools/call", authn.Identity{}, anonymousRequest())
	if exceeded == nil || !exceeded.Quota || exceeded.QuotaScope != "daily" {
		t.Fatalf("burst redis error must not skip quota check, got %+v", exceeded)
	}
	if exceeded.RetryAfter != 50 {
		t.Fatalf("RetryAfter = %d, want 50 (超限键剩余 TTL)", exceeded.RetryAfter)
	}
}

// quotaTTLFailRedis 复现 quotaRetryAfter 的读取失败路径：配额桶 hit 内部
// 的 TTL 自愈检查（第 1 次 TTL 调用）必须成功才能走到超限判定；之后的
// quotaRetryAfter（第 2 次 TTL 调用）报错或返回非正值时回退整窗秒数。
type quotaTTLFailRedis struct {
	incrCalls int
	ttlCalls  int
	// secondTTL / secondTTLErr 是 quotaRetryAfter 那次 TTL 调用的结果。
	secondTTL    time.Duration
	secondTTLErr error
}

func (r *quotaTTLFailRedis) Incr(context.Context, string) (int64, error) {
	r.incrCalls++
	if r.incrCalls == 1 {
		return 1, nil // 分钟桶
	}
	return 2, nil // 配额桶超限（limit=1）
}

func (r *quotaTTLFailRedis) TTL(context.Context, string) (time.Duration, error) {
	r.ttlCalls++
	if r.ttlCalls == 1 {
		return 50 * time.Second, nil // hit 自愈检查：有 TTL，无需重新武装
	}
	return r.secondTTL, r.secondTTLErr
}

func (r *quotaTTLFailRedis) Expire(context.Context, string, time.Duration) (bool, error) {
	return true, nil
}

func TestQuotaRetryAfterFallsBack(t *testing.T) {
	cases := []struct {
		name         string
		secondTTL    time.Duration
		secondTTLErr error
	}{
		{"ttl-error", 0, errors.New("ttl boom")},
		// 键丢 TTL 时自愈已重新武装，这里覆盖 best-effort 读取到非正值
		// （如并发下键恰好过期）仍回退整窗。
		{"ttl-non-positive", time.Duration(-1), nil},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			fake := &quotaTTLFailRedis{secondTTL: tc.secondTTL, secondTTLErr: tc.secondTTLErr}
			limiter := NewLimiter(fake, "", func(l *Limits) {
				l.AnonymousDailyToolCallQuota = 1
			})
			exceeded := limiter.Enforce(context.Background(), "tools/call", authn.Identity{}, anonymousRequest())
			if exceeded == nil || !exceeded.Quota {
				t.Fatalf("should hit quota, got %+v", exceeded)
			}
			if exceeded.RetryAfter != QuotaDailyWindowSeconds {
				t.Fatalf("RetryAfter should fall back to window %d, got %d", QuotaDailyWindowSeconds, exceeded.RetryAfter)
			}
		})
	}
}
