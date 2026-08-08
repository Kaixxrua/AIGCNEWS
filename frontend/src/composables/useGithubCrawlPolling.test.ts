import { computed } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { MonitorApi } from '@/services/monitor/monitorApi'
import type { GithubCrawlStatus } from '@/features/monitor/monitorModel'
import { i18n } from '@/i18n'
import { CRAWL_POLL_INTERVAL, useGithubCrawlPolling } from './useGithubCrawlPolling'

const idleCrawlStatus = (): GithubCrawlStatus => ({
  status: 'idle',
  channel: '',
  first_seen_after: '',
  task_id: null,
  task_status: '',
  item_count: 0,
  error_msg: null,
  started_at: null,
  finished_at: null,
  candidates_upserted: 0,
  scope_total: 0,
  enriched_succeeded: 0,
  enriched_failed: 0,
})

const runningCrawlStatus = (overrides: Partial<GithubCrawlStatus> = {}): GithubCrawlStatus => ({
  ...idleCrawlStatus(),
  status: 'running',
  channel: 'admin_crawl_x',
  first_seen_after: '2026-08-04T12:30:15+00:00',
  task_id: 42,
  task_status: 'running',
  item_count: 7,
  started_at: '2026-08-04T12:30:16+00:00',
  candidates_upserted: 7,
  scope_total: 7,
  enriched_succeeded: 3,
  ...overrides,
})

const createPolling = (isAdmin = true) => {
  const api = { fetchGithubCrawlStatus: vi.fn(async () => idleCrawlStatus()) } as unknown as MonitorApi
  const schedule = vi.fn((callback: () => void, delay: number) => setTimeout(callback, delay))
  const setSuccess = vi.fn()
  const setError = vi.fn()
  const refreshTasks = vi.fn(async () => {})
  const polling = useGithubCrawlPolling({ api, isAdmin: computed(() => isAdmin), schedule, setSuccess, setError, refreshTasks })
  return { api, schedule, setSuccess, setError, refreshTasks, polling }
}

const RUN = { channel: 'admin_crawl_x', first_seen_after: '2026-08-04T12:30:15+00:00' }

