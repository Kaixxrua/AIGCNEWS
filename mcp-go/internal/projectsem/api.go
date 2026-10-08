package projectsem

import (
	"strings"
	"unicode"
	"unicode/utf8"
)

// api.go 钉死 projectsem 的导出 API 面（PR 2.7/2.8 跨 agent 契约）。
// 当前函数体为 panic 占位，由移植 agent 逐字复刻
// backend/app/domain/search_semantics.py 后替换；签名与类型一经定稿
// 不得变更（internal/projectsearch 引擎与 internal/mcpapp 校验镜像按此
// 编译）。
//
// Python 锚点：
//   - search_semantics.py:745-759  ProjectSearchIntent（frozen dataclass）
//   - search_semantics.py:762-763  normalize_search_query
//   - search_semantics.py:766-790  search_terms / project_search_terms
//   - search_semantics.py:883-910  build_project_lexical_retrieval_plan
//   - search_semantics.py:913-978  build_project_search_intent
//   - search_semantics.py:981-1000 normalize_client_intent_values
//   - search_semantics.py:1003-1020 client_intent_preserves_protected_tokens
//   - search_semantics.py:1023-1068 build_client_project_search_intent
//   - search_semantics.py:1071-1072 escape_like_literal
//   - repositories/project_catalog.py:8-31  Lexical* 数据类

// Intent 对应 ProjectSearchIntent。切片槽位语义对齐 Python tuple：
// 空恒为非 nil 空切片以外的语义差异不存在（引擎只读长度与元素）。
// Language ∈ zh|en|mixed|und；IntentClass ∈ exact_lookup|learning|
// examples|sdk|framework|self_hosted|general_discovery。
type Intent struct {
	SchemaVersion    string
	NormalizedQuery  string
	Language         string
	LexicalTerms     []string
	SemanticQueries  []string
	IntentClass      string
	Topics           []string
	Languages        []string
	ArtifactTypes    []string
	MustHave         []string
	ShouldHave       []string
	ConceptIDs       []string
	BilingualAliases []string
}

// LexicalConcept 对应 ProjectLexicalConcept（repositories/project_catalog.py:8）。
type LexicalConcept struct {
	ConceptID    string
	PrimaryTerms []string
	Aliases      []string
}

// LexicalRetrievalPlan 对应 ProjectLexicalRetrievalPlan（project_catalog.py:15）。
type LexicalRetrievalPlan struct {
	NormalizedQuery string
	StrictTerms     []string
	Concepts        []LexicalConcept
}

// LexicalCandidate 对应 ProjectLexicalCandidate（project_catalog.py:22）。
// Lane ∈ "strict"|"relaxed"。
type LexicalCandidate struct {
	RepoID        string
	Lane          string
	TermCoverage  int
	MatchStrength int
}

// LexicalCandidateLanes 对应 ProjectLexicalCandidateLanes（project_catalog.py:30）。
type LexicalCandidateLanes struct {
	Strict  []LexicalCandidate
	Relaxed []LexicalCandidate
}

// NormalizeSearchQuery 复刻 normalize_search_query：
// " ".join(NFKC(value).strip().split())——NFKC 兼容归一、Python 空白表、
// 空白游程折叠。
func NormalizeSearchQuery(value string) string {
	return normalizeSearch(value)
}

// SearchTerms 复刻 search_terms：TECHNICAL_TOKEN_RE 分词 → casefold 去重、
// 剔除 blocked（casefold 比对）、剔除单字符非数字，上限 max(1, maxTerms)。
func SearchTerms(value string, maxTerms int, blockedTerms []string) []string {
	blocked := make(map[string]bool, len(blockedTerms))
	for _, term := range blockedTerms {
		blocked[fold(term)] = true
	}
	return searchTerms(value, maxTerms, blocked)
}

// ProjectSearchTerms 复刻 project_search_terms：blocked 固定为
// _PROJECT_TRANSPORT_TERMS（{"github","repo","repository","repositories",
// "project","projects","项目","仓库","工具"}）。
func ProjectSearchTerms(value string, maxTerms int) []string {
	return searchTerms(value, maxTerms, projectTransportTerms)
}

