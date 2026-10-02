import type { AppLocale } from '@/i18n'
import { formatLocaleDate, formatLocaleNumber } from '@/i18n/formatters'
import type {
  GitHubProjectItem,
  GitHubProjectSort,
  GitHubProjectTrendPoint,
  ProjectScope,
} from '@/services/projects/projectApi'
import { isWebsite } from './projectPresentation'

/* 项目库紧凑版面（榜单）的换算：哪一行取行情、名次与昨日对照的升降、近两周火花线逐日铺开。 */

// 与后端 /projects/github/trends 的校验同一格式：一页里混进一个对不上的键，整页请求都会被拒。
const TREND_KEY = /^[A-Za-z0-9-]+\/[A-Za-z0-9_.-]+$/

/** 行情接口认的仓库键（库里的 repo_id，即 owner/repo）；网页收藏和对不上格式的条目不取行情。 */
export const projectTrendKey = (project: GitHubProjectItem): string => {
  if (isWebsite(project)) return ''
  for (const value of [project.repo_id, project.full_name]) {
    const key = typeof value === 'string' ? value.trim() : ''
    if (TREND_KEY.test(key)) return key
  }
  return ''
}

/** 榜单一行先摆出的标签数；多的收在「+n」后面，点它或按 x 展开。 */
export const CHART_ROW_TAGS = 3

/** 名次只在按热度或星标排的时候有意义；按更新、收录时间或名称排时不编号。 */
export const projectChartRanked = (sort: GitHubProjectSort) => sort === 'hot' || sort === 'stars'

/** 今日热门是一张日榜，才和昨天的收盘热榜对照升降。 */
export const projectChartShowsMovement = (scope: ProjectScope) => scope === 'today'

export type ProjectRankMovement =
  | { kind: 'new' }
  | { kind: 'same' }
  | { kind: 'up' | 'down'; steps: number }

/** 今天第 position 名，昨天第 previousRank 名（不在昨天的热榜上为 null，记作新上榜）。 */
export const projectRankMovement = (position: number, previousRank: number | null): ProjectRankMovement => {
  if (previousRank === null || !Number.isFinite(previousRank) || previousRank < 1) return { kind: 'new' }
  const steps = previousRank - position
  if (steps === 0) return { kind: 'same' }
  return steps > 0 ? { kind: 'up', steps } : { kind: 'down', steps: -steps }
}

export interface ProjectSparkDay {
  date: string
  /** 那天的新增星标；null 是那天没有统计，不是 0。 */
  gain: number | null
}

const DAY_MS = 86_400_000

const parseDay = (value: string): number | null => {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  return match ? Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])) : null
}

/** 截至 metricDate 的 days 天逐日铺开：库里缺的那天留空位，火花线画成空位而不是 0。 */
export const projectSparkDays = (
  points: readonly GitHubProjectTrendPoint[],
  metricDate: string,
  days: number,
): ProjectSparkDay[] => {
  const end = parseDay(metricDate)
  if (end === null || days < 1) return []
  const gains = new Map(points.map((point) => [point.date, point.gain]))
  return Array.from({ length: days }, (_, index) => {
    const date = new Date(end - (days - 1 - index) * DAY_MS).toISOString().slice(0, 10)
    return { date, gain: gains.get(date) ?? null }
  })
}

export interface ProjectSparkSummary {
  /** 有统计的那些天加起来 */
  total: number
  /** 新增最多的一天；一天都没有统计时为 null */
  peak: ProjectSparkDay | null
  /** 有统计的天数 */
  counted: number
}

export const projectSparkSummary = (series: readonly ProjectSparkDay[]): ProjectSparkSummary => {
  let total = 0
  let counted = 0
  let peak: ProjectSparkDay | null = null
  for (const day of series) {
    if (day.gain === null) continue
    counted += 1
    total += day.gain
    if (peak === null || day.gain > (peak.gain ?? 0)) peak = day
  }
  return { total, peak, counted }
}

/** 星标增量带符号：+1,203、0、−3（取消星标多于新增的日子是负数）。 */
export const formatStarDelta = (value: number, locale?: AppLocale) => {
  if (value > 0) return `+${formatLocaleNumber(value, locale)}`
  if (value < 0) return `−${formatLocaleNumber(-value, locale)}`
  return '0'
}

/** 火花线上的日期：10月1日 / Oct 1。按 UTC 读，免得访客时区把日子挪一天。 */
export const formatSparkDate = (date: string, locale?: AppLocale) => {
  const time = parseDay(date)
  return time === null
    ? date
    : formatLocaleDate(new Date(time), { month: 'short', day: 'numeric', timeZone: 'UTC' }, locale)
}
