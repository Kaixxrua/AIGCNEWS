package mcpapp

// project_search_ai.go implements the search_github_ai_projects handler and
// its pydantic-v2-compatible input model. The generic project search handler in
// project_search.go shares the engine and response finalizer, while AI search
// keeps the full taxonomy, scope, and client intent surface.

import (
	"fmt"
	"sort"
	"strings"
	"unicode/utf8"

	"aigcnews/mcp-go/internal/projectsem"
)

// searchGitHubAIProjectsInput is the complete model_dump-shaped result of
// SearchGitHubAIProjectsInput. A nil intent means that the field was omitted or
// explicitly set to null; sort uses the empty string for Python None.
type searchGitHubAIProjectsInput struct {
	q, category, subcategory, language string
	intent                             *projectsem.ClientIntentFields
	lang, scope, sort                  string
	page, limit                        int
}

var projectScopeChoices = []string{"all", "today", "recommended"}

// The taxonomy is deliberately kept as slug-only data in the handler. Labels
// are not part of validation, and this mirrors CATEGORY_BY_SLUG and
// SUBCATEGORY_BY_CATEGORY_SLUG without coupling mcpapp to the catalog store.
var aiProjectCategorySlugs = map[string]struct{}{
	"productivity_tools": {}, "coding_tools": {}, "agents_automation": {},
	"ai_apps": {}, "learning_resources": {}, "rag_knowledge": {},
	"multimodal_tools": {}, "models_infra": {}, "data_eval_training": {},
	"security_privacy": {}, "other": {},
}

var aiProjectSubcategorySlugs = map[string]map[string]struct{}{
	"productivity_tools": {
		"writing_docs": {}, "meetings_email": {}, "browser_search": {},
		"office_automation": {}, "notes_knowledge": {}, "personal_assistant": {},
		"spreadsheet_analysis": {}, "productivity_other": {},
	},
	"coding_tools": {
		"code_generation": {}, "code_review": {}, "ide_plugins": {},
		"testing_ci": {}, "dev_agents": {}, "code_search_docs": {},
		"low_code_scaffold": {}, "coding_other": {},
	},
	"agents_automation": {
		"agent_frameworks": {}, "multi_agent": {}, "workflow_automation": {},
		"mcp_tool_use": {}, "browser_rpa": {}, "research_agents": {},
		"personal_automation": {}, "agent_other": {},
	},
	"ai_apps": {
		"chat_clients": {}, "ai_search_products": {}, "vertical_saas": {},
		"desktop_mobile_apps": {}, "marketing_sales": {}, "education_apps": {},
		"customer_ops": {}, "ai_apps_other": {},
	},
	"learning_resources": {
		"awesome_lists": {}, "tutorials_courses": {}, "prompt_collections": {},
		"papers_reading": {}, "examples_templates": {}, "newsletters_news": {},
		"project_collections": {}, "learning_other": {},
	},
	"rag_knowledge": {
		"vector_search": {}, "document_qa": {}, "graph_rag": {},
		"enterprise_knowledge": {}, "retrieval_infra": {}, "ai_search_engine": {},
		"document_parsing": {}, "rag_other": {},
	},
	"multimodal_tools": {
		"image_generation": {}, "video_generation": {}, "speech_audio": {},
		"ocr_vision": {}, "multimodal_chat": {}, "creative_design": {},
		"three_d_spatial": {}, "multimodal_other": {},
	},
	"models_infra": {
		"local_llm_runtime": {}, "inference_serving": {}, "llm_gateway": {},
		"model_deploy_mlops": {}, "model_compression_accel": {}, "edge_runtime": {},
		"model_management": {}, "models_infra_other": {},
	},
	"data_eval_training": {
		"datasets": {}, "benchmark_eval": {}, "fine_tuning": {},
		"synthetic_data": {}, "training_frameworks": {}, "observability": {},
		"data_labeling_cleaning": {}, "data_training_other": {},
	},
	"security_privacy": {
		"prompt_security": {}, "privacy_local_first": {}, "redteam_eval": {},
		"compliance_guardrails": {}, "vulnerability_analysis": {}, "content_safety": {},
		"security_other": {},
	},
	"other": {"other_uncategorized": {}},
}

var projectIntentLanguageChoices = []string{"zh", "en", "mixed", "und"}
var projectIntentClassChoices = []string{
	"exact_lookup", "learning", "examples", "sdk", "framework", "self_hosted", "general_discovery",
}

const projectIntentSchemaVersion = "project-search-intent-client-v1"

// Search is the search_github_ai_projects ToolHandler. Resources use the same
// method value, so their query arguments follow exactly the same validation and
// response enrichment path.
func (s *ProjectSearchService) Search(arguments map[string]any) (any, error) {
	input, err := validateSearchGitHubAIProjectsArgs(arguments)
	if err != nil {
		return nil, err
	}
	lang := input.lang
	if lang != "zh" && lang != "en" {
		lang = "zh"
	}
	result, err := s.engine.SearchProjects(ProjectSearchInput{
		Query:        input.q,
		Mode:         "ai",
		Language:     input.language,
		Category:     input.category,
		Subcategory:  input.subcategory,
		Scope:        input.scope,
		Sort:         input.sort,
		Page:         input.page,
		Limit:        input.limit,
		ClientIntent: input.intent,
	})
	if err != nil {
		return nil, err
	}
	return finalizeProjectSearchResult(result, lang, s.publicBaseURL), nil
}

