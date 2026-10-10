// Package ratelimit 实现 /api/mcp 入站端点的 Redis 固定窗口限流；
// 配额常量与 backend/app/services/api_access/quota.py 保持一致，命中原语
// 与 backend/app/services/auth/rate_limit.py 的 hit_rate_limit 等价：
//
//   - 两层正交限速：分钟级突发桶防爬（所有方法），tools/call 再叠加
//     分层配额桶（匿名按 IP 每 24 小时 5 次；Free 按用户每 24 小时
//     10 次 + 滚动 30 天 200 次；VIP 按用户每 24 小时 200 次 + 滚动
//     30 天 4000 次；24 小时桶是 pacing 层，防脉冲烧穿长窗口额度）；
//   - 先分钟桶后配额桶，被分钟桶 429 的请求不消耗配额；
//   - admin 豁免配额（运营排查不受商业约束），但不豁免分钟桶；
//   - 除超限外任何 Redis 错误 fail-open（可用性优先于严格性）。
package ratelimit

import (
	"context"
	"log/slog"
	"net/http"
	"net/netip"
	"strconv"
	"time"

	"github.com/redis/go-redis/v9"

	"aigcnews/mcp-go/internal/authn"
)

// 与 REST 配额及认证限流常量逐字一致（api_access/quota.py + auth/rate_limit.py）。
const (
	// WindowSeconds 是分钟级突发桶窗口（MCP_RATE_LIMIT_WINDOW_SECONDS）。
	WindowSeconds = 60
	// ProtocolBucket / ToolCallBucket 是分钟级突发桶名；tools/call 单独
	// 成桶，因为工具处理器可能触达数据库或有界的 GitHub API 兜底。
	ProtocolBucket = "mcp.protocol"
	ToolCallBucket = "mcp.tool_call"
	// RateLimitedCode 是限流 429 投影的 JSON-RPC 错误码
	// （MCP_JSONRPC_RATE_LIMITED）。
	RateLimitedCode = -32000

	// QuotaDailyBucket / QuotaMonthlyBucket 是 tools/call 分层配额桶名。
	QuotaDailyBucket   = "mcp.quota.daily"
	QuotaMonthlyBucket = "mcp.quota.monthly"
	// QuotaDailyWindowSeconds / QuotaMonthlyWindowSeconds 是兼容命名：
	// 分别表示固定 86400 秒与 2592000 秒窗口，不是自然日或自然月。
	QuotaDailyWindowSeconds   = 86400
	QuotaMonthlyWindowSeconds = 2592000

	// KeyPrefix 是所有限流键的公共前缀（RATE_LIMIT_PREFIX），
	// 键形为 ratelimit:<bucket>:<identity>。
	KeyPrefix = "ratelimit:"
)

// Limits 集中九个限额常量，默认值与 Python 逐字一致；字段导出供回放
// 语料按场景覆盖（如提速测试的小配额）。
type Limits struct {
	AnonymousProtocolPerMinute     int64 // MCP_ANONYMOUS_PROTOCOL_LIMIT = 60
	AnonymousToolCallPerMinute     int64 // MCP_ANONYMOUS_TOOL_CALL_LIMIT = 30
	AuthenticatedProtocolPerMinute int64 // MCP_AUTHENTICATED_PROTOCOL_LIMIT = 240
	AuthenticatedToolCallPerMinute int64 // MCP_AUTHENTICATED_TOOL_CALL_LIMIT = 120
	AnonymousDailyToolCallQuota    int64 // MCP_ANONYMOUS_DAILY_TOOL_CALL_QUOTA = 5
	FreeDailyToolCallQuota         int64 // MCP_FREE_DAILY_TOOL_CALL_QUOTA = 10
	FreeMonthlyToolCallQuota       int64 // MCP_FREE_MONTHLY_TOOL_CALL_QUOTA = 200
	MemberDailyToolCallQuota       int64 // MCP_MEMBER_DAILY_TOOL_CALL_QUOTA = 200
	MemberMonthlyToolCallQuota     int64 // MCP_MEMBER_MONTHLY_TOOL_CALL_QUOTA = 4000
}

func defaultLimits() Limits {
	return Limits{
		AnonymousProtocolPerMinute:     60,
		AnonymousToolCallPerMinute:     30,
		AuthenticatedProtocolPerMinute: 240,
		AuthenticatedToolCallPerMinute: 120,
		AnonymousDailyToolCallQuota:    5,
		FreeDailyToolCallQuota:         10,
		FreeMonthlyToolCallQuota:       200,
		MemberDailyToolCallQuota:       200,
		MemberMonthlyToolCallQuota:     4000,
	}
}

