import { api } from '@/services/http/apiClient'
import type {
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
}
