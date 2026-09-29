import { effectScope, nextTick, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchLiveStats } from '@/services/dashboard/dashboardLiveApi'
import { subscribeLiveStats, type LiveStatsListener } from '@/composables/useLiveStatsStream'
import type { Stats } from '@/features/dashboard/dashboardViewModel'
import { useDshPluginCalls } from './useDshPluginCalls'

vi.mock('@/services/dashboard/dashboardLiveApi', () => ({ fetchLiveStats: vi.fn() }))
vi.mock('@/composables/useLiveStatsStream', () => ({ subscribeLiveStats: vi.fn() }))

const stats = (calls?: number) => ({ mcp_dsh_calls: calls }) as unknown as Stats

describe('dsh plugin call count', () => {
  let listener: LiveStatsListener | null
  const unsubscribe = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    listener = null
    vi.mocked(fetchLiveStats).mockResolvedValue(stats(627))
    vi.mocked(subscribeLiveStats).mockImplementation((next) => {
      listener = next
      return unsubscribe
    })
  })

  it('stays idle while inactive, then follows the shared live stats and unsubscribes', async () => {
    const active = ref(false)
    const scope = effectScope()
    const calls = scope.run(() => useDshPluginCalls(active))!
    expect(fetchLiveStats).not.toHaveBeenCalled()
    expect(subscribeLiveStats).not.toHaveBeenCalled()
    expect(calls.value).toBeNull()

    active.value = true
    await nextTick()
    await Promise.resolve()
    expect(calls.value).toBe(627)
    listener!(stats(628))
    expect(calls.value).toBe(628)
    listener!(stats())
    expect(calls.value).toBe(628)

    active.value = false
    await nextTick()
    expect(unsubscribe).toHaveBeenCalledOnce()
    active.value = true
    await nextTick()
    scope.stop()
    expect(unsubscribe).toHaveBeenCalledTimes(2)
  })

  it('keeps the placeholder when the first fetch fails', async () => {
    vi.mocked(fetchLiveStats).mockRejectedValue(new Error('offline'))
    const scope = effectScope()
    const calls = scope.run(() => useDshPluginCalls(ref(true)))!
    await Promise.resolve()
    await Promise.resolve()
    expect(calls.value).toBeNull()
    scope.stop()
  })
})
