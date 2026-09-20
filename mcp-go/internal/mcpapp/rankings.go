package mcpapp

import (
	"sort"
	"strings"
	"time"

	"aigcnews/mcp-go/internal/jsonx"
)

var rankingSources = []string{"all", "arxiv", "github", "news", "producthunt", "hackernews", "x"}
var rankingPeriods = []string{"daily", "weekly", "monthly"}

// RankSnapshotDocument is one public document joined to a rank snapshot.
type RankSnapshotDocument struct {
	DocumentRow
}

type RankSnapshotReader interface {
	GetSnapshotDocuments(snapshotDate, sourceChannel, sourceType string, limit int) ([]DocumentRow, error)
	GetSnapshotDocIDs(snapshotDate, sourceChannel string) (map[string]bool, error)
}

type GetTopItemsService struct {
	rank      RankSnapshotReader
	documents DocumentsService
	now       func() time.Time
}

func NewGetTopItemsService(rank RankSnapshotReader, publicBaseURL string) *GetTopItemsService {
	return &GetTopItemsService{rank: rank, documents: DocumentsService{publicBaseURL: publicBaseURL}, now: func() time.Time { return time.Now().UTC().Add(8 * time.Hour) }}
}

// SetNow 注入看板时钟（回放冻结 2026-08-10T12:00+08:00，对齐 recorder 的
// dashboard_policy.datetime patch）。
func (s *GetTopItemsService) SetNow(now func() time.Time) { s.now = now }

func (s *GetTopItemsService) Get(arguments map[string]any) (any, error) {
	input, err := validateGetTopItemsArgs(arguments)
	if err != nil {
		return nil, err
	}
	date := input.date
	if date == "" {
		date = s.now().Format("2006-01-02")
	}
	finalized, _ := boardStatus(date, s.now(), input.source)
	base := func(items []any, total int, isEmbargoed bool) jsonx.Object {
		return jsonx.Object{
			{Key: "items", Value: items}, {Key: "total", Value: total}, {Key: "period", Value: input.period}, {Key: "source", Value: input.source},
			{Key: "snapshot_date", Value: date}, {Key: "is_finalized", Value: finalized}, {Key: "is_embargoed", Value: isEmbargoed},
			{Key: "attribution", Value: "Data provided by AIGC Radar · " + s.documents.attributionBase()},
		}
	}
	docs, err := s.getDocs(date, input.period, input.source)
	if err != nil {
		return nil, err
	}
	docs = dedupeRows(docs)
	if len(docs) > input.limit {
		docs = docs[:input.limit]
	}
	items := make([]any, 0, len(docs))
	for _, row := range docs {
		// _tool_get_top_items 用 _public_doc(..., dashboard=True)：pdf_media_url
		// 不走 arxiv 代理兜底（仅 local_pdf_path 媒体库路径）。
		items = append(items, s.documents.dashboardDocument(row))
	}
	return base(items, len(items), false), nil
}

type topItemsInput struct {
	source, period, date string
	limit                int
}

func validateGetTopItemsArgs(args map[string]any) (topItemsInput, error) {
	input := topItemsInput{source: "all", period: "daily", limit: 10}
	var failures []string
	if v, ok := args["source"]; ok {
		s, good := v.(string)
		if !good || !contains(rankingSources, s) {
			failures = append(failures, "source: Input should be 'all', 'arxiv', 'github', 'news', 'producthunt', 'hackernews' or 'x'")
		} else {
			input.source = s
		}
	}
	if v, ok := args["period"]; ok {
		p, good := v.(string)
		if !good || !contains(rankingPeriods, p) {
			failures = append(failures, "period: Input should be 'daily', 'weekly' or 'monthly'")
		} else {
			input.period = p
		}
	}
	if v, ok := args["date"]; ok && v != nil {
		d, good := v.(string)
		if !good {
			failures = append(failures, "date: Input should be a valid string")
		} else if len([]rune(d)) < 10 {
			failures = append(failures, "date: String should have at least 10 characters")
		} else if len([]rune(d)) > 10 {
			failures = append(failures, "date: String should have at most 10 characters")
		} else if _, e := time.Parse("2006-01-02", d); e != nil {
			failures = append(failures, "date: Input should be a valid date")
		} else {
			input.date = d
		}
	}
	if v, ok := args["limit"]; ok {
		n, good := strictInt(v)
		if !good {
			failures = append(failures, "limit: Input should be a valid integer")
		} else if n < 1 {
			failures = append(failures, "limit: Input should be greater than or equal to 1")
		} else if n > 20 {
			failures = append(failures, "limit: Input should be less than or equal to 20")
		} else {
			input.limit = n
		}
	}
	known := map[string]bool{"source": true, "period": true, "date": true, "limit": true}
	var extra []string
	for k := range args {
		if !known[k] {
			extra = append(extra, k)
		}
	}
	sort.Strings(extra)
	for _, k := range extra {
		failures = append(failures, k+": Extra inputs are not permitted")
	}
	if len(failures) > 0 {
		return topItemsInput{}, ToolInputError{Message: strings.Join(failures, "; ")}
	}
	return input, nil
}
func contains(values []string, value string) bool {
	for _, v := range values {
		if v == value {
			return true
		}
	}
	return false
}
func boardStatus(date string, now time.Time, source ...string) (bool, bool) {
	hour := 17
	if len(source) > 0 {
		switch source[0] {
		case "github", "news", "hackernews", "x":
			hour = 1
		case "arxiv", "producthunt", "all", "":
		default:
			hour = 15
		}
	}
	yesterday := now.AddDate(0, 0, -1).Format("2006-01-02")
	return date < yesterday || (date == yesterday && now.Hour() >= hour), false
}

