// Package usage 记录 /api/mcp 的每日用量汇总：每天有多少客户端在用、
// 叫什么客户端、调了哪些工具、被限流多少次，按匿名/免费/会员分开。
// 读路径在 backend/app/monitoring/mcp_daily_usage.py（管理员监控页）。
//
// 口径：
//   - 按北京时间自然日分键，每个键保留 400 天；
//   - 受众按请求身份分 anonymous（未带令牌）/ free / member（生效档位）；
//     管理员与压测 UA（mcp-latency-bench/）整体不记；
//   - 去重客户端用 HyperLogLog：登录用户按用户 id，匿名按「当天日期 + IP」
//     的 SHA-256 摘要前 16 位十六进制。原始 IP 从不发往 Redis，HLL 也无法
//     反推出成员；
//   - 客户端名取 initialize 的 params.clientInfo.name，小写归一；空名记
//     __unknown__，含非法字符或超长记 __other__；每天最多 MaxClientNames
//     个名字，之后的新名字并入 __other__，防止随意命名撑大键；
//   - fail-open：Redis 出错只记日志，绝不影响 MCP 响应。
//
// 键布局（day 为北京时间 YYYY-MM-DD）：
//
//	mcpusage:since                                首次记录的日期（SETNX，不过期）
//	mcpusage:{day}:clients:{audience}             HLL，当天去重客户端
//	mcpusage:{day}:calls                          HASH {audience}|{tool} → tools/call 次数
//	mcpusage:{day}:limited                        HASH {audience}|{kind} → 429 次数
//	mcpusage:{day}:client_names                   HASH {audience}|{name} → initialize 次数
//	mcpusage:{day}:name_clients:{audience}|{name} HLL，该客户端名的去重客户端
//
// kind 取 burst（分钟突发桶）、daily（24 小时配额）、monthly（30 天额度）。
package usage

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"log/slog"
	"strconv"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"

	"github.com/redis/go-redis/v9"

	"aigcnews/mcp-go/internal/authn"
	"aigcnews/mcp-go/internal/metrics"
)

const (
	Namespace = "mcpusage"

	AudienceAnonymous = "anonymous"
	AudienceFree      = "free"
	AudienceMember    = "member"

	LimitBurst   = "burst"
	LimitDaily   = "daily"
	LimitMonthly = "monthly"

	UnknownClientName = "__unknown__"
	OtherClientName   = "__other__"
	// MaxClientNames 是每天 client_names 哈希接受的名字上限（三类受众合计）。
	MaxClientNames = 64

	maxClientNameRunes = 48
	keyTTL             = 400 * 24 * time.Hour
	writeTimeout       = 250 * time.Millisecond
)

// beijing 与 Python cst_today() 同口径：固定 UTC+8，不依赖系统时区库。
var beijing = time.FixedZone("Asia/Shanghai", 8*60*60)

// recordScript 一次 EVAL 完成一条记录，全原子。
// KEYS: since, 受众 HLL, [计数哈希, [名字 HLL, 溢出名字 HLL]]
// ARGV: day, ttl 秒, HLL 成员, 哈希字段, 字段上限（0 不限）, 溢出字段
var recordScript = redis.NewScript(`
local ttl = tonumber(ARGV[2])
redis.call('SETNX', KEYS[1], ARGV[1])
redis.call('PFADD', KEYS[2], ARGV[3])
redis.call('EXPIRE', KEYS[2], ttl)
if #KEYS < 3 then return 1 end
local field = ARGV[4]
local overflow = false
local cap = tonumber(ARGV[5])
if cap > 0 and redis.call('HEXISTS', KEYS[3], field) == 0 and redis.call('HLEN', KEYS[3]) >= cap then
  field = ARGV[6]
  overflow = true
end
redis.call('HINCRBY', KEYS[3], field, 1)
redis.call('EXPIRE', KEYS[3], ttl)
if #KEYS >= 5 then
  local hll = KEYS[4]
  if overflow then hll = KEYS[5] end
  redis.call('PFADD', hll, ARGV[3])
  redis.call('EXPIRE', hll, ttl)
end
return 1
`)

