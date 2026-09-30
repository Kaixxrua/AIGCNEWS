package postgres

// documents.go 移植 backend/app/repositories/postgres_document_repository.py
// 的 search_document_page 及其候选词管线（_document_search_candidates），
// 以及 domain/search_semantics.py 的 normalize_search_query /
// TECHNICAL_TOKEN_RE / escape_like_literal 三个语义件。
//
// 语义对齐要点：
//   - normalize = NFKC + strip + 空白折叠（" ".join(split())）。
//   - casefold 用 golang.org/x/text/cases.Fold（全 Unicode 折叠，对齐 Python
//     str.casefold 的常见字符集行为）。
//   - 意图短语剥离等价 re.sub(escape(phrase), " ", IGNORECASE)——短语均为
//     小写 ASCII/中文，Go 侧按 rune 大小写不敏感匹配 ASCII 区间实现。
//   - 学习/帮我 前缀正则带 (?=[A-Za-z0-9]) 前瞻（RE2 不支持），手工扫描。
//   - TECHNICAL_TOKEN_RE 含同一前瞻，整体手工分词（交替优先级：字母数字词 →
//     点前导词 → CJK 连续段）。
//   - escape_like_literal: "="→"==" → "%"→"=%" → "_"→"=_"（顺序替换；
//     替换产物不含新特殊符，单趟 NewReplacer 等价）。

import (
	"context"
	"fmt"
	"log/slog"
	"math"
	"sort"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"golang.org/x/text/cases"
	"golang.org/x/text/unicode/norm"

	"aigcnews/mcp-go/internal/mcpapp"
)

// documentSearchIntentPhrases / documentSearchStopTerms 逐字搬运
// postgres_document_repository.py 的 _DOCUMENT_SEARCH_INTENT_PHRASES /
// _DOCUMENT_SEARCH_STOP_TERMS。
var documentSearchIntentPhrases = []string{
	"learning resources", "learning materials", "help me find", "i would like to",
	"related content", "找一些", "找一点", "相关的内容", "相关内容", "学习资料",
	"学习材料", "进行学习", "我想要", "帮我找", "i want to", "find me",
}

var documentSearchStopTerms = map[string]bool{
	"about": true, "content": true, "find": true, "help": true, "learn": true,
	"learning": true, "material": true, "materials": true, "related": true,
	"resource": true, "resources": true, "tutorial": true, "tutorials": true,
	"want": true, "学习": true, "内容": true, "帮我": true, "教程": true, "资料": true,
}

var caseFolder = cases.Fold()

// normalizeSearchQuery 复刻 normalize_search_query：NFKC + strip + split-join。
func normalizeSearchQuery(value string) string {
	normalized := norm.NFKC.String(value)
	return strings.Join(strings.Fields(strings.TrimSpace(normalized)), " ")
}

// escapeLikeLiteral 复刻 escape_like_literal(escape="=")。
var escapeLikeLiteral = strings.NewReplacer("=", "==", "%", "=%", "_", "=_")

// caseInsensitiveReplaceAll 等价 re.sub(re.escape(phrase), " ", s, IGNORECASE)。
// 短语字符仅小写 ASCII/中文/空格：ASCII 字母按大小写不敏感比较，其余 rune
// 精确相等（Python IGNORECASE 对 ſ/K 等长者的额外匹配是未记录的边角，
// 生产查询与语料均不触发）。
func caseInsensitiveReplaceAll(s, phrase string) string {
	sRunes := []rune(s)
	pRunes := []rune(phrase)
	var out strings.Builder
	i := 0
	for i < len(sRunes) {
		if i+len(pRunes) <= len(sRunes) && runesEqualFoldASCII(sRunes[i:i+len(pRunes)], pRunes) {
			out.WriteByte(' ')
			i += len(pRunes)
			continue
		}
		out.WriteRune(sRunes[i])
		i++
	}
	return out.String()
}

func runesEqualFoldASCII(a, b []rune) bool {
	for i := range a {
		ra, rb := a[i], b[i]
		if ra >= 'A' && ra <= 'Z' {
			ra += 'a' - 'A'
		}
		if rb >= 'A' && rb <= 'Z' {
			rb += 'a' - 'A'
		}
		if ra != rb {
			return false
		}
	}
	return true
}