// BuildProjectSearchIntent 复刻 build_project_search_intent（max_chars 恒为
// 默认 120）：剥请求短语 → 语言判定 → 概念匹配（115 条词表、ASCII 词边界
// 守卫、长度降序+起始序+concept_id 选不重叠前 8）→ 别名扩展 → variants →
// intent_terms → intent_class 规则链。SchemaVersion 恒
// "project-search-intent-v1"。
func BuildProjectSearchIntent(value string) Intent {
	const maxChars = 120 // Python 调用方恒用默认 max_chars=120
	normalized := truncateRunes(normalizeSearch(value), maxChars)
	cleaned := normalized
	for _, phrase := range projectRequestPhrases {
		cleaned = caseInsensitiveReplaceAll(cleaned, phrase)
	}
	// Python: cleaned = normalize_search_query(cleaned) or normalized。
	if c := normalizeSearch(cleaned); c != "" {
		cleaned = c
	} else {
		cleaned = normalized
	}
	hasHan := containsHan(cleaned)
	latinTerms := []string{}
	for _, term := range technicalTokens(cleaned) {
		if !containsHan(term) {
			latinTerms = append(latinTerms, term)
		}
	}
	proseLatin := false
	for _, term := range latinTerms {
		switch fold(term) {
		case "ai", "llm", "rag", "mcp":
		default:
			proseLatin = true
		}
	}
	language := "und"
	switch {
	case hasHan && proseLatin:
		language = "mixed"
	case hasHan:
		language = "zh"
	case len(latinTerms) > 0:
		language = "en"
	}
	conceptMatches := projectConceptMatches(cleaned, 8)
	// 别名扩展：单概念命中取全量别名，多概念命中仅各取第一别名。
	aliasPool := []string{}
	for _, m := range conceptMatches {
		spec := &projectConceptLexicon[m.spec]
		if len(conceptMatches) == 1 {
			aliasPool = append(aliasPool, spec.aliases...)
		} else {
			aliasPool = append(aliasPool, spec.aliases[:min(1, len(spec.aliases))]...)
		}
	}
	expanded := cleaned
	compactAliases := []string{}
	aliasSeen := make(map[string]bool)
	// Python 在循环内反复取 expanded.casefold()，但 expanded 循环内不变——
	// 「key not in expanded.casefold()」是 casefold 串上的子串判定。
	foldedExpanded := fold(expanded)
	for _, alias := range aliasPool {
		key := fold(alias)
		if !strings.Contains(foldedExpanded, key) && !aliasSeen[key] {
			aliasSeen[key] = true
			compactAliases = append(compactAliases, alias)
		}
	}
	if len(compactAliases) > 0 {
		expanded = expanded + " " + strings.Join(compactAliases, " ")
	}
	variants := []string{}
	variantSeen := make(map[string]bool)
	for _, query := range []string{cleaned, normalizeSearch(expanded)} {
		bounded := pythonTrimRight(truncateRunes(query, maxChars))
		key := fold(bounded)
		if bounded != "" && !variantSeen[key] {
			variantSeen[key] = true
			variants = append(variants, bounded)
		}
	}
	terms := projectIntentTerms(cleaned, conceptMatches, 8)
	lowered := fold(cleaned)
	rawTerms := searchTerms(cleaned, 8, projectTransportTerms)
	intentClass := "general_discovery"
	switch {
	case strings.Contains(cleaned, "/") ||
		(len(rawTerms) == 1 && fold(rawTerms[0]) == lowered && len(conceptMatches) == 0):
		intentClass = "exact_lookup"
	case containsAny(lowered, "学习", "教程", "入门", "learn", "tutorial", "beginner"):
		intentClass = "learning"
	case containsAny(lowered, "example", "sample", "示例"):
		intentClass = "examples"
	case strings.Contains(lowered, "sdk"):
		intentClass = "sdk"
	case containsAny(lowered, "framework", "框架"):
		intentClass = "framework"
	case containsAny(lowered, "本地部署", "self-hosted", "self hosted"):
		intentClass = "self_hosted"
	}
	conceptIDs := make([]string, 0, len(conceptMatches))
	for _, m := range conceptMatches {
		conceptIDs = append(conceptIDs, projectConceptLexicon[m.spec].conceptID)
	}
	return Intent{
		SchemaVersion:    "project-search-intent-v1",
		NormalizedQuery:  cleaned,
		Language:         language,
		LexicalTerms:     terms,
		SemanticQueries:  variants,
		IntentClass:      intentClass,
		Topics:           []string{},
		Languages:        []string{},
		ArtifactTypes:    []string{},
		MustHave:         []string{},
		ShouldHave:       []string{},
		ConceptIDs:       conceptIDs,
		BilingualAliases: compactAliases,
	}
}

