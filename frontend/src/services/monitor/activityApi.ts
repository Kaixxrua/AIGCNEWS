import { api } from '@/services/http/apiClient'

export interface ReturnVisitDay {
  day: string
  coverage: 'unavailable' | 'partial' | 'complete'
  total_visitors: number | null
  active_users: number | null
  returning_users: number | null
  new_users: number | null
  return_rate: number | null
}

export interface ReturnVisits {
  timezone: string
  tracking_started_at: string
  as_of: string
  days: ReturnVisitDay[]
}

export interface EmailQuota {
  used: number
  limit: number | null
  resets_at: string
}

export interface EmailProvider {
  name: string
  host: string
  port: number
  smtp: { status: 'ok' | 'failed'; error?: string }
  usage: { daily: EmailQuota; monthly: EmailQuota } | null
  usage_error: string | null
  recent: { count: number; has_more: boolean; statuses: Record<string, number> } | null
  events_error: string | null
}

export interface EmailAlert {
  id: string
  key: string
  active: boolean
  detail: string
  level: number
  opened_at: string
  resolved_at?: string
  notified_at: string | null
  notification_error: string | null
}

export interface EmailMonitoring {
  stale: boolean
  tracking_started_at: string
  checked_at?: string
  recipient?: string
  providers?: EmailProvider[]
  local?: { accepted_24h: number; failed_24h: number; failed_15m: number }
  alerts?: EmailAlert[]
}

export const activityApi = {
  async returnVisits(days = 30): Promise<ReturnVisits> {
    return (await api.get('/monitor/user-return-visits', { params: { days } })).data
  },
  async email(): Promise<EmailMonitoring> {
    return (await api.get('/monitor/email')).data
  },
}

export function formatReturnRate(rate: number | null): string {
  return rate === null ? '—' : `${(rate * 100).toFixed(2)}%`
}
