import type {
  McpDailyUsageResponse,
  McpUsageAudience,
  McpUsageAudienceCounts,
  McpUsageDay,
  McpUsageDays,
  McpUsageStats,
} from './monitorModel'

export type { McpDailyUsageResponse, McpUsageAudience, McpUsageDays }

export type McpUsageMetric = keyof McpUsageStats

/** 受众列顺序与后端 mcp_daily_usage.AUDIENCES 一致。 */
export const MCP_USAGE_AUDIENCES: readonly McpUsageAudience[] = ['anonymous', 'free', 'member']

export const MCP_USAGE_WINDOWS: readonly McpUsageDays[] = [7, 14, 30]

export const DEFAULT_MCP_USAGE_DAYS: McpUsageDays = 14

export const MCP_USAGE_METRICS: readonly McpUsageMetric[] = ['clients', 'connections', 'calls', 'limited']

export const DEFAULT_MCP_USAGE_METRIC: McpUsageMetric = 'calls'

/** Go 侧的兜底桶名：工具名不在注册表、客户端没报名字时记 __unknown__，名字非法或当天超上限记 __other__。 */
const SPECIAL_TOOL_KEYS: Record<string, string> = {
  __unknown__: 'mcpUsage.unknownTool',
}

const SPECIAL_CLIENT_KEYS: Record<string, string> = {
  __unknown__: 'mcpUsage.unnamedClient',
  __other__: 'mcpUsage.otherClients',
}

const LIMIT_KIND_KEYS: Record<string, string> = {
  burst: 'mcpUsage.limitKind.burst',
  daily: 'mcpUsage.limitKind.daily',
  monthly: 'mcpUsage.limitKind.monthly',
}

/** 429 文案链接的来源标记，与后端 landing_sources.LANDING_SOURCES 同一组值。 */
const LANDING_SOURCE_KEYS: Record<string, string> = {
  'mcp-429-anon': 'mcpUsage.landingSource.mcpAnon',
  'mcp-429-daily': 'mcpUsage.landingSource.mcpDaily',
  'mcp-429-monthly': 'mcpUsage.landingSource.mcpMonthly',
  'api-429-anon': 'mcpUsage.landingSource.apiAnon',
  'api-429-daily': 'mcpUsage.landingSource.apiDaily',
  'api-429-monthly': 'mcpUsage.landingSource.apiMonthly',
}

/** 兜底桶与限流类别的文案键；普通名字返回 null，按原样显示。 */
export const specialToolKey = (tool: string): string | null => SPECIAL_TOOL_KEYS[tool] ?? null

export const specialClientNameKey = (name: string): string | null => SPECIAL_CLIENT_KEYS[name] ?? null

export const limitKindKey = (kind: string): string | null => LIMIT_KIND_KEYS[kind] ?? null

/** 落地来源标记与「其他页面」桶的文案键；/mcp、/membership 这类真实路径返回 null，按原样显示。 */
export const landingSourceKey = (source: string): string | null => LANDING_SOURCE_KEYS[source] ?? null

export const landingPathKey = (path: string): string | null => (path === 'other' ? 'mcpUsage.landingOtherPath' : null)

/** 开始统计之前的日子不进日表，免得一列 0 被误读成没人用。 */
export const trackedDays = (usage: McpDailyUsageResponse | null | undefined): McpUsageDay[] =>
  (usage?.daily ?? []).filter((day) => day.tracked)

/** 窗口内有没有任何记录。 */
export const hasUsage = (usage: McpDailyUsageResponse | null | undefined): boolean => {
  const total = usage?.summary?.total
  return !!total && total.clients + total.connections + total.calls + total.limited > 0
}

/** 首次记录日落在窗口里面（窗口前段没有数据）时为 true，面板据此提示从哪天开始统计。 */
export const trackingStartsInWindow = (usage: McpDailyUsageResponse | null | undefined): boolean =>
  !!usage?.since && usage.since > usage.start_date

/** 只列有数的受众，给客户端名那一列「分布」用。 */
export const nonZeroAudiences = (
  counts: McpUsageAudienceCounts,
): Array<{ audience: McpUsageAudience; count: number }> =>
  MCP_USAGE_AUDIENCES.filter((audience) => counts[audience] > 0).map((audience) => ({
    audience,
    count: counts[audience],
  }))

/** 日表合计列行内条的宽度（百分比）；全为 0 时不画条。 */
export const barPercent = (value: number, max: number): number =>
  max > 0 ? Math.round((Math.max(0, value) / max) * 100) : 0

export const dailyMax = (days: McpUsageDay[], metric: McpUsageMetric): number =>
  days.reduce((max, day) => Math.max(max, day.total[metric]), 0)
