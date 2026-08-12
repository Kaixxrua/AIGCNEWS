export interface Task {
  id: number
  task_name: string
  status: string
  item_count: number
  error_msg: string | null
  started_at: string | null
  finished_at: string | null
}

export interface SchedulerJobConfig {
  job_id: string
  name: string
  start_time: string
  end_time: string
  interval_minutes: number
  enabled: boolean
}

export interface SchedulerJobConfigForm {
  job_id: string
  name: string
  start_time: string
  end_time: string
  interval_minutes: number
  enabled: boolean
}

export const createEmptySchedulerJobConfigForm = (job?: SchedulerJobConfig): SchedulerJobConfigForm => ({
  job_id: job?.job_id || '',
  name: job?.name || '',
  start_time: job?.start_time || '00:00',
  end_time: job?.end_time || '23:59',
  interval_minutes: job?.interval_minutes || 60,
  enabled: job?.enabled ?? true,
})

export const buildSchedulerJobConfigPayload = (form: SchedulerJobConfigForm) => ({
  start_time: form.start_time,
  end_time: form.end_time,
  interval_minutes: form.interval_minutes,
  enabled: form.enabled,
})

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

// 推理强度为自填自由文本（原样透传给服务商）；常用档位 minimal/low/medium/high
// 仅作建议值展示，不做枚举校验。空串表示不下发该参数。
export type ReasoningEffort = string

export interface ProviderConfig {
  provider: 'openai' | 'anthropic'
  base_url: string
  model_name: string
  api_key_configured: boolean
  api_key_masked: string | null
  updated_at: string | null
  reasoning_effort: ReasoningEffort
}

export interface ProviderForm {
  provider: 'openai' | 'anthropic'
  base_url: string
  model_name: string
  api_key: string
  clear_api_key: boolean
  reasoning_effort: ReasoningEffort
}

// 连接测试结果：HTTP 恒 200，status=success/failed 表达业务结果
export interface ProviderTestResult {
  status: string
  message: string
  provider?: string
  base_url?: string
  model_name?: string
  latency_ms?: number | null
}

// SMTP 投递配置生效来源：database=页面保存的 DB 覆盖行；environment=env；
// unconfigured=两者皆无（此状态下测试投递按钮禁用）
export type SmtpConfigSource = 'database' | 'environment' | 'unconfigured'

export interface SmtpConfig {
  host: string
  port: number
  username: string
  password_configured: boolean
  password_masked: string | null
  from_email: string
  from_name: string
  use_tls: boolean
  source: SmtpConfigSource
  updated_at: string | null
}

export interface SmtpForm {
  host: string
  port: number
  username: string
  password: string
  clear_password: boolean
  from_email: string
  from_name: string
  use_tls: boolean
}

