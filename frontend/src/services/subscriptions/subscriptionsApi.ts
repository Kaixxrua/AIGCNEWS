import { api } from '@/services/http/apiClient'
import type {
  PushChannel,
  PushChannelStatus,
  SubscriptionFrequency,
  SubscriptionSource,
  SubscriptionStatus,
  UserSubscription,
} from '@/features/subscriptions/subscriptionsModel'

export interface SubscriptionsApi {
  listChannels(): Promise<PushChannel[]>
  createEmailChannel(email: string): Promise<PushChannel>
  createWebhookChannel(url: string): Promise<PushChannel>
  verifyChannel(channelId: number, code: string): Promise<PushChannel>
  setChannelStatus(channelId: number, status: PushChannelStatus): Promise<PushChannel>
  deleteChannel(channelId: number): Promise<void>
  testChannel(channelId: number): Promise<void>
  listSubscriptions(): Promise<UserSubscription[]>
  createSubscription(
    channelId: number,
    source: SubscriptionSource,
    frequency: SubscriptionFrequency,
  ): Promise<UserSubscription>
  setSubscriptionStatus(
    subscriptionId: number,
    status: SubscriptionStatus,
  ): Promise<UserSubscription>
  deleteSubscription(subscriptionId: number): Promise<void>
}

export const subscriptionsApi: SubscriptionsApi = {
  async listChannels(): Promise<PushChannel[]> {
    return (await api.get('/push/me/channels')).data
  },

  async createEmailChannel(email: string): Promise<PushChannel> {
    return (await api.post('/push/me/channels', { channel_type: 'email', target: email })).data
  },

  async createWebhookChannel(url: string): Promise<PushChannel> {
    return (await api.post('/push/me/channels', { channel_type: 'webhook', target: url })).data
  },

  async verifyChannel(channelId: number, code: string): Promise<PushChannel> {
    return (
      await api.post(`/push/me/channels/${encodeURIComponent(channelId)}/verify`, { code })
    ).data
  },

  async setChannelStatus(channelId: number, status: PushChannelStatus): Promise<PushChannel> {
    return (
      await api.patch(`/push/me/channels/${encodeURIComponent(channelId)}`, { status })
    ).data
  },

  async deleteChannel(channelId: number): Promise<void> {
    await api.delete(`/push/me/channels/${encodeURIComponent(channelId)}`)
  },

  async testChannel(channelId: number): Promise<void> {
    await api.post(`/push/me/channels/${encodeURIComponent(channelId)}/test`)
  },

  async listSubscriptions(): Promise<UserSubscription[]> {
    return (await api.get('/push/me/subscriptions')).data
  },

  async createSubscription(
    channelId: number,
    source: SubscriptionSource,
    frequency: SubscriptionFrequency,
  ): Promise<UserSubscription> {
    return (
      await api.post('/push/me/subscriptions', {
        channel_id: channelId,
        source,
        frequency,
      })
    ).data
  },

  async setSubscriptionStatus(
    subscriptionId: number,
    status: SubscriptionStatus,
  ): Promise<UserSubscription> {
    return (
      await api.patch(`/push/me/subscriptions/${encodeURIComponent(subscriptionId)}`, {
        status,
      })
    ).data
  },

  async deleteSubscription(subscriptionId: number): Promise<void> {
    await api.delete(`/push/me/subscriptions/${encodeURIComponent(subscriptionId)}`)
  },
}
