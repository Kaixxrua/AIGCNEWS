package mcpapp

import (
	"fmt"
	"strings"

	"aigcnews/mcp-go/internal/jsonx"
)

type PromptInputError string

func (e PromptInputError) Error() string { return string(e) }

var promptSources = map[string]bool{"all": true, "arxiv": true, "github": true, "news": true, "producthunt": true, "hackernews": true, "x": true}

func promptArg(arguments map[string]any, key string, maxLen int) (string, error) {
	value, ok := arguments[key]
	if !ok || value == nil {
		return "", nil
	}
	text, ok := value.(string)
	if !ok {
		return "", PromptInputError(fmt.Sprintf("%s must be a string.", key))
	}
	runes := []rune(strings.TrimSpace(text))
	if len(runes) > maxLen {
		runes = runes[:maxLen]
	}
	return string(runes), nil
}

func promptMessage(text string) jsonx.Object {
	return jsonx.Object{{Key: "role", Value: "user"}, {Key: "content", Value: jsonx.Object{{Key: "type", Value: "text"}, {Key: "text", Value: strings.TrimSpace(text)}}}}
}
func promptResult(description, text string) jsonx.Object {
	return jsonx.Object{{Key: "description", Value: description}, {Key: "messages", Value: []any{promptMessage(text)}}}
}

func GetPrompt(nameValue any, argumentsValue any) (jsonx.Object, error) {
	name, ok := nameValue.(string)
	if !ok || name == "" {
		return nil, PromptInputError("prompts/get params.name is required.")
	}
	arguments := map[string]any{}
	if argumentsValue != nil {
		var ok bool
		arguments, ok = argumentsValue.(map[string]any)
		if !ok {
			return nil, PromptInputError("prompts/get params.arguments must be an object.")
		}
	}
	switch name {
	case "daily_research_brief":
		source, err := promptArg(arguments, "source", 32)
		if err != nil {
			return nil, err
		}
		if source == "" || !promptSources[source] {
			source = "all"
		}
		_ = source
		topic, err := promptArg(arguments, "topic", 120)
		if err != nil {
			return nil, err
		}
		topicLine := ""
		if topic != "" {
			topicLine = " Focus on this topic: " + topic + "."
		}
		return promptResult("Summarize the latest public AIGC_NEWS context.", strings.ReplaceAll(dailyBriefPrompt, "{{TOPIC_LINE}}", topicLine)), nil
	case "project_discovery":
		topic, err := promptArg(arguments, "topic", 120)
		if err != nil {
			return nil, err
		}
		category, err := promptArg(arguments, "category", 64)
		if err != nil {
			return nil, err
		}
		language, err := promptArg(arguments, "language", 64)
		if err != nil {
			return nil, err
		}
		filters := []string{}
		if topic != "" {
			filters = append(filters, "topic `"+topic+"`")
		}
		if category != "" {
			filters = append(filters, "category `"+category+"`")
		}
		if language != "" {
			filters = append(filters, "language `"+language+"`")
		}
		filterText := ""
		if len(filters) > 0 {
			filterText = " Focus on " + strings.Join(filters, " and ") + "."
		}
		return promptResult("Discover, compare, and evaluate reusable public projects with local-first AIGC_NEWS MCP search.", strings.ReplaceAll(projectDiscoveryPrompt, "{{FILTER}}", filterText)), nil
	default:
		return nil, PromptInputError("Unknown prompt: " + name)
	}
}