// BuildProjectLexicalRetrievalPlan uses the original query and validated host hints.
func BuildProjectLexicalRetrievalPlan(intent Intent) LexicalRetrievalPlan {
	inputs := []string{intent.NormalizedQuery}
	if intent.SchemaVersion == "project-search-intent-client-v1" {
		inputs = append(inputs, intent.LexicalTerms...)
	}
	concepts := []LexicalConcept{}
	strictTerms := []string{}
	seenConcepts, seenTerms := map[string]bool{}, map[string]bool{}
	for _, value := range inputs {
		matches := projectConceptMatches(value, 8)
		for _, m := range matches {
			spec := &projectConceptLexicon[m.spec]
			if !seenConcepts[spec.conceptID] {
				seenConcepts[spec.conceptID] = true
				concepts = append(concepts, LexicalConcept{ConceptID: spec.conceptID, PrimaryTerms: []string{m.text}, Aliases: append([]string{}, spec.aliases...)})
			}
		}
		for _, tok := range projectLiteralTerms(value, matches) {
			key := fold(tok.text)
			if key != "ai" && !seenTerms[key] {
				seenTerms[key] = true
				strictTerms = append(strictTerms, tok.text)
			}
		}
	}
	return LexicalRetrievalPlan{NormalizedQuery: intent.NormalizedQuery, StrictTerms: strictTerms, Concepts: concepts}
}

// NormalizeClientIntentValues 复刻 normalize_client_intent_values：
// 先截 values[:maxItems]；逐条：含 Cc 控制字符 → error；NFKC 归一后空或
// 超 maxChars（按字符）→ error；casefold 去重。错误消息恒为
// "intent values must be non-empty, bounded text without control characters"。
func NormalizeClientIntentValues(values []string, maxItems, maxChars int) ([]string, error) {
	// Python values[:max_items] 截断发生在逐条校验之前（截断线后的
	// 非法值不触发 error）。调用方 maxItems 恒正；负值按空截断防御
	// （Python 负切片语义不可达）。
	if maxItems < 0 {
		maxItems = 0
	}
	if len(values) > maxItems {
		values = values[:maxItems]
	}
	normalized := []string{}
	seen := make(map[string]bool)
	for _, value := range values {
		for _, r := range value {
			// unicodedata.category(ch) == "Cc" ⟺ unicode.IsControl：
			// 两者同为 C0(0x00-0x1F)+DEL(0x7F)+C1(0x80-0x9F) 控制字符表
			// （对拍语料对 0x00-0x2FF 全区间逐字符验证）。
			if unicode.IsControl(r) {
				return nil, errIntentValues
			}
		}
		clean := normalizeSearch(value)
		if clean == "" || utf8.RuneCountInString(clean) > maxChars {
			return nil, errIntentValues
		}
		key := fold(clean)
		if !seen[key] {
			seen[key] = true
			normalized = append(normalized, clean)
		}
	}
	return normalized, nil
}

// ClientIntentPreservesProtectedTokens 复刻 client_intent_preserves_protected_tokens：
// q 分词中属于 _PROTECTED_PROJECT_TOKENS（{"c++","c#",".net","mcp","rag",
// "langgraph"}，casefold 比对）的 token 必须全部出现在
// lexicalTerms+semanticQueries 的 token 并集里。
func ClientIntentPreservesProtectedTokens(query string, lexicalTerms, semanticQueries []string) bool {
	protected := make(map[string]bool)
	for _, token := range technicalTokens(normalizeSearch(query)) {
		key := fold(token)
		if protectedProjectTokens[key] {
			protected[key] = true
		}
	}
	// Python: TECHNICAL_TOKEN_RE.findall(" ".join((*lexical, *semantic)))
	// ——输出侧不二次归一化，直接拼接分词。
	var sb strings.Builder
	for _, term := range lexicalTerms {
		sb.WriteString(term)
		sb.WriteByte(' ')
	}
	for _, query := range semanticQueries {
		sb.WriteString(query)
		sb.WriteByte(' ')
	}
	outputTokens := make(map[string]bool)
	for _, token := range technicalTokens(sb.String()) {
		outputTokens[fold(token)] = true
	}
	for token := range protected {
		if !outputTokens[token] {
			return false
		}
	}
	return true
}

