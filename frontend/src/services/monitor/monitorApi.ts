import { api } from '@/services/http/apiClient'
import type {
  ErrorLogPage,
  EmailPoolConfig, EmailPoolForm, EmailPoolTestResult,
  GithubCrawlForm, GithubCrawlStatus, GithubCrawlStatusQuery, GithubCrawlTriggerResult,
  GithubEnrichmentConfig, GithubEnrichmentStatus, GithubEnrichmentTriggerResult, GithubEnrichmentCancelResult,
  McpServerConfig, McpServerForm, McpToolCallMetricsSnapshot, MembershipGrantForm, MembershipGrantResult, PagedResult, PaymentConfig, PaymentConfigForm, ProviderConfig, ProviderForm, ProviderTestResult,
  SchedulerJobConfig, SchedulerJobConfigForm, SchedulerStatus, SiteContactPageConfig, SiteContactPageForm, SiteImageUploadResult, SmtpConfig, SmtpForm, SmtpTestResult, SourceKey, XCredential, XCredentialForm, XTranslationRetryResult, XTranslationStatus, XWatchAccount, XWatchAccountForm,
} from '@/features/monitor/monitorModel'
import { buildEmailPoolPayload, buildGithubCrawlPayload, buildMcpPayload, buildMembershipGrantPayload, buildPaymentConfigPayload, buildProviderPayload, buildSchedulerJobConfigPayload, buildSiteContactPagePayload, buildSmtpPayload, buildXCredentialPayload, buildXWatchPayload, createEmptyMcpToolCallMetrics, normalizeReasoningEffort } from '@/features/monitor/monitorModel'

export interface MonitorApi {
  fetchTasks(page: number, pageSize: number): Promise<PagedResult>
  fetchErrorLogs(page: number, pageSize: number): Promise<ErrorLogPage>
  fetchPaymentOrders(params: { status?: string; channel?: string; planCode?: string; email?: string; page: number; pageSize: number }): Promise<import('@/features/monitor/monitorModel').PaymentOrderPage>
  fetchPaymentOrderDetail(orderNo: string): Promise<import('@/features/monitor/monitorModel').PaymentOrder>
  markPaymentOrderPaid(orderNo: string, note?: string): Promise<{ order?: import('@/features/monitor/monitorModel').PaymentOrder }>
  closePaymentOrder(orderNo: string): Promise<{ order?: import('@/features/monitor/monitorModel').PaymentOrder }>
  fetchPaymentConfig(): Promise<PaymentConfig>
  savePaymentConfig(form: PaymentConfigForm): Promise<PaymentConfig>
  resetPaymentConfig(): Promise<PaymentConfig>
  fetchSchedulerStatus(): Promise<SchedulerStatus>
  fetchSchedulerConfigs(): Promise<SchedulerJobConfig[]>
  saveSchedulerConfig(form: SchedulerJobConfigForm): Promise<{ item?: SchedulerJobConfig; message?: string }>
  fetchMcpToolCalls(): Promise<McpToolCallMetricsSnapshot>
  fetchProviderConfig(): Promise<ProviderConfig>
  saveProviderConfig(form: ProviderForm): Promise<ProviderConfig>
  testProviderConnection(): Promise<ProviderTestResult>
  fetchSmtpConfig(): Promise<SmtpConfig>
  saveSmtpConfig(form: SmtpForm): Promise<SmtpConfig>
  testSmtpConfig(): Promise<SmtpTestResult>
  fetchEmailPoolConfig(): Promise<EmailPoolConfig>
  saveEmailPoolConfig(form: EmailPoolForm): Promise<EmailPoolConfig>
  testEmailPoolConfig(): Promise<EmailPoolTestResult>
  fetchSiteContactPageConfig(): Promise<SiteContactPageConfig>
  saveSiteContactPageConfig(form: SiteContactPageForm): Promise<SiteContactPageConfig>
  uploadSiteImage(file: File): Promise<SiteImageUploadResult>
  fetchMcpServers(): Promise<McpServerConfig[]>
  saveMcpServer(form: McpServerForm): Promise<McpServerConfig>
  testMcpServer(id: number): Promise<{ server?: McpServerConfig; status?: string; message?: string }>
  deleteMcpServer(id: number): Promise<{ message?: string }>
  fetchXWatchAccounts(): Promise<XWatchAccount[]>
  saveXWatchAccount(form: XWatchAccountForm): Promise<XWatchAccount>
  deleteXWatchAccount(id: number): Promise<{ message?: string; deleted?: boolean }>
  testXWatchAccount(id: number): Promise<{ status?: string; message?: string; account?: XWatchAccount }>
  fetchXCredentials(): Promise<XCredential[]>
  saveXCredential(form: XCredentialForm): Promise<XCredential>
  deleteXCredential(id: number): Promise<{ message?: string; deleted?: boolean }>
  testXCredential(id: number): Promise<{ status?: string; message?: string; credential?: XCredential }>
  fetchXTranslationStatus(): Promise<XTranslationStatus>
  retryXTranslations(limit?: number, concurrency?: number): Promise<XTranslationRetryResult>
  ingestSource(source: SourceKey): Promise<{ message?: string }>
  generateAllBriefings(forceRegenerate: boolean): Promise<{ message?: string }>
  clearDashboardCache(): Promise<{ message?: string }>
  syncData(force: boolean): Promise<{ message?: string }>
  ingestByDate(targetDate: string): Promise<{ message?: string }>
  clearAllData(): Promise<{ message?: string }>
  crawlGithubProjects(form: GithubCrawlForm): Promise<GithubCrawlTriggerResult>
  fetchGithubCrawlStatus(query?: GithubCrawlStatusQuery): Promise<GithubCrawlStatus>
  fetchGithubEnrichmentStatus(): Promise<GithubEnrichmentStatus>
  fetchGithubEnrichmentConfig(): Promise<GithubEnrichmentConfig>
  saveGithubEnrichmentConfig(reasoningEffort: string): Promise<GithubEnrichmentConfig>
  triggerGithubEnrichment(limit: number, concurrency: number): Promise<GithubEnrichmentTriggerResult>
  cancelGithubEnrichment(): Promise<GithubEnrichmentCancelResult>
  grantMembership(form: MembershipGrantForm): Promise<MembershipGrantResult>
}

