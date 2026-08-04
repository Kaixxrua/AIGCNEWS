import { api } from '@/services/http/apiClient'
import type {
  McpServerConfig, McpServerForm, PagedResult, ProviderConfig, ProviderForm, SchedulerStatus, SourceKey,
} from '@/features/monitor/monitorModel'
import { buildMcpPayload, buildProviderPayload } from '@/features/monitor/monitorModel'

export interface MonitorApi {
  fetchTasks(page: number, pageSize: number): Promise<PagedResult>
  fetchSchedulerStatus(): Promise<SchedulerStatus>
  fetchProviderConfig(): Promise<ProviderConfig>
  saveProviderConfig(form: ProviderForm): Promise<ProviderConfig>
  fetchMcpServers(): Promise<McpServerConfig[]>
  saveMcpServer(form: McpServerForm): Promise<McpServerConfig>
  testMcpServer(id: number): Promise<{ server?: McpServerConfig; status?: string; message?: string }>
  deleteMcpServer(id: number): Promise<{ message?: string }>
  ingestSource(source: SourceKey): Promise<{ message?: string }>
  generateAllBriefings(forceRegenerate: boolean): Promise<{ message?: string }>
  clearDashboardCache(): Promise<{ message?: string }>
  syncData(force: boolean): Promise<{ message?: string }>
  ingestByDate(targetDate: string): Promise<{ message?: string }>
  clearAllData(): Promise<{ message?: string }>
}

export const monitorApi: MonitorApi = {
  async fetchTasks(page, pageSize) {
    const { data } = await api.get('/monitor/tasks', { params: { page, page_size: pageSize } })
    return { items: data?.items || [], total: data?.total || 0, page: data?.page || page, page_size: data?.page_size || pageSize }
  },
  async fetchSchedulerStatus() { return (await api.get('/ops/scheduler/status')).data },
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
  async ingestSource(source) { return (await api.post('/ops/ingest-source', null, { params: { source, limit: 20 } })).data },
  async generateAllBriefings(forceRegenerate) {
    return (await api.post('/ops/briefing/generate-all', null, { params: { force_regenerate: forceRegenerate } })).data
  },
  async clearDashboardCache() { return (await api.post('/ops/cache/clear-dashboard')).data },
  async syncData(force) { return (await api.post('/ops/ingest', { limit: 20, force })).data },
  async ingestByDate(targetDate) { return (await api.post('/ops/ingest-by-date', { target_date: targetDate, limit: 30 })).data },
  async clearAllData() { return (await api.post('/ops/clear-data')).data },
}
