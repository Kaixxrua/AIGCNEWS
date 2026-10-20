import type { LocationQuery } from 'vue-router'
import type { ReportLoadState } from '@/composables/useReportController'
import { parseReportDateQuery, parseReportTypeQuery } from '@/features/report/reportViewModel'
import type { PageHeadOverride } from './pageHead'

/** 已确认不存在的期号不收录；加载中、未发布和临时故障不等同于不存在。 */
export function reportPageHead(query: LocationQuery, state: ReportLoadState, title: string): PageHeadOverride | null {
  const date = parseReportDateQuery(query.date)
  if (!date) return null
  const type = parseReportTypeQuery(query.type)
  return {
    title: `${title} ${date}`,
    noindex: state === 'missing',
    canonicalQuery: { date, type: type === 'all' ? null : type },
  }
}
