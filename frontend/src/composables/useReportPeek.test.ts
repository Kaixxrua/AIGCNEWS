import { describe, expect, it, vi } from 'vitest'
import { nextTick, ref } from 'vue'
import type { PaperItem } from '@/services/papers/paperApi'
import { useReportPeek, type PeekEntry } from './useReportPeek'

const paper = (arxivId: string): PaperItem => ({ id: `doc-${arxivId}`, source: 'arxiv', title: `Paper ${arxivId}`, arxiv_id: arxivId })
const link = (arxivId: string, label = '') => ({ arxivId, href: `https://hf-mirror.com/papers/${arxivId}`, label })

const ENTRIES: PeekEntry[] = [
  { key: '1-0-0', papers: [link('2609.00001', 'Raven'), link('2609.00002', 'Omni')] },
  { key: '1-0-1', papers: [link('2609.00003')] },
  { key: '2-0-0', papers: [link('2609.00004')] },
  { key: '2-0-1', papers: [link('2609.00005')] },
]

const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

type Load = (arxivId: string) => Promise<PaperItem | null>

const setup = (load = vi.fn<Load>(async (arxivId) => paper(arxivId))) => {
  const available = ref(true)
  const peek = useReportPeek({ available, load })
  peek.broadsheet.setEntries(ENTRIES)
  return { available, load, peek }
}

describe('useReportPeek', () => {
  it('opens a paper, loads it once and prefetches the first paper of the items either side', async () => {
    const { load, peek } = setup()
    expect(peek.broadsheet.open({ key: '1-0-1', arxivId: '2609.00003' })).toBe(true)
    expect(peek.target.value).toEqual({ key: '1-0-1', arxivId: '2609.00003' })
    expect(peek.current.value).toEqual({ status: 'loading' })
    expect(load.mock.calls.map(([id]) => id)).toEqual(['2609.00003', '2609.00004', '2609.00001'])
    expect(peek.index.value).toBe(1)
    expect(peek.entry.value?.key).toBe('1-0-1')

    await flush()
    expect(peek.current.value).toEqual({ status: 'ready', paper: paper('2609.00003') })

    // 预取过的不再取
    peek.step(1)
    expect(peek.target.value).toEqual({ key: '2-0-0', arxivId: '2609.00004' })
    expect(load.mock.calls.map(([id]) => id)).toEqual(['2609.00003', '2609.00004', '2609.00001', '2609.00005'])
  })

  it('tells a missing paper from a failed request, and retries only the failed one', async () => {
    const load = vi.fn<Load>(async (arxivId) => {
      if (arxivId === '2609.00001') return null
      throw new Error('offline')
    })
    const { peek } = setup(load)
    peek.open({ key: '1-0-0', arxivId: '2609.00001' })
    await flush()
    expect(peek.current.value).toEqual({ status: 'missing' })
    peek.retry()
    expect(load).toHaveBeenCalledTimes(2)

    peek.open({ key: '1-0-1', arxivId: '2609.00003' })
    await flush()
    expect(peek.current.value).toEqual({ status: 'error' })
    load.mockImplementation(async (arxivId) => paper(arxivId))
    peek.retry()
    expect(peek.current.value).toEqual({ status: 'loading' })
    await flush()
    expect(peek.current.value).toEqual({ status: 'ready', paper: paper('2609.00003') })
  })

  it('steps item by item with a direction, stops at either end, and switches papers within an item sideways', () => {
    const { peek } = setup()
    peek.open({ key: '1-0-0', arxivId: '2609.00001' })
    expect([peek.direction.value, peek.withinItem.value]).toEqual([0, false])

    peek.open({ key: '1-0-0', arxivId: '2609.00002' })
    expect([peek.direction.value, peek.withinItem.value]).toEqual([1, true])
    peek.open({ key: '1-0-0', arxivId: '2609.00001' })
    expect([peek.direction.value, peek.withinItem.value]).toEqual([-1, true])

    expect(peek.step(-1)).toBeNull()
    expect(peek.target.value).toEqual({ key: '1-0-0', arxivId: '2609.00001' })
    expect(peek.step(1)).toEqual({ key: '1-0-1', arxivId: '2609.00003' })
    expect([peek.direction.value, peek.withinItem.value]).toEqual([1, false])
    peek.step(1)
    peek.step(1)
    expect(peek.step(1)).toBeNull()
    expect(peek.target.value?.key).toBe('2-0-1')
    expect(peek.step(-1)).toEqual({ key: '2-0-0', arxivId: '2609.00004' })
    expect(peek.direction.value).toBe(-1)
  })

  it('closes when the item goes off the page or the pane stops being available, and does nothing while unavailable', async () => {
    const { available, peek } = setup()
    peek.open({ key: '2-0-0', arxivId: '2609.00004' })
    peek.broadsheet.setEntries(ENTRIES.slice(0, 2))
    expect(peek.target.value).toBeNull()

    peek.broadsheet.setEntries(ENTRIES)
    peek.open({ key: '1-0-0', arxivId: '2609.00001' })
    available.value = false
    await nextTick()
    expect(peek.target.value).toBeNull()
    expect(peek.broadsheet.open({ key: '1-0-0', arxivId: '2609.00001' })).toBe(false)
    expect(peek.broadsheet.target).toBeNull()
    expect(peek.step(1)).toBeNull()
  })

  it('lets a broadsheet hand back only the entries it registered', () => {
    const { peek } = setup()
    const next = ENTRIES.slice(2)
    peek.broadsheet.setEntries(next)
    peek.broadsheet.releaseEntries(ENTRIES)
    expect(peek.entries.value).toBe(next)
    peek.broadsheet.releaseEntries(next)
    expect(peek.entries.value).toEqual([])
  })
})