// Redis 是限流需要的最小命令面；测试用 miniredis 起的真实 client
// 经 GoRedis 适配接入。
type Redis interface {
	Incr(ctx context.Context, key string) (int64, error)
	TTL(ctx context.Context, key string) (time.Duration, error)
	Expire(ctx context.Context, key string, window time.Duration) (bool, error)
}

// GoRedis 把 *redis.Client 适配到 Redis 命令面（go-redis 方法返回
// Cmd 类型，需要一次显式收窄为 (值, error)）。
type GoRedis struct {
	Client *redis.Client
}

func (g GoRedis) Incr(ctx context.Context, key string) (int64, error) {
	return g.Client.Incr(ctx, key).Result()
}

func (g GoRedis) TTL(ctx context.Context, key string) (time.Duration, error) {
	return g.Client.TTL(ctx, key).Result()
}

func (g GoRedis) Expire(ctx context.Context, key string, window time.Duration) (bool, error) {
	return g.Client.Expire(ctx, key, window).Result()
}

// Limiter 按请求执行两层限流；redis 为 nil 时整体禁用（Enforce 直接
// 放行，对齐 Python 侧 app.state.redis 缺失的早期返回）。
type Limiter struct {
	redis   Redis
	limits  Limits
	trusted []netip.Prefix
	logger  *slog.Logger
}

// NewLimiter 构造 Limiter。trustedProxyRaw 形如
// "127.0.0.1,::1,172.16.0.0/12"（解析规则见 parseTrustedProxies）；
// overrides 逐项改写默认限额。
func NewLimiter(r Redis, trustedProxyRaw string, overrides ...func(*Limits)) *Limiter {
	limits := defaultLimits()
	for _, override := range overrides {
		override(&limits)
	}
	return &Limiter{
		redis:   r,
		limits:  limits,
		trusted: parseTrustedProxies(trustedProxyRaw),
		logger:  slog.Default(),
	}
}

// ClientIP 按本限流器的可信代理配置解析请求来源 IP；nil 限流器只认直连对端。
func (l *Limiter) ClientIP(r *http.Request) string {
	if l == nil {
		return ClientIP(r, nil)
	}
	return ClientIP(r, l.trusted)
}

// Enforce 为本次请求消费一发额度；返回 nil 表示放行，非 nil 表示超限。
// 语义严格按 Python enforce_mcp_rate_limit 的顺序：分钟桶 →（tools/call
// 且非 admin）配额桶；被分钟桶 429 的请求不消耗配额。
func (l *Limiter) Enforce(ctx context.Context, method string, id authn.Identity, r *http.Request) *Exceeded {
	if l == nil || l.redis == nil {
		return nil
	}

	// 1. 分钟级突发桶：tools/call 独立成桶，认证按用户、匿名按 IP。
	bucket := ProtocolBucket
	anonymousLimit := l.limits.AnonymousProtocolPerMinute
	authenticatedLimit := l.limits.AuthenticatedProtocolPerMinute
	if method == "tools/call" {
		bucket = ToolCallBucket
		anonymousLimit = l.limits.AnonymousToolCallPerMinute
		authenticatedLimit = l.limits.AuthenticatedToolCallPerMinute
	}
	var identity string
	limit := anonymousLimit
	if id.UserID > 0 {
		identity = "user:" + strconv.Itoa(id.UserID)
		limit = authenticatedLimit
	} else {
		identity = "ip:" + ClientIP(r, l.trusted)
	}
	exceeded, err := l.hit(ctx, bucket, identity, limit, WindowSeconds*time.Second)
	if err != nil {
		// Python 同款 fail-open：分钟桶 Redis 故障只记日志，不提前返回——
		// 配额桶判定仍继续（enforce_mcp_rate_limit 的 except Exception 分支
		// 之后顺序执行 _enforce_tool_call_quota）。
		l.logger.Warn("MCP rate limit skipped: redis unavailable", "error", err)
	} else if exceeded {
		return &Exceeded{Quota: false, RetryAfter: WindowSeconds}
	}

	// 2. 非 tools/call 或 admin → 放行（admin 豁免配额但不豁免分钟桶）。
	if method != "tools/call" || id.Role == "admin" {
		return nil
	}

	// 3. tools/call 分层配额桶：认证按用户先检查固定 24 小时 pacing 桶，
	// 再检查滚动 30 天商业额度桶（档位取生效档，未知档 fail-closed 按
	// free；被短窗口拒绝的请求不再消耗长窗口额度）；匿名按 IP 仅使用
	// 固定 24 小时配额（按免费档口径报告）。配额是商业
	// 软约束而非安全边界：固定窗口 + INCR 在并发下可能瞬时超 1，与
	// Python 同口径，可接受。
	if id.UserID > 0 {
		tier := id.EffectiveTier(time.Now())
		quotaIdentity := "user:" + strconv.Itoa(id.UserID)
		// 3.1 固定 24 小时 pacing 桶（与匿名同桶不同键）
		dailyLimit := l.limits.FreeDailyToolCallQuota
		if tier == authn.TierMember {
			dailyLimit = l.limits.MemberDailyToolCallQuota
		}
		if exceeded := l.enforceQuotaBucket(
			ctx, QuotaDailyBucket, quotaIdentity, QuotaDailyWindowSeconds,
			"daily", tier, dailyLimit, "user",
		); exceeded != nil {
			return exceeded
		}
		// 3.2 滚动 30 天商业额度桶
		monthlyLimit := l.limits.FreeMonthlyToolCallQuota
		if tier == authn.TierMember {
			monthlyLimit = l.limits.MemberMonthlyToolCallQuota
		}
		return l.enforceQuotaBucket(
			ctx, QuotaMonthlyBucket, quotaIdentity, QuotaMonthlyWindowSeconds,
			"monthly", tier, monthlyLimit, "user",
		)
	}
	// 匿名没有账号档位，按免费档口径返回（24 小时配额本身更紧）
	return l.enforceQuotaBucket(
		ctx, QuotaDailyBucket, "ip:"+ClientIP(r, l.trusted), QuotaDailyWindowSeconds,
		"daily", authn.TierFree, l.limits.AnonymousDailyToolCallQuota, "ip",
	)
}