// learningPrefixSeparators 对应前缀正则字符类 [\s,，。！？!?;:：；]。
// Python re 的 \s 在 str 模式含 \x1c-\x1f，Go unicode.IsSpace 不含——边角已记录。
func isLearningPrefixSeparator(r rune) bool {
	if unicode.IsSpace(r) {
		return true
	}
	switch r {
	case ',', '，', '。', '！', '？', '!', '?', ';', ':', '：', '；':
		return true
	}
	return false
}

// stripLearningHelpPrefixes 等价
// re.sub(r"(^|[\s,，。！？!?;:：；])(?:学习|帮我)(?=[A-Za-z0-9])", r"\1", s)：
// 前瞻不消费字符，RE2 不可用，手工扫描；前瞻字符是字母数字，不会成为下一次
// 匹配的分隔符，故逐段跳词即可保持 Python 的非重叠左到右语义。
func stripLearningHelpPrefixes(s string) string {
	runes := []rune(s)
	var out strings.Builder
	i := 0
	for i < len(runes) {
		if i == 0 || isLearningPrefixSeparator(runes[i-1]) {
			wordLen := 0
			if rest := runes[i:]; len(rest) >= 2 && rest[0] == '学' && rest[1] == '习' {
				wordLen = 2
			} else if len(rest) >= 2 && rest[0] == '帮' && rest[1] == '我' {
				wordLen = 2
			}
			if wordLen > 0 && i+wordLen < len(runes) && isASCIIAlnum(runes[i+wordLen]) {
				i += wordLen
				continue
			}
		}
		out.WriteRune(runes[i])
		i++
	}
	return out.String()
}

func isASCIIAlnum(r rune) bool {
	return isASCIILetter(r) || r >= '0' && r <= '9'
}

func isASCIILetter(r rune) bool {
	return r >= 'A' && r <= 'Z' || r >= 'a' && r <= 'z'
}

func isCJKTokenRune(r rune) bool {
	return r >= 0x3400 && r <= 0x4DBF || r >= 0x4E00 && r <= 0x9FFF
}

// technicalTokens 复刻 TECHNICAL_TOKEN_RE.findall：
//
//	[A-Za-z0-9](?:[A-Za-z0-9_+#-]|\.(?=[A-Za-z0-9]))*  |  字母数字词（点后续字母数字可并入）
//	\.[A-Za-z][A-Za-z0-9]*                              |  点前导词
//	[㐀-䶿一-鿿]+                                        |  CJK 连续段
//
// findall 语义：从左到右扫描，每个位置先尝交替首项；未匹配则前进一个字符。
// 注意 Python re 按字符前进（不是按 rune 之外的任何粒度），Go 侧按 rune 前进。
func technicalTokens(s string) []string {
	runes := []rune(s)
	var tokens []string
	i := 0
	for i < len(runes) {
		switch r := runes[i]; {
		case isASCIIAlnum(r):
			// 交替首项：首字符字母数字，续接 [A-Za-z0-9_+#-] 或 ".[字母数字]"。
			end := i + 1
			for end < len(runes) {
				c := runes[end]
				if isASCIIAlnum(c) || c == '_' || c == '+' || c == '#' || c == '-' {
					end++
					continue
				}
				if c == '.' && end+1 < len(runes) && isASCIIAlnum(runes[end+1]) {
					end++
					continue
				}
				break
			}
			tokens = append(tokens, string(runes[i:end]))
			i = end
		case r == '.' && i+1 < len(runes) && isASCIILetter(runes[i+1]):
			// 交替次项：. 后接 ASCII 字母，再接字母数字。
			end := i + 2
			for end < len(runes) && isASCIIAlnum(runes[end]) {
				end++
			}
			tokens = append(tokens, string(runes[i:end]))
			i = end
		case isCJKTokenRune(r):
			end := i + 1
			for end < len(runes) && isCJKTokenRune(runes[end]) {
				end++
			}
			tokens = append(tokens, string(runes[i:end]))
			i = end
		default:
			i++
		}
	}
	return tokens
}

// documentSearchPlan 是 DocumentSearchPlan 的 Go 对应物：ILIKE 候选词
// （按优先级）+ 可选 published_date 窗口；candidates 空而 window 非空 =
// 纯时间查询，只按日期过滤。
type documentSearchPlan struct {
	candidates []string
	window     *dateWindow
	// semantic 是语义通道的查询文本（Go 独有，Python 参考实现无语义通道）：
	// 提问式查询用剥掉时间短语后的原句，其余用归一化原句；无关键词时为空。
	semantic string
}

