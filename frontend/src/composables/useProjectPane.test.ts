import { effectScope, nextTick, ref, type EffectScope } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { GitHubProjectPeek, GitHubProjectTrendsResponse } from '@/services/projects/projectApi'
import { useProjectPeekData } from './useProjectPeek'
import { useProjectPane, type ProjectPane } from './useProjectPane'

const peekOf = (repoId: string): GitHubProjectPeek => ({
  repo_id: repoId,
  status: 'ok',
  has_readme: true,
  readme: [`About ${repoId}`],
  readme_more: false,
  commit: null,
})

const trendsOf = (repoIds: string[]): GitHubProjectTrendsResponse => ({
  metric_date: '2026-10-02',
  previous_date: null,
  days: 30,
  items: Object.fromEntries(repoIds.map((id) => [id, { points: [{ date: '2026-10-02', stars: 7, gain: 1 }], previous_rank: null }])),
})

let scope: EffectScope | undefined
afterEach(() => {
  scope?.stop()
  scope = undefined
})

// 网页收藏（site）没有仓库，不开详情栏
const setup = (initial: string[] = ['a', 'b', 'site', 'c', 'd']) => {
  const keys = ref<string[]>(initial)
  const pending = ref(false)
  const available = ref(true)
  const load = vi.fn(async (repoId: string) => peekOf(repoId))
  const loadTrends = vi.fn(async (repoIds: string[]) => trendsOf(repoIds))
  const repoOf = (key: string) => (key === 'site' ? '' : `acme/${key}`)
  scope = effectScope()
  const pane = scope.run(() => {
    const data = useProjectPeekData({ keys, repoOf, load, loadTrends })
    return useProjectPane({ available, keys, pending, repoOf, data })
  }) as ProjectPane
  return { keys, pending, available, load, loadTrends, pane }
}

const settle = async () => {
  await nextTick()
  await Promise.resolve()
  await nextTick()
}

describe('useProjectPane', () => {
  it('opens a row with its README, commit and curve, and reads ahead the rows on either side', async () => {
    const { pane, load, loadTrends } = setup()
    expect(pane.open('d')).toBe(true)
    expect(pane.target.value).toEqual({ key: 'd', repoId: 'acme/d' })
    expect(pane.index.value).toBe(4)
    expect(pane.direction.value).toBe(0)
    expect(pane.content.value).toEqual({ status: 'loading' })

    await settle()
    expect(pane.content.value).toMatchObject({ status: 'ready', peek: { readme: ['About acme/d'] } })
    expect(pane.curve.value).toMatchObject({ status: 'ready', days: 30 })
    // 前一行 c 先取 README 和提交；后面没有了
    expect(load.mock.calls.map(([repoId]) => repoId)).toEqual(['acme/d', 'acme/c'])
    // 曲线一次取这一页的
    expect(loadTrends).toHaveBeenCalledTimes(1)
    expect(loadTrends.mock.calls[0]![0]).toEqual(expect.arrayContaining(['acme/a', 'acme/b', 'acme/c', 'acme/d']))

    // 已经开着的再开不重取；没有仓库的行开不了
    expect(pane.open('d')).toBe(true)
    expect(pane.open('site')).toBe(false)
    expect(pane.target.value?.key).toBe('d')
    expect(load).toHaveBeenCalledTimes(2)
  })

  it('steps down and up past rows without a repository and stops at the ends of the page', () => {
    const { pane } = setup()
    pane.open('a')
    expect(pane.step(-1)).toBe(false)
    expect(pane.step(1)).toBe(true)
    expect(pane.target.value?.key).toBe('b')
    expect(pane.direction.value).toBe(1)
    expect(pane.step(1)).toBe(true)
    expect(pane.target.value?.key).toBe('c')
    expect(pane.step(-1)).toBe(true)
    expect(pane.target.value?.key).toBe('b')
    expect(pane.direction.value).toBe(-1)
    pane.open('d')
    expect(pane.direction.value).toBe(1)
    expect(pane.step(1)).toBe(false)
    expect(pane.target.value?.key).toBe('d')
  })

  it('carries on with the first row of the next page, or the last of the previous one, once it has loaded', async () => {
    const { pane, keys, pending } = setup()
    pane.open('d')
    pane.expectFlip(1)
    pending.value = true
    keys.value = []
    await nextTick()
    expect(pane.target.value?.key).toBe('d')

    keys.value = ['site', 'e', 'f']
    await nextTick()
    // 还在取的时候不动
    expect(pane.target.value?.key).toBe('d')
    pending.value = false
    await nextTick()
    expect(pane.target.value).toEqual({ key: 'e', repoId: 'acme/e' })
    expect(pane.direction.value).toBe(1)

    pane.expectFlip(-1)
    keys.value = ['a', 'b', 'site']
    await nextTick()
    expect(pane.target.value?.key).toBe('b')
    expect(pane.direction.value).toBe(-1)
  })

  it('closes when the list changes without the open row, but not while it is still loading', async () => {
    const { pane, keys, pending } = setup()
    pane.open('b')
    pending.value = true
    keys.value = ['x', 'y']
    await nextTick()
    expect(pane.target.value?.key).toBe('b')

    // 换了排序，b 还在
    keys.value = ['c', 'b', 'a']
    pending.value = false
    await nextTick()
    expect(pane.target.value?.key).toBe('b')
    expect(pane.index.value).toBe(1)

    keys.value = ['x', 'y']
    await nextTick()
    expect(pane.target.value).toBeNull()
  })

  it('closes when the window gets too narrow, and says whether it was open', async () => {
    const { pane, available } = setup()
    expect(pane.close()).toBe(false)
    pane.open('a')
    available.value = false
    await nextTick()
    expect(pane.target.value).toBeNull()
    expect(pane.open('a')).toBe(false)

    available.value = true
    pane.open('a')
    // 翻页前收起了，取到后不再打开
    pane.expectFlip(1)
    expect(pane.close()).toBe(true)
    expect(pane.direction.value).toBe(0)
    expect(pane.content.value).toBeNull()
    expect(pane.curve.value).toBeNull()
  })

  it('retries what did not load', async () => {
    const { pane, load } = setup()
    load.mockRejectedValueOnce(new Error('offline'))
    pane.open('a')
    await settle()
    expect(pane.content.value).toEqual({ status: 'error' })
    pane.retry()
    await settle()
    expect(pane.content.value).toMatchObject({ status: 'ready', peek: { status: 'ok' } })
    expect(load.mock.calls.filter(([repoId]) => repoId === 'acme/a')).toHaveLength(2)
  })
})