// 测试投递结果：HTTP 层 200/400/502 表达配置与投递状态，status 表达业务结果
export interface SmtpTestResult {
  status: string
  message: string
  to_email?: string
  latency_ms?: number | null
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

export interface GithubEnrichmentStatus {
  eligible: number
  succeeded: number
  failed: number
  pending: number
  // 后端进程内是否有富化批处理在跑；刷新页面后据此恢复「终止」入口
  running?: boolean
  by_category?: Array<{ slug: string; name: string; count: number }>
}

// 富化任务专用推理强度配置：reasoning_effort 为空串表示跟随模型服务配置，
// effective_reasoning_effort 为后端按 专用 > 模型服务 > medium 解析出的当前生效值
export interface GithubEnrichmentConfig {
  reasoning_effort: ReasoningEffort
  effective_reasoning_effort: string
}

export interface GithubEnrichmentTriggerResult {
  status: string
  message: string
  result?: Record<string, unknown> | null
}

export interface GithubEnrichmentCancelResult {
  status: string
  message: string
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

// 归一规则与后端 control_plane 一致：trim + 小写 + 截断列宽（VARCHAR(32)）
export const REASONING_EFFORT_MAX_LENGTH = 32

export const normalizeReasoningEffort = (value: string | null | undefined): ReasoningEffort =>
  (value || '').trim().toLowerCase().slice(0, REASONING_EFFORT_MAX_LENGTH)

// 富化并发度：与后端 GitHubProjectsEnrichRequest 的 ge=1/le=10 对齐，前端先做无害截断
export const ENRICHMENT_CONCURRENCY_MIN = 1
export const ENRICHMENT_CONCURRENCY_MAX = 10

export const normalizeEnrichmentConcurrency = (value: number | string | null | undefined): number => {
  const parsed = typeof value === 'string' ? Number(value) : value
  if (typeof parsed !== 'number' || !Number.isFinite(parsed)) return ENRICHMENT_CONCURRENCY_MIN
  return Math.min(ENRICHMENT_CONCURRENCY_MAX, Math.max(ENRICHMENT_CONCURRENCY_MIN, Math.trunc(parsed)))
}

export const createProviderForm = (config?: ProviderConfig | null): ProviderForm => ({
  provider: config?.provider || 'openai',
  base_url: config?.base_url || '',
  model_name: config?.model_name || '',
  api_key: '',
  clear_api_key: false,
  reasoning_effort: normalizeReasoningEffort(config?.reasoning_effort),
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
  reasoning_effort: normalizeReasoningEffort(form.reasoning_effort),
})

export const createSmtpForm = (config?: SmtpConfig | null): SmtpForm => ({
  host: config?.host || '',
  port: config?.port || 587,
  username: config?.username || '',
  password: '',
  clear_password: false,
  from_email: config?.from_email || '',
  from_name: config?.from_name || '',
  use_tls: config?.use_tls ?? true,
})

export const buildSmtpPayload = (form: SmtpForm) => ({
  host: form.host,
  port: form.port,
  username: form.username,
  // null has backend-defined retain semantics; never send a masked response value
  password: form.password || null,
  clear_password: form.clear_password,
  from_email: form.from_email,
  from_name: form.from_name,
  use_tls: form.use_tls,
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

export interface XWatchAccount {
  id: number
  screen_name: string
  display_name: string
  note: string
  enabled: boolean
  sort_order: number
  last_test_status: string
  last_test_message: string
  last_test_at: string | null
  created_at: string | null
  updated_at: string | null
}

export interface XWatchAccountForm {
  id: number | null
  screen_name: string
  display_name: string
  note: string
  enabled: boolean
  sort_order: number
}

export const createEmptyXWatchForm = (): XWatchAccountForm => ({
  id: null, screen_name: '', display_name: '', note: '', enabled: true, sort_order: 0,
})

export const createXWatchForm = (account: XWatchAccount): XWatchAccountForm => ({
  id: account.id,
  screen_name: account.screen_name,
  display_name: account.display_name || '',
  note: account.note || '',
  enabled: account.enabled,
  sort_order: account.sort_order,
})

export const buildXWatchPayload = (form: XWatchAccountForm) => ({
  screen_name: form.screen_name,
  display_name: form.display_name,
  note: form.note,
  enabled: form.enabled,
  sort_order: form.sort_order,
})

export const upsertXWatchAccount = (accounts: XWatchAccount[], saved: XWatchAccount) => {
  const index = accounts.findIndex((item) => item.id === saved.id)
  if (index < 0) return [saved, ...accounts]
  return accounts.map((item, itemIndex) => itemIndex === index ? saved : item)
}

export const removeXWatchAccount = (accounts: XWatchAccount[], id: number) => accounts.filter((item) => item.id !== id)

export const replaceXWatchAccount = (accounts: XWatchAccount[], updated?: XWatchAccount) => (
  updated ? accounts.map((item) => item.id === updated.id ? updated : item) : accounts
)

export interface XCredential {
  id: number
  display_name: string
  note: string
  enabled: boolean
  sort_order: number
  auth_token_configured: boolean
  auth_token_masked: string | null
  ct0_configured: boolean
  ct0_masked: string | null
  last_test_status: string
  last_test_message: string
  last_test_at: string | null
  created_at: string | null
  updated_at: string | null
}

export interface XCredentialForm {
  id: number | null
  display_name: string
  note: string
  enabled: boolean
  sort_order: number
  auth_token: string
  ct0: string
}

export const createEmptyXCredentialForm = (): XCredentialForm => ({
  id: null,
  display_name: '',
  note: '',
  enabled: true,
  sort_order: 0,
  auth_token: '',
  ct0: '',
})

export const createXCredentialForm = (credential: XCredential): XCredentialForm => ({
  id: credential.id,
  display_name: credential.display_name || '',
  note: credential.note || '',
  enabled: credential.enabled,
  sort_order: credential.sort_order,
  // Secrets are write-only. Editing a credential must never copy masked values into the form.
  auth_token: '',
  ct0: '',
})

export const buildXCredentialPayload = (form: XCredentialForm) => ({
  display_name: form.display_name,
  note: form.note,
  enabled: form.enabled,
  sort_order: form.sort_order,
  // null has backend-defined retain semantics; never send a masked response value.
  auth_token: form.auth_token || null,
  ct0: form.ct0 || null,
})

export const upsertXCredential = (credentials: XCredential[], saved: XCredential) => {
  const index = credentials.findIndex((item) => item.id === saved.id)
  if (index < 0) return [saved, ...credentials]
  return credentials.map((item, itemIndex) => itemIndex === index ? saved : item)
}

export const removeXCredential = (credentials: XCredential[], id: number) => credentials.filter((item) => item.id !== id)

export const replaceXCredential = (credentials: XCredential[], updated?: XCredential) => (
  updated ? credentials.map((item) => item.id === updated.id ? updated : item) : credentials
)