var sourceChannels = map[string]map[string]string{
	"arxiv":       {"daily": "huggingface_daily_html", "weekly": "huggingface_weekly_html", "monthly": "huggingface_monthly_html"},
	"github":      {"daily": "github_trending_daily", "weekly": "github_trending_weekly", "monthly": "github_trending_monthly"},
	"news":        {"daily": "techmeme_daily_rss", "weekly": "techmeme_daily_rss", "monthly": "techmeme_daily_rss"},
	"producthunt": {"daily": "producthunt_daily_html", "weekly": "producthunt_weekly_html", "monthly": "producthunt_monthly_html"},
	"hackernews":  {"daily": "hn_daily_html", "weekly": "hn_weekly_html", "monthly": "hn_monthly_html"},
	"x":           {"daily": "x_daily_watchlist"},
}

// samePeriodFallbacks 复刻 query_service.SAME_PERIOD_FALLBACKS：github 主榜
// 空时按序取首个非空的同周期兜底渠道。
var samePeriodFallbacks = map[string]map[string][]string{
	"github": {
		"daily":   {"github_hot_daily", "github_fallback"},
		"weekly":  {"github_hot_weekly"},
		"monthly": {"github_hot_monthly"},
	},
}

// getDocs 复刻 DashboardQueryService.get_docs_for_date（MCP inbound 不注入
// github_hot，故 github 日榜保持 trending 快照口径）：按 SOURCE_PERIOD_CHANNELS
// 注册序收集，空渠道走同周期 fallback；读错误不吞（Python 无 try/except）。
// 收集非空且 period=daily 时应用 _apply_hackernews_daily_dedup。
func (s *GetTopItemsService) getDocs(date, period, source string) ([]DocumentRow, error) {
	var out []DocumentRow
	appendFirstFallback := func(src string) error {
		for _, fallbackChannel := range samePeriodFallbacks[src][period] {
			docs, err := s.rank.GetSnapshotDocuments(date, fallbackChannel, src, 500)
			if err != nil {
				return err
			}
			if len(docs) > 0 {
				out = append(out, docs...)
				return nil
			}
		}
		return nil
	}
	if source != "all" {
		if ch := sourceChannels[source][period]; ch != "" {
			rows, err := s.rank.GetSnapshotDocuments(date, ch, source, 500)
			if err != nil {
				return nil, err
			}
			out = append(out, rows...)
		}
		if len(out) == 0 {
			if err := appendFirstFallback(source); err != nil {
				return nil, err
			}
		}
	} else {
		for _, src := range []string{"arxiv", "github", "news", "producthunt", "hackernews", "x"} {
			ch := sourceChannels[src][period]
			if ch == "" {
				continue
			}
			rows, err := s.rank.GetSnapshotDocuments(date, ch, src, 500)
			if err != nil {
				return nil, err
			}
			if len(rows) > 0 {
				out = append(out, rows...)
				continue
			}
			if err := appendFirstFallback(src); err != nil {
				return nil, err
			}
		}
	}
	if len(out) > 0 && period == "daily" {
		return s.applyHackernewsDailyDedup(date, out)
	}
	return out, nil
}

// applyHackernewsDailyDedup 复刻 _apply_hackernews_daily_dedup：HN 条目
// 整体拆出，剔除昨日 hn_daily_html 已上榜 id（昨日 = date−1 天，解析失败
// 回退 today_local 即当前 CST 钟日期），剩余按 float(raw_score or score or 0)
// 降序（Python sort 稳定 → SliceStable）后移到榜尾。
func (s *GetTopItemsService) applyHackernewsDailyDedup(date string, docs []DocumentRow) ([]DocumentRow, error) {
	var hn, other []DocumentRow
	for _, d := range docs {
		if strings.ToLower(derefString(d.Source)) == "hackernews" {
			hn = append(hn, d)
		} else {
			other = append(other, d)
		}
	}
	if len(hn) == 0 {
		return docs, nil
	}
	current, err := time.Parse("2006-01-02", date)
	if err != nil {
		current = s.now()
	}
	yesterday := current.AddDate(0, 0, -1).Format("2006-01-02")
	yesterdayIDs, err := s.rank.GetSnapshotDocIDs(yesterday, "hn_daily_html")
	if err != nil {
		return nil, err
	}
	if len(yesterdayIDs) > 0 {
		filtered := make([]DocumentRow, 0, len(hn))
		for _, d := range hn {
			if yesterdayIDs[derefString(d.ID)] {
				continue
			}
			filtered = append(filtered, d)
		}
		hn = filtered
	}
	sort.SliceStable(hn, func(i, j int) bool {
		return hnScore(hn[i]) > hnScore(hn[j])
	})
	return append(other, hn...), nil
}

// hnScore 复刻 float(doc.get("raw_score") or doc.get("score") or 0) 的
// 真值链：raw_score 为 0/None 时落到 score。
func hnScore(d DocumentRow) float64 {
	v := rawScoreAsFloat(d.RawScore)
	if v == 0 && d.Score != nil {
		v = *d.Score
	}
	return v
}
func dedupeRows(rows []DocumentRow) []DocumentRow {
	seen := map[string]bool{}
	out := make([]DocumentRow, 0, len(rows))
	for _, r := range rows {
		k := derefString(r.URL)
		if k == "" {
			k = derefString(r.Title)
		}
		if k != "" && seen[k] {
			continue
		}
		if k != "" {
			seen[k] = true
		}
		out = append(out, r)
	}
	return out
}