// documentSearchCandidates 复刻 _document_search_candidates(query, max_terms=5)。
func documentSearchCandidates(query string, maxTerms int, today time.Time) []string {
	return buildDocumentSearchPlan(query, maxTerms, today).candidates
}

// buildDocumentSearchPlan 复刻 _document_search_plan(query, today, max_terms)。
func buildDocumentSearchPlan(query string, maxTerms int, today time.Time) documentSearchPlan {
	normalized := normalizeSearchQuery(query)
	if normalized == "" {
		return documentSearchPlan{}
	}
	lowered := caseFolder.String(normalized)
	hasIntent := false
	for _, phrase := range documentSearchIntentPhrases {
		if strings.Contains(lowered, phrase) {
			hasIntent = true
			break
		}
	}
	intent := parseQueryIntent(normalized, today)
	// 提问式查询（带时间意图或提问词）：先剥时间短语，后续再剥问句外壳。
	asks := intent.window != nil || intent.asks
	if !hasIntent && !asks && utf8.RuneCountInString(normalized) <= 48 {
		return documentSearchPlan{candidates: []string{normalized}, semantic: normalized}
	}
	cleaned := normalized
	if asks {
		cleaned = intent.remainder
	}
	for _, phrase := range intentPhrasesByLengthDesc() {
		cleaned = caseInsensitiveReplaceAll(cleaned, phrase)
	}
	if asks {
		cleaned = stripAskFillers(cleaned)
	}
	cleaned = stripLearningHelpPrefixes(cleaned)
	cleaned = strings.Join(strings.Fields(strings.Trim(cleaned, " ，。！？,.!?;:：；")), " ")
	if asks && intent.window != nil && !hasSearchKeyword(cleaned) {
		return documentSearchPlan{window: intent.window}
	}
	candidates := []string{normalized}
	cleanedFolded := caseFolder.String(cleaned)
	residualIntent := false
	for term := range documentSearchStopTerms {
		if strings.Contains(cleanedFolded, term) {
			residualIntent = true
			break
		}
	}
	if cleaned != "" && !residualIntent && cleanedFolded != lowered {
		candidates = append(candidates, cleaned)
	}
	seen := map[string]bool{}
	for _, candidate := range candidates {
		seen[caseFolder.String(candidate)] = true
	}
	var technicalTerms []string
	tokenSource := cleaned
	if tokenSource == "" {
		tokenSource = normalized
	}
	limit := maxTerms
	if limit > 5 {
		limit = 5
	}
	if limit < 1 {
		limit = 1
	}
	for _, token := range technicalTokens(tokenSource) {
		key := caseFolder.String(token)
		if documentSearchStopTerms[key] || seen[key] {
			continue
		}
		if utf8.RuneCountInString(token) == 1 && !unicode.IsDigit(rune(token[0])) {
			continue
		}
		seen[key] = true
		technicalTerms = append(technicalTerms, token)
		if len(technicalTerms) >= limit {
			break
		}
	}
	if len(technicalTerms) > 1 {
		hasNonAI := false
		for _, term := range technicalTerms {
			if caseFolder.String(term) != "ai" {
				hasNonAI = true
				break
			}
		}
		if hasNonAI {
			filtered := technicalTerms[:0]
			for _, term := range technicalTerms {
				if caseFolder.String(term) != "ai" {
					filtered = append(filtered, term)
				}
			}
			technicalTerms = filtered
		}
	}
	semantic := normalized
	if asks {
		semantic = intent.remainder
	}
	return documentSearchPlan{candidates: append(candidates, technicalTerms...), window: intent.window, semantic: semantic}
}

// hasSearchKeyword 复刻 _has_keyword：剥壳后是否还剩可检索的词
// （停用词、标点残渣与单个非数字字符不算）。
func hasSearchKeyword(cleaned string) bool {
	for _, token := range technicalTokens(cleaned) {
		if documentSearchStopTerms[caseFolder.String(token)] {
			continue
		}
		if utf8.RuneCountInString(token) > 1 || unicode.IsDigit([]rune(token)[0]) {
			return true
		}
	}
	return false
}