// Event 是一次已通过解析的 /api/mcp 请求。
type Event struct {
	Identity  authn.Identity
	ClientIP  string
	UserAgent string
	Method    string
	// Tool 是 tools/call 已归桶的工具名（metrics.BucketToolName 的结果）。
	Tool string
	// ClientName 是 initialize 原样的 params.clientInfo.name。
	ClientName string
	// Limited 非空表示本请求被限流，取 LimitKind 的结果。
	Limited string
}

// Recorder 写 mcpusage:*；nil *Recorder 表示未接线，Record 不做任何事。
type Recorder struct {
	client *redis.Client
	now    func() time.Time
}

// NewRecorder 接线；client 为 nil 时返回 nil。
func NewRecorder(client *redis.Client) *Recorder {
	if client == nil {
		return nil
	}
	return &Recorder{client: client, now: time.Now}
}

// Day 返回 now 所在的北京时间日期。
func Day(now time.Time) string {
	return now.In(beijing).Format("2006-01-02")
}

// Audience 按请求身份分受众；登录用户按生效档位分免费与会员。
func Audience(identity authn.Identity, now time.Time) string {
	if identity.UserID <= 0 {
		return AudienceAnonymous
	}
	if identity.EffectiveTier(now) == authn.TierMember {
		return AudienceMember
	}
	return AudienceFree
}

// LimitKind 把限流结果归成 burst / daily / monthly。
func LimitKind(quota bool, quotaScope string) string {
	if !quota {
		return LimitBurst
	}
	if quotaScope == LimitMonthly {
		return LimitMonthly
	}
	return LimitDaily
}

// NormalizeClientName 把 clientInfo.name 归一成可做哈希字段的名字：
// 去首尾空白、转小写；只允许字母、数字和 ` ._-/@()`，最多 48 个字符。
func NormalizeClientName(raw string) string {
	name := strings.ToLower(strings.TrimSpace(raw))
	if name == "" {
		return UnknownClientName
	}
	if utf8.RuneCountInString(name) > maxClientNameRunes {
		return OtherClientName
	}
	for _, r := range name {
		if unicode.IsLetter(r) || unicode.IsDigit(r) {
			continue
		}
		switch r {
		case ' ', '.', '_', '-', '/', '@', '(', ')':
			continue
		}
		return OtherClientName
	}
	return name
}

// clientMember 是 HLL 成员：登录用户 u:<id>；匿名 a:<sha256(day|ip) 前 16 位>。
// 摘要带日期，同一 IP 跨天得到不同成员。
func clientMember(day string, identity authn.Identity, clientIP string) string {
	if identity.UserID > 0 {
		return "u:" + strconv.Itoa(identity.UserID)
	}
	sum := sha256.Sum256([]byte(day + "|" + clientIP))
	return "a:" + hex.EncodeToString(sum[:8])
}

func dayKey(day, suffix string) string {
	return Namespace + ":" + day + ":" + suffix
}

// Record 写一条用量记录。管理员与压测流量直接跳过。
func (r *Recorder) Record(ctx context.Context, event Event) {
	if r == nil || event.Identity.Role == "admin" || metrics.IsBenchmarkUserAgent(event.UserAgent) {
		return
	}
	now := r.now()
	day := Day(now)
	audience := Audience(event.Identity, now)
	member := clientMember(day, event.Identity, event.ClientIP)
	keys := []string{Namespace + ":since", dayKey(day, "clients:"+audience)}
	args := []any{day, int64(keyTTL / time.Second), member}

	switch {
	case event.Limited != "":
		keys = append(keys, dayKey(day, "limited"))
		args = append(args, audience+"|"+event.Limited, 0, "")
	case event.Method == "tools/call":
		tool := event.Tool
		if tool == "" {
			tool = metrics.UnknownToolName
		}
		keys = append(keys, dayKey(day, "calls"))
		args = append(args, audience+"|"+tool, 0, "")
	case event.Method == "initialize":
		field := audience + "|" + NormalizeClientName(event.ClientName)
		overflow := audience + "|" + OtherClientName
		keys = append(keys,
			dayKey(day, "client_names"),
			dayKey(day, "name_clients:"+field),
			dayKey(day, "name_clients:"+overflow),
		)
		args = append(args, field, MaxClientNames, overflow)
	}

	writeCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), writeTimeout)
	defer cancel()
	if err := recordScript.Run(writeCtx, r.client, keys, args...).Err(); err != nil {
		slog.Warn("mcp daily usage redis write failed", "err", err)
	}
}
