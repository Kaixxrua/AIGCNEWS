// 订阅推送（用户域）：渠道与订阅的视图模型与纯函数助手。
// 词汇表与后端 schema_push / 简报管线保持一致。

export type SubscriptionSource =
  | 'all'
  | 'arxiv'
  | 'github'
  | 'news'
  | 'producthunt'
  | 'hackernews'
  | 'x'
  | 'dailyhot'

export type SubscriptionFrequency = 'daily' | 'weekly' | 'monthly'

export type PushChannelType = 'email' | 'webhook'
export type PushChannelStatus = 'active' | 'disabled'
export type SubscriptionStatus = 'active' | 'paused'

export interface PushChannel {
  id: number
  channel_type: PushChannelType
  target: string
  verified: boolean
  status: PushChannelStatus
  created_at: string
}

export interface UserSubscription {
  id: number
  channel_id: number
  channel_type: PushChannelType
  target: string
  source: SubscriptionSource
  frequency: SubscriptionFrequency
  status: SubscriptionStatus
  created_at: string
}

export const SUBSCRIPTION_SOURCES: readonly SubscriptionSource[] = [
  'all',
  'arxiv',
  'github',
  'news',
  'producthunt',
  'hackernews',
  'x',
  'dailyhot',
]

export const SUBSCRIPTION_FREQUENCIES: readonly SubscriptionFrequency[] = [
  'daily',
  'weekly',
  'monthly',
]

export type WebhookPlatform = 'wecom' | 'dingtalk' | 'lark' | 'generic'

// 与后端 webhook_service._PROVIDER_HOSTS 保持同一识别表（仅用于展示标签）。
const PLATFORM_HOSTS: Readonly<Record<string, WebhookPlatform>> = {
  'qyapi.weixin.qq.com': 'wecom',
  'oapi.dingtalk.com': 'dingtalk',
  'open.feishu.cn': 'lark',
  'open.larksuite.com': 'lark',
}

export const detectWebhookPlatform = (url: string): WebhookPlatform => {
  try {
    const host = new URL(url).hostname.toLowerCase()
    return PLATFORM_HOSTS[host] ?? 'generic'
  } catch {
    return 'generic'
  }
}

// 订阅可绑定的渠道：已验证且启用。
export const isChannelBindable = (channel: PushChannel): boolean =>
  channel.verified && channel.status === 'active'

export const normalizeEmail = (raw: string): string => raw.trim().toLowerCase()

export const isValidEmailShape = (raw: string): boolean =>
  /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalizeEmail(raw))

export const isHttpsUrlShape = (raw: string): boolean => {
  const candidate = raw.trim()
  if (!candidate || candidate.length > 2048) return false
  try {
    return new URL(candidate).protocol === 'https:'
  } catch {
    return false
  }
}

export const isValidOtpCode = (raw: string): boolean => /^\d{6}$/.test(raw.trim())
