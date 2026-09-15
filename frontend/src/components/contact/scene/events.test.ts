import { describe, expect, it } from 'vitest'
import {
  EVENT_JITTER,
  FIELD_TIMELINE,
  FieldEventScheduler,
  mulberry32,
  type FieldEventKind,
} from './events'

/** 以固定步长回放调度器，收集 [时刻, 事件] 序列 */
const collect = (scheduler: FieldEventScheduler, until: number, step = 0.25) => {
  const hits: Array<{ at: number; kind: FieldEventKind }> = []
  for (let t = 0; t <= until; t += step) {
    for (const kind of scheduler.tick(t)) hits.push({ at: t, kind })
  }
  return hits
}

describe('mulberry32', () => {
  it('同种子同序列（场景确定性根基）', () => {
    const a = mulberry32(0xa16c)
    const b = mulberry32(0xa16c)
    for (let i = 0; i < 16; i++) expect(a()).toBe(b())
  })

  it('序列落在 [0, 1) 且不同种子不同序列', () => {
    const a = mulberry32(1)
    const b = mulberry32(2)
    for (let i = 0; i < 16; i++) {
      const v = a()
      expect(v).toBeGreaterThanOrEqual(0)
      expect(v).toBeLessThan(1)
    }
    const seqA = Array.from({ length: 8 }, () => a())
    const seqB = Array.from({ length: 8 }, () => b())
    expect(seqA).not.toEqual(seqB)
  })
})

describe('FieldEventScheduler 循环时间线', () => {
  it('同种子两次回放产生完全相同的事件序列', () => {
    expect(collect(new FieldEventScheduler(), 120)).toEqual(collect(new FieldEventScheduler(), 120))
  })

  it('首个周期内四个事件都在 offset ± 抖动窗口内触发', () => {
    const hits = collect(new FieldEventScheduler(), 50)
    for (const spec of FIELD_TIMELINE) {
      const first = hits.find((hit) => hit.kind === spec.kind)
      expect(first, spec.kind).toBeDefined()
      expect(first!.at).toBeGreaterThanOrEqual(spec.offset - EVENT_JITTER)
      expect(first!.at).toBeLessThanOrEqual(spec.offset + EVENT_JITTER)
    }
  })

  it('事件按 period 重排：120 秒内每种至少触发两次', () => {
    const hits = collect(new FieldEventScheduler(), 120)
    for (const spec of FIELD_TIMELINE) {
      expect(hits.filter((hit) => hit.kind === spec.kind).length).toBeGreaterThanOrEqual(2)
    }
  })

  it('reset 后时间线从头开始（按剩余随机序列重新抖动排期）', () => {
    const scheduler = new FieldEventScheduler()
    collect(scheduler, 60)
    scheduler.reset()
    const hits = collect(scheduler, 50)
    // 重新排期后每个事件仍落在自己的 offset ± 抖动窗口内
    for (const spec of FIELD_TIMELINE) {
      const first = hits.find((hit) => hit.kind === spec.kind)
      expect(first, spec.kind).toBeDefined()
      expect(first!.at).toBeGreaterThanOrEqual(spec.offset - EVENT_JITTER)
      expect(first!.at).toBeLessThanOrEqual(spec.offset + EVENT_JITTER)
    }
  })
})

describe('FieldEventScheduler 昼夜跨越', () => {
  it('首次调用只记录不触发（启动不闪灯）', () => {
    const scheduler = new FieldEventScheduler()
    expect(scheduler.checkDayCrossing(0.1)).toBeNull() // 首次虽处夜侧也不点灯
    expect(scheduler.checkDayCrossing(0.3)).toBeNull() // 同侧
    expect(scheduler.checkDayCrossing(0.9)).toBe('lamps-off') // 之后按真实跨越触发
  })

  it('下穿阈值恰触发一次点灯，上穿恰触发一次熄灯', () => {
    const scheduler = new FieldEventScheduler()
    expect(scheduler.checkDayCrossing(1)).toBeNull() // 首次只记录
    expect(scheduler.checkDayCrossing(0.9)).toBeNull() // 同侧
    expect(scheduler.checkDayCrossing(0.4)).toBe('lamps-on')
    expect(scheduler.checkDayCrossing(0.3)).toBeNull() // 同侧不重复
    expect(scheduler.checkDayCrossing(0.8)).toBe('lamps-off')
    expect(scheduler.checkDayCrossing(0.9)).toBeNull()
  })

  it('边界值：0.5 视为昼', () => {
    const scheduler = new FieldEventScheduler()
    scheduler.checkDayCrossing(0.5) // 昼侧记录
    expect(scheduler.checkDayCrossing(0.49)).toBe('lamps-on')
    expect(scheduler.checkDayCrossing(0.5)).toBe('lamps-off')
  })
})
