// Code generated from backend/tests/parity/corpus/protocol.jsonl (bff9da5 冻结字节); DO NOT EDIT.
//
// 注意：同一提交内 contracts.py 的 ProjectDiscoverySort 枚举序为
// relevance 居首，而语料中 search_github_projects / search_github_ai_projects
// 的 sort enum 仍是 relevance 居尾；验收以语料字节为准，本文件刻意对齐语料，
// 语料重录后须同步再生成。

package mcpapp

import "aigcnews/mcp-go/internal/jsonx"

// catalogPrompts 逐字冻结 MCP_PROMPTS。
var catalogPrompts = []any{
	jsonx.Object{
		{Key: "name", Value: "daily_research_brief"},
		{Key: "title", Value: "Daily AIGC research brief"},
		{Key: "description", Value: "Guide a client to summarize today's AIGC_NEWS context using public tools and resources."},
		{Key: "arguments", Value: []any{
			jsonx.Object{
				{Key: "name", Value: "source"},
				{Key: "description", Value: "Optional source filter: all, arxiv, github, news, producthunt, hackernews, x."},
				{Key: "required", Value: false},
			},
			jsonx.Object{
				{Key: "name", Value: "topic"},
				{Key: "description", Value: "Optional topic or keyword focus."},
				{Key: "required", Value: false},
			},
		}},
	},
	jsonx.Object{
		{Key: "name", Value: "project_discovery"},
		{Key: "title", Value: "Open-source project reuse discovery"},
		{Key: "description", Value: "Guide a client to discover, compare, and evaluate reusable public projects with AIGC_NEWS local-first search."},
		{Key: "arguments", Value: []any{
			jsonx.Object{
				{Key: "name", Value: "topic"},
				{Key: "description", Value: "Optional search topic, e.g. RAG Web UI local deploy."},
				{Key: "required", Value: false},
			},
			jsonx.Object{
				{Key: "name", Value: "category"},
				{Key: "description", Value: "Optional project category slug."},
				{Key: "required", Value: false},
			},
			jsonx.Object{
				{Key: "name", Value: "language"},
				{Key: "description", Value: "Optional GitHub repository programming language filter, e.g. Python or C++. Do not use zh, en, 中文, or 英文."},
				{Key: "required", Value: false},
			},
		}},
	},
}

// PromptsList 复刻 application.py prompts/list 分支：
// result = {"prompts": MCP_PROMPTS}。
func PromptsList() jsonx.Object {
	return jsonx.Object{{Key: "prompts", Value: catalogPrompts}}
}
