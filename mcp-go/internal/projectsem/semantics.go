package projectsem

// semantics.go 私有实现件。normalizeSearch / technicalTokenSpans /
// caseInsensitiveReplaceAll / caseFolder / isCJKTokenRune 与
// internal/postgres/documents.go 同名件同源复制（该包私有不可 import，
// PR 2.7 §5 契约允许复制）；pythonSpace 族与 internal/mcpapp/project_items.go
// 同款同源（Python 空白表 = unicode.IsSpace 并集 \x1c-\x1f）。
//
// 坐标系纪律（_project_concept_matches 的最大地雷）：查找在 casefold 后的
// 串上做（Python str.find 的码点下标），但选中文本用同一下标切**原串**
// （value[start:end]，越界钳制，空串回退 phrase）。casefold 变长字符
// （ß→ss、İ→i̇ 等）会让两坐标系错位——Python 原样承受该错位，Go 必须
// 逐字复刻而非「修正」。

import (
	"cmp"
	"errors"
	"slices"
	"strings"
	"unicode"
	"unicode/utf8"

	"golang.org/x/text/cases"
	"golang.org/x/text/unicode/norm"
)

var caseFolder = cases.Fold()

// 三条错误文案逐字对齐 Python ValueError 消息。
var (
	// errIntentValues 对应 normalize_client_intent_values 的两处 ValueError
	// （控制字符 / 归一后空或超长，同一条消息）。
	errIntentValues = errors.New("intent values must be non-empty, bounded text without control characters")
	// errClientSlots 对应 build_client_project_search_intent 的空槽位校验。
	errClientSlots = errors.New("client intent requires lexical_terms and semantic_queries")
	// errProtectedTokens 对应受保护 token 校验失败。
	errProtectedTokens = errors.New("client intent must preserve protected technical tokens from q")
)

// fold 等价 Python str.casefold()（全 Unicode 折叠；x/text cases.Fold 与
// Python 同遵 CaseFolding.txt C+F 映射，Unicode 表版本差是已记录近似）。
func fold(s string) string {
	return caseFolder.String(s)
}

// pythonSpace 复刻 Python str.isspace()/split()/strip() 的空白表：
// unicode.IsSpace 并集 \x1c-\x1f（FS/GS/RS/US，Python 因历史原因计入，
// Unicode White_Space 属性不含）。
func pythonSpace(r rune) bool {
	return unicode.IsSpace(r) || (r >= 0x1c && r <= 0x1f)
}

// pythonFields 等价 Python str.split()（无参）：按空白游程切分，丢弃空段。
func pythonFields(s string) []string {
	return strings.FieldsFunc(s, pythonSpace)
}

// pythonTrim / pythonTrimRight 等价 Python str.strip()/str.rstrip()（无参）。
func pythonTrim(s string) string {
	return strings.TrimFunc(s, pythonSpace)
}

func pythonTrimRight(s string) string {
	return strings.TrimRightFunc(s, pythonSpace)
}

// normalizeSearch 复刻 normalize_search_query：
// " ".join(NFKC(value).strip().split())（Python 锚点 search_semantics.py:762-763）。
// value or "" 的 None 防御在 Go 签名（恒 string）下不可达。
func normalizeSearch(value string) string {
	normalized := norm.NFKC.String(value)
	return strings.Join(pythonFields(pythonTrim(normalized)), " ")
}

// projectRequestPhrases 逐字搬运 _PROJECT_REQUEST_PHRASES（7 条，顺序敏感：
// 逐条 re.sub(escape(phrase), " ", IGNORECASE)，「帮我找一下」先于「帮我找」）。
var projectRequestPhrases = []string{
	"帮我找一下",
	"帮我找",
	"给我推荐",
	"我想要学习",
	"我想学习",
	"find me",
	"recommend me",
}

