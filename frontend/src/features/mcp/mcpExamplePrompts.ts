/**
 * mcpExamplePrompts — MCP 示例提示词唯一数据源
 *
 * 供三处引导 UI 复用：项目页推广卡、项目页搜索空状态、/mcp 页示例区。
 * promptKey 指向 i18n 文案（mcpExamples.<id 驼峰>.prompt）；
 * demoQuery 存在时项目页可将示例直接填入站内搜索做演示，缺失表示该条仅支持复制；
 * toolTag 必须存在于 publicToolsModel.PUBLIC_TOOLS（由 mcpExamplePrompts.test.ts 校验）。
 */

export interface McpExamplePrompt {
  id: string
  promptKey: string
  demoQuery?: string
  toolTag?: string
}

export const MCP_EXAMPLE_PROMPTS: readonly McpExamplePrompt[] = [
  {
    id: 'rag-frameworks',
    promptKey: 'mcpExamples.ragFrameworks.prompt',
    demoQuery: 'RAG 框架',
    toolTag: 'search_github_ai_projects',
  },
  {
    id: 'agent-frameworks',
    promptKey: 'mcpExamples.agentFrameworks.prompt',
    demoQuery: 'Agent 框架',
    toolTag: 'search_github_ai_projects',
  },
  {
    id: 'weekly-ranking',
    promptKey: 'mcpExamples.weeklyRanking.prompt',
    toolTag: 'get_top_items',
  },
  {
    id: 'papers-rag-survey',
    promptKey: 'mcpExamples.papersRagSurvey.prompt',
    demoQuery: 'RAG',
    toolTag: 'search_papers',
  },
  {
    id: 'categories',
    promptKey: 'mcpExamples.categories.prompt',
    toolTag: 'get_project_categories',
  },
  {
    id: 'non-ai-screenshot',
    promptKey: 'mcpExamples.nonAiScreenshot.prompt',
    demoQuery: '截图',
    toolTag: 'search_github_projects',
  },
]

/** 项目页推广卡：4 条，weekly-ranking 无站内等价演示（榜单），仅复制 */
export const MCP_PROMO_EXAMPLE_IDS: readonly string[] = [
  'rag-frameworks',
  'agent-frameworks',
  'weekly-ranking',
  'papers-rag-survey',
]

/** 项目页空状态：3 条全部可演示，保证「点一下就能看到结果」的承诺 */
export const MCP_EMPTY_STATE_EXAMPLE_IDS: readonly string[] = [
  'rag-frameworks',
  'agent-frameworks',
  'papers-rag-survey',
]

/** /mcp 页示例区：全量 6 条，覆盖公开工具面 */
export const MCP_PAGE_EXAMPLE_IDS: readonly string[] = MCP_EXAMPLE_PROMPTS.map((example) => example.id)

export const MCP_PROMO_DISMISSED_STORAGE_KEY = 'aigcnews:mcp-promo-dismissed'

export function mcpExamplesByIds(ids: readonly string[]): McpExamplePrompt[] {
  const byId = new Map(MCP_EXAMPLE_PROMPTS.map((example) => [example.id, example]))
  const resolved: McpExamplePrompt[] = []
  for (const id of ids) {
    const example = byId.get(id)
    if (example) resolved.push(example)
  }
  return resolved
}
