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
/** vip 关键词热度飙升：最近 24 小时命中数与前 7 天日均（保留一位小数）。 */
export interface TrackingSurge {
  query: string
  count: number
  baseline: number
}
export interface TrackingDigest {
  id: number
  issue_date: string
  items: TrackingItem[]
  truncated: boolean
  // Older backends omit it; free accounts and older issues get an empty list.
  surges?: TrackingSurge[]
  delivery_status: 'none' | 'pending' | 'sending' | 'sent' | 'failed' | 'cancelled'
  created_at: string
}
export interface TrackingOverview {
  limit: number
  rules: TrackingRule[]
  settings: TrackingSettings
  digests: TrackingDigest[]
}
export interface TrackingSourceCount {
  source: string
  count: number
}
export interface TrackingExpansion {
  term: string
  aliases: string[]
  exclude: boolean
}
export interface TrackingPreview {
  items: TrackingItem[]
  truncated: boolean
  // Matches in the preview window (items list at most 50 of them). Older backends omit these three.
  total?: number
  sources?: TrackingSourceCount[]
  expansions?: TrackingExpansion[]
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
/** vip 导出最近 90 天简报：CSV 每行一条结果，JSON 另含规则和热度飙升。 */
export type TrackingExportFormat = 'csv' | 'json'
export interface TrackingExportFile {
  blob: Blob
  filename: string
}