describe('useGithubCrawlPolling', () => {
  beforeEach(() => vi.useFakeTimers())

  it('begins polling on the interval and keeps polling on non-terminal status', async () => {
    const { api, schedule, polling } = createPolling()
    vi.mocked(api.fetchGithubCrawlStatus).mockResolvedValue(runningCrawlStatus())

    polling.beginCrawlPolling(RUN)
    expect(polling.crawlPolling.value).toBe(true)
    expect(schedule).toHaveBeenCalledWith(expect.any(Function), CRAWL_POLL_INTERVAL)
    expect(api.fetchGithubCrawlStatus).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(CRAWL_POLL_INTERVAL)
    expect(api.fetchGithubCrawlStatus).toHaveBeenCalledWith(RUN)
    expect(polling.crawlStatus.value).toEqual(runningCrawlStatus())
    expect(polling.crawlPolling.value).toBe(true)

    await vi.advanceTimersByTimeAsync(CRAWL_POLL_INTERVAL)
    expect(api.fetchGithubCrawlStatus).toHaveBeenCalledTimes(2)
    expect(polling.crawlPolling.value).toBe(true)
  })

  it('stops on terminal success, notifies, refreshes tasks, and clears the active run', async () => {
    const { api, setSuccess, setError, refreshTasks, polling } = createPolling()
    vi.mocked(api.fetchGithubCrawlStatus).mockResolvedValue(runningCrawlStatus())

    polling.beginCrawlPolling(RUN)
    vi.mocked(api.fetchGithubCrawlStatus).mockResolvedValue(runningCrawlStatus({
      task_status: 'success', finished_at: '2026-08-04T12:40:00+00:00',
    }))
    await vi.advanceTimersByTimeAsync(CRAWL_POLL_INTERVAL)

    expect(polling.crawlPolling.value).toBe(false)
    expect(setSuccess).toHaveBeenCalledWith(i18n.global.t('monitor.crawl.runFinished'))
    expect(setError).not.toHaveBeenCalled()
    expect(refreshTasks).toHaveBeenCalledOnce()

    const calls = vi.mocked(api.fetchGithubCrawlStatus).mock.calls.length
    await vi.advanceTimersByTimeAsync(CRAWL_POLL_INTERVAL * 3)
    expect(api.fetchGithubCrawlStatus).toHaveBeenCalledTimes(calls)
  })

  it('stops on terminal failure and surfaces the task error', async () => {
    const { api, setSuccess, setError, refreshTasks, polling } = createPolling()
    polling.beginCrawlPolling(RUN)
    vi.mocked(api.fetchGithubCrawlStatus).mockResolvedValue(runningCrawlStatus({
      task_status: 'failed', error_msg: 'boom', finished_at: '2026-08-04T12:35:00+00:00',
    }))
    await vi.advanceTimersByTimeAsync(CRAWL_POLL_INTERVAL)

    expect(polling.crawlPolling.value).toBe(false)
    expect(setError).toHaveBeenCalledWith(i18n.global.t('monitor.crawl.runFailed', { error: 'boom' }))
    expect(setSuccess).not.toHaveBeenCalled()
    expect(refreshTasks).toHaveBeenCalledOnce()

    const calls = vi.mocked(api.fetchGithubCrawlStatus).mock.calls.length
    await vi.advanceTimersByTimeAsync(CRAWL_POLL_INTERVAL * 3)
    expect(api.fetchGithubCrawlStatus).toHaveBeenCalledTimes(calls)
  })

  it('tolerates transient poll failures without dropping the chain or the last status', async () => {
    const { api, polling } = createPolling()
    vi.mocked(api.fetchGithubCrawlStatus).mockResolvedValue(runningCrawlStatus())

    polling.beginCrawlPolling(RUN)
    await vi.advanceTimersByTimeAsync(CRAWL_POLL_INTERVAL)
    expect(polling.crawlStatus.value).toEqual(runningCrawlStatus())

    vi.mocked(api.fetchGithubCrawlStatus).mockRejectedValueOnce(new Error('boom'))
    await vi.advanceTimersByTimeAsync(CRAWL_POLL_INTERVAL)
    expect(polling.crawlPolling.value).toBe(true)
    expect(polling.crawlStatus.value).toEqual(runningCrawlStatus())

    await vi.advanceTimersByTimeAsync(CRAWL_POLL_INTERVAL)
    expect(api.fetchGithubCrawlStatus).toHaveBeenCalledTimes(3)
    expect(polling.crawlPolling.value).toBe(true)
  })

  it('resumes polling only for an active admin run', async () => {
    // 非管理员不触发任何状态拉取
    const anonymous = createPolling(false)
    await anonymous.polling.resumeGithubCrawlPolling()
    expect(anonymous.api.fetchGithubCrawlStatus).not.toHaveBeenCalled()
    expect(anonymous.polling.crawlPolling.value).toBe(false)

    // 无活动任务（task_id 为空）不进入轮询
    const idle = createPolling()
    await idle.polling.resumeGithubCrawlPolling()
    expect(idle.api.fetchGithubCrawlStatus).toHaveBeenCalledWith()
    expect(idle.polling.crawlPolling.value).toBe(false)
    expect(idle.schedule).not.toHaveBeenCalled()

    // 运行中任务恢复轮询并回填状态
    const active = createPolling()
    vi.mocked(active.api.fetchGithubCrawlStatus).mockResolvedValue(runningCrawlStatus())
    await active.polling.resumeGithubCrawlPolling()
    expect(active.polling.crawlStatus.value?.channel).toBe('admin_crawl_x')
    expect(active.polling.crawlPolling.value).toBe(true)
    expect(active.schedule).toHaveBeenCalledWith(expect.any(Function), CRAWL_POLL_INTERVAL)

    // 已在轮询时不重复拉取
    vi.mocked(active.api.fetchGithubCrawlStatus).mockClear()
    await active.polling.resumeGithubCrawlPolling()
    expect(active.api.fetchGithubCrawlStatus).not.toHaveBeenCalled()
  })

  it('does not resume when the run already reached a terminal state', async () => {
    const { api, polling } = createPolling()
    vi.mocked(api.fetchGithubCrawlStatus).mockResolvedValue(runningCrawlStatus({ task_status: 'success' }))
    await polling.resumeGithubCrawlPolling()
    expect(polling.crawlStatus.value?.task_status).toBe('success')
    expect(polling.crawlPolling.value).toBe(false)
  })
})