// intentPhrasesByLengthDesc 对齐 sorted(phrases, key=len, reverse=True)；
// Python len 是字符数，且 sorted 稳定（等长保持声明序）。
var intentPhrasesByLengthDesc = func() func() []string {
	phrases := append([]string(nil), documentSearchIntentPhrases...)
	// 稳定插入排序（列表仅 16 项）：按 rune 数降序，等长保持原序。
	for i := 1; i < len(phrases); i++ {
		for j := i; j > 0 && utf8.RuneCountInString(phrases[j-1]) < utf8.RuneCountInString(phrases[j]); j-- {
			phrases[j-1], phrases[j] = phrases[j], phrases[j-1]
		}
	}
	return func() []string { return phrases }
}()

// SemanticDocumentSearcher 是语义召回通道（docsemantic.Retriever 实现）：
// 返回按相似度降序的文档 id，since/until 为 [since, until) 的 YYYY-MM-DD。
type SemanticDocumentSearcher interface {
	SearchDocumentIDs(query, source, since, until string) ([]string, error)
}

// DocumentRepository 适配 documents 表的 MCP 检索读路径。timezone 对应
// settings.scheduler_timezone：时间意图（昨晚/今天/最近N天）以该时区自然日为锚。
type DocumentRepository struct {
	pool     *pgxpool.Pool
	timezone string
	now      func() time.Time
	semantic SemanticDocumentSearcher
}

func NewDocumentRepository(pool *pgxpool.Pool, timezone string) *DocumentRepository {
	if timezone == "" {
		timezone = "Asia/Shanghai"
	}
	return &DocumentRepository{pool: pool, timezone: timezone, now: time.Now}
}

// WithSemantic 打开关键词 + 语义混合检索；nil 保持纯关键词行为。
func (r *DocumentRepository) WithSemantic(searcher SemanticDocumentSearcher) *DocumentRepository {
	r.semantic = searcher
	return r
}

// localToday 复刻 _local_today()：调度时区当前自然日；时区名非法时回退 UTC+8
// （Python 侧 ZoneInfo 会直接抛错，这里宁可给出可用锚点也不让检索失败）。
func (r *DocumentRepository) localToday() time.Time {
	zone, err := time.LoadLocation(r.timezone)
	if err != nil {
		zone = time.FixedZone("CST", 8*3600)
	}
	return r.now().In(zone)
}

const documentSelectColumns = `id, source, source_channel, title, url, summary,
                               published_date, tags, score, raw_score, rank_in_period,
                               local_pdf_path, authors, arxiv_id, created_at`

const documentFieldMatch = "(COALESCE(title, '') ILIKE %s ESCAPE '=' OR COALESCE(summary, '') ILIKE %s ESCAPE '=' OR COALESCE(tags, '') ILIKE %s ESCAPE '=')"

// sqlArgs 按出现顺序把 fragment 里的 %s 改写成 $N 并收集参数，使 Python
// 的 %s 元组位次与 pgx 占位符一一对应。
type sqlArgs struct{ values []any }

func (a *sqlArgs) bind(fragment string, values ...any) string {
	for _, value := range values {
		a.values = append(a.values, value)
		fragment = strings.Replace(fragment, "%s", fmt.Sprintf("$%d", len(a.values)), 1)
	}
	return fragment
}

// documentQuery 是一次检索的 SQL 片段来源：ILIKE 模式 + 可选日期窗口 + 可选来源。
type documentQuery struct {
	patterns []string
	window   *dateWindow
	source   string
}

func newDocumentQuery(plan documentSearchPlan, source string) documentQuery {
	patterns := make([]string, len(plan.candidates))
	for i, candidate := range plan.candidates {
		patterns[i] = "%" + escapeLikeLiteral.Replace(candidate) + "%"
	}
	return documentQuery{patterns: patterns, window: plan.window, source: strings.ToLower(strings.TrimSpace(source))}
}

// matchSQL 是关键词命中条件（任一模式命中标题/摘要/标签）；无模式时为空串。
func (q documentQuery) matchSQL(args *sqlArgs) string {
	if len(q.patterns) == 0 {
		return ""
	}
	var match strings.Builder
	match.WriteByte('(')
	for i, pattern := range q.patterns {
		if i > 0 {
			match.WriteString(" OR ")
		}
		match.WriteString(args.bind(documentFieldMatch, pattern, pattern, pattern))
	}
	match.WriteByte(')')
	return match.String()
}

