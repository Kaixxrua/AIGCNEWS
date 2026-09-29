import { Circle, Code2, FileText, Flame, Globe, Newspaper, Rocket } from 'lucide-vue-next'
import { XLogoIcon } from '@/components/icons/XLogoIcon'

export const REPORT_TYPES = [
  { key: 'all',         labelKey: 'allLabel', icon: Globe, descKey: 'allDesc' },
  { key: 'arxiv',       labelKey: 'arxivLabel', icon: FileText, descKey: 'arxivDesc' },
  { key: 'github',      labelKey: 'githubLabel', icon: Code2, descKey: 'githubDesc' },
  { key: 'news',        labelKey: 'newsLabel', icon: Newspaper, descKey: 'newsDesc' },
  { key: 'producthunt', labelKey: 'producthuntLabel', icon: Rocket, descKey: 'producthuntDesc' },
  { key: 'hackernews',  labelKey: 'hackernewsLabel', icon: Circle, descKey: 'hackernewsDesc' },
  { key: 'x',           labelKey: 'xLabel', icon: XLogoIcon, descKey: 'xDesc' },
  { key: 'dailyhot',    labelKey: 'dailyhotLabel', icon: Flame, descKey: 'dailyhotDesc' },
] as const

export type ReportKey = (typeof REPORT_TYPES)[number]['key']

export interface Subscription {
  source: string
  is_active?: number | boolean | string
  period?: string
  frequency?: string
}

export interface SubscriptionListResponse {
  items: Subscription[]
}

export type ReportDelivery = 'rss' | 'email' | 'push'

export interface BatchSubscriptionPayload {
  sources: ReportKey[]
  deliveries?: ReportDelivery[]
}

export interface BatchSubscriptionResponse {
  message?: string
  sources?: string[]
  deliveries?: ReportDelivery[]
}

export interface ReportMessageResponse {
  message: string
}

export type DeliveryKind = 'account_email' | 'push_channel' | 'rss'

export interface PlanDeliveryCapability {
  kind: DeliveryKind
  key: string
  feed?: string
  channel_id?: number
  channel_type?: string
  target?: string
  verified?: boolean
  status?: string
  selectable: boolean
  active?: boolean
  disabled_reason?: string | null
}

export interface SubscriptionPlan {
  can_select_multiple_sources: boolean
  max_sources: number
  active_sources: ReportKey[]
  capabilities: PlanDeliveryCapability[]
}

export interface PlanDeliveryRequest {
  kind: DeliveryKind
  channel_id?: number
  feed?: string
}

export interface PlanAppliedDelivery {
  kind: DeliveryKind
  channel_id?: number
  feed?: string
  status: string
}

export interface SubscriptionPlanApplyResponse {
  sources: ReportKey[]
  deliveries: PlanAppliedDelivery[]
  removed_sources?: string[]
  idempotency_key?: string
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

export const isActiveSubscription = (subscription: Subscription): boolean =>
  subscription.is_active === undefined ||
  subscription.is_active === true ||
  subscription.is_active === 1 ||
  subscription.is_active === '1' ||
  subscription.is_active === 'true'

// 简报仅按日生成，活跃订阅即日报订阅。
export const selectActiveDailySubscriptions = (subscriptions: Subscription[]): Subscription[] =>
  subscriptions.filter(isActiveSubscription)

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

// 简报缓存键按后端 CST（UTC+8）日期生成，前端默认选中日期必须同口径：
// 用 UTC（toISOString）或浏览器本地时区都会在跨日时错位一天。
export const REPORT_TIME_ZONE = 'Asia/Shanghai'

export const todayInReportTimeZone = (now: Date = new Date()): string => {
  try {
    const parts = new Intl.DateTimeFormat('en-CA', {
      timeZone: REPORT_TIME_ZONE,
      year: 'numeric', month: '2-digit', day: '2-digit',
    }).formatToParts(now)
    const get = (type: string) => parts.find(part => part.type === type)?.value ?? ''
    return `${get('year')}-${get('month')}-${get('day')}`
  } catch {
    // Intl 时区数据缺失等极端环境：退回 UTC+8 偏移换算。
    const shifted = new Date(now.getTime() + (8 * 60 + now.getTimezoneOffset()) * 60000)
    return shifted.toISOString().slice(0, 10)
  }
}

// RSS 简报条目按期号回链 /report?date=YYYY-MM-DD。只认合法日历日且不晚于今天
// （CST）；缺省、重复参数、脏串、未来日期一律返回 null，页面回落默认的今天。
export const parseReportDateQuery = (
  value: unknown,
  today: string = todayInReportTimeZone(),
): string | null => {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null
  const parsed = new Date(`${value}T00:00:00Z`)
  if (Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value) return null
  return value <= today ? value : null
}

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

// 桌面漫画版把简报逐节画成面板：按顶层 h2 分节，每节包进 <section class="report-section">。
// 只在已消毒的渲染结果上重排顶层节点，不增删内容；没有 h2 时原样返回。
export const groupReportSections = (html: string): string => {
  if (!/<h2[\s>]/.test(html)) return html
  const template = document.createElement('template')
  template.innerHTML = html
  const root = template.content
  let section: HTMLElement | null = null
  for (const node of Array.from(root.childNodes)) {
    if (node.nodeName === 'H2') {
      section = document.createElement('section')
      section.className = 'report-section'
      root.insertBefore(section, node)
    }
    section?.appendChild(node)
  }
  return template.innerHTML
}