// validateSearchGitHubAIProjectsArgs mirrors SearchGitHubAIProjectsInput's
// field order and after-validator order. Field validation is completed before
// either the nested or outer semantic validator is invoked.
func validateSearchGitHubAIProjectsArgs(args map[string]any) (searchGitHubAIProjectsInput, error) {
	input := searchGitHubAIProjectsInput{lang: "zh", scope: "all", page: 1, limit: 10}
	var failures []string

	input.q = aiStrictString(args, "q", 120, &failures)
	input.category = aiStrictString(args, "category", 64, &failures)
	input.subcategory = aiStrictString(args, "subcategory", 64, &failures)

	if raw, present := args["language"]; present {
		value, ok := raw.(string)
		if !ok {
			failures = append(failures, "language: Input should be a valid string")
		} else {
			value = strings.TrimSpace(value)
			switch {
			case utf8.RuneCountInString(value) > 64:
				failures = append(failures, "language: String should have at most 64 characters")
			case !validateRepoLanguage(value):
				failures = append(failures, "language: Value error, "+repositoryLanguageMessage)
			default:
				input.language = value
			}
		}
	}

	if raw, present := args["intent"]; present && raw != nil {
		var intent *projectsem.ClientIntentFields
		intent, intentFailures := validateProjectSearchClientIntent(raw)
		failures = append(failures, intentFailures...)
		if len(intentFailures) == 0 {
			input.intent = intent
		}
	}

	if raw, present := args["lang"]; present {
		value, ok := raw.(string)
		if !ok || (value != "zh" && value != "en") {
			failures = append(failures, "lang: Input should be 'zh' or 'en'")
		} else {
			input.lang = value
		}
	}
	if raw, present := args["scope"]; present {
		value, ok := raw.(string)
		if !ok || !contains(projectScopeChoices, value) {
			failures = append(failures, "scope: Input should be 'all', 'today' or 'recommended'")
		} else {
			input.scope = value
		}
	}
	if raw, present := args["sort"]; present && raw != nil {
		value, ok := raw.(string)
		if !ok || !contains(projectDiscoverySortChoices, value) {
			failures = append(failures, "sort: Input should be 'hot', 'stars', 'updated', 'recent', 'name' or 'relevance'")
		} else {
			input.sort = value
		}
	}
	if raw, present := args["page"]; present {
		if value, ok := strictInt(raw); !ok {
			failures = append(failures, "page: Input should be a valid integer")
		} else if value < 1 {
			failures = append(failures, "page: Input should be greater than or equal to 1")
		} else {
			input.page = value
		}
	}
	if raw, present := args["limit"]; present {
		if value, ok := strictInt(raw); !ok {
			failures = append(failures, "limit: Input should be a valid integer")
		} else if value < 1 {
			failures = append(failures, "limit: Input should be greater than or equal to 1")
		} else if value > 20 {
			failures = append(failures, "limit: Input should be less than or equal to 20")
		} else {
			input.limit = value
		}
	}

	known := map[string]bool{
		"q": true, "category": true, "subcategory": true, "language": true,
		"intent": true, "lang": true, "scope": true, "sort": true,
		"page": true, "limit": true,
	}
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
		return searchGitHubAIProjectsInput{}, ToolInputError{Message: strings.Join(failures, "; ")}
	}

	// Outer model_validator(mode="after"): intent first, then taxonomy.
	if input.intent != nil {
		if _, err := projectsem.BuildClientProjectSearchIntent(input.q, *input.intent); err != nil {
			return searchGitHubAIProjectsInput{}, ToolInputError{Message: ": Value error, " + err.Error()}
		}
	}
	if input.category != "" {
		if _, ok := aiProjectCategorySlugs[input.category]; !ok {
			return searchGitHubAIProjectsInput{}, ToolInputError{Message: ": Value error, category must be a valid AIGC_NEWS category slug"}
		}
	}
	if input.subcategory == "" {
		return input, nil
	}
	if input.category != "" {
		if _, ok := aiProjectSubcategorySlugs[input.category][input.subcategory]; !ok {
			return searchGitHubAIProjectsInput{}, ToolInputError{Message: ": Value error, subcategory must belong to category"}
		}
		return input, nil
	}
	parents := make([]string, 0, 1)
	for category, children := range aiProjectSubcategorySlugs {
		if _, ok := children[input.subcategory]; ok {
			parents = append(parents, category)
		}
	}
	if len(parents) != 1 {
		return searchGitHubAIProjectsInput{}, ToolInputError{Message: ": Value error, subcategory requires an unambiguous category"}
	}
	input.category = parents[0]
	return input, nil
}

