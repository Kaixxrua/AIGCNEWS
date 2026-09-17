package mcpapp

import "aigcnews/mcp-go/internal/jsonx"

const uiHostInstructions = "Whenever the user asks to create, build, redesign, or substantially improve a user-facing frontend UI, complete page, layout block, color theme, shader, animated background, or text effect, you MUST call search_ui_templates before writing implementation code, even when the user never mentions templates, assets, search, or MCP. Then call get_ui_template for the best relevant result to inspect original source, dependencies, author, and license before implementation. The search tool automatically relaxes long natural-language briefs when exact matching is empty. Reuse the chosen original effect and adapt only integration details; preserve its visual design. This UI-specific route takes priority over the general project search route below. Do not call it for a narrow copy edit, minor CSS adjustment, or localized bug fix. When the task needs icons, call search_ui_icons and then get_ui_icon for verbatim, license-audited SVG source instead of redrawing or approximating icons. "

func (a *App) hasUILibrary() bool {
	if a.tools == nil {
		return false
	}
	_, search := a.tools.Lookup("search_ui_templates")
	_, get := a.tools.Lookup("get_ui_template")
	return search && get
}

func (a *App) instructions() string {
	if a.hasUILibrary() {
		return uiHostInstructions + hostInstructions
	}
	return hostInstructions
}

func (a *App) toolsList(authenticated bool) jsonx.Object {
	if !a.hasUILibrary() {
		return ToolsList(authenticated)
	}
	tools := make([]any, 0, len(publicTools)+len(uiTemplateTools)+len(uiIconTools)+len(privateTools))
	tools = append(tools, publicTools...)
	tools = append(tools, uiTemplateTools...)
	tools = append(tools, uiIconTools...)
	if authenticated {
		tools = append(tools, privateTools...)
	}
	return jsonx.Object{{Key: "tools", Value: tools}}
}

// Additive public tools; the established project, paper and feed contracts stay intact.
var uiTemplateTools = []any{
	jsonx.Object{
		{Key: "name", Value: "search_ui_templates"},
		{Key: "description", Value: "Proactively find original UI components, complete pages, layout blocks, color themes, shaders, animated backgrounds and text effects before implementing a new or substantially redesigned frontend, even when the user did not ask to search for templates. Search Chinese, English or mixed natural-language briefs (e.g. 液态金属 / liquid metal); empty exact matches automatically relax to the strongest matching terms or an explicit category. Filter by kind (component, block, template, theme), purpose (dashboard, authentication, navigation, etc.), and HTML/Tailwind, React, Vue/Nuxt or CSS. Returns licensed upstream references and live previews. Follow with get_ui_template to obtain real source instead of inventing a visual approximation."},
		{Key: "annotations", Value: jsonx.Object{{Key: "readOnlyHint", Value: true}, {Key: "destructiveHint", Value: false}, {Key: "idempotentHint", Value: true}, {Key: "openWorldHint", Value: false}}},
		{Key: "inputSchema", Value: jsonx.Object{
			{Key: "type", Value: "object"},
			{Key: "additionalProperties", Value: false},
			{Key: "properties", Value: jsonx.Object{
				{Key: "q", Value: jsonx.Object{{Key: "type", Value: "string"}, {Key: "maxLength", Value: 256}, {Key: "default", Value: ""}}},
				{Key: "kind", Value: jsonx.Object{{Key: "type", Value: "string"}, {Key: "enum", Value: []string{"", "component", "block", "template", "theme"}}, {Key: "default", Value: ""}}},
				{Key: "category", Value: jsonx.Object{{Key: "type", Value: "string"}, {Key: "enum", Value: []string{"", "shader", "background", "text", "component", "theme", "hero", "pricing", "features", "testimonials", "faq", "footer", "dashboard", "authentication", "navigation", "cards", "buttons", "inputs", "checkboxes", "toggles", "loaders", "tabs", "accordions", "tables", "badges", "color-theme", "other"}}, {Key: "default", Value: ""}}},
				{Key: "framework", Value: jsonx.Object{{Key: "type", Value: "string"}, {Key: "enum", Value: []string{"", "react", "vue", "nuxt", "html", "css"}}, {Key: "default", Value: ""}}},
				{Key: "language", Value: jsonx.Object{{Key: "type", Value: "string"}, {Key: "enum", Value: []string{"zh", "en"}}, {Key: "default", Value: "en"}}},
				{Key: "limit", Value: jsonx.Object{{Key: "type", Value: "integer"}, {Key: "minimum", Value: 1}, {Key: "maximum", Value: 30}, {Key: "default", Value: 12}}},
			}},
		}},
	},
	jsonx.Object{
		{Key: "name", Value: "get_ui_template"},
		{Key: "description", Value: "Retrieve a curated UI template by its search result id: original source files, SHA-256 hashes, pinned upstream revision, dependencies, author, license and Chinese/English integration prompt. Keep the original appearance. Large templates return omitted_files; retrieve each with file set to its exact name to get all sources without truncation. A large file returns next_offset: repeat with file_offset until null and concatenate content. Full required notices may be linked in license_notice_files. Set include_source=false for metadata only."},
		{Key: "annotations", Value: jsonx.Object{{Key: "readOnlyHint", Value: true}, {Key: "destructiveHint", Value: false}, {Key: "idempotentHint", Value: true}, {Key: "openWorldHint", Value: false}}},
		{Key: "inputSchema", Value: jsonx.Object{
			{Key: "type", Value: "object"},
			{Key: "additionalProperties", Value: false},
			{Key: "required", Value: []string{"id"}},
			{Key: "properties", Value: jsonx.Object{
				{Key: "id", Value: jsonx.Object{{Key: "type", Value: "string"}, {Key: "minLength", Value: 1}, {Key: "maxLength", Value: 96}}},
				{Key: "file", Value: jsonx.Object{{Key: "type", Value: "string"}, {Key: "maxLength", Value: 240}, {Key: "default", Value: ""}, {Key: "description", Value: "Optional exact source file name from the template manifest; retrieves only this file's content."}}},
				{Key: "language", Value: jsonx.Object{{Key: "type", Value: "string"}, {Key: "enum", Value: []string{"zh", "en"}}, {Key: "default", Value: "en"}}},
				{Key: "file_offset", Value: jsonx.Object{{Key: "type", Value: "integer"}, {Key: "minimum", Value: 0}, {Key: "maximum", Value: 262144}, {Key: "description", Value: "Unicode character offset returned as next_offset; requires file."}}},
				{Key: "include_source", Value: jsonx.Object{{Key: "type", Value: "boolean"}, {Key: "default", Value: true}}},
			}},
		}},
	},
}