// projectTransportTerms 逐字搬运 _PROJECT_TRANSPORT_TERMS（9 条；词表本身
// 均为小写 ASCII/中文，casefold 后与原文相同）。
var projectTransportTerms = map[string]bool{
	"github": true, "repo": true, "repository": true, "repositories": true,
	"project": true, "projects": true,
	"项目": true, "仓库": true, "工具": true,
}

// protectedProjectTokens 逐字搬运 _PROTECTED_PROJECT_TOKENS（frozenset，
// casefold 比对；词表全小写 ASCII，原文即折叠态）。
var protectedProjectTokens = map[string]bool{
	"c++": true, "c#": true, ".net": true,
	"mcp": true, "rag": true, "langgraph": true,
}

// escapeLikeLiteralReplacer 复刻 escape_like_literal(escape="=") 的链式
// replace("=","==").replace("%","=%").replace("_","=_")：替换产物引入的
// "=" 不再被二次加倍，与单趟 NewReplacer（命中文本不重扫）语义一致。
var escapeLikeLiteralReplacer = strings.NewReplacer("=", "==", "%", "=%", "_", "=_")

// caseInsensitiveReplaceAll 等价 re.sub(re.escape(phrase), " ", s, IGNORECASE)。
// 词表短语仅小写 ASCII/中文/空格；unicode.SimpleFold 的等价类与 Python
// re.IGNORECASE 的单字符 Unicode case-insensitive 匹配一致（包括 ſ/K 等
// 四个 ASCII 交叉字符），且按 rune 扫描保持 re.sub 的非重叠左到右语义。
func caseInsensitiveReplaceAll(s, phrase string) string {
	sRunes := []rune(s)
	pRunes := []rune(phrase)
	var out strings.Builder
	i := 0
	for i < len(sRunes) {
		if i+len(pRunes) <= len(sRunes) && runesEqualIgnoreCase(sRunes[i:i+len(pRunes)], pRunes) {
			out.WriteByte(' ')
			i += len(pRunes)
			continue
		}
		out.WriteRune(sRunes[i])
		i++
	}
	return out.String()
}

func runesEqualIgnoreCase(a, b []rune) bool {
	for i := range a {
		if a[i] == b[i] {
			continue
		}
		matched := false
		for r := unicode.SimpleFold(a[i]); r != a[i]; r = unicode.SimpleFold(r) {
			if r == b[i] {
				matched = true
				break
			}
		}
		if !matched {
			return false
		}
	}
	return true
}

func isASCIIAlnum(r rune) bool {
	return isASCIILetter(r) || r >= '0' && r <= '9'
}

func isASCIILetter(r rune) bool {
	return r >= 'A' && r <= 'Z' || r >= 'a' && r <= 'z'
}

// isCJKTokenRune 对应 TECHNICAL_TOKEN_RE 与 _HAN_RE 的区间
// [㐀-䶿一-鿿] = U+3400–U+4DBF（CJK Ext A）∪ U+4E00–U+9FFF。
func isCJKTokenRune(r rune) bool {
	return r >= 0x3400 && r <= 0x4DBF || r >= 0x4E00 && r <= 0x9FFF
}

// tokenSpan 是 TECHNICAL_TOKEN_RE.finditer 的一个匹配：原文与起止 rune 下标
// （Python str 下标 = 码点）。
type tokenSpan struct {
	text       string
	start, end int
}