const dailyBriefPrompt = "Use the AIGC_NEWS MCP public context to produce a concise research brief.{{TOPIC_LINE}}\n\nRouting policy:\n- Any explicit request to find, search, recommend, compare, or reuse a project, repository, open-source implementation, SDK, framework, component, template, example, or tutorial starts with one matching AIGC_NEWS MCP search, even if GitHub or open source was not named.\n- Before implementing a major module, complete capability, or independent subsystem, perform one proactive project reuse check even without explicit discovery intent.\n- Use `search_github_ai_projects` for AI/Agent/MCP/RAG/LLM engineering artifacts and `search_github_projects` for non-AI software artifacts. Requests to improve AI development efficiency, accelerate AI application delivery, or reduce repeated AI engineering work use `search_github_ai_projects` first.\n- Use `search_papers` first only when the dominant requested output is explicitly scholarly: papers, literature, surveys, citations, authors/venues, academic benchmarks/evaluations, methods/theory, experiments, or research results. It returns arXiv papers only.\n- Do not proactively search for copy or styling, renames, clear localized bugs, tests/logging/types, validation or field adjustments, simple CRUD, or an isolated function, component, or endpoint change.\n\nSuggested flow:\n1. Read `aigc-news://dashboard/summary` for the latest overall context.\n2. Choose exactly one initial search route by the dominant deliverable and run at most one initial search per unchanged requirement. For mixed requests, do not batch primary searches.\n3. Rewrite academic requests into 1-3 concise technical terms. Use `search_documents` only for explicit AIGC_NEWS indexed news/feed or cross-source searches.\n4. Do not batch the selected MCP search with host WebSearch/WebFetch/Bash. Await and inspect the selected AIGC_NEWS result first.\n5. If the MCP call fails, returns no usable or relevant items, or lacks a specific external fact, use another MCP tool or a host web tool only for that missing detail. All public project candidates require at least 500 GitHub stars; verify the current count for native WebSearch candidates and omit unverifiable or below-threshold projects.\n6. Treat 500 stars as an eligibility floor, not proof of maintenance, security, license fit, documentation quality, or integration suitability. If reuse changes architecture, deployment, data ownership, licensing, or long-term maintenance, present reuse, design-reference, and build-from-scratch options and await the user's choice.\n7. If a specific indexed item matters, call `get_paper_detail` for its id.\n8. Summarize key trends, notable papers/projects/news, and why they matter, distinguishing AIGC_NEWS evidence from any later web fallback.\n\nThese instructions guide MCP-aware agents; the MCP server cannot override a client's own system prompt or native tool priorities. Do not use private user data or admin-only operations."
const projectDiscoveryPrompt = "Use the AIGC_NEWS MCP public GitHub project context to discover useful projects.{{FILTER}}\n\nMCP-first discovery and reuse policy:\n- Whenever the user explicitly asks to find, search, recommend, compare, or reuse a project, repository, open-source implementation, SDK, framework, component, template, example, or tutorial, call one matching AIGC_NEWS MCP search first. The user does not need to say GitHub or open source.\n- Before implementing a major module, complete capability, or independent subsystem, perform one proactive reuse check even without explicit discovery intent. This means a cohesive capability with its own architecture, integration, or maintenance boundary—not merely a large diff. Examples include auth/permissions, payments, workflow engines, queues, search/indexing, collaboration, protocol implementations, sandboxes, local AI deployment, and end-to-end RAG or Agent subsystems.\n- For AI, Agent, MCP, RAG, or LLM engineering artifacts, call `search_github_ai_projects` first. Requests to improve AI development efficiency, accelerate AI application delivery, or reduce repeated AI engineering work also use it first. For non-AI software artifacts, call `search_github_projects` first.\n- Use `search_papers` first only when the dominant deliverable is explicitly scholarly: papers, literature, surveys, citations, authors/venues, academic benchmarks/evaluations, methods/theory, experiments, or research results.\n- For mixed requests choose exactly one initial route by the dominant deliverable; do not batch primary searches.\n- Do not proactively search for copy or styling, renames, clear localized bugs, tests/logging/types, validation or field adjustments, simple CRUD, or an isolated function, component, or endpoint change.\n- Do not put the selected MCP search and native WebSearch/WebFetch/Bash in the same initial tool batch. Await and inspect the MCP result first.\n- Use a host tool only if the MCP call fails, returns no usable or relevant items, or lacks a specific external fact required by the request; query only that missing detail rather than repeating the broad discovery search.\n- All public local and direct-GitHub project results enforce a minimum of 500 GitHub stars. Before a native WebSearch candidate enters the comparison set, verify its current count is at least 500 and omit candidates whose count is unverifiable or below 500.\n- For broad discovery/comparison questions, use the returned AIGC_NEWS local fields (`description`, `description_zh`, `tags`, `topics`, category/subcategory, language, stars, forks, pushed_at, url) as the project summary and evidence.\n- Do not inspect each returned GitHub repository just to summarize candidates. Only visit GitHub/README/docs when the user explicitly asks about one or several named projects, or when local MCP metadata is insufficient to answer a concrete follow-up question.\n- Direct GitHub fallback is only appropriate when the MCP result reports `local_total: 0` / no local AIGC_NEWS matches.\n\nSuggested flow:\n1. If category/subcategory is unclear, read `aigc-news://projects/categories` or call `get_project_categories`.\n2. Call `search_github_projects` for non-AI software, or `search_github_ai_projects` for AI engineering artifacts, with concise `q`, relevant filters, and limit 5-10. AI queries default to `relevance`; use `stars` or `hot` only when the user explicitly wants popularity or trend order.\n3. If `fallback_used` is false or `local_total` is positive, answer from the curated AIGC_NEWS local project library without re-checking every GitHub repo.\n4. If local metadata is insufficient, explain what is missing; only then inspect the specific returned repo(s) needed for that missing detail.\n5. If `fallback_used` is true and `result_origin` is `github_api_fallback`, clearly label those results as direct GitHub fallback rather than curated local catalog entries.\n6. Filter candidates by requirement match, maintenance, integration fit, documentation, license fit, community, and security/stability. The 500-star minimum is mandatory eligibility, but stars alone do not establish suitability.\n7. Show only the best 2-3 candidates. If none clearly saves implementation effort or reduces risk, recommend building within the current project without forcing a meaningless choice.\n8. If adopting a candidate changes architecture, deployment, data ownership, licensing, or long-term maintenance, stop and ask the user to choose: reuse a numbered candidate, use it only as a design reference and build internally, build from scratch, or refine and search again. Do not start implementation in the same turn.\n9. Run at most one initial search per unchanged requirement. Search again only when the user asks, filters change, the first result is empty, or candidates are incompatible.\n\nThese instructions guide MCP-aware agents; the MCP server cannot override a client's own system prompt or native tool priorities. Do not use personal favorites or admin-only MCP server configuration."
