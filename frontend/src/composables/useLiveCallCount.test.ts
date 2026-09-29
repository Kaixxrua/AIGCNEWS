import { effectScope, nextTick, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchLiveStats } from '@/services/dashboard/dashboardLiveApi'
import { subscribeLiveStats, type LiveStatsListener } from '@/composables/useLiveStatsStream'
import type { Stats } from '@/features/dashboard/dashboardViewModel'
import { useLiveCallCount } from './useLiveCallCount'

vi.mock('@/services/dashboard/dashboardLiveApi', () => ({ fetchLiveStats: vi.fn() }))
vi.mock('@/composables/useLiveStatsStream', () => ({ subscribeLiveStats: vi.fn() }))

describe('live MCP call count', () => {
  let listener: LiveStatsListener | null

  beforeEach(() => {
    vi.clearAllMocks()
    listener = null
    vi.mocked(fetchLiveStats).mockResolvedValue({ mcp_total_calls: 4545, mcp_dsh_calls: 627 } as Stats)
    vi.mocked(subscribeLiveStats).mockImplementation((next) => {
      listener = next
      return vi.fn()
    })
  })

  it('reads only its own field from the shared live stats', async () => {
    const scope = effectScope()
    const calls = scope.run(() => useLiveCallCount('mcp_total_calls', ref(true)))!
    await nextTick()
    await Promise.resolve()
    expect(calls.value).toBe(4545)
    listener!({ mcp_dsh_calls: 700 } as Stats)
    expect(calls.value).toBe(4545)
    listener!({ mcp_total_calls: 4546 } as Stats)
    expect(calls.value).toBe(4546)
    scope.stop()
  })
})
