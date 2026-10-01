import { effectScope, nextTick, ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import type { DashboardTop, DashboardTopParams } from '@/services/dashboard/dashboardContracts'
import { useSameDayPapers } from './useSameDayPapers'

vi.mock('@/services/dashboard/dashboardApi', () => ({ dashboardApi: { fetchTop: vi.fn() } }))

const board = (overrides: Partial<DashboardTop> = {}): DashboardTop => ({
  items: [
    { id: 'a', title: 'First', raw_score: 161, source_channel: 'huggingface_daily_html' },
    { id: 'b', title: 'Second', raw_score: 128, source_channel: 'huggingface_daily_html' },
  ],
  resolvedDate: '2026-10-01', isEmbargoed: false, sourceStatus: {},
  ...overrides,
})

const flush = async () => { await nextTick(); await Promise.resolve(); await nextTick() }

function setup(fetchTop: (params: DashboardTopParams) => Promise<DashboardTop>, day = '2026-10-01', enabled = true) {
  const scope = effectScope()
  const state = { day: ref<string | null>(day), currentId: ref('b'), enabled: ref(enabled) }
  const { entries } = scope.run(() => useSameDayPapers({ ...state, fetchTop }))!
  return { scope, state, entries }
}

describe('useSameDayPapers', () => {
  it('loads the day board for the paper and marks the open one', async () => {
    const fetchTop = vi.fn(async () => board())
    const { entries } = setup(fetchTop)
    await flush()
    expect(fetchTop).toHaveBeenCalledWith(expect.objectContaining({ source: 'arxiv', date: '2026-10-01', limit: 10 }))
    expect(entries.value.map((entry) => [entry.rank, entry.title, entry.current])).toEqual([[1, 'First', false], [2, 'Second', true]])
  })

  it('stays empty when disabled, without a day, embargoed, moved to another day or failing', async () => {
    const off = setup(vi.fn(async () => board()), '2026-10-01', false)
    await flush()
    expect(off.entries.value).toEqual([])

    const noDay = vi.fn(async () => board())
    setup(noDay, '')
    await flush()
    expect(noDay).not.toHaveBeenCalled()

    const embargoed = setup(vi.fn(async () => board({ isEmbargoed: true })))
    await flush()
    expect(embargoed.entries.value).toEqual([])

    const moved = setup(vi.fn(async () => board({ resolvedDate: '2026-09-30' })))
    await flush()
    expect(moved.entries.value).toEqual([])

    const failing = setup(vi.fn(async () => { throw new Error('network') }))
    await flush()
    expect(failing.entries.value).toEqual([])
  })

  it('aborts the previous request when the paper moves to another day and on dispose', async () => {
    const signals: AbortSignal[] = []
    const resolvers: Array<(value: DashboardTop) => void> = []
    const fetchTop = vi.fn((params: DashboardTopParams) => new Promise<DashboardTop>((resolve) => {
      signals.push(params.signal!)
      resolvers.push(resolve)
    }))
    const { scope, state, entries } = setup(fetchTop)
    await flush()
    state.day.value = '2026-09-30'
    await flush()
    expect(signals[0]?.aborted).toBe(true)
    resolvers[0]?.(board())
    await flush()
    expect(entries.value).toEqual([])
    resolvers[1]?.(board({ resolvedDate: '2026-09-30' }))
    await flush()
    expect(entries.value).toHaveLength(2)
    scope.stop()
    expect(signals[1]?.aborted).toBe(true)
  })
})
