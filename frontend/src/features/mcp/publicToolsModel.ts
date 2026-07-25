export interface PublicTool {
  name: string
  description: string
}

export type PublicToolDiscoveryState =
  | { status: 'idle'; endpoint: string }
  | { status: 'running'; endpoint: string; runId: number }
  | { status: 'success'; endpoint: string; runId: number; tools: PublicTool[] }
  | { status: 'error'; endpoint: string; runId: number }

export const PUBLIC_TOOLS: readonly PublicTool[] = [
  { name: 'search_papers', description: '检索公开 arXiv 论文与学术文献。' },
  { name: 'search_documents', description: '检索新闻、论文、GitHub 等跨来源索引内容。' },
  { name: 'get_paper_detail', description: '读取单篇公开索引文档的详细元数据。' },
  { name: 'get_top_items', description: '读取 daily / weekly / monthly 公开排行。' },
  { name: 'search_github_projects', description: '优先搜索非 AI 项目、组件、SDK、框架、模板与开源软件。' },
  { name: 'search_github_ai_projects', description: '优先搜索本地 AI / Agent / MCP / RAG / LLM 项目库。' },
  { name: 'get_project_library', description: '兼容读取 GitHub AI 项目库。' },
  { name: 'get_project_categories', description: '读取 AI 项目分类与数量。' },
]

const UNKNOWN_TOOL_DESCRIPTION = '该端点提供的公开 MCP 工具。'
const localizedDescriptions = new Map(PUBLIC_TOOLS.map((tool) => [tool.name, tool.description]))

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
      description: localizedDescriptions.get(name) ?? UNKNOWN_TOOL_DESCRIPTION,
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
