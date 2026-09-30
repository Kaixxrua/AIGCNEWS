package postgres

// 混合检索（Go 独有，无 Python 参照）：检索计划的语义文本、RRF 融合与
// "融合头部 + 关键词尾部"分页切分的纯函数门禁。

import (
	"fmt"
	"reflect"
	"strings"
	"testing"
	"time"
)

func TestDocumentSearchPlanSemanticText(t *testing.T) {
	today := time.Date(2026, 9, 30, 10, 0, 0, 0, time.FixedZone("CST", 8*3600))
	cases := map[string]string{
		"OpenAI":         "OpenAI",
		"agent memory":   "agent memory",
		"  什么是 MCP 协议？ ": "什么是 MCP 协议?",
		"简洁总结昨晚openai发布了什么":   "简洁总结 openai发布了什么", // 提问式：剥掉时间短语
		"最近7天 Claude Code 更新": "Claude Code 更新",
		"有哪些关于视频生成的新模型":       "有哪些关于视频生成的新模型",
		"昨天":      "", // 纯时间查询不走语义
		"昨晚发布了什么": "",
	}
	for query, want := range cases {
		if got := buildDocumentSearchPlan(query, 5, today).semantic; got != want {
			t.Errorf("semantic(%q) = %q, want %q", query, got, want)
		}
	}
}

func TestFuseDocumentRankings(t *testing.T) {
	cases := []struct {
		name              string
		lexical, semantic []string
		want              []string
	}{
		{"empty", nil, nil, []string{}},
		{"lexical only keeps keyword order", []string{"c", "a", "b"}, nil, []string{"c", "a", "b"}},
		{"semantic only keeps similarity order", nil, []string{"z", "y"}, []string{"z", "y"}},
		// c: 1/63+1/61 居首；a: 1/61；b 与 d 同为 1/62，关键词名次在前的 b 先。
		{"overlap boosts shared hits", []string{"a", "b", "c"}, []string{"c", "d"}, []string{"c", "a", "b", "d"}},
		{"duplicates ranked once", []string{"a", "a", "b"}, []string{"b", "b"}, []string{"b", "a"}},
		// 两路同名次同分：关键词命中者优先，再按语义名次。
		{"interleave ties prefer lexical", []string{"l1", "l2"}, []string{"s1", "s2"}, []string{"l1", "s1", "l2", "s2"}},
	}
	for _, tc := range cases {
		if got := fuseDocumentRankings(tc.lexical, tc.semantic); !reflect.DeepEqual(got, tc.want) {
			t.Errorf("%s: fuse = %v, want %v", tc.name, got, tc.want)
		}
	}
}

// 语义通道失败时 hybridPage 以 semantic=nil 融合：头部必须原样保持关键词序，
// 否则"回落纯关键词"就不成立。
func TestFuseDocumentRankingsWithoutSemanticIsIdentity(t *testing.T) {
	lexical := make([]string, hybridLexicalDepth)
	for i := range lexical {
		lexical[i] = fmt.Sprintf("doc-%03d", hybridLexicalDepth-i) // 故意与 id 字典序相反
	}
	if got := fuseDocumentRankings(lexical, nil); !reflect.DeepEqual(got, lexical) {
		t.Fatal("lexical order changed without semantic hits")
	}
}

// 逐页拼接必须恰好还原"融合头部 + 关键词尾部"这条虚拟序列：不重不漏、不越界。
func TestHybridPageWindowCoversVirtualSequence(t *testing.T) {
	for fusedLen := 0; fusedLen <= 12; fusedLen++ {
		for tailLen := 0; tailLen <= 7; tailLen++ {
			for pageSize := 1; pageSize <= 5; pageSize++ {
				fused := make([]string, fusedLen)
				for i := range fused {
					fused[i] = fmt.Sprintf("f%d", i)
				}
				tail := make([]string, tailLen)
				for i := range tail {
					tail[i] = fmt.Sprintf("t%d", i)
				}
				var got []string
				for page := 1; page <= fusedLen+tailLen+2; page++ {
					window := hybridPageWindow(fusedLen, page, pageSize, tailLen > 0)
					if window.headFrom > window.headTo || window.headTo > fusedLen || window.tailLimit < 0 || window.tailOffset < 0 {
						t.Fatalf("fused=%d tail=%d size=%d page=%d: bad window %+v", fusedLen, tailLen, pageSize, page, window)
					}
					items := append([]string{}, fused[window.headFrom:window.headTo]...)
					if window.tailLimit > 0 && window.tailOffset < tailLen {
						items = append(items, tail[window.tailOffset:min(tailLen, window.tailOffset+window.tailLimit)]...)
					}
					if len(items) > pageSize {
						t.Fatalf("fused=%d tail=%d size=%d page=%d: %d items", fusedLen, tailLen, pageSize, page, len(items))
					}
					got = append(got, items...)
				}
				if want := append(append([]string{}, fused...), tail...); strings.Join(got, ",") != strings.Join(want, ",") {
					t.Fatalf("fused=%d tail=%d size=%d: pages = %v, want %v", fusedLen, tailLen, pageSize, got, want)
				}
			}
		}
	}
}

