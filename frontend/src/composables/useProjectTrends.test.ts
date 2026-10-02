import { effectScope, nextTick, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { GitHubProjectTrendsResponse } from '@/services/projects/projectApi'

const fetchProjectTrends = vi.hoisted(() => vi.fn())
vi.mock('@/services/projects/projectApi', () => ({ fetchProjectTrends }))

import { PROJECT_TRENDS_STALE_MS, useProjectTrends, type ProjectTrendsRequest } from './useProjectTrends'

const response = (repoIds: string[], ranks = false): GitHubProjectTrendsResponse => ({
  metric_date: '2026-10-02',
  previous_date: ranks ? '2026-10-01' : null,
  days: 14,
  items: Object.fromEntries(repoIds.map((repoId, index) => [repoId, {
    points: [{ date: '2026-10-02', stars: 100 + index, gain: index }],
    previous_rank: ranks ? index + 1 : null,
  }])),
})

const flush = async () => {
  await Promise.resolve()
  await Promise.resolve()
  await nextTick()
}

const setup = (initial: ProjectTrendsRequest | null) => {
  const request = ref<ProjectTrendsRequest | null>(initial)
  const clock = { now: 1_000_000 }
  const scope = effectScope()
  const state = scope.run(() => useProjectTrends(() => request.value && { ...request.value }, { now: () => clock.now }))!
  return { request, clock, scope, ...state }
}

describe('useProjectTrends', () => {
  beforeEach(() => {
    fetchProjectTrends.mockReset()
    fetchProjectTrends.mockImplementation(async (repoIds: string[], { ranks }: { ranks: boolean }) => response(repoIds, ranks))
  })

  it('asks once for the whole page and answers per repository', async () => {
    const { trends, trendFor, scope } = setup({ repoIds: ['acme/beta', 'acme/alpha', 'acme/beta', ''], ranks: true })
    await flush()

    expect(fetchProjectTrends).toHaveBeenCalledTimes(1)
    expect(fetchProjectTrends).toHaveBeenCalledWith(['acme/alpha', 'acme/beta'], expect.objectContaining({ ranks: true }))
    expect(trends.value?.previous_date).toBe('2026-10-01')
    expect(trendFor('acme/beta')?.previous_rank).toBe(2)
    expect(trendFor('acme/nobody')).toBeUndefined()
    expect(trendFor('')).toBeUndefined()
    scope.stop()
  })

  it('does not refetch the same page until it goes stale, even when the order changes', async () => {
    const { request, clock, scope } = setup({ repoIds: ['acme/alpha', 'acme/beta'], ranks: true })
    await flush()

    request.value = { repoIds: ['acme/beta', 'acme/alpha'], ranks: true }
    await flush()
    clock.now += PROJECT_TRENDS_STALE_MS - 1
    request.value = { repoIds: ['acme/alpha', 'acme/beta'], ranks: true }
    await flush()
    expect(fetchProjectTrends).toHaveBeenCalledTimes(1)

    clock.now += 2
    request.value = { repoIds: ['acme/alpha', 'acme/beta'], ranks: true }
    await flush()
    expect(fetchProjectTrends).toHaveBeenCalledTimes(2)
    scope.stop()
  })

  it('keeps the last page on screen until the next one arrives and reuses pages already seen', async () => {
    const { request, trends, scope } = setup({ repoIds: ['acme/alpha'], ranks: false })
    await flush()

    let release: (value: GitHubProjectTrendsResponse) => void = () => {}
    fetchProjectTrends.mockImplementationOnce(() => new Promise((resolve) => { release = resolve }))
    request.value = { repoIds: ['acme/gamma'], ranks: false }
    await flush()
    expect(Object.keys(trends.value?.items ?? {})).toEqual(['acme/alpha'])

    release(response(['acme/gamma']))
    await flush()
    expect(Object.keys(trends.value?.items ?? {})).toEqual(['acme/gamma'])

    request.value = { repoIds: ['acme/alpha'], ranks: false }
    await flush()
    expect(Object.keys(trends.value?.items ?? {})).toEqual(['acme/alpha'])
    expect(fetchProjectTrends).toHaveBeenCalledTimes(2)
    scope.stop()
  })

  it('treats ranked and plain requests for the same page as different pages', async () => {
    const { request, trends, scope } = setup({ repoIds: ['acme/alpha'], ranks: false })
    await flush()
    request.value = { repoIds: ['acme/alpha'], ranks: true }
    await flush()

    expect(fetchProjectTrends).toHaveBeenCalledTimes(2)
    expect(trends.value?.previous_date).toBe('2026-10-01')
    scope.stop()
  })

  it('gives up quietly on failure and waits before trying again', async () => {
    fetchProjectTrends.mockRejectedValueOnce(new Error('offline'))
    const { request, clock, trends, scope } = setup({ repoIds: ['acme/alpha'], ranks: false })
    await flush()
    expect(trends.value).toBeNull()

    request.value = { repoIds: ['acme/alpha'], ranks: false }
    await flush()
    expect(fetchProjectTrends).toHaveBeenCalledTimes(1)

    clock.now += PROJECT_TRENDS_STALE_MS
    request.value = { repoIds: ['acme/alpha'], ranks: false }
    await flush()
    expect(fetchProjectTrends).toHaveBeenCalledTimes(2)
    expect(trends.value?.items['acme/alpha']).toBeDefined()
    scope.stop()
  })

  it('stays idle without a request and abandons a request in flight', async () => {
    const { request, scope } = setup(null)
    await flush()
    expect(fetchProjectTrends).not.toHaveBeenCalled()

    let signal: AbortSignal | undefined
    fetchProjectTrends.mockImplementationOnce((_ids: string[], options: { signal: AbortSignal }) => {
      signal = options.signal
      return new Promise(() => {})
    })
    request.value = { repoIds: ['acme/alpha'], ranks: false }
    await flush()
    expect(signal?.aborted).toBe(false)

    request.value = null
    await flush()
    expect(signal?.aborted).toBe(true)

    request.value = { repoIds: ['acme/alpha'], ranks: false }
    await flush()
    expect(fetchProjectTrends).toHaveBeenCalledTimes(2)
    scope.stop()
  })

  it('abandons the request in flight when the page goes away', async () => {
    let signal: AbortSignal | undefined
    fetchProjectTrends.mockImplementationOnce((_ids: string[], options: { signal: AbortSignal }) => {
      signal = options.signal
      return new Promise(() => {})
    })
    const { scope } = setup({ repoIds: ['acme/alpha'], ranks: false })
    await flush()

    scope.stop()
    expect(signal?.aborted).toBe(true)
  })
})
