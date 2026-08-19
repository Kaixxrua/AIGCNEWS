// Code generated from backend/tests/parity/corpus/protocol.jsonl (bff9da5 冻结字节); DO NOT EDIT.
//
// 注意：同一提交内 contracts.py 的 ProjectDiscoverySort 枚举序为
// relevance 居首，而语料中 search_github_projects / search_github_ai_projects
// 的 sort enum 仍是 relevance 居尾；验收以语料字节为准，本文件刻意对齐语料，
// 语料重录后须同步再生成。

package mcpapp

import "aigcnews/mcp-go/internal/jsonx"

// catalogResources 逐字冻结 MCP_RESOURCES。
var catalogResources = []any{
	jsonx.Object{
		{Key: "uri", Value: "aigc-news://dashboard/summary"},
		{Key: "name", Value: "dashboard_summary"},
		{Key: "title", Value: "AIGC_NEWS Dashboard Summary"},
		{Key: "description", Value: "Latest public dashboard context: top items, trend radar, and aggregate source stats."},
		{Key: "mimeType", Value: "application/json"},
	},
	jsonx.Object{
		{Key: "uri", Value: "aigc-news://projects/categories"},
		{Key: "name", Value: "project_categories"},
		{Key: "title", Value: "AI Project Categories"},
		{Key: "description", Value: "Public GitHub AI project category and subcategory counts."},
		{Key: "mimeType", Value: "application/json"},
	},
	jsonx.Object{
		{Key: "uri", Value: "aigc-news://report/latest"},
		{Key: "name", Value: "latest_briefing"},
		{Key: "title", Value: "Latest AIGC_NEWS Briefing"},
		{Key: "description", Value: "Latest generated public daily briefing. Query parameters: source, date."},
		{Key: "mimeType", Value: "text/markdown"},
	},
}

// catalogResourceTemplates 逐字冻结 MCP_RESOURCE_TEMPLATES。
var catalogResourceTemplates = []any{
	jsonx.Object{
		{Key: "uriTemplate", Value: "aigc-news://dashboard/top{?source,period,date,limit}"},
		{Key: "name", Value: "dashboard_top_items"},
		{Key: "title", Value: "Dashboard Top Items"},
		{Key: "description", Value: "Read public ranked AIGC_NEWS items by source, period, optional date, and limit."},
		{Key: "mimeType", Value: "application/json"},
	},
	jsonx.Object{
		{Key: "uriTemplate", Value: "aigc-news://papers/{paper_id}"},
		{Key: "name", Value: "paper_detail"},
		{Key: "title", Value: "Paper or Indexed Item Detail"},
		{Key: "description", Value: "Read public metadata for one indexed AIGC_NEWS document by id."},
		{Key: "mimeType", Value: "application/json"},
	},
	jsonx.Object{
		{Key: "uriTemplate", Value: "aigc-news://projects/library{?q,category,subcategory,language,scope,sort,page,limit}"},
		{Key: "name", Value: "project_library"},
		{Key: "title", Value: "AI Project Library"},
		{Key: "description", Value: "Read public GitHub AI project library slices by query, taxonomy, language, scope, and sort."},
		{Key: "mimeType", Value: "application/json"},
	},
	jsonx.Object{
		{Key: "uriTemplate", Value: "aigc-news://report/latest{?source,date}"},
		{Key: "name", Value: "latest_briefing_by_filter"},
		{Key: "title", Value: "Filtered Latest Briefing"},
		{Key: "description", Value: "Read the latest generated daily briefing for a source and optional date."},
		{Key: "mimeType", Value: "text/markdown"},
	},
}

// ResourcesList 复刻 application.py resources/list 分支：
// result = {"resources": MCP_RESOURCES}。
func ResourcesList() jsonx.Object {
	return jsonx.Object{{Key: "resources", Value: catalogResources}}
}

// ResourceTemplatesList 复刻 application.py resources/templates/list 分支：
// result = {"resourceTemplates": MCP_RESOURCE_TEMPLATES}。
func ResourceTemplatesList() jsonx.Object {
	return jsonx.Object{{Key: "resourceTemplates", Value: catalogResourceTemplates}}
}
