/**
 * 原野事件调度器（纯 TS，不引 three，jsdom 可测）。
 * - mulberry32 固定种子 → 整场景完全确定性（测试可回放）；
 * - 循环时间线：每个事件带 offset/period，到期后按 period ±2s 抖动重排；
 * - 昼夜跨越检测：uDay 每次下穿 0.5 恰触发一次点灯，上穿恰触发一次熄灯。
 */

/** 经典 mulberry32 PRNG：同种子同序列 */
export const mulberry32 = (seed: number): (() => number) => {
  let state = seed >>> 0
  return () => {
    state = (state + 0x6d2b79f5) >>> 0
    let t = state
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/** uDay 昼夜阈值：>= 为昼，< 为夜 */
export const DAY_NIGHT_THRESHOLD = 0.5

export const FIELD_EVENT_SEED = 0xa16c

export type FieldEventKind =
  | 'elder-lamp-visit'
  | 'kid-merchant-meet'
  | 'cat-chase-butterfly'
  | 'dog-follow-traveler'

export type LampToggle = 'lamps-on' | 'lamps-off'

interface RecurringSpec {
  kind: FieldEventKind
  /** 首次触发（秒） */
  offset: number
  /** 循环周期（秒），到期后按 ±EVENT_JITTER 抖动 */
  period: number
}

export const EVENT_JITTER = 2

/** 一条 ~48s 的循环生活流：碰面寒暄 → 老人巡灯 → 猫追蝶 → 狗跟旅人 */
export const FIELD_TIMELINE: readonly RecurringSpec[] = [
  { kind: 'kid-merchant-meet', offset: 6, period: 48 },
  { kind: 'elder-lamp-visit', offset: 18, period: 48 },
  { kind: 'cat-chase-butterfly', offset: 30, period: 48 },
  { kind: 'dog-follow-traveler', offset: 40, period: 48 },
]

export class FieldEventScheduler {
  private readonly rng: () => number
  private readonly nextAt = new Map<FieldEventKind, number>()
  private lastDay: number | null = null

  constructor(seed: number = FIELD_EVENT_SEED) {
    this.rng = mulberry32(seed)
    this.scheduleAll(0)
  }

  private jitter(): number {
    return (this.rng() * 2 - 1) * EVENT_JITTER
  }

  private scheduleAll(base: number): void {
    for (const spec of FIELD_TIMELINE) {
      this.nextAt.set(spec.kind, base + spec.offset + this.jitter())
    }
  }

  /** 每帧调用；返回本帧到期的循环事件（可能为空数组） */
  tick(elapsed: number): FieldEventKind[] {
    const due: FieldEventKind[] = []
    for (const spec of FIELD_TIMELINE) {
      const at = this.nextAt.get(spec.kind)
      if (at !== undefined && elapsed >= at) {
        due.push(spec.kind)
        this.nextAt.set(spec.kind, elapsed + spec.period + this.jitter())
      }
    }
    return due
  }

  /**
   * uDay 跨越检测：每次跨越阈值恰返回一次对应事件；
   * 同侧重复调用返回 null。首次调用只记录不触发（启动不闪灯）。
   */
  checkDayCrossing(day: number): LampToggle | null {
    const prev = this.lastDay
    this.lastDay = day
    if (prev === null || prev === day) return null
    const wasDay = prev >= DAY_NIGHT_THRESHOLD
    const isDay = day >= DAY_NIGHT_THRESHOLD
    if (wasDay === isDay) return null
    return isDay ? 'lamps-off' : 'lamps-on'
  }

  /** 重置循环时间线（不动昼夜跨越记忆，避免重置瞬间误触发） */
  reset(): void {
    this.scheduleAll(0)
  }
}
