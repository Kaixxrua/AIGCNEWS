export interface PublicTool {
  name: string
  descriptionKey: string
}

export type PublicToolDiscoveryState =
  | { status: 'idle'; endpoint: string }
  | { status: 'running'; endpoint: string; runId: number }
  | { status: 'success'; endpoint: string; runId: number; tools: PublicTool[] }
  | { status: 'error'; endpoint: string; runId: number }

export const UNKNOWN_TOOL_DESCRIPTION_KEY = 'mcp.tools.unknown'

export const PUBLIC_TOOLS: readonly PublicTool[] = [
  { name: 'search_papers', descriptionKey: 'mcp.tools.search_papers' },
  { name: 'search_documents', descriptionKey: 'mcp.tools.search_documents' },
  { name: 'get_paper_detail', descriptionKey: 'mcp.tools.get_paper_detail' },
  { name: 'get_top_items', descriptionKey: 'mcp.tools.get_top_items' },
  { name: 'search_github_projects', descriptionKey: 'mcp.tools.search_github_projects' },
  { name: 'search_github_ai_projects', descriptionKey: 'mcp.tools.search_github_ai_projects' },
  { name: 'get_project_categories', descriptionKey: 'mcp.tools.get_project_categories' },
  { name: 'search_ui_templates', descriptionKey: 'mcp.tools.search_ui_templates' },
  { name: 'get_ui_template', descriptionKey: 'mcp.tools.get_ui_template' },
]

const localizedDescriptionKeys = new Map(PUBLIC_TOOLS.map((tool) => [tool.name, tool.descriptionKey]))

export function normalizePublicTools(value: unknown[]): PublicTool[] {
  const seen = new Set<string>()
  const tools: PublicTool[] = []

  for (const item of value) {
    if (!item || typeof item !== 'object') continue
    const rawName = (item as { name?: unknown }).name
    if (typeof rawName !== 'string') continue
    const name = rawName.trim()
    if (!name || seen.has(name)) continue
    seen.add(name)
    tools.push({
      name,
      descriptionKey: localizedDescriptionKeys.get(name) ?? UNKNOWN_TOOL_DESCRIPTION_KEY,
    })
  }

  return tools
}

export function displayedPublicTools(
  endpoint: string,
  state: PublicToolDiscoveryState,
): PublicTool[] {
  if (state.status === 'success' && state.endpoint === endpoint) return state.tools
  return PUBLIC_TOOLS.map((tool) => ({ ...tool }))
}

export function isActivePublicToolDiscovery(
  endpoint: string,
  runId: number,
  state: PublicToolDiscoveryState,
): boolean {
  return state.status === 'running' && state.endpoint === endpoint && state.runId === runId
}
