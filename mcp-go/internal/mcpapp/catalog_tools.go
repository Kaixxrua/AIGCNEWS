// Code generated from backend/tests/parity/corpus/protocol.jsonl (bff9da5 冻结字节); DO NOT EDIT.
//
// 注意：同一提交内 contracts.py 的 ProjectDiscoverySort 枚举序为
// relevance 居首，而语料中 search_github_projects / search_github_ai_projects
// 的 sort enum 仍是 relevance 居尾；验收以语料字节为准，本文件刻意对齐语料，
// 语料重录后须同步再生成。

package mcpapp

import "aigcnews/mcp-go/internal/jsonx"

// publicTools 逐字冻结 tools/list 匿名响应的 8 个公开工具定义，
// 数组序与单对象键序均等于 Python MCP_TOOLS 插入序。
var publicTools = []any{
	jsonx.Object{
		{Key: "name", Value: "search_papers"},
		{Key: "description", Value: "MCP-first search for public AIGC_NEWS arXiv papers. Call this when the user explicitly asks to find, search, recommend, compare, or reuse scholarly outputs and the dominant deliverable is papers, literature, surveys or systematic reviews, citations, authors or venues, benchmarks or academic evaluations, methods or theory, experiments, or research results. Agent/MCP is only a topic, not an academic-intent signal. For Agent/MCP tutorials, examples, implementations, SDKs, servers/clients, workflows, tool calling, demos, templates, or other engineering artifacts, call search_github_ai_projects first. Rewrite natural-language academic intent into 1-3 established technical terms. For mixed requests choose one initial route by the dominant deliverable; do not batch primary searches or native WebSearch/WebFetch/Bash. Never answer a find, search, recommend, or compare request from memory alone: issue this search call in your first assistant message rather than replying in prose. When papers are the dominant deliverable, call ONLY search_papers in that first message; a search_github_ai_projects or search_github_projects call for supplementary projects belongs in a LATER turn after you inspect these paper results, never in the same message or parallel tool block. Inspect the MCP result first. Use a host web tool only if this call fails, returns no usable or relevant items, or lacks a specific external fact, then search only for that missing detail. Every result item carries authors (array) and arxiv_id: when you present, summarize, or compare papers in your final answer, cite each paper's authors and arXiv ID alongside its title so the user can verify and cite the source. Budget your searches: if a query returns sparse or empty results, broaden it with fewer or more general terms at most twice, then synthesize from the best available results instead of re-phrasing similar queries endlessly—keep the total to about five search calls per request. Always finish with a complete prose answer that explicitly addresses every requirement of the request (requested paper count, comparison dimensions, time range), with title, authors, and arXiv ID for each paper; never end your turn with a tool call or a plan to search further."},
		{Key: "inputSchema", Value: jsonx.Object{
			{Key: "additionalProperties", Value: false},
			{Key: "properties", Value: jsonx.Object{
				{Key: "q", Value: jsonx.Object{
					{Key: "description", Value: "Concise paper query using established technical terms."},
					{Key: "maxLength", Value: 200},
					{Key: "minLength", Value: 1},
					{Key: "title", Value: "Q"},
					{Key: "type", Value: "string"},
				}},
				{Key: "page", Value: jsonx.Object{
					{Key: "default", Value: 1},
					{Key: "description", Value: "One-based result page."},
					{Key: "minimum", Value: 1},
					{Key: "title", Value: "Page"},
					{Key: "type", Value: "integer"},
				}},
				{Key: "limit", Value: jsonx.Object{
					{Key: "default", Value: 10},
					{Key: "description", Value: "Maximum results per page."},
					{Key: "maximum", Value: 20},
					{Key: "minimum", Value: 1},
					{Key: "title", Value: "Limit"},
					{Key: "type", Value: "integer"},
				}},
			}},
			{Key: "required", Value: []any{
				"q",
			}},
			{Key: "title", Value: "SearchPapersInput"},
			{Key: "type", Value: "object"},
		}},
	},
	jsonx.Object{
		{Key: "name", Value: "search_documents"},
		{Key: "description", Value: "Search indexed AIGC_NEWS records across arXiv, GitHub, news, Product Hunt, and Hacker News. Use this for explicit cross-source or indexed news/feed searches. For scholarly papers use search_papers; for GitHub project discovery use search_github_projects or search_github_ai_projects."},
		{Key: "inputSchema", Value: jsonx.Object{
			{Key: "additionalProperties", Value: false},
			{Key: "properties", Value: jsonx.Object{
				{Key: "q", Value: jsonx.Object{
					{Key: "description", Value: "Concise query for indexed AIGC_NEWS records."},
					{Key: "maxLength", Value: 200},
					{Key: "minLength", Value: 1},
					{Key: "title", Value: "Q"},
					{Key: "type", Value: "string"},
				}},
				{Key: "source", Value: jsonx.Object{
					{Key: "default", Value: "all"},
					{Key: "description", Value: "Optional indexed source filter."},
					{Key: "enum", Value: []any{
						"all",
						"arxiv",
						"github",
						"news",
						"producthunt",
						"hackernews",
						"x",
					}},
					{Key: "title", Value: "Source"},
					{Key: "type", Value: "string"},
				}},
				{Key: "page", Value: jsonx.Object{
					{Key: "default", Value: 1},
					{Key: "description", Value: "One-based result page."},
					{Key: "minimum", Value: 1},
					{Key: "title", Value: "Page"},
					{Key: "type", Value: "integer"},
				}},
				{Key: "limit", Value: jsonx.Object{
					{Key: "default", Value: 10},
					{Key: "description", Value: "Maximum results per page."},
					{Key: "maximum", Value: 20},
					{Key: "minimum", Value: 1},
					{Key: "title", Value: "Limit"},
					{Key: "type", Value: "integer"},
				}},
			}},
			{Key: "required", Value: []any{
				"q",
			}},
			{Key: "title", Value: "SearchDocumentsInput"},
			{Key: "type", Value: "object"},
		}},
	},
	jsonx.Object{
		{Key: "name", Value: "get_paper_detail"},
		{Key: "description", Value: "Fetch public metadata for one indexed AIGC_NEWS document by id. Call this after search_papers or get_top_items when the user needs details for a specific item. The payload includes authors (array) and arxiv_id: cite them alongside the title when you present the paper."},
		{Key: "inputSchema", Value: jsonx.Object{
			{Key: "additionalProperties", Value: false},
			{Key: "properties", Value: jsonx.Object{
				{Key: "paper_id", Value: jsonx.Object{
					{Key: "description", Value: "Document id returned by a search or ranking tool."},
					{Key: "maxLength", Value: 128},
					{Key: "minLength", Value: 1},
					{Key: "title", Value: "Paper Id"},
					{Key: "type", Value: "string"},
				}},
			}},
			{Key: "required", Value: []any{
				"paper_id",
			}},
			{Key: "title", Value: "GetPaperDetailInput"},
			{Key: "type", Value: "object"},
		}},
	},
	jsonx.Object{
		{Key: "name", Value: "get_top_items"},
		{Key: "description", Value: "Return the authoritative AIGC_NEWS ranking board (official 日榜/周榜/月榜 top-N) for a source, period, and optional snapshot date. ALWAYS call this tool — never a search tool — whenever the user asks for a ranking, leaderboard, top-N list, daily/weekly/monthly chart, today's hot list, or any 榜单/日榜/周榜/月榜 question. Search tools with scope='today' are for exploratory discovery of newly hot projects, not for official rankings."},
		{Key: "inputSchema", Value: jsonx.Object{
			{Key: "additionalProperties", Value: false},
			{Key: "properties", Value: jsonx.Object{
				{Key: "source", Value: jsonx.Object{
					{Key: "default", Value: "all"},
					{Key: "enum", Value: []any{
						"all",
						"arxiv",
						"github",
						"news",
						"producthunt",
						"hackernews",
						"x",
					}},
					{Key: "title", Value: "Source"},
					{Key: "type", Value: "string"},
				}},
				{Key: "period", Value: jsonx.Object{
					{Key: "default", Value: "daily"},
					{Key: "enum", Value: []any{
						"daily",
						"weekly",
						"monthly",
					}},
					{Key: "title", Value: "Period"},
					{Key: "type", Value: "string"},
				}},
				{Key: "date", Value: jsonx.Object{
					{Key: "anyOf", Value: []any{
						jsonx.Object{
							{Key: "maxLength", Value: 10},
							{Key: "minLength", Value: 10},
							{Key: "type", Value: "string"},
						},
						jsonx.Object{
							{Key: "type", Value: "null"},
						},
					}},
					{Key: "default", Value: nil},
					{Key: "description", Value: "Snapshot date in YYYY-MM-DD format."},
					{Key: "title", Value: "Date"},
				}},
				{Key: "limit", Value: jsonx.Object{
					{Key: "default", Value: 10},
					{Key: "maximum", Value: 20},
					{Key: "minimum", Value: 1},
					{Key: "title", Value: "Limit"},
					{Key: "type", Value: "integer"},
				}},
			}},
			{Key: "title", Value: "GetTopItemsInput"},
			{Key: "type", Value: "object"},
		}},
	},
	jsonx.Object{
		{Key: "name", Value: "search_github_projects"},
		{Key: "description", Value: "MCP-first search for public non-AI GitHub repositories and open-source software; this never searches the authenticated user's favorites. Call it whenever the user explicitly asks to find, search, recommend, compare, or reuse a non-AI project, repository, open-source implementation, SDK, framework, component, template, example, or tutorial, even if they do not say GitHub or open source. Also call it once before implementing a major non-AI module, complete capability, or independent subsystem to check whether a mature project, SDK, framework, component, or reference architecture can be reused. It covers Windows, macOS, Linux, desktop, screenshot, screen-capture, productivity, developer tools, and other non-AI domains. Do not proactively search for copy or styling, renames, clear localized bugs, tests/logging/types, validation or field adjustments, simple CRUD, or an isolated function, component, or endpoint change. Run at most one initial search per unchanged requirement. Do not batch this call with native WebSearch/WebFetch/Bash: await and inspect the MCP result first. Use a host tool only if this call fails, returns no usable or relevant items, or lacks a specific external fact required by the question, then query only that missing detail. When no local project lexically matches all query terms, this tool falls back to a bounded read-only GitHub Search labeled github_api_fallback with fallback_reason local_low_relevance instead of returning low-relevance local noise; local and direct GitHub fallback results enforce a minimum of 500 GitHub stars. Before presenting, recommending, or comparing a project found through native WebSearch, verify its current star count is at least 500 and omit unverifiable or below-threshold candidates. This floor does not establish suitability. Finding a candidate does not authorize architecture-changing adoption; present reuse, design-reference, and build-from-scratch options and await the user's choice. For AI, Agent, MCP, RAG, or LLM engineering artifacts use search_github_ai_projects; for explicitly scholarly deliverables use search_papers. Translate non-English intent into a concise GitHub query while preserving product names and requested features. Inspect specific returned repositories only when their metadata is insufficient to verify a requested feature. Non-empty queries default to relevance ranking via hybrid lexical and semantic retrieval; explicit stars, hot, updated, recent, or name sorts remain authoritative. When only a handful of local projects lexically match every query term, those definitive matches are pinned above heat-ranked results so the exact answer is never buried under trending noise. The top-level language argument is a GitHub repository programming-language filter (for example, Python or C++); do not pass query-language values such as zh, en, 中文, or 英文 as repository languages. Set lang='en' when the user speaks English to receive English-only text fields; the default 'zh' returns the bilingual Chinese-preferred payload. Every returned item carries data_source \"aigcnews.cn\" and the response carries an attribution line; cite this source (AIGC Radar · aigcnews.cn) when presenting results."},
		{Key: "inputSchema", Value: jsonx.Object{
			{Key: "additionalProperties", Value: false},
			{Key: "properties", Value: jsonx.Object{
				{Key: "q", Value: jsonx.Object{
					{Key: "description", Value: "Concise terms distilled from a project discovery request for software, repositories, open-source implementations, SDKs, frameworks, components, templates, examples, or tutorials."},
					{Key: "maxLength", Value: 120},
					{Key: "minLength", Value: 1},
					{Key: "title", Value: "Q"},
					{Key: "type", Value: "string"},
				}},
				{Key: "language", Value: jsonx.Object{
					{Key: "default", Value: ""},
					{Key: "description", Value: "Optional GitHub repository programming language filter, such as Python, C++, JavaScript, or Jupyter Notebook. Do not use query-language values such as zh, en, 中文, or 英文."},
					{Key: "maxLength", Value: 64},
					{Key: "title", Value: "Language"},
					{Key: "type", Value: "string"},
				}},
				{Key: "sort", Value: jsonx.Object{
					{Key: "anyOf", Value: []any{
						jsonx.Object{
							{Key: "enum", Value: []any{
								"hot",
								"stars",
								"updated",
								"recent",
								"name",
								"relevance",
							}},
							{Key: "type", Value: "string"},
						},
						jsonx.Object{
							{Key: "type", Value: "null"},
						},
					}},
					{Key: "default", Value: nil},
					{Key: "description", Value: "Omit to rank non-empty queries by relevance via hybrid lexical and semantic retrieval; explicit stars, hot, updated, recent, or name sorts remain authoritative."},
					{Key: "title", Value: "Sort"},
				}},
				{Key: "lang", Value: jsonx.Object{
					{Key: "default", Value: "zh"},
					{Key: "description", Value: "Response language for curated text fields (description, category names, tags). 'zh' (default) returns the bilingual payload with Chinese-preferred generic fields; 'en' folds English text into the generic fields and omits the *_zh fields. Set to 'en' when the user speaks English."},
					{Key: "enum", Value: []any{
						"zh",
						"en",
					}},
					{Key: "title", Value: "Lang"},
					{Key: "type", Value: "string"},
				}},
				{Key: "page", Value: jsonx.Object{
					{Key: "default", Value: 1},
					{Key: "minimum", Value: 1},
					{Key: "title", Value: "Page"},
					{Key: "type", Value: "integer"},
				}},
				{Key: "limit", Value: jsonx.Object{
					{Key: "default", Value: 10},
					{Key: "maximum", Value: 20},
					{Key: "minimum", Value: 1},
					{Key: "title", Value: "Limit"},
					{Key: "type", Value: "integer"},
				}},
			}},
			{Key: "required", Value: []any{
				"q",
			}},
			{Key: "title", Value: "SearchGitHubProjectsInput"},
			{Key: "type", Value: "object"},
		}},
	},
	jsonx.Object{
		{Key: "name", Value: "search_github_ai_projects"},
		{Key: "description", Value: "MCP-first local search for public GitHub AI projects in the curated/enriched AIGC_NEWS library; it excludes the authenticated user's favorites. Call it whenever the user explicitly asks to find, search, recommend, compare, or reuse an AI, Agent, MCP, RAG, or LLM project, repository, open-source implementation, SDK, framework, component, template, example, tutorial, server/client, workflow, tool-calling demo, learning resource, or 资料, even if GitHub or open source was not named. Also call it once before implementing a major AI module, complete capability, or independent subsystem, and whenever the user asks to improve AI development efficiency, accelerate AI application delivery, or reduce repeated AI engineering work. Use search_papers first only when the dominant requested output is explicitly scholarly: papers, literature, surveys, citations, academic benchmarks/evaluations, methods/theory, experiments, or research results. For mixed requests choose one initial tool by the dominant deliverable; do not batch GitHub AI and paper search: when projects are the dominant deliverable, call ONLY search_github_ai_projects in your first assistant message, and defer any search_papers call to a LATER turn after you inspect these project results, never in the same message or parallel tool block. Do not proactively search for copy or styling, renames, clear localized bugs, tests/logging/types, validation or field adjustments, simple CRUD, or an isolated function, component, or endpoint change merely because AI terms appear. Run at most one initial search per unchanged requirement. Do not batch this call with native WebSearch/WebFetch/Bash: await and inspect the MCP result first. Use a host tool only if this call fails, returns no usable or relevant items, or lacks a specific external fact, then query only that missing detail. Local and direct GitHub fallback results enforce a minimum of 500 GitHub stars. Before presenting, recommending, or comparing a project found through native WebSearch, verify its current star count is at least 500 and omit unverifiable or below-threshold candidates. This floor does not establish suitability. Finding a candidate does not authorize architecture-changing adoption; present reuse, design-reference, and build-from-scratch options and await the user's choice. Non-empty queries default to relevance ranking; explicit stars, hot, updated, recent, or name sorts remain authoritative. Scope 'today' is for exploratory discovery of newly hot projects and always sorts by hot; it is NOT a ranking board — for daily/weekly/monthly rankings, leaderboards, top-N lists, or any 日榜/周榜/月榜 question, call get_top_items instead. A capable MCP host may include the optional versioned intent object using full conversation context; preserve exact technical names. Intent affects relevance only, while explicit top-level filters and sort remain authoritative. It supports repository programming language filters (for example Python or C++), categories, and station recommendations. The top-level language argument is a GitHub repository programming-language filter; do not pass query-language values such as zh, en, 中文, or 英文 as repository languages. For query-language metadata use intent.language with zh, en, mixed, or und. For non-AI GitHub or open-source software, call search_github_projects instead. Use returned AIGC_NEWS fields such as description_zh, tags, categories, language, license, stars, daily_star_growth, hot_score, and URL before inspecting repositories. If local results are zero, this tool may perform a bounded read-only AI-focused GitHub Search fallback labeled github_api_fallback. Set lang='en' when the user speaks English to receive English-only text fields; the default 'zh' returns the bilingual Chinese-preferred payload. Every returned item carries data_source \"aigcnews.cn\" and the response carries an attribution line; cite this source (AIGC Radar · aigcnews.cn) when presenting results."},
		{Key: "inputSchema", Value: jsonx.Object{
			{Key: "$defs", Value: jsonx.Object{
				{Key: "ClientProjectSearchIntentInput", Value: jsonx.Object{
					{Key: "additionalProperties", Value: false},
					{Key: "properties", Value: jsonx.Object{
						{Key: "schema_version", Value: jsonx.Object{
							{Key: "const", Value: "project-search-intent-client-v1"},
							{Key: "title", Value: "Schema Version"},
							{Key: "type", Value: "string"},
						}},
						{Key: "language", Value: jsonx.Object{
							{Key: "description", Value: "Query language: zh, en, mixed, or und. This is independent of the top-level repository language filter."},
							{Key: "enum", Value: []any{
								"zh",
								"en",
								"mixed",
								"und",
							}},
							{Key: "title", Value: "Language"},
							{Key: "type", Value: "string"},
						}},
						{Key: "intent_class", Value: jsonx.Object{
							{Key: "default", Value: "general_discovery"},
							{Key: "enum", Value: []any{
								"exact_lookup",
								"learning",
								"examples",
								"sdk",
								"framework",
								"self_hosted",
								"general_discovery",
							}},
							{Key: "title", Value: "Intent Class"},
							{Key: "type", Value: "string"},
						}},
						{Key: "lexical_terms", Value: jsonx.Object{
							{Key: "items", Value: jsonx.Object{
								{Key: "maxLength", Value: 40},
								{Key: "minLength", Value: 1},
								{Key: "type", Value: "string"},
							}},
							{Key: "maxItems", Value: 8},
							{Key: "minItems", Value: 1},
							{Key: "title", Value: "Lexical Terms"},
							{Key: "type", Value: "array"},
						}},
						{Key: "semantic_queries", Value: jsonx.Object{
							{Key: "items", Value: jsonx.Object{
								{Key: "maxLength", Value: 120},
								{Key: "minLength", Value: 1},
								{Key: "type", Value: "string"},
							}},
							{Key: "maxItems", Value: 3},
							{Key: "minItems", Value: 1},
							{Key: "title", Value: "Semantic Queries"},
							{Key: "type", Value: "array"},
						}},
						{Key: "topics", Value: jsonx.Object{
							{Key: "items", Value: jsonx.Object{
								{Key: "maxLength", Value: 40},
								{Key: "minLength", Value: 1},
								{Key: "type", Value: "string"},
							}},
							{Key: "maxItems", Value: 6},
							{Key: "title", Value: "Topics"},
							{Key: "type", Value: "array"},
						}},
						{Key: "languages", Value: jsonx.Object{
							{Key: "items", Value: jsonx.Object{
								{Key: "maxLength", Value: 30},
								{Key: "minLength", Value: 1},
								{Key: "type", Value: "string"},
							}},
							{Key: "maxItems", Value: 3},
							{Key: "title", Value: "Languages"},
							{Key: "type", Value: "array"},
						}},
						{Key: "artifact_types", Value: jsonx.Object{
							{Key: "items", Value: jsonx.Object{
								{Key: "maxLength", Value: 40},
								{Key: "minLength", Value: 1},
								{Key: "type", Value: "string"},
							}},
							{Key: "maxItems", Value: 6},
							{Key: "title", Value: "Artifact Types"},
							{Key: "type", Value: "array"},
						}},
						{Key: "must_have", Value: jsonx.Object{
							{Key: "items", Value: jsonx.Object{
								{Key: "maxLength", Value: 40},
								{Key: "minLength", Value: 1},
								{Key: "type", Value: "string"},
							}},
							{Key: "maxItems", Value: 6},
							{Key: "title", Value: "Must Have"},
							{Key: "type", Value: "array"},
						}},
						{Key: "should_have", Value: jsonx.Object{
							{Key: "items", Value: jsonx.Object{
								{Key: "maxLength", Value: 40},
								{Key: "minLength", Value: 1},
								{Key: "type", Value: "string"},
							}},
							{Key: "maxItems", Value: 8},
							{Key: "title", Value: "Should Have"},
							{Key: "type", Value: "array"},
						}},
					}},
					{Key: "required", Value: []any{
						"schema_version",
						"language",
						"lexical_terms",
						"semantic_queries",
					}},
					{Key: "title", Value: "ClientProjectSearchIntentInput"},
					{Key: "type", Value: "object"},
				}},
			}},
			{Key: "additionalProperties", Value: false},
			{Key: "properties", Value: jsonx.Object{
				{Key: "q", Value: jsonx.Object{
					{Key: "default", Value: ""},
					{Key: "maxLength", Value: 120},
					{Key: "title", Value: "Q"},
					{Key: "type", Value: "string"},
				}},
				{Key: "category", Value: jsonx.Object{
					{Key: "default", Value: ""},
					{Key: "maxLength", Value: 64},
					{Key: "title", Value: "Category"},
					{Key: "type", Value: "string"},
				}},
				{Key: "subcategory", Value: jsonx.Object{
					{Key: "default", Value: ""},
					{Key: "maxLength", Value: 64},
					{Key: "title", Value: "Subcategory"},
					{Key: "type", Value: "string"},
				}},
				{Key: "language", Value: jsonx.Object{
					{Key: "default", Value: ""},
					{Key: "description", Value: "Optional GitHub repository programming language filter, such as Python, C++, JavaScript, or Jupyter Notebook. Do not use query-language values such as zh, en, 中文, or 英文; for query language use intent.language (zh/en/mixed/und)."},
					{Key: "maxLength", Value: 64},
					{Key: "title", Value: "Language"},
					{Key: "type", Value: "string"},
				}},
				{Key: "intent", Value: jsonx.Object{
					{Key: "anyOf", Value: []any{
						jsonx.Object{
							{Key: "$ref", Value: "#/$defs/ClientProjectSearchIntentInput"},
						},
						jsonx.Object{
							{Key: "type", Value: "null"},
						},
					}},
					{Key: "default", Value: nil},
					{Key: "description", Value: "Optional host-generated relevance intent; explicit top-level filters remain authoritative."},
				}},
				{Key: "lang", Value: jsonx.Object{
					{Key: "default", Value: "zh"},
					{Key: "description", Value: "Response language for curated text fields (description, category names, tags). 'zh' (default) returns the bilingual payload with Chinese-preferred generic fields; 'en' folds English text into the generic fields and omits the *_zh fields. Set to 'en' when the user speaks English."},
					{Key: "enum", Value: []any{
						"zh",
						"en",
					}},
					{Key: "title", Value: "Lang"},
					{Key: "type", Value: "string"},
				}},
				{Key: "scope", Value: jsonx.Object{
					{Key: "default", Value: "all"},
					{Key: "enum", Value: []any{
						"all",
						"today",
						"recommended",
					}},
					{Key: "title", Value: "Scope"},
					{Key: "type", Value: "string"},
				}},
				{Key: "sort", Value: jsonx.Object{
					{Key: "anyOf", Value: []any{
						jsonx.Object{
							{Key: "enum", Value: []any{
								"hot",
								"stars",
								"updated",
								"recent",
								"name",
								"relevance",
							}},
							{Key: "type", Value: "string"},
						},
						jsonx.Object{
							{Key: "type", Value: "null"},
						},
					}},
					{Key: "default", Value: nil},
					{Key: "description", Value: "Omit to rank non-empty queries by relevance; queryless defaults are all=stars, today=hot, recommended=recent. Scope 'today' is exploratory discovery of newly hot projects, not an official ranking; for rankings, leaderboards, or top-N lists, call get_top_items instead."},
					{Key: "title", Value: "Sort"},
				}},
				{Key: "page", Value: jsonx.Object{
					{Key: "default", Value: 1},
					{Key: "minimum", Value: 1},
					{Key: "title", Value: "Page"},
					{Key: "type", Value: "integer"},
				}},
				{Key: "limit", Value: jsonx.Object{
					{Key: "default", Value: 10},
					{Key: "maximum", Value: 20},
					{Key: "minimum", Value: 1},
					{Key: "title", Value: "Limit"},
					{Key: "type", Value: "integer"},
				}},
			}},
			{Key: "title", Value: "SearchGitHubAIProjectsInput"},
			{Key: "type", Value: "object"},
		}},
	},
	jsonx.Object{
		{Key: "name", Value: "get_project_categories"},
		{Key: "description", Value: "List public AIGC_NEWS GitHub AI project categories and subcategory counts. Call this first only when category/subcategory taxonomy is unclear, then call search_github_ai_projects. Do not use direct GitHub or web search just to discover available AIGC_NEWS project categories."},
		{Key: "inputSchema", Value: jsonx.Object{
			{Key: "additionalProperties", Value: false},
			{Key: "properties", Value: jsonx.Object{}},
			{Key: "title", Value: "GetProjectCategoriesInput"},
			{Key: "type", Value: "object"},
		}},
	},
	jsonx.Object{
		{Key: "name", Value: "submit_project_adoption"},
		{Key: "description", Value: "Record the outcome of a project reuse decision as an adoption receipt. Call this once after any search_github_ai_projects/search_github_projects result leads to a concrete decision: 'adopted' when the project was integrated or added as a dependency, 'reference_only' when it served as design reference only, or 'declined' when it was rejected in favor of building from scratch. Include the query that surfaced the project when known. Call at most once per project per decision; do not call for projects that were merely listed, mentioned, or compared without a decision. These receipts power the library's reuse-rate metric, which is returned in the response alongside the stored receipt."},
		{Key: "inputSchema", Value: jsonx.Object{
			{Key: "additionalProperties", Value: false},
			{Key: "properties", Value: jsonx.Object{
				{Key: "project_full_name", Value: jsonx.Object{
					{Key: "description", Value: "GitHub repository full name (owner/repo) the decision applies to."},
					{Key: "maxLength", Value: 200},
					{Key: "minLength", Value: 3},
					{Key: "title", Value: "Project Full Name"},
					{Key: "type", Value: "string"},
				}},
				{Key: "decision", Value: jsonx.Object{
					{Key: "description", Value: "The reuse outcome: 'adopted' (the project was integrated or depended on), 'reference_only' (used as design reference only), or 'declined' (rejected, build-from-scratch chosen)."},
					{Key: "enum", Value: []any{
						"adopted",
						"reference_only",
						"declined",
					}},
					{Key: "title", Value: "Decision"},
					{Key: "type", Value: "string"},
				}},
				{Key: "reason", Value: jsonx.Object{
					{Key: "default", Value: ""},
					{Key: "description", Value: "Optional short reason for the decision; keep under one sentence."},
					{Key: "maxLength", Value: 500},
					{Key: "title", Value: "Reason"},
					{Key: "type", Value: "string"},
				}},
				{Key: "query", Value: jsonx.Object{
					{Key: "default", Value: ""},
					{Key: "description", Value: "Optional search query that surfaced this project, for recall-quality review."},
					{Key: "maxLength", Value: 200},
					{Key: "title", Value: "Query"},
					{Key: "type", Value: "string"},
				}},
				{Key: "source", Value: jsonx.Object{
					{Key: "default", Value: "mcp"},
					{Key: "description", Value: "Receipt origin: mcp (default), rest, plugin, or hook."},
					{Key: "enum", Value: []any{
						"mcp",
						"rest",
						"plugin",
						"hook",
					}},
					{Key: "title", Value: "Source"},
					{Key: "type", Value: "string"},
				}},
			}},
			{Key: "required", Value: []any{
				"project_full_name",
				"decision",
			}},
			{Key: "title", Value: "SubmitProjectAdoptionInput"},
			{Key: "type", Value: "object"},
		}},
	},
}

