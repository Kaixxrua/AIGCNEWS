import type {
  VisitPlatformKey,
  VisitPlatformShare,
  VisitPlatformStatsResponse,
  VisitStatsWindow,
} from './monitorModel'

export type { VisitPlatformKey, VisitPlatformShare, VisitPlatformStatsResponse, VisitStatsWindow }

/* 桶顺序与后端 visit_platforms.PLATFORM_BUCKETS 双向冻结；颜色按 dataviz 规范
   固定实体→槽位映射（不随数据排序变化），浅/深色双 token 经面板 CSS 变量落地。
   linux 后加，取下一个空槽位 6，other 保持槽位 5 不改色。
   已按环上相邻顺序（含 other→ios 首尾相接）跑 validate_palette.js：浅色系于
   --projects-paper-light(#fffdf5)、深色系于 #111410 表面硬门禁全过；浅色的 3:1
   对比 WARN 与深色 macos↔linux 的 CVD ΔE 6.9（6–8 合法区间）由 2px 分段间隙
   与图例数值列表（table view）兜底。 */
export const VISIT_PLATFORM_ORDER: readonly VisitPlatformKey[] = ['ios', 'android', 'windows', 'macos', 'linux', 'other']

/** 桶 → dataviz 分类槽位（面板 CSS 变量 --visit-series-N 按此槽位取色） */
export const PLATFORM_COLOR_SLOT: Record<VisitPlatformKey, 1 | 2 | 3 | 4 | 5 | 6> = {
  ios: 1,
  android: 2,
  windows: 3,
  macos: 4,
  linux: 6,
  other: 5,
}

export const VISIT_STATS_WINDOWS: readonly VisitStatsWindow[] = ['today', '7d', '30d', 'all']

export const DEFAULT_VISIT_STATS_WINDOW: VisitStatsWindow = '7d'

export const isEmptyStats = (stats: VisitPlatformStatsResponse | null | undefined): boolean =>
  !stats || stats.total_visits <= 0

/** 自动化访问次数：单列展示、不进环图；缺字段或脏值按 0。 */
export const automatedVisits = (stats: VisitPlatformStatsResponse | null | undefined): number =>
  Math.max(0, Math.round(stats?.automated_visits ?? 0))

/** 归一化为固定桶序（缺失桶补零），未知桶名静默丢弃——后端契约已保证集合。 */
export const orderedPlatformShares = (
  platforms: readonly VisitPlatformShare[] | null | undefined,
): VisitPlatformShare[] =>
  VISIT_PLATFORM_ORDER.map((platform) => {
    const hit = (platforms ?? []).find((entry) => entry.platform === platform)
    return { platform, visits: Math.max(0, Math.round(hit?.visits ?? 0)), share: hit?.share ?? 0 }
  })

/* 展示百分比：原始 visits 经大余数法取整到 0.1，非零总量时各桶和恒为 100.0。
   （后端 share 一位小数直接相加可能漂移 ±0.1，仅作信息性字段。） */
export const computeShares = (
  platforms: readonly VisitPlatformShare[] | null | undefined,
): Record<VisitPlatformKey, number> => {
  const ordered = orderedPlatformShares(platforms)
  const total = ordered.reduce((sum, entry) => sum + entry.visits, 0)
  const shares = {} as Record<VisitPlatformKey, number>
  if (total <= 0) {
    for (const entry of ordered) shares[entry.platform] = 0
    return shares
  }
  // 以 0.1% 为一个单位：先取整，再把剩余单位按小数余量从大到小补给各桶
  const units = ordered.map((entry, index) => {
    const exact = (entry.visits * 1000) / total
    return { index, platform: entry.platform, floor: Math.floor(exact), remainder: exact - Math.floor(exact) }
  })
  let leftover = 1000 - units.reduce((sum, unit) => sum + unit.floor, 0)
  for (const unit of [...units].sort((a, b) => b.remainder - a.remainder || a.index - b.index)) {
    if (leftover <= 0) break
    unit.floor += 1
    leftover -= 1
  }
  for (const unit of units) shares[unit.platform] = unit.floor / 10
  return shares
}

export interface DonutSegment {
  platform: VisitPlatformKey
  /** 两段式 dasharray：`${visible} ${rest}` */
  dasharray: string
  dashoffset: number
  share: number
  visits: number
}

export const DONUT_RADIUS = 80
export const DONUT_CIRCUMFERENCE = 2 * Math.PI * DONUT_RADIUS
/** 分段之间的表面色间隙（px，沿环路径量）——dataviz 标记规范的 2px 间隙 */
export const DONUT_SEGMENT_GAP_PX = 2

const formatLength = (value: number): string => value.toFixed(4)

/** 把固定桶序的访问次数切成 donut 分段；从 12 点顺时针（配合 SVG rotate(-90)）。 */
export const buildDonutSegments = (
  platforms: readonly VisitPlatformShare[] | null | undefined,
): DonutSegment[] => {
  const ordered = orderedPlatformShares(platforms)
  const shares = computeShares(ordered)
  const nonZero = ordered.filter((entry) => shares[entry.platform] > 0)
  // 单桶 100% 时不留假间隙
  const gap = nonZero.length > 1 ? DONUT_SEGMENT_GAP_PX : 0
  let travelled = 0
  return ordered.map((entry) => {
    const share = shares[entry.platform]
    const length = (share / 100) * DONUT_CIRCUMFERENCE
    const visible = length > 0 ? Math.max(length - gap, 0) : 0
    const segment: DonutSegment = {
      platform: entry.platform,
      dasharray: `${formatLength(visible)} ${formatLength(DONUT_CIRCUMFERENCE - visible)}`,
      dashoffset: -(travelled + (length > 0 ? gap / 2 : 0)),
      share,
      visits: entry.visits,
    }
    travelled += length
    return segment
  })
}
