import { api } from '@/services/http/apiClient'
import type {
  PushChannel,
  PushChannelStatus,
  SubscriptionFrequency,
  SubscriptionSource,
  SubscriptionStatus,
  UserSubscription,
  TelegramLinkAttempt,
} from '@/features/subscriptions/subscriptionsModel'

// 与后端 /auth/me/feed-token 载荷同形：完整 token 供拼 RSS 链接，hint 供展示
export interface FeedTokenInfo {
  token: string
  token_hint: string
  created: boolean
  created_at: string | null
}

export interface SubscriptionsApi {
  listChannels(): Promise<PushChannel[]>
  createEmailChannel(email: string): Promise<PushChannel>
  createWebhookChannel(url: string): Promise<PushChannel>
  createDiscordChannel(url: string): Promise<PushChannel>
  createTelegramLink(): Promise<TelegramLinkAttempt>
  getTelegramLink(attemptId: string): Promise<TelegramLinkAttempt>
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
  getFeedToken(): Promise<FeedTokenInfo>
  rotateFeedToken(): Promise<FeedTokenInfo>
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

  async createDiscordChannel(url: string): Promise<PushChannel> {
    return (await api.post('/push/me/channels', { channel_type: 'discord', target: url })).data
  },

  async createTelegramLink(): Promise<TelegramLinkAttempt> {
    return (await api.post('/push/me/channels/telegram/link')).data
  },

  async getTelegramLink(attemptId: string): Promise<TelegramLinkAttempt> {
    return (await api.get(`/push/me/channels/telegram/link/${encodeURIComponent(attemptId)}`)).data
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

  async getFeedToken(): Promise<FeedTokenInfo> {
    return (await api.get('/auth/me/feed-token')).data
  },

  async rotateFeedToken(): Promise<FeedTokenInfo> {
    return (await api.post('/auth/me/feed-token/rotate')).data
  },
}
