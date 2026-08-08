import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { MonitorApi } from '@/services/monitor/monitorApi'
import type { GithubEnrichmentStatus } from '@/features/monitor/monitorModel'
import { i18n } from '@/i18n'
import { ENRICHMENT_POLL_INTERVAL, useEnrichmentPolling } from './useEnrichmentPolling'

const createPolling = (status: GithubEnrichmentStatus = { eligible: 10, succeeded: 5, failed: 5, pending: 0 }) => {
  const api = { fetchGithubEnrichmentStatus: vi.fn(async () => status) } as unknown as MonitorApi
  const schedule = vi.fn((callback: () => void, delay: number) => setTimeout(callback, delay))
  const setSuccess = vi.fn()
  const polling = useEnrichmentPolling({ api, schedule, setSuccess })
  return { api, schedule, setSuccess, polling }
}

describe('useEnrichmentPolling', () => {
  beforeEach(() => vi.useFakeTimers())

  it('stops retry polling with retryDone once failures clear', async () => {
    const { api, schedule, setSuccess, polling } = createPolling()
    polling.enrichmentStatus.value = { eligible: 10, succeeded: 5, failed: 5, pending: 0 }

    polling.beginEnrichmentPolling('retry')
    expect(polling.enrichmentPolling.value).toBe(true)
    expect(schedule).toHaveBeenCalledWith(expect.any(Function), ENRICHMENT_POLL_INTERVAL)

    // 第一轮：失败未清零但指纹推进，继续轮询
    vi.mocked(api.fetchGithubEnrichmentStatus).mockResolvedValue({ eligible: 10, succeeded: 8, failed: 2, pending: 0 })
    await vi.advanceTimersByTimeAsync(ENRICHMENT_POLL_INTERVAL)
    expect(polling.enrichmentPolling.value).toBe(true)
    expect(polling.enrichmentStatus.value?.failed).toBe(2)

    // 第二轮：失败清零 → 停止并提示全部补齐
    vi.mocked(api.fetchGithubEnrichmentStatus).mockResolvedValue({ eligible: 10, succeeded: 10, failed: 0, pending: 0 })
    await vi.advanceTimersByTimeAsync(ENRICHMENT_POLL_INTERVAL)
    expect(polling.enrichmentPolling.value).toBe(false)
    expect(setSuccess).toHaveBeenCalledWith(i18n.global.t('monitor.enrichment.retryDone'))

    const calls = vi.mocked(api.fetchGithubEnrichmentStatus).mock.calls.length
    await vi.advanceTimersByTimeAsync(ENRICHMENT_POLL_INTERVAL * 3)
    expect(api.fetchGithubEnrichmentStatus).toHaveBeenCalledTimes(calls)
  })

  it('stops retry polling after the stale limit with retryPartial', async () => {
    const { setSuccess, polling } = createPolling()
    polling.enrichmentStatus.value = { eligible: 10, succeeded: 5, failed: 5, pending: 0 }

    polling.beginEnrichmentPolling('retry')
    // 指纹连续 3 轮无变化 → 判定停滞，提示剩余失败数
    await vi.advanceTimersByTimeAsync(ENRICHMENT_POLL_INTERVAL * 2)
    expect(polling.enrichmentPolling.value).toBe(true)
    await vi.advanceTimersByTimeAsync(ENRICHMENT_POLL_INTERVAL)
    expect(polling.enrichmentPolling.value).toBe(false)
    expect(setSuccess).toHaveBeenCalledWith(i18n.global.t('monitor.enrichment.retryPartial', { count: 5 }))
  })

  it('keeps backfill polling while pending remains and stops with backfillDone when drained', async () => {
    const { api, setSuccess, polling } = createPolling({ eligible: 10, succeeded: 5, failed: 0, pending: 5 })
    polling.enrichmentStatus.value = { eligible: 10, succeeded: 5, failed: 0, pending: 5 }

    polling.beginEnrichmentPolling('backfill')
    // 补跑模式：失败已清零但仍有待处理 → 不停止（区别于重试模式）
    vi.mocked(api.fetchGithubEnrichmentStatus).mockResolvedValue({ eligible: 10, succeeded: 8, failed: 0, pending: 2 })
    await vi.advanceTimersByTimeAsync(ENRICHMENT_POLL_INTERVAL)
    expect(polling.enrichmentPolling.value).toBe(true)

    vi.mocked(api.fetchGithubEnrichmentStatus).mockResolvedValue({ eligible: 10, succeeded: 10, failed: 0, pending: 0 })
    await vi.advanceTimersByTimeAsync(ENRICHMENT_POLL_INTERVAL)
    expect(polling.enrichmentPolling.value).toBe(false)
    expect(setSuccess).toHaveBeenCalledWith(i18n.global.t('monitor.enrichment.backfillDone'))
  })

  it('keeps backfill polling past the retry stale limit and settles at its own limit', async () => {
    const { setSuccess, polling } = createPolling({ eligible: 10, succeeded: 5, failed: 0, pending: 5 })
    polling.enrichmentStatus.value = { eligible: 10, succeeded: 5, failed: 0, pending: 5 }

    polling.beginEnrichmentPolling('backfill')
    // 重试模式 3 轮停滞即停止；补跑低并发时富化慢，3 轮无变化仍在轮询
    await vi.advanceTimersByTimeAsync(ENRICHMENT_POLL_INTERVAL * 3)
    expect(polling.enrichmentPolling.value).toBe(true)

    // 累计 15 轮（约 60s）指纹无变化 → 判定批次停滞，提示剩余待补齐
    await vi.advanceTimersByTimeAsync(ENRICHMENT_POLL_INTERVAL * 12)
    expect(polling.enrichmentPolling.value).toBe(false)
    expect(setSuccess).toHaveBeenCalledWith(i18n.global.t('monitor.enrichment.backfillSettled', { count: 5 }))
  })

  it('stops polling at the max poll count to bound a hung batch', async () => {
    const api = {
      fetchGithubEnrichmentStatus: vi.fn(async () => ({ eligible: 100, succeeded: 0, failed: 0, pending: 5 })),
    } as unknown as MonitorApi
    let succeeded = 0
    vi.mocked(api.fetchGithubEnrichmentStatus).mockImplementation(async () => {
      succeeded += 1
      return { eligible: 100, succeeded, failed: 0, pending: 5 }
    })
    const schedule = vi.fn((callback: () => void, delay: number) => setTimeout(callback, delay))
    const setSuccess = vi.fn()
    const polling = useEnrichmentPolling({ api, schedule, setSuccess })

    polling.beginEnrichmentPolling('backfill')
    // 指纹每轮都在推进（不停滞），只能靠 75 轮上限终止
    await vi.advanceTimersByTimeAsync(ENRICHMENT_POLL_INTERVAL * 74)
    expect(polling.enrichmentPolling.value).toBe(true)
    await vi.advanceTimersByTimeAsync(ENRICHMENT_POLL_INTERVAL)
    expect(polling.enrichmentPolling.value).toBe(false)
    expect(setSuccess).toHaveBeenCalledWith(i18n.global.t('monitor.enrichment.backfillStillRunning'))
  })

  it('tolerates transient status fetch failures and keeps polling', async () => {
    const { api, polling } = createPolling()
    polling.enrichmentStatus.value = { eligible: 10, succeeded: 5, failed: 5, pending: 0 }

    polling.beginEnrichmentPolling('retry')
    vi.mocked(api.fetchGithubEnrichmentStatus).mockRejectedValueOnce(new Error('boom'))
    await vi.advanceTimersByTimeAsync(ENRICHMENT_POLL_INTERVAL)
    expect(polling.enrichmentPolling.value).toBe(true)

    await vi.advanceTimersByTimeAsync(ENRICHMENT_POLL_INTERVAL)
    expect(api.fetchGithubEnrichmentStatus).toHaveBeenCalledTimes(2)
  })

  it('ignores a second begin while polling is active', async () => {
    const { schedule, polling } = createPolling()
    polling.beginEnrichmentPolling('retry')
    expect(polling.enrichmentPolling.value).toBe(true)
    expect(schedule).toHaveBeenCalledTimes(1)

    polling.beginEnrichmentPolling('backfill')
    expect(schedule).toHaveBeenCalledTimes(1)
  })
})
