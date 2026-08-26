export interface Task {
  id: number
  task_name: string
  status: string
  item_count: number
  error_msg: string | null
  started_at: string | null
  finished_at: string | null
}

export interface XTranslationStatus {
  pending: number
  running: number
  succeeded: number
  failed: number
  skipped: number
  retryable: number
  stale_running: number
  batch_running: number
  latest_failure_error: string | null
  latest_failure_model_provider: string | null
  latest_failure_model_name: string | null
}

export interface XTranslationRetryResult {
  status: string
  message: string
  result?: { retryable?: number; limit?: number }
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

// 后端错误事件（error_events 表）：/monitor/errors 分页包络与 /monitor/tasks 同形
export interface ErrorLogEntry {
  id: number
  occurred_at: string | null
  level: string
  logger_name: string
  message: string
  exception_type: string | null
  stack_trace: string | null
}

export interface ErrorLogPage {
  items: ErrorLogEntry[]
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

// ── 站点联系合作页 ────────────────────────────────────────────────────────

export interface SiteContactServiceCardForm {
  title: string
  description: string
  icon: string
}

export interface SiteContactEntryForm {
  label: string
  value: string
  href: string
  qr_image_url: string
}

/** 管理端读取的联系合作页配置（wire 与响应同构，snake_case） */
export interface SiteContactPageConfig {
  enabled: boolean
  nav_label: string
  title: string
  subtitle: string
  service_cards: SiteContactServiceCardForm[]
  contact_entries: SiteContactEntryForm[]
  body_markdown: string
  updated_at: string | null
}

export interface SiteContactPageForm {
  enabled: boolean
  nav_label: string
  title: string
  subtitle: string
  service_cards: SiteContactServiceCardForm[]
  contact_entries: SiteContactEntryForm[]
  body_markdown: string
}

/** 站点公开素材上传结果（wire 与响应同构，snake_case）；url 为站内 /api/media/site/... 相对路径 */
export interface SiteImageUploadResult {
  url: string
  filename: string
  size_bytes: number
  mime_type: string
}

// 测试投递结果：HTTP 层 200/400/502 表达配置与投递状态，status 表达业务结果
export interface SmtpTestResult {
  status: string
  message: string
  to_email?: string
  latency_ms?: number | null
}

// ── 邮件池（多服务商 priority failover + 配额护栏）─────────────────────────────
// 生效来源与单 SMTP 同语义；保存空 entries = 删除 DB 覆盖行、整体回退
// EMAIL_POOL_JSON env。entry 以 name 为键：password 留空保留同名已存密码，
// 改名视为新 entry（不继承密码）。
export interface EmailPoolEntryConfig {
  name: string
  host: string
  port: number
  username: string
  password_configured: boolean
  password_masked: string | null
  from_email: string
  from_name: string
  use_tls: boolean
  daily_limit: number
  monthly_limit: number
  priority: number
}

export interface EmailPoolConfig {
  entries: EmailPoolEntryConfig[]
  source: SmtpConfigSource
  updated_at: string | null
}

export interface EmailPoolEntryForm {
  name: string
  host: string
  port: number
  username: string
  password: string
  clear_password: boolean
  from_email: string
  from_name: string
  use_tls: boolean
  daily_limit: number
  monthly_limit: number
  priority: number
}

export interface EmailPoolForm {
  entries: EmailPoolEntryForm[]
}

// 池测试投递结果：provider 为实际投递成功的服务商名（验证 failover 链路）
export interface EmailPoolTestResult {
  status: string
  message: string
  to_email?: string
  provider?: string | null
  latency_ms?: number | null
}

// 按 Asia/Shanghai 自然日归日的 email 渠道投递统计；无记录的日期不下发
export interface EmailDeliveryDayStat {
  date: string
  sent: number
  failed: number
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

export interface GithubUnprocessableProject {
  repo_id: string
  full_name: string
  url: string
  stars: number
  reason: 'missing_description'
}

// 在库但已退出可执行队列的项目（catalog_succeeded − eligible 差额）的互斥原因：
// not_found=源仓库 404 下架；snapshot_below_threshold=最新快照星数回落至门槛以下；
// lost_input=简介被作者删除且无有效 README；tombstone=改名前的旧仓库行（成果归一到新名）
export type GithubRetainedReason =
  | 'not_found'
  | 'snapshot_below_threshold'
  | 'lost_input'
  | 'tombstone'

export interface GithubRetainedProject {
  repo_id: string
  full_name: string
  url: string
  stars: number
  reason: GithubRetainedReason
}

export interface GithubEnrichmentStatus {
  eligible: number
  succeeded: number
  failed: number
  pending: number
  // 在库但按当前口径不再处理的项目：分桶计数 + 溯源列表（上限 100 条）
  retained_total?: number
  retained_buckets?: Partial<Record<GithubRetainedReason, number>>
  retained_projects?: GithubRetainedProject[]
  /** All canonical projects with successful generated enrichment, independent of current intake stars/input. */
  content_total?: number
  /** Same project-library total used by the homepage GitHub source card. */
  github_library_total?: number
  catalog_total?: number
  catalog_succeeded?: number
  catalog_failed?: number
  catalog_pending?: number
  catalog_unprocessable?: number
  /** Pending count in the currently executable queue; distinct from catalog pending. */
  queue_pending?: number
  queue_failed?: number
  catalog_progress?: { total: number; succeeded: number; failed: number; unprocessable: number; pending: number }
  // 后端进程内是否有富化批处理在跑；刷新页面后据此恢复「终止」入口
  running?: boolean
  by_category?: Array<{ slug: string; name: string; count: number }>
  unprocessable?: number
  unprocessable_projects?: GithubUnprocessableProject[]
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

/* 访客平台统计：桶集合与后端 visit_platforms.PLATFORM_BUCKETS 双向冻结。
   share 是后端信息性字段（一位小数直接相加可能漂移 ±0.1），
   UI 展示百分比以 visits 经 visitStatsViewModel.computeShares 本地重算为准。 */
export type VisitPlatformKey = 'ios' | 'android' | 'windows' | 'macos' | 'other'

export type VisitStatsWindow = 'today' | '7d' | '30d' | 'all'

export interface VisitPlatformShare {
  platform: VisitPlatformKey
  visits: number
  share: number
}

export interface VisitPlatformStatsResponse {
  window: VisitStatsWindow
  /** all 窗口为 null（无下界） */
  start_date: string | null
  end_date: string
  total_visits: number
  platforms: VisitPlatformShare[]
}

/* 用户与会员统计：member_users 是生效 VIP 数（member 档且未到期），
   口径与后端 tiers.resolve_effective_tier 一致（到期自动回落 free，库内不回写）。 */
export interface UserStatsResponse {
  total_users: number
  member_users: number
}

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

export const createEmailPoolEntryForm = (
  entry?: EmailPoolEntryConfig | null,
): EmailPoolEntryForm => ({
  name: entry?.name || '',
  host: entry?.host || '',
  port: entry?.port || 587,
  username: entry?.username || '',
  password: '',
  clear_password: false,
  from_email: entry?.from_email || '',
  from_name: entry?.from_name || '',
  use_tls: entry?.use_tls ?? true,
  daily_limit: entry?.daily_limit || 0,
  monthly_limit: entry?.monthly_limit || 0,
  priority: entry?.priority ?? 100,
})

export const createEmailPoolForm = (config?: EmailPoolConfig | null): EmailPoolForm => ({
  entries: (config?.entries ?? []).map((entry) => createEmailPoolEntryForm(entry)),
})

export const buildEmailPoolPayload = (form: EmailPoolForm) => ({
  entries: form.entries.map((entry) => ({
    name: entry.name.trim(),
    host: entry.host.trim(),
    port: entry.port,
    username: entry.username.trim(),
    // null has backend-defined retain-by-name semantics
    password: entry.password || null,
    clear_password: entry.clear_password,
    from_email: entry.from_email.trim(),
    from_name: entry.from_name.trim(),
    use_tls: entry.use_tls,
    daily_limit: entry.daily_limit,
    monthly_limit: entry.monthly_limit,
    priority: entry.priority,
  })),
})

export const createSiteContactPageForm = (
  config?: SiteContactPageConfig | null,
): SiteContactPageForm => ({
  enabled: config?.enabled ?? false,
  nav_label: config?.nav_label || '',
  title: config?.title || '',
  subtitle: config?.subtitle || '',
  service_cards: (config?.service_cards ?? []).map((card) => ({
    title: card.title || '',
    description: card.description || '',
    icon: card.icon || '',
  })),
  contact_entries: (config?.contact_entries ?? []).map((entry) => ({
    label: entry.label || '',
    value: entry.value || '',
    href: entry.href || '',
    qr_image_url: entry.qr_image_url || '',
  })),
  body_markdown: config?.body_markdown || '',
})

export const buildSiteContactPagePayload = (form: SiteContactPageForm) => ({
  enabled: form.enabled,
  nav_label: form.nav_label.trim(),
  title: form.title.trim(),
  subtitle: form.subtitle.trim(),
  service_cards: form.service_cards.map((card) => ({
    title: card.title.trim(),
    description: card.description.trim(),
    icon: card.icon.trim(),
  })),
  contact_entries: form.contact_entries.map((entry) => ({
    label: entry.label.trim(),
    value: entry.value.trim(),
    href: entry.href.trim(),
    qr_image_url: entry.qr_image_url.trim(),
  })),
  body_markdown: form.body_markdown,
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

// ── 用户组（会员档位）运营授予 ─────────────────────────────────────────────
// 与后端 routes_ops_membership 契约同构：库内权威档位只有 free / member，
// tier=free 即吊销会员；授予/吊销下一个请求即生效（RequireUser 每请求查库）。
export type MembershipTier = 'free' | 'member'

export interface MembershipGrantForm {
  email: string
  tier: MembershipTier
  /** YYYY-MM-DD；空串 = 长期有效。仅 member 档有意义（free 吊销时后端强制清空） */
  expires_on: string
}

export interface MembershipGrantResult {
  user_id: number
  email: string | null
  membership_tier: string
  membership_expires_at: string | null
  revoked: boolean
}

// ── 用户列表（会员运营）─────────────────────────────────────────────────────
// 与 GET /ops/membership/users 契约同构；effective_tier 为后端裁决的生效档位
// （member 到期自动回落 free，库内 membership_tier 不回写）。
export interface MembershipUserItem {
  user_id: number
  email: string | null
  phone: string | null
  username: string | null
  role: string
  disabled: boolean
  membership_tier: MembershipTier
  membership_expires_at: string | null
  created_at: string | null
  effective_tier: MembershipTier
}

export interface MembershipUserPage {
  items: MembershipUserItem[]
  total: number
  page: number
  page_size: number
}

export interface PaymentOrder {
  id: number
  order_no: string
  user_id: number
  email: string | null
  plan_code: string
  channel: string
  amount_cents: number
  currency: string
  status: string
  channel_order_no: string
  idempotency_key: string
  paid_at: string | null
  grant_expires_at: string | null
  expires_at: string
  created_at: string
  updated_at: string
  callback_payload?: string
}

export interface PaymentOrderPage {
  items: PaymentOrder[]
  total: number
  page: number
  page_size: number
}

// ── 支付渠道配置（ADR 0002 面板）────────────────────────────────────────────
// 生效来源与 SMTP 同语义：database=页面保存的 DB 覆盖行；environment=env；
// unconfigured=两者皆无。密文字段只回 *_configured 布尔 + *_masked 脱敏值，
// 永不回明文；表单密文留空=保留，勾选 clear_*=擦除。

export interface PaymentConfig {
  enabled: boolean
  order_ttl_minutes: number
  public_base_url: string
  wechat_appid: string
  wechat_mchid: string
  wechat_mch_serial_no: string
  alipay_appid: string
  source: SmtpConfigSource
  updated_at: string | null
  wechat_configured: boolean
  alipay_configured: boolean
  overseas_configured: boolean
  overseas_provider: string
  overseas_sandbox: boolean
  overseas_client_id: string
  wechat_api_v3_key_configured: boolean
  wechat_api_v3_key_masked: string | null
  wechat_private_key_pem_configured: boolean
  wechat_private_key_pem_masked: string | null
  wechat_public_key_id: string
  wechat_public_key_pem_configured: boolean
  wechat_public_key_pem_masked: string | null
  alipay_private_key_pem_configured: boolean
  alipay_private_key_pem_masked: string | null
  alipay_public_key_pem_configured: boolean
  alipay_public_key_pem_masked: string | null
  overseas_client_secret_configured: boolean
  overseas_client_secret_masked: string | null
  overseas_webhook_secret_configured: boolean
  overseas_webhook_secret_masked: string | null
}

export interface PaymentConfigForm {
  enabled: boolean
  order_ttl_minutes: number
  public_base_url: string
  wechat_appid: string
  wechat_mchid: string
  wechat_mch_serial_no: string
  wechat_api_v3_key: string
  wechat_private_key_pem: string
  wechat_public_key_id: string
  wechat_public_key_pem: string
  alipay_appid: string
  alipay_private_key_pem: string
  alipay_public_key_pem: string
  overseas_provider: string
  overseas_sandbox: boolean
  overseas_client_id: string
  overseas_client_secret: string
  overseas_webhook_secret: string
  clear_wechat_api_v3_key: boolean
  clear_wechat_private_key_pem: boolean
  clear_wechat_public_key_pem: boolean
  clear_alipay_private_key_pem: boolean
  clear_alipay_public_key_pem: boolean
  clear_overseas_client_secret: boolean
  clear_overseas_webhook_secret: boolean
}

export const createPaymentConfigForm = (config?: PaymentConfig | null): PaymentConfigForm => ({
  enabled: config?.enabled ?? false,
  order_ttl_minutes: config?.order_ttl_minutes || 30,
  public_base_url: config?.public_base_url || '',
  wechat_appid: config?.wechat_appid || '',
  wechat_mchid: config?.wechat_mchid || '',
  wechat_mch_serial_no: config?.wechat_mch_serial_no || '',
  wechat_api_v3_key: '',
  wechat_private_key_pem: '',
  wechat_public_key_id: config?.wechat_public_key_id || '',
  wechat_public_key_pem: '',
  alipay_appid: config?.alipay_appid || '',
  alipay_private_key_pem: '',
  alipay_public_key_pem: '',
  overseas_provider: config?.overseas_provider || '',
  overseas_sandbox: config?.overseas_sandbox ?? false,
  overseas_client_id: config?.overseas_client_id || '',
  overseas_client_secret: '',
  overseas_webhook_secret: '',
  clear_wechat_api_v3_key: false,
  clear_wechat_private_key_pem: false,
  clear_wechat_public_key_pem: false,
  clear_alipay_private_key_pem: false,
  clear_alipay_public_key_pem: false,
  clear_overseas_client_secret: false,
  clear_overseas_webhook_secret: false,
})

// null 密文 = 后端保留语义；绝不回传 masked 响应值
export const buildPaymentConfigPayload = (form: PaymentConfigForm) => ({
  enabled: form.enabled,
  order_ttl_minutes: form.order_ttl_minutes,
  public_base_url: form.public_base_url.trim(),
  wechat_appid: form.wechat_appid.trim(),
  wechat_mchid: form.wechat_mchid.trim(),
  wechat_mch_serial_no: form.wechat_mch_serial_no.trim(),
  wechat_api_v3_key: form.wechat_api_v3_key || null,
  wechat_private_key_pem: form.wechat_private_key_pem || null,
  wechat_public_key_id: form.wechat_public_key_id.trim(),
  wechat_public_key_pem: form.wechat_public_key_pem || null,
  alipay_appid: form.alipay_appid.trim(),
  alipay_private_key_pem: form.alipay_private_key_pem || null,
  alipay_public_key_pem: form.alipay_public_key_pem || null,
  overseas_provider: form.overseas_provider,
  overseas_sandbox: form.overseas_sandbox,
  overseas_client_id: form.overseas_client_id.trim(),
  overseas_client_secret: form.overseas_client_secret || null,
  overseas_webhook_secret: form.overseas_webhook_secret || null,
  clear_wechat_api_v3_key: form.clear_wechat_api_v3_key,
  clear_wechat_private_key_pem: form.clear_wechat_private_key_pem,
  clear_wechat_public_key_pem: form.clear_wechat_public_key_pem,
  clear_alipay_private_key_pem: form.clear_alipay_private_key_pem,
  clear_alipay_public_key_pem: form.clear_alipay_public_key_pem,
  clear_overseas_client_secret: form.clear_overseas_client_secret,
  clear_overseas_webhook_secret: form.clear_overseas_webhook_secret,
})

// ── 会员套餐定价（监控页自助调价，ADR 0002 运行时覆盖）────────────────────
// 默认价权威在后端 plans.py；本面板写的是 payment_plan_overrides 覆盖行，
// null = 删除覆盖恢复默认。金额入表单按元（最多两位小数），出 payload 转整数分。

export interface PaymentPlanPricing {
  code: string
  tier: string
  currency: string
  months: number
  default_amount_cents: number
  override_amount_cents: number | null
  amount_cents: number
  updated_at: string | null
}

export interface PaymentPlanPricingForm {
  monthly_yuan: string
  yearly_yuan: string
}

export interface PaymentPlanPricingPayload {
  monthly_amount_cents: number | null
  yearly_amount_cents: number | null
}

const centsToYuanInput = (cents: number | null): string =>
  cents === null ? '' : String(cents / 100)

export const createPaymentPlanPricingForm = (
  plans?: PaymentPlanPricing[] | null,
): PaymentPlanPricingForm => ({
  monthly_yuan: centsToYuanInput(
    plans?.find((plan) => plan.code === 'member_monthly')?.override_amount_cents ?? null,
  ),
  yearly_yuan: centsToYuanInput(
    plans?.find((plan) => plan.code === 'member_yearly')?.override_amount_cents ?? null,
  ),
})

// '' = 恢复默认（null）；正则钉死「元、最多两位小数」，×100 四舍五入到分；
// 边界 1–10000 元与后端 100–1000000 分一致（拦「把分当元」录入事故）。
const PRICING_YUAN_PATTERN = /^\d+(\.\d{1,2})?$/
const PRICING_MIN_YUAN = 1
const PRICING_MAX_YUAN = 10000

const yuanToCents = (yuan: string): number | null | undefined => {
  const trimmed = yuan.trim()
  if (trimmed === '') return null
  if (!PRICING_YUAN_PATTERN.test(trimmed)) return undefined
  const value = Number(trimmed)
  if (!(value >= PRICING_MIN_YUAN && value <= PRICING_MAX_YUAN)) return undefined
  return Math.round(value * 100)
}

export const buildPaymentPlanPricingPayload = (
  form: PaymentPlanPricingForm,
): PaymentPlanPricingPayload | null => {
  const monthly = yuanToCents(form.monthly_yuan)
  const yearly = yuanToCents(form.yearly_yuan)
  if (monthly === undefined || yearly === undefined) return null
  return { monthly_amount_cents: monthly, yearly_amount_cents: yearly }
}

// ── OAuth 快捷登录配置（Monitor 面板）────────────────────────────────────────
// 与支付配置同语义：database=DB 覆盖行；environment=env；unconfigured=两者皆无。
// 密文（client secret / app secret）只写入不回填；留空=保留，勾选 clear_*=擦除。
// 保存/重置后由控制器调用 refreshFeatureFlags() 让登录页按钮即时显隐。

export type OAuthProviderKey = 'github' | 'google' | 'wechat'

export interface OAuthConfig {
  enabled_providers: OAuthProviderKey[]
  public_base_url: string
  github_client_id: string
  google_client_id: string
  wechat_app_id: string
  state_ttl_seconds: number
  handoff_ttl_seconds: number
  source: SmtpConfigSource
  updated_at: string | null
  github_client_secret_configured: boolean
  github_client_secret_masked: string | null
  google_client_secret_configured: boolean
  google_client_secret_masked: string | null
  wechat_app_secret_configured: boolean
  wechat_app_secret_masked: string | null
}

export interface OAuthConfigForm {
  enabled_providers: OAuthProviderKey[]
  public_base_url: string
  github_client_id: string
  github_client_secret: string
  google_client_id: string
  google_client_secret: string
  wechat_app_id: string
  wechat_app_secret: string
  state_ttl_seconds: number
  handoff_ttl_seconds: number
  clear_github_client_secret: boolean
  clear_google_client_secret: boolean
  clear_wechat_app_secret: boolean
}

export const createOAuthConfigForm = (config?: OAuthConfig | null): OAuthConfigForm => ({
  enabled_providers: [...(config?.enabled_providers ?? [])],
  public_base_url: config?.public_base_url || '',
  github_client_id: config?.github_client_id || '',
  github_client_secret: '',
  google_client_id: config?.google_client_id || '',
  google_client_secret: '',
  wechat_app_id: config?.wechat_app_id || '',
  wechat_app_secret: '',
  state_ttl_seconds: config?.state_ttl_seconds || 300,
  handoff_ttl_seconds: config?.handoff_ttl_seconds || 120,
  clear_github_client_secret: false,
  clear_google_client_secret: false,
  clear_wechat_app_secret: false,
})

// null 密文 = 后端保留语义；绝不回传 masked 响应值
export const buildOAuthConfigPayload = (form: OAuthConfigForm) => ({
  enabled_providers: form.enabled_providers,
  public_base_url: form.public_base_url.trim(),
  github_client_id: form.github_client_id.trim(),
  github_client_secret: form.github_client_secret || null,
  google_client_id: form.google_client_id.trim(),
  google_client_secret: form.google_client_secret || null,
  wechat_app_id: form.wechat_app_id.trim(),
  wechat_app_secret: form.wechat_app_secret || null,
  state_ttl_seconds: form.state_ttl_seconds,
  handoff_ttl_seconds: form.handoff_ttl_seconds,
  clear_github_client_secret: form.clear_github_client_secret,
  clear_google_client_secret: form.clear_google_client_secret,
  clear_wechat_app_secret: form.clear_wechat_app_secret,
})

// ── Telegram 推送配置（Monitor 面板）─────────────────────────────────────────
// 与 OAuth 同语义：database=DB 覆盖行；environment=env；unconfigured=两者皆无。
// bot_token / webhook_secret 只写入不回填；留空=保留，勾选 clear_*=擦除。
// 保存新 token 时后端先调 getMe 校验并以返回值回填 bot username；
// 保存/重置后由控制器调用 refreshFeatureFlags() 让订阅页 Telegram 卡片即时显隐。

export interface TelegramWebhookStatus {
  url: string
  pending_update_count: number | null
  last_error_message: string | null
}

export interface TelegramConfig {
  enabled: boolean
  bot_username: string
  link_ttl_seconds: number
  request_timeout_seconds: number
  source: SmtpConfigSource
  updated_at: string | null
  bot_token_configured: boolean
  bot_token_masked: string | null
  webhook_secret_configured: boolean
  webhook_secret_masked: string | null
  webhook: TelegramWebhookStatus | null
}

export interface TelegramConfigForm {
  enabled: boolean
  bot_token: string
  bot_username: string
  webhook_secret: string
  link_ttl_seconds: number
  request_timeout_seconds: number
  clear_bot_token: boolean
  clear_webhook_secret: boolean
}

export const createTelegramConfigForm = (config?: TelegramConfig | null): TelegramConfigForm => ({
  enabled: config?.enabled ?? false,
  bot_token: '',
  bot_username: config?.bot_username || '',
  webhook_secret: '',
  link_ttl_seconds: config?.link_ttl_seconds || 300,
  request_timeout_seconds: config?.request_timeout_seconds || 5,
  clear_bot_token: false,
  clear_webhook_secret: false,
})

// null 密文 = 后端保留语义；绝不回传 masked 响应值
export const buildTelegramConfigPayload = (form: TelegramConfigForm) => ({
  enabled: form.enabled,
  bot_token: form.bot_token || null,
  bot_username: form.bot_username.trim().replace(/^@/, ''),
  webhook_secret: form.webhook_secret || null,
  link_ttl_seconds: form.link_ttl_seconds,
  request_timeout_seconds: form.request_timeout_seconds,
  clear_bot_token: form.clear_bot_token,
  clear_webhook_secret: form.clear_webhook_secret,
})

export const createMembershipGrantForm = (): MembershipGrantForm => ({
  email: '',
  tier: 'member',
  expires_on: '',
})

// 到期日为日期粒度：按北京时间当日 23:59:59 收口（+08:00 显式时区），
// 与站点「北京时间」口径一致；后端对 naive datetime 才按 UTC 兜底。
export const buildMembershipGrantPayload = (form: MembershipGrantForm) => ({
  email: form.email.trim().toLowerCase(),
  tier: form.tier,
  expires_at: form.tier === 'member' && form.expires_on
    ? `${form.expires_on}T23:59:59+08:00`
    : null,
})

// 列表「编辑」回填表单：ISO 到期时刻 → 北京时间日期（buildMembershipGrantPayload
// 的逆运算），date input 只接受 YYYY-MM-DD；NULL 到期 = 长期有效，回填空串
export const membershipExpiryToFormDate = (value: string | null | undefined): string => {
  if (!value) return ''
  const timestamp = Date.parse(value)
  if (Number.isNaN(timestamp)) return ''
  return new Date(timestamp + 8 * 3600 * 1000).toISOString().slice(0, 10)
}
