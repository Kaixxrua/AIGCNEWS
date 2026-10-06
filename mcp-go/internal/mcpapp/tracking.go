package mcpapp

// tracking.go 实现 get_my_tracking（Go 独有，无 Python 参照）：vip 会员在 AI
// 客户端里读自己的「情报追踪」——追踪规则，以及最近几期每日追踪简报里的
// 命中条目。
//
//   - 执行序：匿名 → 参数校验 → scope（tracking:read）→ 会员档位 → 读库 →
//     投影；任何一步不通过都不读追踪数据；
//   - 会员档位用 token 属主的实时生效档位（authn 每次请求从 users 读），
//     试用、付费与到期回落和网站同一口径；
//   - 只读后端已生成的追踪简报（tracking_digests：每天到投递整点按启用的
//     规则生成，条目链接与文本在生成时已清洗），不在 MCP 里重跑匹配；
//   - 条目按期号新到旧、期内保持生成时的顺序（新到旧）；rule 过滤按规则
//     原文大小写不敏感地比 matched_rules；
//   - 参数校验文案沿用其它工具的 pydantic v2 口径。

import (
	"fmt"
	"sort"
	"strings"
	"time"

	"aigcnews/mcp-go/internal/authn"
	"aigcnews/mcp-go/internal/jsonx"
)

// TrackingReadScope 是读取追踪的 token scope；与 backend routes_auth.py 的
// MCP_TOKEN_SCOPES 同一字面量（test_mcp_tracking_contract.py 钉住）。
const TrackingReadScope = "tracking:read"

// trackingZone 是追踪简报期号与投递整点所在时区（backend domain/tracking.CST）。
var trackingZone = time.FixedZone("UTC+8", 8*60*60)

// TrackingRule 是一条追踪规则（tracking_rules）。
type TrackingRule struct {
	ID            int64
	Kind          string
	Query         string
	Source        string
	Excludes      []string
	StarThreshold int
	Enabled       bool
}

// TrackingItem 是追踪简报里的一个命中条目（tracking_digests.items 的元素）。
type TrackingItem struct {
	ObservedAt   string
	Title        string
	URL          string
	Summary      string
	Source       string
	MatchedRules []string
}

// TrackingIssue 是一期追踪简报；IssueDate 为 UTC+8 的 YYYY-MM-DD。
type TrackingIssue struct {
	IssueDate string
	Truncated bool
	Items     []TrackingItem
}

// TrackingSnapshot 是一个用户的追踪读取结果。tracking_settings 缺行时
// Enabled/DeliveryHour 取后端默认（开启、8 点）；Issues 只含 since 当天及
// 以后的期，新到旧。
type TrackingSnapshot struct {
	Rules        []TrackingRule
	Enabled      bool
	DeliveryHour int
	Issues       []TrackingIssue
}

// TrackingReader 是追踪读取的存储边界（生产=Postgres，测试=stub）。
type TrackingReader interface {
	ReadTracking(userID int, since string) (TrackingSnapshot, error)
}

// TrackingService 装配 get_my_tracking 的校验、把关、查询与投影。
type TrackingService struct {
	reader TrackingReader
	// publicBaseURL 仅来自 PUBLIC_BASE_URL 配置，接线时已 TrimRight("/")。
	publicBaseURL string
	now           func() time.Time
}

func NewTrackingService(reader TrackingReader, publicBaseURL string) *TrackingService {
	return &TrackingService{reader: reader, publicBaseURL: publicBaseURL, now: time.Now}
}

