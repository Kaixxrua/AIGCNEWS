import { api } from '@/services/http/apiClient'
import type {
  GithubCrawlForm, GithubCrawlStatus, GithubCrawlStatusQuery, GithubCrawlTriggerResult,
  McpServerConfig, McpServerForm, McpToolCallMetricsSnapshot, PagedResult, ProviderConfig, ProviderForm,
  SchedulerJobConfig, SchedulerJobConfigForm, SchedulerStatus, SourceKey, XCredential, XCredentialForm, XWatchAccount, XWatchAccountForm,
} from '@/features/monitor/monitorModel'
import { buildGithubCrawlPayload, buildMcpPayload, buildProviderPayload, buildSchedulerJobConfigPayload, buildXCredentialPayload, buildXWatchPayload, createEmptyMcpToolCallMetrics } from '@/features/monitor/monitorModel'

export interface MonitorApi {
  fetchTasks(page: number, pageSize: number): Promise<PagedResult>
  fetchSchedulerStatus(): Promise<SchedulerStatus>
  fetchSchedulerConfigs(): Promise<SchedulerJobConfig[]>
  saveSchedulerConfig(form: SchedulerJobConfigForm): Promise<{ item?: SchedulerJobConfig; message?: string }>
  fetchMcpToolCalls(): Promise<McpToolCallMetricsSnapshot>
  fetchProviderConfig(): Promise<ProviderConfig>
  saveProviderConfig(form: ProviderForm): Promise<ProviderConfig>
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
  ingestSource(source: SourceKey): Promise<{ message?: string }>
  generateAllBriefings(forceRegenerate: boolean): Promise<{ message?: string }>
  clearDashboardCache(): Promise<{ message?: string }>
  syncData(force: boolean): Promise<{ message?: string }>
  ingestByDate(targetDate: string): Promise<{ message?: string }>
  clearAllData(): Promise<{ message?: string }>
  crawlGithubProjects(form: GithubCrawlForm): Promise<GithubCrawlTriggerResult>
  fetchGithubCrawlStatus(query?: GithubCrawlStatusQuery): Promise<GithubCrawlStatus>
}

export const monitorApi: MonitorApi = {
  async fetchTasks(page, pageSize) {
    const { data } = await api.get('/monitor/tasks', { params: { page, page_size: pageSize } })
    return { items: data?.items || [], total: data?.total || 0, page: data?.page || page, page_size: data?.page_size || pageSize }
  },
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
  // 测试会真实请求 X 拉取推文（先例：testMcpServer 的 30s 超时）
  async testXWatchAccount(id) { return (await api.post(`/ops/x-watch-accounts/${id}/test`, null, { timeout: 30_000 })).data },
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
  async testXCredential(id) { return (await api.post(`/ops/x-credentials/${id}/test`, null, { timeout: 30_000 })).data },
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
}