// BuildClientProjectSearchIntent 复刻 build_client_project_search_intent：
// deterministic = BuildProjectSearchIntent(query)；lexical/semantic 槽位经
// NormalizeClientIntentValues（8×40 / 3×120）后非空校验 →
// "client intent requires lexical_terms and semantic_queries"；
// 受保护 token 校验 → "client intent must preserve protected technical
// tokens from q"。返回 Intent：SchemaVersion 恒
// "project-search-intent-client-v1"；NormalizedQuery/ConceptIDs/
// BilingualAliases 继承 deterministic；Language/IntentClass 取 payload
// （IntentClass 空串按 Python payload.get 缺省 "general_discovery" 处理——
// 调用方（校验镜像）已保证 model_dump 恒完整，此为防御分支）；
// Topics/Languages/ArtifactTypes/MustHave/ShouldHave 经
// NormalizeClientIntentValues（6×40 / 3×30 / 6×40 / 6×40 / 8×40）。
func BuildClientProjectSearchIntent(query string, payload ClientIntentFields) (Intent, error) {
	deterministic := BuildProjectSearchIntent(query)
	// 校验序逐字对齐 Python：lexical(8×40) → semantic(3×120) → 空槽位 →
	// 受保护 token → topics(6×40) → languages(3×30) → artifact_types(6×40) →
	// must_have(6×40) → should_have(8×40)。payload.get(...) or () 的 None
	// 防御由 nil 切片天然覆盖。
	lexicalTerms, err := NormalizeClientIntentValues(payload.LexicalTerms, 8, 40)
	if err != nil {
		return Intent{}, err
	}
	semanticQueries, err := NormalizeClientIntentValues(payload.SemanticQueries, 3, 120)
	if err != nil {
		return Intent{}, err
	}
	if len(lexicalTerms) == 0 || len(semanticQueries) == 0 {
		return Intent{}, errClientSlots
	}
	if !ClientIntentPreservesProtectedTokens(deterministic.NormalizedQuery, lexicalTerms, semanticQueries) {
		return Intent{}, errProtectedTokens
	}
	topics, err := NormalizeClientIntentValues(payload.Topics, 6, 40)
	if err != nil {
		return Intent{}, err
	}
	languages, err := NormalizeClientIntentValues(payload.Languages, 3, 30)
	if err != nil {
		return Intent{}, err
	}
	artifactTypes, err := NormalizeClientIntentValues(payload.ArtifactTypes, 6, 40)
	if err != nil {
		return Intent{}, err
	}
	mustHave, err := NormalizeClientIntentValues(payload.MustHave, 6, 40)
	if err != nil {
		return Intent{}, err
	}
	shouldHave, err := NormalizeClientIntentValues(payload.ShouldHave, 8, 40)
	if err != nil {
		return Intent{}, err
	}
	// payload.get("intent_class", "general_discovery")：校验镜像的
	// model_dump 恒完整，空串防御分支按缺省值处理。
	intentClass := payload.IntentClass
	if intentClass == "" {
		intentClass = "general_discovery"
	}
	return Intent{
		SchemaVersion:    "project-search-intent-client-v1",
		NormalizedQuery:  deterministic.NormalizedQuery,
		Language:         payload.Language,
		LexicalTerms:     lexicalTerms,
		SemanticQueries:  semanticQueries,
		IntentClass:      intentClass,
		Topics:           topics,
		Languages:        languages,
		ArtifactTypes:    artifactTypes,
		MustHave:         mustHave,
		ShouldHave:       shouldHave,
		ConceptIDs:       deterministic.ConceptIDs,
		BilingualAliases: deterministic.BilingualAliases,
	}, nil
}

// EscapeLikeLiteral 复刻 escape_like_literal（escape="="）：
// 顺序替换 "=" → "=="，"%" → "=%"，"_" → "=_"。
func EscapeLikeLiteral(value string) string {
	return escapeLikeLiteralReplacer.Replace(value)
}