// technicalTokenSpans 复刻 TECHNICAL_TOKEN_RE.finditer：
//
//	[A-Za-z0-9](?:[A-Za-z0-9_+#-]|\.(?=[A-Za-z0-9]))*  |  字母数字词（点后续字母数字可并入）
//	\.[A-Za-z][A-Za-z0-9]*                              |  点前导词
//	[㐀-䶿一-鿿]+                                        |  CJK 连续段
//
// finditer 语义：从左到右扫描，每个位置先尝交替首项；未匹配则前进一个字符。
// Go RE2 无前瞻，整体手工分词（与 documents.go technicalTokens 同源）。
func technicalTokenSpans(s string) []tokenSpan {
	runes := []rune(s)
	var tokens []tokenSpan
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
			tokens = append(tokens, tokenSpan{text: string(runes[i:end]), start: i, end: end})
			i = end
		case r == '.' && i+1 < len(runes) && isASCIILetter(runes[i+1]):
			// 交替次项：. 后接 ASCII 字母，再接字母数字。
			end := i + 2
			for end < len(runes) && isASCIIAlnum(runes[end]) {
				end++
			}
			tokens = append(tokens, tokenSpan{text: string(runes[i:end]), start: i, end: end})
			i = end
		case isCJKTokenRune(r):
			end := i + 1
			for end < len(runes) && isCJKTokenRune(runes[end]) {
				end++
			}
			tokens = append(tokens, tokenSpan{text: string(runes[i:end]), start: i, end: end})
			i = end
		default:
			i++
		}
	}
	return tokens
}

// technicalTokens 复刻 TECHNICAL_TOKEN_RE.findall（finditer 的 group(0) 序列）。
func technicalTokens(s string) []string {
	spans := technicalTokenSpans(s)
	tokens := make([]string, 0, len(spans))
	for _, sp := range spans {
		tokens = append(tokens, sp.text)
	}
	return tokens
}

// containsHan 等价 bool(_HAN_RE.search(s))。
func containsHan(s string) bool {
	for _, r := range s {
		if isCJKTokenRune(r) {
			return true
		}
	}
	return false
}

// pyIsDigit 对齐 Python str.isdigit() 的单字符判定。Python isdigit 认
// Numeric_Type ∈ {Decimal, Digit}；Go unicode.IsDigit 只认 Nd（Decimal）。
// 差异字符（²、① 等 Digit 型）要成为判定对象，须作为概念选中文本被切成
// 单 rune——这要求 casefold 变长字符在查询中精确错位叠加（见文件头坐标系
// 注释），生产查询与对拍语料不可达；TECHNICAL_TOKEN_RE 产物的单字符仅
// ASCII 字母数字或 CJK 表意文字，两实现判定恒等（CJK 数字「一」的
// isdigit() 为 False，IsDigit 亦为 False）。
func pyIsDigit(r rune) bool {
	return unicode.IsDigit(r)
}

// truncateRunes 等价 Python s[:maxChars]（按码点截断；maxChars 恒正，
// 负值切片语义不可达）。
func truncateRunes(s string, maxChars int) string {
	n := 0
	for i := range s {
		if n == maxChars {
			return s[:i]
		}
		n++
	}
	return s
}

// sliceRunesClamped 等价 Python value[start:end] 的钳制切片（start≥0 恒；
// end 越界钳到 len；start≥end → ""）。
func sliceRunesClamped(r []rune, start, end int) string {
	if start < 0 {
		start = 0
	}
	if end > len(r) {
		end = len(r)
	}
	if start >= end {
		return ""
	}
	return string(r[start:end])
}

// indexRunes 等价 Python haystack.find(needle, from)（needle 非空恒；
// 词表无空短语，空 needle 的 find("") 恒 0 分支不可达）。
func indexRunes(haystack, needle []rune, from int) int {
	if from < 0 {
		from = 0
	}
	for i := from; i+len(needle) <= len(haystack); i++ {
		match := true
		for j := range needle {
			if haystack[i+j] != needle[j] {
				match = false
				break
			}
		}
		if match {
			return i
		}
	}
	return -1
}

func isASCIIRunes(rs []rune) bool {
	for _, r := range rs {
		if r >= utf8.RuneSelf {
			return false
		}
	}
	return true
}