func TestHybridPageWindowSkipsTailWhenHeadHoldsEverything(t *testing.T) {
	if got := hybridPageWindow(3, 2, 5, false); got != (hybridSlice{headFrom: 3, headTo: 3}) {
		t.Fatalf("window = %+v", got)
	}
	if got := hybridPageWindow(3, 1, 5, true); got != (hybridSlice{headFrom: 0, headTo: 3, tailLimit: 2, tailOffset: 0}) {
		t.Fatalf("window = %+v", got)
	}
	if got := hybridPageWindow(3, 3, 5, true); got != (hybridSlice{headFrom: 3, headTo: 3, tailLimit: 5, tailOffset: 7}) {
		t.Fatalf("window = %+v", got)
	}
}

// 参数位次：where（关键词 → 日期窗口 → 来源）→ order → limit，与 Python %s 元组一致。
func TestDocumentQuerySQLPlaceholderOrder(t *testing.T) {
	plan := documentSearchPlan{candidates: []string{"a_b", "c"}, window: &dateWindow{since: "2026-09-29", until: "2026-10-01"}}
	q := newDocumentQuery(plan, " ArXiv ")
	if q.source != "arxiv" || !reflect.DeepEqual(q.patterns, []string{"%a=_b%", "%c%"}) {
		t.Fatalf("query = %+v", q)
	}
	args := &sqlArgs{}
	where := q.whereSQL(args)
	wantWhere := "((COALESCE(title, '') ILIKE $1 ESCAPE '=' OR COALESCE(summary, '') ILIKE $2 ESCAPE '=' OR COALESCE(tags, '') ILIKE $3 ESCAPE '=')" +
		" OR (COALESCE(title, '') ILIKE $4 ESCAPE '=' OR COALESCE(summary, '') ILIKE $5 ESCAPE '=' OR COALESCE(tags, '') ILIKE $6 ESCAPE '='))" +
		" AND published_date >= $7 AND published_date < $8 AND source = $9"
	if where != wantWhere {
		t.Fatalf("where =\n%s\nwant\n%s", where, wantWhere)
	}
	order := q.orderSQL(args)
	if !strings.HasPrefix(order, "CASE WHEN COALESCE(title, '') ILIKE $10 ESCAPE '=' THEN 0 ") ||
		!strings.Contains(order, "ELSE 4 END ASC") ||
		!strings.Contains(order, "LEFT(published_date, 10) DESC") ||
		!strings.HasSuffix(order, `created_at DESC, id COLLATE "C" ASC`) {
		t.Fatalf("order = %s", order)
	}
	if limit := args.bind("LIMIT %s OFFSET %s", 20, 40); limit != "LIMIT $22 OFFSET $23" {
		t.Fatalf("limit = %s (args %d)", limit, len(args.values))
	}
	wantArgs := []any{"%a=_b%", "%a=_b%", "%a=_b%", "%c%", "%c%", "%c%", "2026-09-29", "2026-10-01", "arxiv"}
	if !reflect.DeepEqual(args.values[:9], wantArgs) {
		t.Fatalf("where args = %v", args.values[:9])
	}
}

func TestDocumentQueryWithoutKeywordsHasNoMatchClause(t *testing.T) {
	q := newDocumentQuery(documentSearchPlan{window: &dateWindow{since: "2026-09-29", until: "2026-10-01"}}, "")
	args := &sqlArgs{}
	if where := q.whereSQL(args); where != "published_date >= $1 AND published_date < $2" {
		t.Fatalf("where = %s", where)
	}
	if order := q.orderSQL(args); order != "LEFT(published_date, 10) DESC,\n                                 COALESCE(raw_score, score, 0) DESC,\n                                 created_at DESC, id COLLATE \"C\" ASC" {
		t.Fatalf("order = %q", order)
	}
}