// filterSQL 是与关键词无关的硬过滤（日期窗口、来源），语义命中同样要满足。
func (q documentQuery) filterSQL(args *sqlArgs) []string {
	var parts []string
	if q.window != nil {
		// published_date 是 YYYY-MM-DD 前缀的 VARCHAR（arXiv 带 T 时刻），字典序即时间序。
		parts = append(parts, args.bind("published_date >= %s AND published_date < %s", q.window.since, q.window.until))
	}
	if q.source != "" {
		parts = append(parts, args.bind("source = %s", q.source))
	}
	return parts
}

func (q documentQuery) whereSQL(args *sqlArgs) string {
	var parts []string
	if match := q.matchSQL(args); match != "" {
		parts = append(parts, match)
	}
	return strings.Join(append(parts, q.filterSQL(args)...), " AND ")
}

func (q documentQuery) orderSQL(args *sqlArgs) string {
	var parts []string
	if len(q.patterns) > 0 {
		var tier strings.Builder
		tier.WriteString("CASE ")
		for index, pattern := range q.patterns {
			fmt.Fprintf(&tier, "%s ", args.bind(fmt.Sprintf("WHEN COALESCE(title, '') ILIKE %%s ESCAPE '=' THEN %d", index*2), pattern))
			fmt.Fprintf(&tier, "%s ", args.bind(fmt.Sprintf("WHEN (COALESCE(summary, '') ILIKE %%s ESCAPE '=' OR COALESCE(tags, '') ILIKE %%s ESCAPE '=') THEN %d", index*2+1), pattern, pattern))
		}
		fmt.Fprintf(&tier, "ELSE %d END ASC", len(q.patterns)*2)
		parts = append(parts, tier.String())
		counts := make([]string, len(q.patterns))
		for i, pattern := range q.patterns {
			counts[i] = "CASE WHEN " + args.bind(documentFieldMatch, pattern, pattern, pattern) + " THEN 1 ELSE 0 END"
		}
		parts = append(parts, "("+strings.Join(counts, " + ")+") DESC")
	}
	if q.window != nil {
		// 只比日期：arXiv 的 T 时刻后缀不应压过同日其他源，同日内交给热度。
		parts = append(parts, "LEFT(published_date, 10) DESC")
	}
	parts = append(parts, "COALESCE(raw_score, score, 0) DESC", `created_at DESC, id COLLATE "C" ASC`)
	return strings.Join(parts, ",\n                                 ")
}

