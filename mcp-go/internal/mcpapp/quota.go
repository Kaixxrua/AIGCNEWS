package mcpapp

// quota.go 实现 get_my_quota（Go 独有，无 Python 参照）：认证用户在 AI 客户端
// 里查自己的档位与 MCP 工具调用额度——24 小时与 30 天两个窗口各用了多少、
// 还剩多少、多久重置。网站的接入提示词也用它验证连接是否成功。
//
//   - 不计配额：Handler 对本工具只过分钟级突发桶（ratelimit.EnforceBurst），
//     额度用尽的用户仍能查到何时恢复；
//   - 只读：限流器对配额键只做 GET + TTL，不计数、不续期；
//   - 档位用 token 属主的实时生效档位（authn 每次请求从 users 读），与限流
//     同口径；admin 豁免配额，只报档位；
//   - Redis 不可用时照常返回档位与限额，用量字段为 null 并在 summary 说明；
//   - 不收参数，多余参数沿用 pydantic v2 文案报错。

import (
	"context"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"

	"aigcnews/mcp-go/internal/authn"
	"aigcnews/mcp-go/internal/jsonx"
	"aigcnews/mcp-go/internal/ratelimit"
)

// QuotaToolName 是额度查询工具名：Handler 据此免计配额，main.go 据此注册与计数。
const QuotaToolName = "get_my_quota"

// quotaStatusTimeout 限定一次额度查询的 Redis 往返总时长。
const quotaStatusTimeout = 2 * time.Second

// QuotaReader 是额度查询的边界（生产=*ratelimit.Limiter，测试=stub）。
type QuotaReader interface {
	QuotaStatus(ctx context.Context, identity authn.Identity, now time.Time) ratelimit.QuotaStatus
	TierQuotaLimits(tier string) (daily, monthly int64)
}

// QuotaService 装配 get_my_quota 的校验、查询与投影。
type QuotaService struct {
	reader QuotaReader
	// publicBaseURL 仅来自 PUBLIC_BASE_URL 配置，接线时已 TrimRight("/")。
	publicBaseURL string
	now           func() time.Time
}

func NewQuotaService(reader QuotaReader, publicBaseURL string) *QuotaService {
	return &QuotaService{reader: reader, publicBaseURL: publicBaseURL, now: time.Now}
}

// Get 是 get_my_quota 工具处理器（IdentityToolHandler）。
func (s *QuotaService) Get(identity authn.Identity, arguments map[string]any) (any, error) {
	// 匿名短路在参数校验之前，与其它私有工具同文案。
	if identity.UserID <= 0 {
		return nil, ToolInputError{Message: "Authentication is required for this tool."}
	}
	if err := validateGetMyQuotaArgs(arguments); err != nil {
		return nil, err
	}
	ctx, cancel := context.WithTimeout(context.Background(), quotaStatusTimeout)
	defer cancel()
	status := s.reader.QuotaStatus(ctx, identity, s.now())

	plan := "free"
	var expiresAt any
	windows := make([]any, 0, len(status.Windows))
	if !status.Exempt {
		for _, window := range status.Windows {
			windows = append(windows, quotaWindowObject(window, status.UsageKnown))
		}
	}
	return jsonx.Object{
		{Key: "plan", Value: plan},
		{Key: "membership_expires_at", Value: expiresAt},
		{Key: "quota_applies", Value: !status.Exempt},
		{Key: "windows", Value: windows},
		{Key: "counts_toward_quota", Value: false},
		{Key: "summary", Value: s.quotaSummary(status)},
		{Key: "manage_url", Value: s.attributionBase() + "/mcp"},
	}, nil
}

// attributionBase 与其它工具同口径：配置为空回退品牌站点。
func (s *QuotaService) attributionBase() string {
	if s.publicBaseURL != "" {
		return s.publicBaseURL
	}
	return "https://aigcnews.cn"
}

// quotaWindowObject 投影一个窗口；被拒的尝试也计数，used 封顶为 limit。
// 窗口未开始（键不存在）时 resets_in_seconds 为 null。
func quotaWindowObject(window ratelimit.QuotaWindow, usageKnown bool) jsonx.Object {
	object := jsonx.Object{
		{Key: "window", Value: quotaWindowLabel(window.Scope)},
		{Key: "limit", Value: window.Limit},
	}
	if !usageKnown {
		return append(object,
			jsonx.Pair{Key: "used", Value: nil},
			jsonx.Pair{Key: "remaining", Value: nil},
			jsonx.Pair{Key: "resets_in_seconds", Value: nil},
		)
	}
	var resetsIn any
	if window.ResetsIn > 0 {
		resetsIn = window.ResetsIn
	}
	return append(object,
		jsonx.Pair{Key: "used", Value: min(window.Used, window.Limit)},
		jsonx.Pair{Key: "remaining", Value: quotaRemaining(window)},
		jsonx.Pair{Key: "resets_in_seconds", Value: resetsIn},
	)
}