// privateTools 逐字冻结 _PRIVATE_MCP_TOOLS：仅认证会话可见。
var privateTools = []any{
	jsonx.Object{
		{Key: "name", Value: "search_my_project_favorites"},
		{Key: "description", Value: "Search the authenticated user's private GitHub project favorites. Call this only for the user's own saved or favorited projects. Set lang='en' when the user speaks English to receive English-only text fields; the default 'zh' returns the bilingual Chinese-preferred payload."},
		{Key: "inputSchema", Value: jsonx.Object{
			{Key: "additionalProperties", Value: false},
			{Key: "properties", Value: jsonx.Object{
				{Key: "q", Value: jsonx.Object{
					{Key: "default", Value: ""},
					{Key: "maxLength", Value: 120},
					{Key: "title", Value: "Q"},
					{Key: "type", Value: "string"},
				}},
				{Key: "category", Value: jsonx.Object{
					{Key: "default", Value: ""},
					{Key: "maxLength", Value: 64},
					{Key: "title", Value: "Category"},
					{Key: "type", Value: "string"},
				}},
				{Key: "subcategory", Value: jsonx.Object{
					{Key: "default", Value: ""},
					{Key: "maxLength", Value: 64},
					{Key: "title", Value: "Subcategory"},
					{Key: "type", Value: "string"},
				}},
				{Key: "language", Value: jsonx.Object{
					{Key: "default", Value: ""},
					{Key: "description", Value: "Optional GitHub repository programming language filter, such as Python, C++, JavaScript, or Jupyter Notebook. Do not use query-language values such as zh, en, 中文, or 英文."},
					{Key: "maxLength", Value: 64},
					{Key: "title", Value: "Language"},
					{Key: "type", Value: "string"},
				}},
				{Key: "tag", Value: jsonx.Object{
					{Key: "default", Value: ""},
					{Key: "maxLength", Value: 64},
					{Key: "title", Value: "Tag"},
					{Key: "type", Value: "string"},
				}},
				{Key: "lang", Value: jsonx.Object{
					{Key: "default", Value: "zh"},
					{Key: "description", Value: "Response language for curated text fields (description, category names, tags). 'zh' (default) returns the bilingual payload with Chinese-preferred generic fields; 'en' folds English text into the generic fields and omits the *_zh fields. Set to 'en' when the user speaks English."},
					{Key: "enum", Value: []any{
						"zh",
						"en",
					}},
					{Key: "title", Value: "Lang"},
					{Key: "type", Value: "string"},
				}},
				{Key: "sort", Value: jsonx.Object{
					{Key: "default", Value: "recent"},
					{Key: "enum", Value: []any{
						"hot",
						"stars",
						"updated",
						"recent",
						"name",
					}},
					{Key: "title", Value: "Sort"},
					{Key: "type", Value: "string"},
				}},
				{Key: "limit", Value: jsonx.Object{
					{Key: "default", Value: 10},
					{Key: "maximum", Value: 20},
					{Key: "minimum", Value: 1},
					{Key: "title", Value: "Limit"},
					{Key: "type", Value: "integer"},
				}},
				{Key: "marker", Value: jsonx.Object{
					{Key: "default", Value: ""},
					{Key: "maxLength", Value: 128},
					{Key: "title", Value: "Marker"},
					{Key: "type", Value: "string"},
				}},
			}},
			{Key: "title", Value: "SearchMyProjectFavoritesInput"},
			{Key: "type", Value: "object"},
		}},
	},
}

// ToolsList 复刻 application.py tools/list 分支：
// result = {"tools": MCP_TOOLS + (_PRIVATE_MCP_TOOLS if is_authenticated else [])}。
// 每次调用组装新切片，调用方不得改写返回值的共享表项。
func ToolsList(authenticated bool) jsonx.Object {
	tools := make([]any, 0, len(publicTools)+len(privateTools))
	tools = append(tools, publicTools...)
	if authenticated {
		tools = append(tools, privateTools...)
	}
	return jsonx.Object{{Key: "tools", Value: tools}}
}