// enforceQuotaBucket 镜像 Python 的 _hit_quota_bucket：单桶命中 + 超限
// 投影；Redis 故障 fail-open（返回 nil 放行）。
func (l *Limiter) enforceQuotaBucket(
	ctx context.Context, bucket, identity string, windowSeconds int64,
	quotaScope, tier string, limit int64, identityKind string,
) *Exceeded {
	exceeded, err := l.hit(ctx, bucket, identity, limit, time.Duration(windowSeconds)*time.Second)
	if err != nil {
		l.logger.Warn("MCP quota check skipped: redis unavailable", "error", err)
		return nil
	}
	if !exceeded {
		return nil
	}
	return &Exceeded{
		Quota:        true,
		QuotaScope:   quotaScope,
		Tier:         tier,
		Limit:        limit,
		RetryAfter:   l.quotaRetryAfter(ctx, bucket, identity, windowSeconds),
		IdentityKind: identityKind,
	}
}

// hit 镜像 auth/rate_limit.py 的 hit_rate_limit（含 TTL 自愈）：
// INCR 与 EXPIRE 非原子，若进程在两者间隙被杀键会丢 TTL 永久卡死
// （2026-08-14 生产事故），故 count==1 或 TTL==-1（无过期）时重新
// EXPIRE 武装窗口；count > limit 判超限。err 非 nil 时调用方 fail-open。
func (l *Limiter) hit(ctx context.Context, bucket, identity string, limit int64, window time.Duration) (bool, error) {
	key := KeyPrefix + bucket + ":" + identity
	count, err := l.redis.Incr(ctx, key)
	if err != nil {
		return false, err
	}
	if count == 1 {
		if _, err := l.redis.Expire(ctx, key, window); err != nil {
			return false, err
		}
	} else {
		ttl, err := l.redis.TTL(ctx, key)
		if err != nil {
			return false, err
		}
		// go-redis 对哨兵值不乘精度：无过期 = time.Duration(-1)（-1ns），
		// 键不存在的 -2 在 INCR 之后不会出现。
		if ttl == time.Duration(-1) {
			if _, err := l.redis.Expire(ctx, key, window); err != nil {
				return false, err
			}
		}
	}
	return count > limit, nil
}

// quotaRetryAfter 镜像 _quota_retry_after：best-effort 读取超限键剩余
// TTL 秒数作 Retry-After；读取失败或非正值回退整窗秒数。
func (l *Limiter) quotaRetryAfter(ctx context.Context, bucket, identity string, fallbackSeconds int64) int64 {
	ttl, err := l.redis.TTL(ctx, KeyPrefix+bucket+":"+identity)
	if err != nil || ttl <= 0 {
		return fallbackSeconds
	}
	return int64(ttl.Seconds())
}