// asciiPhraseBoundaryOK 复刻 _ascii_phrase_boundary_ok：folded 串上匹配
// 区间的相邻字符若是 ASCII 字母/数字/下划线则拒绝命中（cli 不命中 client、
// git 不命中 digital、otel 不命中 hotel）；中文邻居不拦截。
// neighbor.isascii() && (neighbor.isalnum() || neighbor == "_") 中
// isascii && isalnum ⟺ ASCII 字母或数字。
func asciiPhraseBoundaryOK(folded []rune, start, end int) bool {
	if start > 0 {
		if r := folded[start-1]; r < utf8.RuneSelf && (isASCIIAlnum(r) || r == '_') {
			return false
		}
	}
	if end < len(folded) {
		if r := folded[end]; r < utf8.RuneSelf && (isASCIIAlnum(r) || r == '_') {
			return false
		}
	}
	return true
}

// conceptMatch 对应 _project_concept_matches 产物的 (start, text, spec)：
// start 是 casefold 串的 rune 下标；text 是原串同下标切片（空回退 phrase）；
// spec 是 projectConceptLexicon 下标。
type conceptMatch struct {
	start int
	text  string
	spec  int
}

// projectConceptMatches 复刻 _project_concept_matches（max_concepts 默认 8）：
// 候选 = 词表序×短语序×出现序的 (start, end, phrase, spec)；排序键
// (-(end-start), start, concept_id) 稳定排序；按 concept_id 去重 +
// occupied 区间重叠（start < stop && end > begin）选前 max(1, maxConcepts) 个；
// 最终按 start 稳定重排。
func projectConceptMatches(value string, maxConcepts int) []conceptMatch {
	orig := []rune(value)
	folded := []rune(fold(value))
	type candidate struct {
		start, end int
		phrase     string
		spec       int
	}
	var candidates []candidate
	for si := range projectConceptLexicon {
		spec := &projectConceptLexicon[si]
		for _, phrase := range spec.phrases {
			needle := []rune(fold(phrase))
			if len(needle) == 0 {
				continue // 词表无空短语，防御
			}
			needsBoundary := isASCIIRunes(needle)
			start := indexRunes(folded, needle, 0)
			for start >= 0 {
				end := start + len(needle)
				if !needsBoundary || asciiPhraseBoundaryOK(folded, start, end) {
					candidates = append(candidates, candidate{start: start, end: end, phrase: phrase, spec: si})
				}
				start = indexRunes(folded, needle, start+1)
			}
		}
	}
	slices.SortStableFunc(candidates, func(a, b candidate) int {
		if la, lb := a.end-a.start, b.end-b.start; la != lb {
			return cmp.Compare(lb, la) // -(end-start) 升序 = 长度降序
		}
		if a.start != b.start {
			return cmp.Compare(a.start, b.start)
		}
		// Python str 比较按码点；Go strings.Compare 按字节——UTF-8 下两者同序。
		return strings.Compare(projectConceptLexicon[a.spec].conceptID, projectConceptLexicon[b.spec].conceptID)
	})
	if maxConcepts < 1 {
		maxConcepts = 1 // Python max(1, max_concepts)
	}
	occupied := make([][2]int, 0, maxConcepts)
	selected := make([]conceptMatch, 0, maxConcepts)
	seen := make(map[string]bool)
	for _, c := range candidates {
		id := projectConceptLexicon[c.spec].conceptID
		if seen[id] {
			continue
		}
		overlap := false
		for _, iv := range occupied {
			if c.start < iv[1] && c.end > iv[0] {
				overlap = true
				break
			}
		}
		if overlap {
			continue
		}
		seen[id] = true
		occupied = append(occupied, [2]int{c.start, c.end})
		text := sliceRunesClamped(orig, c.start, c.end)
		if text == "" {
			text = c.phrase // Python value[start:end] or phrase
		}
		selected = append(selected, conceptMatch{start: c.start, text: text, spec: c.spec})
		if len(selected) >= maxConcepts {
			break
		}
	}
	slices.SortStableFunc(selected, func(a, b conceptMatch) int {
		return cmp.Compare(a.start, b.start)
	})
	return selected
}