func quotaWindowLabel(scope string) string {
	if scope == "monthly" {
		return "30d"
	}
	return "24h"
}

func quotaRemaining(window ratelimit.QuotaWindow) int64 {
	return max(window.Limit-window.Used, 0)
}

// quotaSummary 给模型一段可以直接转述的英文说明。
func (s *QuotaService) quotaSummary(status ratelimit.QuotaStatus) string {
	plan := "Free account access"
	if status.Exempt {
		return plan + "; this admin account is exempt from the 24-hour and 30-day tool-call quotas. " +
			"Only the per-minute burst limit applies."
	}
	daily := quotaWindowByScope(status, "daily")
	monthly := quotaWindowByScope(status, "monthly")
	var b strings.Builder
	if !status.UsageKnown {
		fmt.Fprintf(&b, "%s: up to %s tool calls per 24 hours and %s per 30 days. "+
			"Live usage is temporarily unavailable; try again shortly.",
			plan, groupDigits(daily.Limit), groupDigits(monthly.Limit))
	} else {
		fmt.Fprintf(&b, "%s. 24-hour window: %s of %s tool calls left%s. 30-day window: %s of %s left%s.",
			plan,
			groupDigits(quotaRemaining(daily)), groupDigits(daily.Limit), quotaResetClause(daily),
			groupDigits(quotaRemaining(monthly)), groupDigits(monthly.Limit), quotaResetClause(monthly))
		switch {
		case quotaRemaining(monthly) == 0:
			b.WriteString(" Tool calls are paused until the 30-day window resets.")
		case quotaRemaining(daily) == 0:
			b.WriteString(" Tool calls are paused until the 24-hour window resets.")
		}
	}
	b.WriteString(" Checking quota does not use any.")
	return b.String()
}

func quotaWindowByScope(status ratelimit.QuotaStatus, scope string) ratelimit.QuotaWindow {
	for _, window := range status.Windows {
		if window.Scope == scope {
			return window
		}
	}
	return ratelimit.QuotaWindow{Scope: scope}
}

func quotaResetClause(window ratelimit.QuotaWindow) string {
	switch {
	case window.ResetsIn > 0:
		return ", resets in " + formatQuotaDuration(window.ResetsIn)
	case window.Used == 0:
		return "; it starts with your next tool call"
	}
	return ""
}

// formatQuotaDuration 取两个最大的非零单位，如 "23d 4h"、"3h 12m"。
func formatQuotaDuration(seconds int64) string {
	days, hours, minutes := seconds/86400, seconds%86400/3600, seconds%3600/60
	switch {
	case days > 0 && hours > 0:
		return fmt.Sprintf("%dd %dh", days, hours)
	case days > 0:
		return fmt.Sprintf("%dd", days)
	case hours > 0 && minutes > 0:
		return fmt.Sprintf("%dh %dm", hours, minutes)
	case hours > 0:
		return fmt.Sprintf("%dh", hours)
	case minutes > 0:
		return fmt.Sprintf("%dm", minutes)
	}
	return "under a minute"
}

// groupDigits 给非负整数加千分位（4000 → "4,000"），与网站文案同写法。
func groupDigits(n int64) string {
	digits := strconv.FormatInt(n, 10)
	if n < 0 || len(digits) <= 3 {
		return digits
	}
	var b strings.Builder
	head := len(digits) % 3
	if head > 0 {
		b.WriteString(digits[:head])
	}
	for i := head; i < len(digits); i += 3 {
		if b.Len() > 0 {
			b.WriteByte(',')
		}
		b.WriteString(digits[i : i+3])
	}
	return b.String()
}

// validateGetMyQuotaArgs：本工具不收参数，每个键都按 pydantic v2 口径报
// "Extra inputs are not permitted"，键名排序、"; " 连接。
func validateGetMyQuotaArgs(args map[string]any) error {
	if len(args) == 0 {
		return nil
	}
	keys := make([]string, 0, len(args))
	for key := range args {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	failures := make([]string, 0, len(keys))
	for _, key := range keys {
		failures = append(failures, key+": Extra inputs are not permitted")
	}
	return ToolInputError{Message: strings.Join(failures, "; ")}
}