func aiStrictString(args map[string]any, key string, maxLen int, failures *[]string) string {
	raw, present := args[key]
	if !present {
		return ""
	}
	value, ok := raw.(string)
	if !ok {
		*failures = append(*failures, key+": Input should be a valid string")
		return ""
	}
	value = strings.TrimSpace(value)
	if utf8.RuneCountInString(value) > maxLen {
		*failures = append(*failures, fmt.Sprintf("%s: String should have at most %d characters", key, maxLen))
		return ""
	}
	return value
}

func validateProjectSearchClientIntent(raw any) (*projectsem.ClientIntentFields, []string) {
	object, ok := raw.(map[string]any)
	if !ok {
		return nil, []string{"intent: Input should be a valid dictionary"}
	}
	var failures []string
	payload := projectsem.ClientIntentFields{
		IntentClass: "general_discovery",
		Topics:      []string{}, Languages: []string{}, ArtifactTypes: []string{},
		MustHave: []string{}, ShouldHave: []string{},
	}

	if value, present := object["schema_version"]; !present {
		failures = append(failures, "intent.schema_version: Field required")
	} else if version, ok := value.(string); !ok || version != projectIntentSchemaVersion {
		failures = append(failures, "intent.schema_version: Input should be 'project-search-intent-client-v1'")
	}
	if value, present := object["language"]; !present {
		failures = append(failures, "intent.language: Field required")
	} else if language, ok := value.(string); !ok || !contains(projectIntentLanguageChoices, language) {
		failures = append(failures, "intent.language: Input should be 'zh', 'en', 'mixed' or 'und'")
	} else {
		payload.Language = language
	}
	if value, present := object["intent_class"]; present {
		intentClass, ok := value.(string)
		if !ok || !contains(projectIntentClassChoices, intentClass) {
			failures = append(failures, "intent.intent_class: Input should be 'exact_lookup', 'learning', 'examples', 'sdk', 'framework', 'self_hosted' or 'general_discovery'")
		} else {
			payload.IntentClass = intentClass
		}
	}
	payload.LexicalTerms = validateIntentStringList(object, "lexical_terms", 8, 40, true, &failures)
	payload.SemanticQueries = validateIntentStringList(object, "semantic_queries", 3, 120, true, &failures)
	payload.Topics = validateIntentStringList(object, "topics", 6, 40, false, &failures)
	payload.Languages = validateIntentStringList(object, "languages", 3, 30, false, &failures)
	payload.ArtifactTypes = validateIntentStringList(object, "artifact_types", 6, 40, false, &failures)
	payload.MustHave = validateIntentStringList(object, "must_have", 6, 40, false, &failures)
	payload.ShouldHave = validateIntentStringList(object, "should_have", 8, 40, false, &failures)

	known := map[string]bool{
		"schema_version": true, "language": true, "intent_class": true,
		"lexical_terms": true, "semantic_queries": true, "topics": true,
		"languages": true, "artifact_types": true, "must_have": true, "should_have": true,
	}
	var extras []string
	for key := range object {
		if !known[key] {
			extras = append(extras, key)
		}
	}
	sort.Strings(extras)
	for _, key := range extras {
		failures = append(failures, "intent."+key+": Extra inputs are not permitted")
	}
	if len(failures) > 0 {
		return nil, failures
	}
	if _, err := projectsem.BuildClientProjectSearchIntent("", payload); err != nil {
		return nil, []string{"intent: Value error, " + err.Error()}
	}
	return &payload, nil
}

func validateIntentStringList(object map[string]any, key string, maxItems, maxChars int, required bool, failures *[]string) []string {
	raw, present := object[key]
	if !present {
		if required {
			*failures = append(*failures, "intent."+key+": Field required")
		}
		return []string{}
	}
	values, ok := intentListValues(raw)
	if !ok {
		*failures = append(*failures, "intent."+key+": Input should be a valid list")
		return []string{}
	}
	if len(values) < 1 && required {
		*failures = append(*failures, fmt.Sprintf("intent.%s: List should have at least 1 item after validation, not %d", key, len(values)))
	}
	if len(values) > maxItems {
		*failures = append(*failures, fmt.Sprintf("intent.%s: List should have at most %d items after validation, not %d", key, maxItems, len(values)))
	}
	out := make([]string, 0, len(values))
	for index, rawValue := range values {
		value, ok := rawValue.(string)
		if !ok {
			*failures = append(*failures, fmt.Sprintf("intent.%s.%d: Input should be a valid string", key, index))
			continue
		}
		value = strings.TrimSpace(value)
		if utf8.RuneCountInString(value) < 1 {
			*failures = append(*failures, fmt.Sprintf("intent.%s.%d: String should have at least 1 character", key, index))
			continue
		}
		if utf8.RuneCountInString(value) > maxChars {
			*failures = append(*failures, fmt.Sprintf("intent.%s.%d: String should have at most %d characters", key, index, maxChars))
			continue
		}
		out = append(out, value)
	}
	return out
}

func intentListValues(raw any) ([]any, bool) {
	switch values := raw.(type) {
	case []any:
		return values, true
	case []string:
		out := make([]any, len(values))
		for i, value := range values {
			out[i] = value
		}
		return out, true
	default:
		return nil, false
	}
}