// projectLiteralTerms 复刻 _project_literal_terms：covered 区间取
// (start, start+len(选中文本))（注意是选中文本的码点长，不是 folded 区间长）；
// finditer 在**原串**上进行；剔 HAN 词、概念覆盖区间（start<stop && end>begin）、
// transport 词（casefold 比对）。
func projectLiteralTerms(value string, matches []conceptMatch) []tokenSpan {
	covered := make([][2]int, 0, len(matches))
	for _, m := range matches {
		covered = append(covered, [2]int{m.start, m.start + utf8.RuneCountInString(m.text)})
	}
	terms := []tokenSpan{}
	for _, tok := range technicalTokenSpans(value) {
		if containsHan(tok.text) {
			continue
		}
		overlap := false
		for _, iv := range covered {
			if tok.start < iv[1] && tok.end > iv[0] {
				overlap = true
				break
			}
		}
		if overlap {
			continue
		}
		if projectTransportTerms[fold(tok.text)] {
			continue
		}
		terms = append(terms, tok)
	}
	return terms
}

// projectIntentTerms 复刻 _project_intent_terms：概念命中词 + 字面词按位置
// 稳定排序（等位概念词在前——概念项先入列），casefold 去重，剔单字符非数字，
// 上限 max(1, maxTerms)；空结果回退 project_search_terms。
func projectIntentTerms(value string, matches []conceptMatch, maxTerms int) []string {
	type posTerm struct {
		start int
		term  string
	}
	combined := make([]posTerm, 0, len(matches)+8)
	for _, m := range matches {
		combined = append(combined, posTerm{start: m.start, term: m.text})
	}
	for _, t := range projectLiteralTerms(value, matches) {
		combined = append(combined, posTerm{start: t.start, term: t.text})
	}
	slices.SortStableFunc(combined, func(a, b posTerm) int {
		return cmp.Compare(a.start, b.start)
	})
	if maxTerms < 1 {
		maxTerms = 1
	}
	result := []string{}
	seen := make(map[string]bool)
	for _, pt := range combined {
		key := fold(pt.term)
		if seen[key] {
			continue
		}
		if utf8.RuneCountInString(pt.term) == 1 {
			r, _ := utf8.DecodeRuneInString(pt.term)
			if !pyIsDigit(r) {
				continue
			}
		}
		seen[key] = true
		result = append(result, pt.term)
		if len(result) >= maxTerms {
			break
		}
	}
	if len(result) == 0 {
		return searchTerms(value, maxTerms, projectTransportTerms)
	}
	return result
}

// searchTerms 复刻 search_terms：NFKC 归一 → TECHNICAL_TOKEN_RE 分词 →
// casefold 去重、剔 blocked（casefold 比对）、剔单字符非数字，上限
// max(1, maxTerms)。
func searchTerms(value string, maxTerms int, blocked map[string]bool) []string {
	normalized := normalizeSearch(value)
	if maxTerms < 1 {
		maxTerms = 1
	}
	terms := make([]string, 0, 8)
	seen := make(map[string]bool)
	for _, token := range technicalTokens(normalized) {
		key := fold(token)
		if blocked[key] || seen[key] {
			continue
		}
		// Python: len(token) == 1 and not token.isdigit()。
		// TECHNICAL_TOKEN_RE 产物的单字符仅可能是 ASCII 字母数字或 CJK
		// 表意文字，str.isdigit 在该字符集上等价于 ASCII 0-9 判定。
		if utf8.RuneCountInString(token) == 1 {
			r, _ := utf8.DecodeRuneInString(token)
			if !pyIsDigit(r) {
				continue
			}
		}
		seen[key] = true
		terms = append(terms, token)
		if len(terms) >= maxTerms {
			break
		}
	}
	return terms
}

// containsAny 等价 Python any(v in lowered for v in subs)（patterns 均
// 小写 ASCII/中文，folded 串上 Contains 即子串判定）。
func containsAny(lowered string, subs ...string) bool {
	for _, sub := range subs {
		if strings.Contains(lowered, sub) {
			return true
		}
	}
	return false
}