export const monitorApi: MonitorApi = {
  async fetchTasks(page, pageSize) {
    const { data } = await api.get('/monitor/tasks', { params: { page, page_size: pageSize } })
    return { items: data?.items || [], total: data?.total || 0, page: data?.page || page, page_size: data?.page_size || pageSize }
  },
  async fetchErrorLogs(page, pageSize) {
    const { data } = await api.get('/monitor/errors', { params: { page, page_size: pageSize } })
    return { items: data?.items || [], total: data?.total || 0, page: data?.page || page, page_size: data?.page_size || pageSize }
  },
  async fetchPaymentOrders({ status, channel, planCode, email, page, pageSize }) {
    const { data } = await api.get('/ops/payments/orders', { params: { status, channel, plan_code: planCode, email, page, page_size: pageSize } })
    return { items: Array.isArray(data?.items) ? data.items : [], total: data?.total || 0, page: data?.page || page, page_size: data?.page_size || pageSize }
  },
  async fetchPaymentOrderDetail(orderNo) { return (await api.get(`/ops/payments/orders/${encodeURIComponent(orderNo)}`)).data },
  async markPaymentOrderPaid(orderNo, note = '') { return (await api.post(`/ops/payments/orders/${encodeURIComponent(orderNo)}/mark-paid`, { note })).data },
  async closePaymentOrder(orderNo) { return (await api.post(`/ops/payments/orders/${encodeURIComponent(orderNo)}/close`)).data },
  // 支付渠道配置：GET 只回脱敏投影；PUT 密文留空保留、clear_* 擦除；DELETE 删 DB 覆盖行回退 env
  async fetchPaymentConfig() { return (await api.get('/ops/payments/config')).data },
  async savePaymentConfig(form) { return (await api.put('/ops/payments/config', buildPaymentConfigPayload(form))).data },
  async resetPaymentConfig() { return (await api.delete('/ops/payments/config')).data },
  async fetchSchedulerStatus() { return (await api.get('/ops/scheduler/status')).data },
  async fetchSchedulerConfigs() {
    const { data } = await api.get('/ops/scheduler/config')
    return Array.isArray(data?.items) ? data.items : []
  },
  async saveSchedulerConfig(form) {
    const payload = buildSchedulerJobConfigPayload(form)
    const { data } = await api.put(`/ops/scheduler/config/${encodeURIComponent(form.job_id)}`, payload)
    return { item: data?.item, message: typeof data?.message === 'string' ? data.message : undefined }
  },
  async fetchMcpToolCalls() {
    const { data } = await api.get('/monitor/metrics')
    const section = data?.mcp_tool_calls
    if (!section || typeof section !== 'object') return createEmptyMcpToolCallMetrics()
    return {
      since: typeof section.since === 'string' ? section.since : '',
      total_calls: Number(section.total_calls) || 0,
      tools: section.tools && typeof section.tools === 'object' ? section.tools : {},
    }
  },
  async fetchProviderConfig() { return (await api.get('/ops/provider-config')).data },
  async saveProviderConfig(form) { return (await api.put('/ops/provider-config', buildProviderPayload(form))).data },
  // 测试会真实请求一次模型服务（先例：testMcpServer / testXWatchAccount 的 30s 超时）
  async testProviderConnection() { return (await api.post('/ops/provider-config/test', null, { timeout: 45_000 })).data },
  async fetchSmtpConfig() { return (await api.get('/ops/smtp/config')).data },
  async saveSmtpConfig(form) { return (await api.put('/ops/smtp/config', buildSmtpPayload(form))).data },
  // 测试按最新生效配置真实投递一封邮件（SMTP 握手+投递可能数秒），收件人
  // 缺省为当前管理员登录邮箱；空 body 对象满足后端请求模型
  async testSmtpConfig() { return (await api.post('/ops/smtp/test', {}, { timeout: 45_000 })).data },
  async fetchEmailPoolConfig() { return (await api.get('/ops/email-pool/config')).data },
  async saveEmailPoolConfig(form) { return (await api.put('/ops/email-pool/config', buildEmailPoolPayload(form))).data },
  // 池测试经真实 failover 链路投递：aiosmtplib 默认单步 60s 超时会按 entry 数
  // 累加（死 host 场景），故放宽到 120s；收件人缺省为当前管理员登录邮箱
  async testEmailPoolConfig() { return (await api.post('/ops/email-pool/test', {}, { timeout: 120_000 })).data },
  async fetchSiteContactPageConfig() { return (await api.get('/ops/site/contact-page')).data },
  async saveSiteContactPageConfig(form) { return (await api.put('/ops/site/contact-page', buildSiteContactPagePayload(form))).data },
  // 站点公开素材上传（二维码/正文插图）：multipart 直传，返回站内 /api/media/site/... URL
  // 注意：api 实例默认 Content-Type=application/json，axios 1.x 遇 JSON 头会把 FormData
  // 序列化成 JSON（File 变 {}）导致 422——必须显式声明 multipart（uploadPdfAttachment 同款）。
  async uploadSiteImage(file) {
    const formData = new FormData()
    formData.append('file', file)
    return (await api.post('/ops/site/images', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60_000,
    })).data
  },
  async fetchMcpServers() {
    const { data } = await api.get('/ops/mcp-servers')
    return Array.isArray(data?.items) ? data.items : []
  },
  async saveMcpServer(form) {
    const payload = buildMcpPayload(form)
    return form.id
      ? (await api.put(`/ops/mcp-servers/${form.id}`, payload)).data
      : (await api.post('/ops/mcp-servers', payload)).data
  },
  async testMcpServer(id) { return (await api.post(`/ops/mcp-servers/${id}/test`, null, { timeout: 30_000 })).data },
  async deleteMcpServer(id) { return (await api.delete(`/ops/mcp-servers/${id}`)).data },
  async fetchXWatchAccounts() {
    const { data } = await api.get('/ops/x-watch-accounts')
    return Array.isArray(data?.items) ? data.items : []
  },
  async saveXWatchAccount(form) {
    const payload = buildXWatchPayload(form)
    return form.id
      ? (await api.put(`/ops/x-watch-accounts/${form.id}`, payload)).data
      : (await api.post('/ops/x-watch-accounts', payload)).data
  },
  async deleteXWatchAccount(id) { return (await api.delete(`/ops/x-watch-accounts/${id}`)).data },
  // X 测活要真实请求 X 拉取推文（经代理 GraphQL 多跳，实测 ~20s），30s 容易前端先超时但后端已写好结果
  async testXWatchAccount(id) { return (await api.post(`/ops/x-watch-accounts/${id}/test`, null, { timeout: 60_000 })).data },
  async fetchXCredentials() {
    const { data } = await api.get('/ops/x-credentials')
    return Array.isArray(data?.items) ? data.items : []
  },
  async saveXCredential(form) {
    const payload = buildXCredentialPayload(form)
    return form.id
      ? (await api.put(`/ops/x-credentials/${form.id}`, payload)).data
      : (await api.post('/ops/x-credentials', payload)).data
  },
  async deleteXCredential(id) { return (await api.delete(`/ops/x-credentials/${id}`)).data },
  async testXCredential(id) { return (await api.post(`/ops/x-credentials/${id}/test`, null, { timeout: 60_000 })).data },
  async fetchXTranslationStatus() { return (await api.get('/ops/x-translations/status')).data },
  async retryXTranslations(limit = 200, concurrency = 3) {
    return (await api.post('/ops/x-translations/retry', { limit, concurrency })).data
  },
  async ingestSource(source) { return (await api.post('/ops/ingest-source', null, { params: { source, limit: 20 } })).data },
  async generateAllBriefings(forceRegenerate) {
    return (await api.post('/ops/briefing/generate-all', null, { params: { force_regenerate: forceRegenerate } })).data
  },
  async clearDashboardCache() { return (await api.post('/ops/cache/clear-dashboard')).data },
  async syncData(force) { return (await api.post('/ops/ingest', { limit: 20, force })).data },
  async ingestByDate(targetDate) { return (await api.post('/ops/ingest-by-date', { target_date: targetDate, limit: 30 })).data },
  async clearAllData() { return (await api.post('/ops/clear-data')).data },
  async crawlGithubProjects(form) {
    // dry-run 分片计数可能超过默认 60s 超时（先例：testMcpServer）
    return (await api.post('/ops/github-projects/crawl', buildGithubCrawlPayload(form), { timeout: 180_000 })).data
  },
  async fetchGithubCrawlStatus(query) {
    const params = Object.fromEntries(
      Object.entries(query || {}).filter(([, value]) => value !== undefined && value !== ''),
    )
    return (await api.get(
      '/ops/github-projects/crawl/status',
      Object.keys(params).length ? { params } : undefined,
    )).data
  },
  async fetchGithubEnrichmentStatus() { return (await api.get('/ops/github-projects/enrichment-status')).data },
  async fetchGithubEnrichmentConfig() {
    const data = (await api.get('/ops/github-projects/enrichment-config')).data
    return {
      reasoning_effort: normalizeReasoningEffort(data?.reasoning_effort),
      effective_reasoning_effort: typeof data?.effective_reasoning_effort === 'string' ? data.effective_reasoning_effort : '',
    }
  },
  async saveGithubEnrichmentConfig(reasoningEffort) {
    const data = (await api.put('/ops/github-projects/enrichment-config', {
      reasoning_effort: normalizeReasoningEffort(reasoningEffort),
    })).data
    return {
      reasoning_effort: normalizeReasoningEffort(data?.reasoning_effort),
      effective_reasoning_effort: typeof data?.effective_reasoning_effort === 'string' ? data.effective_reasoning_effort : '',
    }
  },
  async triggerGithubEnrichment(limit, concurrency) {
    // 重试/补跑共用：force/refresh_changed 保持 false，成功的富化结果稳定不重跑
    return (await api.post('/ops/github-projects/enrich', {
      limit, force: false, dry_run: false, retry_failed: true, refresh_changed: false, concurrency,
    })).data
  },
  async cancelGithubEnrichment() { return (await api.post('/ops/github-projects/enrich-cancel')).data },
  // 用户组（会员档位）授予：tier=free 即吊销；后端按邮箱查库，404=用户不存在
  async grantMembership(form) {
    return (await api.post('/ops/membership/grant', buildMembershipGrantPayload(form))).data
  },
}