// Get 是 get_my_tracking 工具处理器（IdentityToolHandler）。
func (s *TrackingService) Get(identity authn.Identity, arguments map[string]any) (any, error) {
	// 匿名短路在参数校验之前，与 search_my_project_favorites 同文案。
	if identity.UserID <= 0 {
		return nil, ToolInputError{Message: "Authentication is required for this tool."}
	}
	input, err := validateGetMyTrackingArgs(arguments)
	if err != nil {
		return nil, err
	}
	base := s.attributionBase()
	if !identity.HasScope(TrackingReadScope) {
		return nil, ToolInputError{Message: "This token requires the " + TrackingReadScope +
			" scope. Create a new token at " + base + "/mcp."}
	}
	now := s.now()
	if identity.EffectiveTier(now) != authn.TierMember {
		return nil, ToolInputError{Message: "get_my_tracking is a vip membership benefit. Tracking results stay " +
			"available on the website at " + base + "/subscriptions; upgrade at " + base + "/membership."}
	}

	local := now.In(trackingZone)
	since := time.Date(local.Year(), local.Month(), local.Day()-(input.days-1), 0, 0, 0, 0, trackingZone).
		Format(time.DateOnly)
	snapshot, err := s.reader.ReadTracking(identity.UserID, since)
	if err != nil {
		return nil, err
	}

	ruleKey := strings.ToLower(input.rule)
	if ruleKey != "" && !hasTrackingRule(snapshot.Rules, ruleKey) {
		return nil, unknownTrackingRuleError(snapshot.Rules)
	}

	items := make([]any, 0, input.limit)
	total := 0
	truncated := false
	for _, issue := range snapshot.Issues {
		listed := false
		for _, item := range issue.Items {
			if ruleKey != "" && !matchesTrackingRule(item.MatchedRules, ruleKey) {
				continue
			}
			total++
			listed = true
			if len(items) < input.limit {
				items = append(items, trackingItemObject(issue.IssueDate, item))
			}
		}
		truncated = truncated || (listed && issue.Truncated)
	}

	return jsonx.Object{
		{Key: "rules", Value: trackingRuleObjects(snapshot.Rules)},
		{Key: "schedule", Value: trackingSchedule(snapshot)},
		{Key: "since", Value: since},
		{Key: "items", Value: items},
		{Key: "total", Value: total},
		{Key: "hint", Value: trackingHint(snapshot, input, total, truncated)},
		{Key: "manage_url", Value: base + "/subscriptions"},
		{Key: "attribution", Value: "Data provided by AIGC Radar · " + base},
	}, nil
}

// attributionBase 与收藏工具同口径：配置为空回退品牌站点。
func (s *TrackingService) attributionBase() string {
	if s.publicBaseURL != "" {
		return s.publicBaseURL
	}
	return "https://aigcnews.cn"
}

func hasTrackingRule(rules []TrackingRule, key string) bool {
	for _, rule := range rules {
		if strings.ToLower(rule.Query) == key {
			return true
		}
	}
	return false
}

func matchesTrackingRule(matched []string, key string) bool {
	for _, query := range matched {
		if strings.ToLower(query) == key {
			return true
		}
	}
	return false
}

// unknownTrackingRuleError 列出可选的规则原文，让模型能直接改正参数。
func unknownTrackingRuleError(rules []TrackingRule) error {
	if len(rules) == 0 {
		return ToolInputError{Message: "rule: You have no tracking rules yet; omit rule."}
	}
	queries := make([]string, 0, len(rules))
	for _, rule := range rules {
		queries = append(queries, fmt.Sprintf("%q", rule.Query))
	}
	sort.Strings(queries)
	return ToolInputError{Message: "rule: Use the query of one of your tracking rules: " + strings.Join(queries, ", ") + "."}
}

func trackingRuleObjects(rules []TrackingRule) []any {
	objects := make([]any, 0, len(rules))
	for _, rule := range rules {
		excludes := make([]any, 0, len(rule.Excludes))
		for _, term := range rule.Excludes {
			excludes = append(excludes, term)
		}
		object := jsonx.Object{
			{Key: "id", Value: rule.ID},
			{Key: "kind", Value: rule.Kind},
			{Key: "query", Value: rule.Query},
			{Key: "source", Value: rule.Source},
			{Key: "excludes", Value: excludes},
		}
		// 星标增长门槛只对项目规则有意义。
		if rule.Kind == "project" {
			object = append(object, jsonx.Pair{Key: "star_threshold", Value: rule.StarThreshold})
		}
		objects = append(objects, append(object, jsonx.Pair{Key: "enabled", Value: rule.Enabled}))
	}
	return objects
}

