import type { GitHubProjectTrendPoint } from '@/services/projects/projectApi'
import { projectSparkDays } from './projectChart'

/* 榜单悬停速览的换算：卡片摆在这一行的下面还是上面、能有多高，近 30 天的星标曲线怎么画。 */

export interface PeekSpan {
  top: number
  bottom: number
}

export interface PeekPlacement {
  /** 相对榜单（卡片的定位框）的纵坐标：摆在行下面时是卡片的顶边，摆在行上面时是卡片的底边。 */
  top: number
  /** 摆在行上面：底边贴着行的顶边，内容多了往上长。 */
  above: boolean
  /** 那一边看得见的高度；内容再多就在卡片里滚。 */
  maxHeight: number
}

/** 卡片和行之间留的缝 */
export const PEEK_GAP = 6
/** 行下面至少有这么高（两栏卡片的常见高度）就摆在下面；不够时哪边宽敞摆哪边 */
export const PEEK_ROOM = 320
/** 两边都挤的时候卡片也至少这么高 */
export const PEEK_MIN_HEIGHT = 160

/**
 * row 是行在视口里的上下边，view 是行看得见的那段视野（扣掉吸顶的表头和底部的 dock），frameTop 是榜单内边距框顶边
 * 在视口里的位置，listTop 是榜单第一行的上沿。
 * 往上长先只盖行，页头、搜索框和表头留在外面；上面的行和行下面都放不下一张卡片时（多半是刚进页面、页头还占着
 * 视口上部），才往上盖过去，免得卡片挤成一小条。
 */
export const peekPlacement = (row: PeekSpan, view: PeekSpan, frameTop: number, listTop = view.top): PeekPlacement => {
  const below = view.bottom - row.bottom - PEEK_GAP
  const overRows = row.top - Math.max(view.top, listTop) - PEEK_GAP
  const above = below >= PEEK_ROOM || overRows >= PEEK_ROOM ? overRows : row.top - view.top - PEEK_GAP
  const up = below < PEEK_ROOM && above > below
  return {
    top: Math.round((up ? row.top - PEEK_GAP : row.bottom + PEEK_GAP) - frameTop),
    above: up,
    maxHeight: Math.max(PEEK_MIN_HEIGHT, Math.floor(up ? above : below)),
  }
}

/** 卡片里的星标曲线看近这么多天（行情接口最多 30 天） */
export const PEEK_CURVE_DAYS = 30
/** 曲线画在 0 0 PEEK_CURVE_W PEEK_CURVE_H 的框里，横向拉伸铺满卡片。 */
export const PEEK_CURVE_W = 300
export const PEEK_CURVE_H = 56
const CURVE_PAD = 4

export interface PeekCurveDay {
  date: string
  stars: number
}

export interface PeekCurve {
  /** 窗口的头一天和最后一天（曲线框的左右两端）；收录晚的仓库曲线从框中间起 */
  from: string
  to: string
  /** 窗口里有数的天数；不到两天画不成线 */
  counted: number
  first: PeekCurveDay | null
  last: PeekCurveDay | null
  /** 最后一天比第一天（有数的那两天）多了几颗星；取消的多于新增时是负数 */
  delta: number
  /** 连续有数的日子连成的折线，库里缺数的日子断开 */
  lines: string[]
  /** 折线下面填色的面：断开处照虚线连过去，面不断开 */
  area: string
  /** 断开处前后两天之间的虚线 */
  bridges: string[]
  /** 最后一天那一点在曲线框里的位置（百分比）：拉伸的 SVG 里画圆会变扁，圆点用 HTML 摆上去 */
  end: { x: number; y: number } | null
}

const round = (value: number) => Math.round(value * 100) / 100

/**
 * 截至 metricDate 的 days 天累计星标：高低按这个仓库自己窗口里的最少到最多铺满（看的是走势，多少写在旁边）。
 * 只有一个值时画一道平线。
 */
export const peekCurve = (points: readonly GitHubProjectTrendPoint[], metricDate: string, days: number): PeekCurve => {
  const stars = new Map(points.map((point) => [point.date, point.stars]))
  const series = projectSparkDays(points, metricDate, days)
  const known = series.flatMap(({ date }, index) => {
    const value = stars.get(date)
    return value === undefined ? [] : [{ index, date, stars: value }]
  })
  const from = series[0]?.date ?? ''
  const to = series[series.length - 1]?.date ?? ''
  if (known.length < 2) {
    return { from, to, counted: known.length, first: null, last: null, delta: 0, lines: [], area: '', bridges: [], end: null }
  }
  const values = known.map((day) => day.stars)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = Math.max(1, series.length - 1)
  const x = (index: number) => round(CURVE_PAD + (index / span) * (PEEK_CURVE_W - 2 * CURVE_PAD))
  const y = (value: number) => round(max === min
    ? PEEK_CURVE_H / 2
    : CURVE_PAD + (1 - (value - min) / (max - min)) * (PEEK_CURVE_H - 2 * CURVE_PAD))

  const runs: Array<typeof known> = []
  for (const day of known) {
    const run = runs[runs.length - 1]
    if (run && run[run.length - 1]!.index === day.index - 1) run.push(day)
    else runs.push([day])
  }
  const lines = runs.map((run) => (run.length === 1
    // 前后都缺数的孤零零一天：画一小截横线，免得看不见
    ? `M${round(x(run[0]!.index) - 1.5)} ${y(run[0]!.stars)}h3`
    : run.map((day, index) => `${index ? 'L' : 'M'}${x(day.index)} ${y(day.stars)}`).join('')))
  const bridges = runs.slice(1).map((run, index) => {
    const before = runs[index]![runs[index]!.length - 1]!
    const after = run[0]!
    return `M${x(before.index)} ${y(before.stars)}L${x(after.index)} ${y(after.stars)}`
  })
  const first = known[0]!
  const last = known[known.length - 1]!
  const area = `M${x(first.index)} ${PEEK_CURVE_H}${known.map((day) => `L${x(day.index)} ${y(day.stars)}`).join('')}L${x(last.index)} ${PEEK_CURVE_H}Z`
  return {
    from,
    to,
    counted: known.length,
    first: { date: first.date, stars: first.stars },
    last: { date: last.date, stars: last.stars },
    delta: last.stars - first.stars,
    lines,
    area,
    bridges,
    end: { x: round((x(last.index) / PEEK_CURVE_W) * 100), y: round((y(last.stars) / PEEK_CURVE_H) * 100) },
  }
}

/** 提交的短哈希，和 GitHub 页面上一样取前七位 */
export const shortSha = (sha: string) => sha.slice(0, 7)