// SearchDocumentPage 复刻 search_document_page：检索计划 → ILIKE 模式 +
// 可选 published_date 窗口 → COUNT 与 SELECT 同一事务（Python 用单个
// transaction 块；pgx 侧用单连接隐式事务等价）。配置了语义通道且查询含
// 关键词时改走 hybridPage（Go 独有；Python 参考实现保持纯关键词）。
//
// 参数位次与 Python %s 元组一一对应（where → order → limit/offset），
// 仅占位符从 %s 改写为 $N。
func (r *DocumentRepository) SearchDocumentPage(query, source string, page, pageSize int) (mcpapp.DocumentPage, error) {
	plan := buildDocumentSearchPlan(query, 5, r.localToday())
	if page < 1 {
		page = 1
	}
	if pageSize < 1 {
		pageSize = 1
	} else if pageSize > 100 {
		pageSize = 100
	}
	if len(plan.candidates) == 0 && plan.window == nil {
		return mcpapp.DocumentPage{Items: []mcpapp.DocumentRow{}, Total: 0}, nil
	}
	q := newDocumentQuery(plan, source)
	if r.semantic != nil && len(q.patterns) > 0 && strings.TrimSpace(plan.semantic) != "" {
		return r.hybridPage(q, plan.semantic, page, pageSize)
	}

	ctx := context.Background() // 对齐 asyncio.to_thread 语义：跑完不随客户端断连取消。
	tx, err := r.pool.Begin(ctx)
	if err != nil {
		return mcpapp.DocumentPage{}, fmt.Errorf("postgres: 文档搜索事务开启失败: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()

	args := &sqlArgs{}
	whereSQL := q.whereSQL(args)
	whereParams := append([]any(nil), args.values...)
	var total int
	if err := tx.QueryRow(ctx,
		"SELECT COUNT(*) AS cnt FROM documents WHERE "+whereSQL, whereParams...,
	).Scan(&total); err != nil {
		return mcpapp.DocumentPage{}, fmt.Errorf("postgres: 文档搜索计数失败: %w", err)
	}

	orderSQL := q.orderSQL(args)
	limitSQL := args.bind("LIMIT %s OFFSET %s", pageSize, (page-1)*pageSize)
	rows, err := tx.Query(ctx, fmt.Sprintf(`SELECT %s
                        FROM documents WHERE %s
                        ORDER BY %s
                        %s`, documentSelectColumns, whereSQL, orderSQL, limitSQL), args.values...)
	if err != nil {
		return mcpapp.DocumentPage{}, fmt.Errorf("postgres: 文档搜索查询失败: %w", err)
	}
	items, err := scanDocumentRows(rows)
	if err != nil {
		return mcpapp.DocumentPage{}, err
	}
	if err := tx.Commit(ctx); err != nil {
		return mcpapp.DocumentPage{}, fmt.Errorf("postgres: 文档搜索事务提交失败: %w", err)
	}
	return mcpapp.DocumentPage{Items: items, Total: total}, nil
}

func scanDocumentRows(rows pgx.Rows) ([]mcpapp.DocumentRow, error) {
	defer rows.Close()
	items := []mcpapp.DocumentRow{}
	for rows.Next() {
		var row mcpapp.DocumentRow
		var rawScore *float64
		if err := rows.Scan(
			&row.ID, &row.Source, &row.SourceChannel, &row.Title, &row.URL,
			&row.Summary, &row.PublishedDate, &row.Tags, &row.Score, &rawScore,
			&row.RankInPeriod, &row.LocalPDFPath, &row.Authors, &row.ArxivID,
			&row.CreatedAt,
		); err != nil {
			return nil, fmt.Errorf("postgres: 文档行扫描失败: %w", err)
		}
		row.RawScore = rawScore
		items = append(items, row)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("postgres: 文档行读取失败: %w", err)
	}
	return items, nil
}

// 混合检索参数：关键词取前 hybridLexicalDepth 名参与融合，更深的关键词结果
// 按原关键词序接在融合结果之后；RRF 常数取业界惯用的 60。
const (
	hybridLexicalDepth   = 200
	hybridRRFConstant    = 60
	hybridLexicalWeight  = 1.0
	hybridSemanticWeight = 1.0
)

type semanticOutcome struct {
	ids []string
	err error
}

// hybridPage 是关键词 + 语义混合检索：
//
//  1. 语义召回（embedding + Milvus，带同样的来源/日期过滤）与关键词前
//     hybridLexicalDepth 名并行；
//  2. 语义命中回 PG 复核过滤条件并标记是否本就被关键词命中；
//  3. 两路按 RRF 融合成头部序列 F，F 之后接关键词序里不在 F 的其余结果；
//  4. total = 关键词命中数 + 仅语义命中数（即 F ∪ 关键词全集 的大小）。
//
// 语义通道任何失败都只记日志并按纯关键词顺序返回（头部即关键词前 N 名）。
func (r *DocumentRepository) hybridPage(q documentQuery, semanticQuery string, page, pageSize int) (mcpapp.DocumentPage, error) {
	since, until := "", ""
	if q.window != nil {
		since, until = q.window.since, q.window.until
	}
	semanticDone := make(chan semanticOutcome, 1)
	go func() {
		ids, err := r.semantic.SearchDocumentIDs(semanticQuery, q.source, since, until)
		semanticDone <- semanticOutcome{ids: ids, err: err}
	}()

	ctx := context.Background()
	tx, err := r.pool.Begin(ctx)
	if err != nil {
		return mcpapp.DocumentPage{}, fmt.Errorf("postgres: 文档搜索事务开启失败: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()

	lexical, lexicalTotal, err := lexicalHead(ctx, tx, q, hybridLexicalDepth)
	if err != nil {
		return mcpapp.DocumentPage{}, err
	}
	outcome := <-semanticDone
	var semantic []string
	semanticOnly := 0
	if outcome.err != nil {
		slog.Warn("[DocumentSearch] 语义通道不可用，回落纯关键词", "err", outcome.err)
	} else if len(outcome.ids) > 0 {
		verified, lexicalMatch, err := verifySemanticHits(ctx, tx, q, outcome.ids)
		if err != nil {
			return mcpapp.DocumentPage{}, err
		}
		semantic = verified
		for _, id := range verified {
			if !lexicalMatch[id] {
				semanticOnly++
			}
		}
	}

	fused := fuseDocumentRankings(lexical, semantic)
	window := hybridPageWindow(len(fused), page, pageSize, lexicalTotal > len(lexical))
	pageIDs := append([]string{}, fused[window.headFrom:window.headTo]...)
	if window.tailLimit > 0 {
		tail, err := lexicalTail(ctx, tx, q, fused, window.tailLimit, window.tailOffset)
		if err != nil {
			return mcpapp.DocumentPage{}, err
		}
		pageIDs = append(pageIDs, tail...)
	}
	items, err := documentsByIDs(ctx, tx, pageIDs)
	if err != nil {
		return mcpapp.DocumentPage{}, err
	}
	if err := tx.Commit(ctx); err != nil {
		return mcpapp.DocumentPage{}, fmt.Errorf("postgres: 文档搜索事务提交失败: %w", err)
	}
	return mcpapp.DocumentPage{Items: items, Total: lexicalTotal + semanticOnly}, nil
}

// lexicalHead 取关键词序前 depth 名 id 与关键词命中总数（窗口函数先于
// LIMIT 计算，一次往返拿到两者）。
func lexicalHead(ctx context.Context, tx pgx.Tx, q documentQuery, depth int) ([]string, int, error) {
	args := &sqlArgs{}
	where := q.whereSQL(args)
	order := q.orderSQL(args)
	limit := args.bind("LIMIT %s", depth)
	rows, err := tx.Query(ctx, "SELECT id, COUNT(*) OVER () AS total FROM documents WHERE "+where+" ORDER BY "+order+" "+limit, args.values...)
	if err != nil {
		return nil, 0, fmt.Errorf("postgres: 文档关键词召回失败: %w", err)
	}
	defer rows.Close()
	var ids []string
	total := 0
	for rows.Next() {
		var id string
		if err := rows.Scan(&id, &total); err != nil {
			return nil, 0, fmt.Errorf("postgres: 文档关键词召回扫描失败: %w", err)
		}
		ids = append(ids, id)
	}
	if err := rows.Err(); err != nil {
		return nil, 0, fmt.Errorf("postgres: 文档关键词召回读取失败: %w", err)
	}
	return ids, total, nil
}

// verifySemanticHits 让语义命中服从与关键词同样的硬过滤（Milvus 侧过滤只是
// 预筛，PG 为准；已删除文档自然落空），保持语义序，并标出哪些本就命中关键词。
func verifySemanticHits(ctx context.Context, tx pgx.Tx, q documentQuery, ids []string) ([]string, map[string]bool, error) {
	args := &sqlArgs{}
	match := q.matchSQL(args)
	where := []string{args.bind("id = ANY(%s)", ids)}
	where = append(where, q.filterSQL(args)...)
	rows, err := tx.Query(ctx, "SELECT id, "+match+" AS lexical FROM documents WHERE "+strings.Join(where, " AND "), args.values...)
	if err != nil {
		return nil, nil, fmt.Errorf("postgres: 文档语义命中复核失败: %w", err)
	}
	defer rows.Close()
	lexicalMatch := map[string]bool{}
	for rows.Next() {
		var id string
		var lexical bool
		if err := rows.Scan(&id, &lexical); err != nil {
			return nil, nil, fmt.Errorf("postgres: 文档语义命中扫描失败: %w", err)
		}
		lexicalMatch[id] = lexical
	}
	if err := rows.Err(); err != nil {
		return nil, nil, fmt.Errorf("postgres: 文档语义命中读取失败: %w", err)
	}
	verified := make([]string, 0, len(lexicalMatch))
	for _, id := range ids {
		if _, ok := lexicalMatch[id]; ok {
			verified = append(verified, id)
		}
	}
	return verified, lexicalMatch, nil
}

// hybridSlice 是一页在融合头部 fused[headFrom:headTo] 与关键词尾部
// （LIMIT tailLimit OFFSET tailOffset；tailLimit 为 0 表示不查）上的切分。
type hybridSlice struct {
	headFrom, headTo      int
	tailLimit, tailOffset int
}

// hybridPageWindow 把第 page 页映射到"融合头部 + 关键词尾部"这条虚拟序列上；
// hasTail 为假（关键词全集已在头部）时不查尾部。
func hybridPageWindow(fusedLen, page, pageSize int, hasTail bool) hybridSlice {
	offset := (page - 1) * pageSize
	end := offset + pageSize
	window := hybridSlice{headFrom: min(offset, fusedLen), headTo: min(end, fusedLen)}
	if hasTail && end > fusedLen {
		window.tailLimit = end - max(offset, fusedLen)
		window.tailOffset = max(0, offset-fusedLen)
	}
	return window
}

// lexicalTail 按关键词序取不在融合头部里的结果。
func lexicalTail(ctx context.Context, tx pgx.Tx, q documentQuery, exclude []string, limit, offset int) ([]string, error) {
	args := &sqlArgs{}
	where := q.whereSQL(args) + " AND NOT (" + args.bind("id = ANY(%s)", exclude) + ")"
	order := q.orderSQL(args)
	page := args.bind("LIMIT %s OFFSET %s", limit, offset)
	rows, err := tx.Query(ctx, "SELECT id FROM documents WHERE "+where+" ORDER BY "+order+" "+page, args.values...)
	if err != nil {
		return nil, fmt.Errorf("postgres: 文档关键词续页失败: %w", err)
	}
	defer rows.Close()
	var ids []string
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, fmt.Errorf("postgres: 文档关键词续页扫描失败: %w", err)
		}
		ids = append(ids, id)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("postgres: 文档关键词续页读取失败: %w", err)
	}
	return ids, nil
}

// documentsByIDs 取整行并按 ids 顺序返回（缺失的 id 跳过）。
func documentsByIDs(ctx context.Context, tx pgx.Tx, ids []string) ([]mcpapp.DocumentRow, error) {
	if len(ids) == 0 {
		return []mcpapp.DocumentRow{}, nil
	}
	rows, err := tx.Query(ctx, "SELECT "+documentSelectColumns+" FROM documents WHERE id = ANY($1)", ids)
	if err != nil {
		return nil, fmt.Errorf("postgres: 文档取行失败: %w", err)
	}
	found, err := scanDocumentRows(rows)
	if err != nil {
		return nil, err
	}
	byID := make(map[string]mcpapp.DocumentRow, len(found))
	for _, row := range found {
		if row.ID != nil {
			byID[*row.ID] = row
		}
	}
	items := make([]mcpapp.DocumentRow, 0, len(ids))
	for _, id := range ids {
		if row, ok := byID[id]; ok {
			items = append(items, row)
		}
	}
	return items, nil
}

// fuseDocumentRankings 是加权 RRF：score = Σ w/(k+rank)，rank 从 1 起、每路
// 先按首次出现去重。同分按关键词名次、语义名次、id 依次决胜，保证分页稳定。
func fuseDocumentRankings(lexical, semantic []string) []string {
	type fused struct {
		id           string
		score        float64
		lexicalRank  int
		semanticRank int
	}
	byID := map[string]*fused{}
	var order []*fused
	accumulate := func(ids []string, weight float64, setRank func(*fused, int)) {
		seen := make(map[string]bool, len(ids))
		rank := 0
		for _, id := range ids {
			if seen[id] {
				continue
			}
			seen[id] = true
			rank++
			item, ok := byID[id]
			if !ok {
				item = &fused{id: id}
				byID[id] = item
				order = append(order, item)
			}
			item.score += weight / float64(hybridRRFConstant+rank)
			setRank(item, rank)
		}
	}
	accumulate(lexical, hybridLexicalWeight, func(item *fused, rank int) { item.lexicalRank = rank })
	accumulate(semantic, hybridSemanticWeight, func(item *fused, rank int) { item.semanticRank = rank })
	absentLast := func(rank int) int {
		if rank == 0 {
			return math.MaxInt
		}
		return rank
	}
	sort.Slice(order, func(i, j int) bool {
		a, b := order[i], order[j]
		if a.score != b.score {
			return a.score > b.score
		}
		if absentLast(a.lexicalRank) != absentLast(b.lexicalRank) {
			return absentLast(a.lexicalRank) < absentLast(b.lexicalRank)
		}
		if absentLast(a.semanticRank) != absentLast(b.semanticRank) {
			return absentLast(a.semanticRank) < absentLast(b.semanticRank)
		}
		return a.id < b.id
	})
	ids := make([]string, len(order))
	for i, item := range order {
		ids[i] = item.id
	}
	return ids
}