func trackingItemObject(issueDate string, item TrackingItem) jsonx.Object {
	matched := make([]any, 0, len(item.MatchedRules))
	for _, query := range item.MatchedRules {
		matched = append(matched, query)
	}
	return jsonx.Object{
		{Key: "issue_date", Value: issueDate},
		{Key: "observed_at", Value: item.ObservedAt},
		{Key: "source", Value: item.Source},
		{Key: "title", Value: item.Title},
		{Key: "summary", Value: item.Summary},
		{Key: "url", Value: item.URL},
		{Key: "matched_rules", Value: matched},
	}
}

func trackingSchedule(snapshot TrackingSnapshot) string {
	if !snapshot.Enabled {
		return "paused"
	}
	return fmt.Sprintf("daily at %02d:00 UTC+8", snapshot.DeliveryHour)
}

// trackingHint 只在需要解释时给一句话：没有规则、追踪暂停、窗口内没有
// 命中，或有期次被单期 50 条上限截断；其余为 null。
func trackingHint(snapshot TrackingSnapshot, input getMyTrackingInput, total int, truncated bool) any {
	enabled := 0
	for _, rule := range snapshot.Rules {
		if rule.Enabled {
			enabled++
		}
	}
	switch {
	case len(snapshot.Rules) == 0:
		return "No tracking rules yet. Add keywords or GitHub projects at manage_url; matches arrive in a daily issue."
	case !snapshot.Enabled:
		return "Tracking is paused for this account, so no new issues are compiled. Resume it at manage_url."
	case enabled == 0:
		return "All tracking rules are disabled, so no new issues are compiled. Enable a rule at manage_url."
	case total == 0:
		return fmt.Sprintf("No matches in issues since %s. A new issue is compiled %s from items "+
			"that match the enabled rules.", trackingSinceLabel(input), trackingSchedule(snapshot))
	case truncated:
		return "Some issues hit the 50-item limit per issue, so not every match is listed."
	}
	return nil
}

func trackingSinceLabel(input getMyTrackingInput) string {
	if input.days == 1 {
		return "today"
	}
	return fmt.Sprintf("%d days ago", input.days-1)
}

// ── 入参校验（pydantic v2 文案口径） ──────────────────────────────────────

type getMyTrackingInput struct {
	days  int
	rule  string
	limit int
}

// validateGetMyTrackingArgs 校验 days（StrictInt 默认 7，1–30）、rule
// （StrictStr 默认 ""，≤120，去首尾空白）、limit（StrictInt 默认 20，1–50）；
// 错误按字段序，未知键按键名排序殿后，多错 "; " 连接。
func validateGetMyTrackingArgs(args map[string]any) (getMyTrackingInput, error) {
	input := getMyTrackingInput{days: 7, limit: 20}
	var failures []string

	input.days = trackingBoundedInt(args, "days", 7, 1, 30, &failures)
	input.rule = favoritesStrictString(args, "rule", 120, &failures)
	input.limit = trackingBoundedInt(args, "limit", 20, 1, 50, &failures)

	known := map[string]bool{"days": true, "rule": true, "limit": true}
	var extras []string
	for key := range args {
		if !known[key] {
			extras = append(extras, key)
		}
	}
	sort.Strings(extras)
	for _, key := range extras {
		failures = append(failures, key+": Extra inputs are not permitted")
	}

	if len(failures) > 0 {
		return getMyTrackingInput{}, ToolInputError{Message: strings.Join(failures, "; ")}
	}
	return input, nil
}

func trackingBoundedInt(args map[string]any, key string, fallback, minimum, maximum int, failures *[]string) int {
	raw, present := args[key]
	if !present {
		return fallback
	}
	value, ok := strictInt(raw)
	switch {
	case !ok:
		*failures = append(*failures, key+": Input should be a valid integer")
	case value < minimum:
		*failures = append(*failures, fmt.Sprintf("%s: Input should be greater than or equal to %d", key, minimum))
	case value > maximum:
		*failures = append(*failures, fmt.Sprintf("%s: Input should be less than or equal to %d", key, maximum))
	default:
		return value
	}
	return fallback
}
