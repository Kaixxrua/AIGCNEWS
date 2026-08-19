// Package ratelimit 实现 /api/mcp 入站端点的 Redis 固定窗口限流，
// 逐项镜像 backend/app/services/mcp/inbound/rate_limit.py 的编排与
// backend/app/services/auth/rate_limit.py 的 hit_rate_limit 原语：
//
//   - 两层正交限速：分钟级突发桶防爬（所有方法），tools/call 再叠加
//     分层配额桶（匿名按日 100 以 IP 为键 / 免费月 2000、会员月 20000
//     以用户为键，月窗为 30 天滚动固定窗口而非自然月）；
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

// 与 Python 侧常量逐字一致（inbound/rate_limit.py + auth/rate_limit.py）。
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
	// QuotaDailyWindowSeconds / QuotaMonthlyWindowSeconds 是配额窗口
	// （日 86400 / 30 天 2592000）。
	QuotaDailyWindowSeconds   = 86400
	QuotaMonthlyWindowSeconds = 2592000

	// KeyPrefix 是所有限流键的公共前缀（RATE_LIMIT_PREFIX），
	// 键形为 ratelimit:<bucket>:<identity>。
	KeyPrefix = "ratelimit:"
)

// Limits 集中七个限额常量，默认值与 Python 逐字一致；字段导出供回放
// 语料按场景覆盖（如提速测试的小配额）。
type Limits struct {
	AnonymousProtocolPerMinute     int64 // MCP_ANONYMOUS_PROTOCOL_LIMIT = 60
	AnonymousToolCallPerMinute     int64 // MCP_ANONYMOUS_TOOL_CALL_LIMIT = 30
	AuthenticatedProtocolPerMinute int64 // MCP_AUTHENTICATED_PROTOCOL_LIMIT = 240
	AuthenticatedToolCallPerMinute int64 // MCP_AUTHENTICATED_TOOL_CALL_LIMIT = 120
	AnonymousDailyToolCallQuota    int64 // MCP_ANONYMOUS_DAILY_TOOL_CALL_QUOTA = 100
	FreeMonthlyToolCallQuota       int64 // MCP_FREE_MONTHLY_TOOL_CALL_QUOTA = 2000
	MemberMonthlyToolCallQuota     int64 // MCP_MEMBER_MONTHLY_TOOL_CALL_QUOTA = 20000
}

func defaultLimits() Limits {
	return Limits{
		AnonymousProtocolPerMinute:     60,
		AnonymousToolCallPerMinute:     30,
		AuthenticatedProtocolPerMinute: 240,
		AuthenticatedToolCallPerMinute: 120,
		AnonymousDailyToolCallQuota:    100,
		FreeMonthlyToolCallQuota:       2000,
		MemberMonthlyToolCallQuota:     20000,
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

	// 3. tools/call 分层配额桶：认证按用户走月配额（档位取生效档，
	// 未知档 fail-closed 按 free），匿名按 IP 走日配额（按免费档口径
	// 报告）。配额是商业软约束而非安全边界：固定窗口 + INCR 在并发下
	// 可能瞬时超 1，与 Python 同口径，可接受。
	var quotaBucket, quotaIdentity, quotaScope, tier string
	var quotaLimit, quotaWindowSeconds int64
	if id.UserID > 0 {
		tier = id.EffectiveTier(time.Now())
		quotaBucket = QuotaMonthlyBucket
		quotaIdentity = "user:" + strconv.Itoa(id.UserID)
		quotaWindowSeconds = QuotaMonthlyWindowSeconds
		quotaScope = "monthly"
		if tier == authn.TierMember {
			quotaLimit = l.limits.MemberMonthlyToolCallQuota
		} else {
			quotaLimit = l.limits.FreeMonthlyToolCallQuota
		}
	} else {
		tier = authn.TierFree
		quotaBucket = QuotaDailyBucket
		quotaIdentity = "ip:" + ClientIP(r, l.trusted)
		quotaWindowSeconds = QuotaDailyWindowSeconds
		quotaScope = "daily"
		quotaLimit = l.limits.AnonymousDailyToolCallQuota
	}
	exceeded, err = l.hit(ctx, quotaBucket, quotaIdentity, quotaLimit, time.Duration(quotaWindowSeconds)*time.Second)
	if err != nil {
		l.logger.Warn("MCP quota check skipped: redis unavailable", "error", err)
		return nil
	}
	if !exceeded {
		return nil
	}
	return &Exceeded{
		Quota:      true,
		QuotaScope: quotaScope,
		Tier:       tier,
		Limit:      quotaLimit,
		RetryAfter: l.quotaRetryAfter(ctx, quotaBucket, quotaIdentity, quotaWindowSeconds),
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
