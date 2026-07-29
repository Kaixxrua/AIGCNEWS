import { Circle, Code2, FileText, Globe, Newspaper, Rocket } from 'lucide-vue-next'

export const REPORT_TYPES = [
  { key: 'all',         labelKey: 'allLabel', icon: Globe, descKey: 'allDesc' },
  { key: 'arxiv',       labelKey: 'arxivLabel', icon: FileText, descKey: 'arxivDesc' },
  { key: 'github',      labelKey: 'githubLabel', icon: Code2, descKey: 'githubDesc' },
  { key: 'news',        labelKey: 'newsLabel', icon: Newspaper, descKey: 'newsDesc' },
  { key: 'producthunt', labelKey: 'producthuntLabel', icon: Rocket, descKey: 'producthuntDesc' },
  { key: 'hackernews',  labelKey: 'hackernewsLabel', icon: Circle, descKey: 'hackernewsDesc' },
] as const

export const PERIOD_TYPES = [
  { key: 'daily' },
  { key: 'weekly' },
  { key: 'monthly' },
] as const

export type ReportKey = (typeof REPORT_TYPES)[number]['key']
export type PeriodKey = (typeof PERIOD_TYPES)[number]['key']

export const DAILY_ONLY_TYPES = new Set<ReportKey>(['all', 'news', 'producthunt', 'hackernews'])

export interface Subscription {
  source: string
  period: string
  is_active?: number | boolean | string
}

export interface SubscriptionListResponse {
  items: Subscription[]
}

export interface BatchSubscriptionResponse {
  message?: string
  sources?: string[]
}

export interface ReportMessageResponse {
  message: string
}

export interface ReportResponse {
  content: string
  content_zh?: string
  content_en?: string
  date: string
  id: number
}

export interface ReportStreamEvent {
  type: string
  data?: unknown
}

export const isPeriodDisabled = (reportKey: ReportKey, periodKey: PeriodKey): boolean =>
  periodKey !== 'daily' && DAILY_ONLY_TYPES.has(reportKey)

export const coercePeriodForReport = (reportKey: ReportKey, periodKey: PeriodKey): PeriodKey =>
  DAILY_ONLY_TYPES.has(reportKey) && periodKey !== 'daily' ? 'daily' : periodKey

export const isActiveSubscription = (subscription: Subscription): boolean =>
  subscription.is_active === undefined ||
  subscription.is_active === true ||
  subscription.is_active === 1 ||
  subscription.is_active === '1' ||
  subscription.is_active === 'true'

export const selectActiveDailySubscriptions = (subscriptions: Subscription[]): Subscription[] =>
  subscriptions.filter(subscription => subscription.period === 'daily' && isActiveSubscription(subscription))

export const isReportKey = (source: string): source is ReportKey =>
  REPORT_TYPES.some(report => report.key === source)

export const selectActiveDailySources = (subscriptions: Subscription[]): ReportKey[] =>
  selectActiveDailySubscriptions(subscriptions)
    .map(subscription => subscription.source)
    .filter(isReportKey)

export const isSourceSubscribed = (subscriptions: Subscription[], source: ReportKey): boolean =>
  selectActiveDailySubscriptions(subscriptions).some(subscription => subscription.source === source)

export const getReportTypeInfo = (reportKey: ReportKey) =>
  REPORT_TYPES.find(report => report.key === reportKey)

export const getPeriodTypeInfo = (periodKey: PeriodKey) =>
  PERIOD_TYPES.find(period => period.key === periodKey)

export const coerceReportStreamText = (data: unknown): string => {
  if (typeof data === 'string') return data
  if (Array.isArray(data)) {
    return data
      .map((block: unknown) =>
        typeof block === 'string' ? block : (block as Record<string, unknown>)?.text ?? '',
      )
      .join('')
  }
  return data != null ? JSON.stringify(data) : ''
}
