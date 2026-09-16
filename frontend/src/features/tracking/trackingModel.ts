import type { SubscriptionSource } from '@/features/subscriptions/subscriptionsModel'

export interface TrackingRuleInput {
  kind: 'keyword' | 'project'
  query: string
  source: SubscriptionSource
  excludes: string[]
  star_threshold: number
  enabled: boolean
}
export interface TrackingRule extends TrackingRuleInput {
  id: number
  active: boolean
  created_at: string
}
export interface TrackingSettings {
  enabled: boolean
  delivery_hour: number
  channel_id: number | null
  last_checked_at?: string | null
}
export interface TrackingItem {
  key: string
  title: string
  url: string
  summary: string
  source: string
  observed_at: string
  matched_rules: string[]
}
export interface TrackingDigest {
  id: number
  issue_date: string
  items: TrackingItem[]
  truncated: boolean
  delivery_status: 'none' | 'pending' | 'sending' | 'sent' | 'failed' | 'cancelled'
  created_at: string
}
export interface TrackingOverview {
  limit: number
  rules: TrackingRule[]
  settings: TrackingSettings
  digests: TrackingDigest[]
}
export interface TrackingPreview {
  items: TrackingItem[]
  truncated: boolean
}

export const emptyRule = (): TrackingRuleInput => ({
  kind: 'keyword',
  query: '',
  source: 'all',
  excludes: [],
  star_threshold: 50,
  enabled: true,
})
export const ruleInput = (row: TrackingRule): TrackingRuleInput => ({
  kind: row.kind,
  query: row.query,
  source: row.source,
  excludes: [...row.excludes],
  star_threshold: row.star_threshold,
  enabled: row.enabled,
})
export interface TrackingUnread {
  latest_digest_id: number
  last_read_digest_id: number
  unread: boolean
}
