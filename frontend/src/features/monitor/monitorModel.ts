export interface Task {
  id: number
  task_name: string
  status: string
  item_count: number
  error_msg: string | null
  started_at: string | null
  finished_at: string | null
}

export interface SchedulerStatus {
  running: boolean
  job_count: number
  jobs: Array<{ id: string; name: string; next_run_time: string | null }>
}

export interface PagedResult {
  items: Task[]
  total: number
  page: number
  page_size: number
}

export interface ProviderConfig {
  provider: 'openai' | 'anthropic'
  base_url: string
  model_name: string
  api_key_configured: boolean
  api_key_masked: string | null
  updated_at: string | null
}

export interface ProviderForm {
  provider: 'openai' | 'anthropic'
  base_url: string
  model_name: string
  api_key: string
  clear_api_key: boolean
}

export interface McpToolSummary { name: string; description: string }

export interface McpServerConfig {
  id: number
  server_key: string
  display_name: string
  description: string
  url: string
  transport: 'streamable_http' | string
  auth_type: 'none' | 'bearer' | string
  auth_token_configured: boolean
  auth_token_masked: string | null
  enabled: boolean
  last_test_status: string
  last_test_message: string
  last_test_at: string | null
  tools: McpToolSummary[]
  created_at: string | null
  updated_at: string | null
}

export interface McpServerForm {
  id: number | null
  server_key: string
  display_name: string
  description: string
  url: string
  auth_type: 'none' | 'bearer'
  auth_token: string
  clear_auth_token: boolean
  enabled: boolean
}

export type SourceKey = 'arxiv' | 'github' | 'hackernews' | 'producthunt' | 'news' | 'x'

export interface GithubCrawlForm {
  minStars: number
  maxStars: number
  createdStart: string
  createdEnd: string
  pushedAfter: string
  limit: number
  enrich: boolean
  dryRun: boolean
}

export interface GithubCrawlTriggerResult {
  status: string
  message: string
  channel: string
  first_seen_after: string
  result?: { shards?: Record<string, number>; total_available?: number } | null
}

export interface GithubCrawlStatus {
  status: string
  channel: string
  first_seen_after: string
  task_id: number | null
  task_status: string
  item_count: number
  error_msg: string | null
  started_at: string | null
  finished_at: string | null
  candidates_upserted: number
  scope_total: number
  enriched_succeeded: number
  enriched_failed: number
}

export interface GithubCrawlStatusQuery {
  channel?: string
  first_seen_after?: string
  min_stars?: number
}

export const createGithubCrawlForm = (today: string): GithubCrawlForm => ({
  minStars: 500,
  maxStars: 0,
  createdStart: '2008-01-01',
  createdEnd: today,
  pushedAfter: '',
  limit: 5000,
  enrich: true,
  dryRun: false,
})

export const buildGithubCrawlPayload = (form: GithubCrawlForm) => ({
  min_stars: form.minStars,
  max_stars: form.maxStars,
  created_start: form.createdStart,
  created_end: form.createdEnd || null,
  pushed_after: form.pushedAfter || null,
  limit: form.limit,
  enrich: form.enrich,
  dry_run: form.dryRun,
})

export interface McpToolCallEntry {
  calls: number
  last_called_at: string
}

export interface McpToolCallMetricsSnapshot {
  since: string
  total_calls: number
  tools: Record<string, McpToolCallEntry>
}

export const createEmptyMcpToolCallMetrics = (): McpToolCallMetricsSnapshot => ({
  since: '', total_calls: 0, tools: {},
})

export const createProviderForm = (config?: ProviderConfig | null): ProviderForm => ({
  provider: config?.provider || 'openai',
  base_url: config?.base_url || '',
  model_name: config?.model_name || '',
  api_key: '',
  clear_api_key: false,
})

export const createEmptyMcpForm = (): McpServerForm => ({
  id: null, server_key: '', display_name: '', description: '', url: '', auth_type: 'none',
  auth_token: '', clear_auth_token: false, enabled: true,
})

export const createMcpForm = (server: McpServerConfig): McpServerForm => ({
  id: server.id,
  server_key: server.server_key,
  display_name: server.display_name,
  description: server.description || '',
  url: server.url,
  auth_type: server.auth_type === 'bearer' ? 'bearer' : 'none',
  auth_token: '',
  clear_auth_token: false,
  enabled: server.enabled,
})

export const buildProviderPayload = (form: ProviderForm) => ({
  provider: form.provider,
  base_url: form.base_url,
  model_name: form.model_name,
  api_key: form.api_key || null,
  clear_api_key: form.clear_api_key,
})

export const buildMcpPayload = (form: McpServerForm) => ({
  server_key: form.server_key,
  display_name: form.display_name,
  description: form.description,
  url: form.url,
  transport: 'streamable_http' as const,
  auth_type: form.auth_type,
  auth_token: form.auth_token || null,
  clear_auth_token: form.clear_auth_token,
  enabled: form.enabled,
})

export const upsertMcpServer = (servers: McpServerConfig[], saved: McpServerConfig) => {
  const index = servers.findIndex((item) => item.id === saved.id)
  if (index < 0) return [saved, ...servers]
  return servers.map((item, itemIndex) => itemIndex === index ? saved : item)
}

export const removeMcpServer = (servers: McpServerConfig[], id: number) => servers.filter((item) => item.id !== id)

export const replaceMcpServer = (servers: McpServerConfig[], updated?: McpServerConfig) => (
  updated ? servers.map((item) => item.id === updated.id ? updated : item) : servers
)
