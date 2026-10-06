import { isAxiosError } from 'axios'
import { api } from '@/services/http/apiClient'
import type {
  TrackingExportFile,
  TrackingExportFormat,
  TrackingOverview,
  TrackingPreview,
  TrackingRuleInput,
  TrackingSettings,
  TrackingUnread,
} from '@/features/tracking/trackingModel'

export const trackingApi = {
  async unread(): Promise<TrackingUnread> {
    return (await api.get('/tracking/unread')).data
  },
  async markRead(digestId: number): Promise<TrackingUnread> {
    return (await api.post('/tracking/read', { digest_id: digestId })).data
  },
  async load(): Promise<TrackingOverview> {
    return (await api.get('/tracking')).data
  },
  async saveRule(input: TrackingRuleInput, id?: number): Promise<TrackingOverview> {
    return id === undefined
      ? (await api.post('/tracking/rules', input)).data
      : (await api.put('/tracking/rules/' + id, input)).data
  },
  async deleteRule(id: number): Promise<TrackingOverview> {
    return (await api.delete('/tracking/rules/' + id)).data
  },
  async settings(input: TrackingSettings): Promise<TrackingOverview> {
    const { enabled, delivery_hour, channel_id } = input
    return (await api.put('/tracking/settings', { enabled, delivery_hour, channel_id })).data
  },
  async preview(id: number): Promise<TrackingPreview> {
    return (await api.get('/tracking/rules/' + id + '/preview')).data
  },
  async exportHistory(format: TrackingExportFormat): Promise<TrackingExportFile> {
    try {
      const response = await api.get<Blob>('/tracking/export', { params: { format }, responseType: 'blob' })
      const named = /filename="([^"]+)"/.exec(String(response.headers['content-disposition'] ?? ''))
      return { blob: response.data, filename: named?.[1] ?? 'aigcnews-tracking.' + format }
    } catch (cause) {
      // 错误正文也按 Blob 取回，转回 JSON 才能读出 detail；不是 JSON（如网关错误页）就保持原样
      if (isAxiosError(cause) && cause.response?.data instanceof Blob) {
        try {
          cause.response.data = JSON.parse(await cause.response.data.text()) as unknown
        } catch {
          // 保留原始 Blob
        }
      }
      throw cause
    }
  },
}
