import { computed } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { MonitorApi } from '@/services/monitor/monitorApi'
import type { GithubCrawlStatus } from '@/features/monitor/monitorModel'
import { useMonitorPageController } from './useMonitorPageController'

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

const createApi = (): MonitorApi => ({
  fetchTasks: vi.fn(async () => ({ items: [], total: 0, page: 1, page_size: 10 })),
  fetchSchedulerStatus: vi.fn(async () => ({ running: false, job_count: 0, jobs: [] })),
  fetchSchedulerConfigs: vi.fn(async () => []),
  saveSchedulerConfig: vi.fn(),
  fetchMcpToolCalls: vi.fn(async () => ({ since: '', total_calls: 0, tools: {} })),
  fetchProviderConfig: vi.fn(), saveProviderConfig: vi.fn(), fetchMcpServers: vi.fn(async () => []),
  saveMcpServer: vi.fn(), testMcpServer: vi.fn(), deleteMcpServer: vi.fn(), ingestSource: vi.fn(),
  generateAllBriefings: vi.fn(), clearDashboardCache: vi.fn(), syncData: vi.fn(), ingestByDate: vi.fn(), clearAllData: vi.fn(),
  crawlGithubProjects: vi.fn(), fetchGithubCrawlStatus: vi.fn(async () => idleCrawlStatus()),
  fetchXWatchAccounts: vi.fn(async () => []), saveXWatchAccount: vi.fn(), deleteXWatchAccount: vi.fn(), testXWatchAccount: vi.fn(),
  fetchXCredentials: vi.fn(async () => []), saveXCredential: vi.fn(), deleteXCredential: vi.fn(), testXCredential: vi.fn(),
})

const createController = (api = createApi(), isAdmin = true) => {
  const schedule = vi.fn((callback: () => void, delay: number) => setTimeout(callback, delay))
  const controller = useMonitorPageController({ isAdmin: computed(() => isAdmin), api, schedule, confirm: () => true })
  return { api, schedule, controller }
}

describe('Monitor page controller contract', () => {
  beforeEach(() => vi.useFakeTimers())

  it('does not request provider or MCP configuration for non-admin users', async () => {
    const { api, controller } = createController(createApi(), false)
    await controller.refreshData()
    expect(api.fetchTasks).toHaveBeenCalledWith(1, 10)
    expect(api.fetchSchedulerStatus).toHaveBeenCalledOnce()
    expect(api.fetchMcpToolCalls).toHaveBeenCalledOnce()
    expect(api.fetchProviderConfig).not.toHaveBeenCalled()
    expect(api.fetchMcpServers).not.toHaveBeenCalled()
  })

  it('loads scheduler configs for admins and validates save constraints', async () => {
    const { api, controller } = createController()
    const job = { job_id: 'ingest:arxiv', name: 'arXiv', start_time: '08:00', end_time: '20:00', interval_minutes: 120, enabled: true }
    vi.mocked(api.fetchSchedulerConfigs).mockResolvedValue([job])
    await controller.fetchSchedulerConfigs()
    expect(controller.schedulerConfigs.value).toEqual([job])

    controller.editSchedulerConfig(job)
    expect(controller.editingSchedulerJobId.value).toBe('ingest:arxiv')

    controller.schedulerConfigForm.value.start_time = '21:00'
    controller.schedulerConfigForm.value.end_time = '08:00'
    await controller.saveSchedulerConfig()
    expect(controller.errorMsg.value).toBe('结束时间必须晚于开始时间。')

    controller.schedulerConfigForm.value.start_time = '08:00'
    controller.schedulerConfigForm.value.end_time = '20:00'
    controller.schedulerConfigForm.value.interval_minutes = 0
    await controller.saveSchedulerConfig()
    expect(controller.errorMsg.value).toBe('轮询时间必须大于 0。')

    vi.mocked(api.saveSchedulerConfig).mockResolvedValue(job)
    controller.schedulerConfigForm.value.interval_minutes = 120
    const payload = controller.schedulerConfigForm.value
    await controller.saveSchedulerConfig()
    expect(api.saveSchedulerConfig).toHaveBeenCalledWith(payload)
    expect(controller.editingSchedulerJobId.value).toBeNull()
    expect(controller.successMsg.value).toContain('配置已保存')
  })

  it('stores fetched MCP tool call metrics on refresh', async () => {
    const { api, controller } = createController()
    const snapshot = {
      since: '2026-08-04T00:00:00+00:00',
      total_calls: 2,
      tools: { get_project_library: { calls: 2, last_called_at: '2026-08-04T01:00:00+00:00' } },
    }
    vi.mocked(api.fetchMcpToolCalls).mockResolvedValue(snapshot)
    await controller.refreshData()
    expect(controller.mcpToolCalls.value).toEqual(snapshot)
  })

  it('preserves source/date ingestion payload delegation and delayed refreshes', async () => {
    const { api, controller } = createController()
    vi.mocked(api.ingestSource).mockResolvedValue({})
    vi.mocked(api.ingestByDate).mockResolvedValue({})
    await controller.ingestSingleSource('github')
    expect(api.ingestSource).toHaveBeenCalledWith('github')
    expect(controller.successMsg.value).toContain('github')
    await vi.advanceTimersByTimeAsync(999)
    expect(api.fetchTasks).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)
    expect(api.fetchTasks).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(3000)
    expect(api.fetchTasks).toHaveBeenCalledTimes(2)
    controller.targetDate.value = '2026-07-20'
    await controller.ingestByDate()
    expect(api.ingestByDate).toHaveBeenCalledWith('2026-07-20')
  })

  it('preserves normal/forced sync guards, messages, and refresh timing', async () => {
    const { api, controller } = createController()
    vi.mocked(api.syncData).mockResolvedValue({})
    await controller.syncDataNow(false)
    expect(api.syncData).toHaveBeenCalledWith(false)
    expect(controller.successMsg.value).toBe('智能同步任务已提交，后台执行中…')
    await vi.advanceTimersByTimeAsync(3000)
    expect(api.fetchTasks).toHaveBeenCalledTimes(2)
    await controller.syncDataNow(true)
    expect(api.syncData).toHaveBeenLastCalledWith(true)
    expect(controller.successMsg.value).toBe('强制采集任务已提交，后台执行中…')
    controller.tasks.value = [{ id: 1, task_name: 'running', status: 'running', item_count: 0, error_msg: null, started_at: null, finished_at: null }]
    await controller.syncDataNow()
    expect(api.syncData).toHaveBeenCalledTimes(2)
  })

  it('preserves error mapping, validation, loading reset, and destructive refresh order', async () => {
    const { api, controller } = createController()
    vi.mocked(api.ingestSource).mockRejectedValue({ response: { status: 409 } })
    await controller.ingestSingleSource('arxiv')
    expect(controller.errorMsg.value).toBe('当前已有任务正在运行，请等待完成后再试。')
    expect(controller.ingestingSource.value).toBeNull()
    controller.targetDate.value = ''
    await controller.ingestByDate()
    expect(controller.errorMsg.value).toBe('请选择目标日期')

    let resolve!: (value: { message: string }) => void
    vi.mocked(api.clearAllData).mockReturnValue(new Promise((done) => { resolve = done }))
    controller.showClearConfirm.value = true
    const pending = controller.clearAllData()
    expect(controller.showClearConfirm.value).toBe(false)
    expect(controller.clearing.value).toBe(true)
    expect(api.fetchTasks).not.toHaveBeenCalled()
    resolve({ message: '已删除' })
    await pending
    expect(controller.successMsg.value).toBe('已删除')
    expect(api.fetchTasks).toHaveBeenCalledOnce()
    expect(controller.clearing.value).toBe(false)
  })

  it('preserves confirmation branch and immutable list ordering', async () => {
    const api = createApi()
    const confirm = vi.fn(() => false)
    const controller = useMonitorPageController({ isAdmin: computed(() => true), api, confirm })
    const server = { id: 7, server_key: 'docs', display_name: 'Docs', description: '', url: 'https://test', transport: 'streamable_http', auth_type: 'none', auth_token_configured: false, auth_token_masked: null, enabled: true, last_test_status: '', last_test_message: '', last_test_at: null, tools: [], created_at: null, updated_at: null }
    controller.mcpServers.value = [server]
    await controller.deleteMcpServer(server)
    expect(confirm).toHaveBeenCalledOnce()
    expect(api.deleteMcpServer).not.toHaveBeenCalled()
    vi.mocked(api.saveMcpServer).mockResolvedValue({ ...server, id: 8 })
    controller.mcpForm.value = { id: null, server_key: 'new', display_name: 'New', description: '', url: 'https://new', auth_type: 'none', auth_token: '', clear_auth_token: false, enabled: true }
    await controller.saveMcpServer()
    expect(controller.mcpServers.value.map(({ id }) => id)).toEqual([8, 7])
  })
})

describe('Monitor GitHub crawl controls', () => {
  beforeEach(() => vi.useFakeTimers())

  it('polls live counts through transient failures and stops at terminal success', async () => {
    const { api, controller } = createController()
    vi.mocked(api.crawlGithubProjects).mockResolvedValue({
      status: 'queued', message: '', channel: 'admin_crawl_x',
      first_seen_after: '2026-08-04T12:30:15+00:00', result: null,
    })
    vi.mocked(api.fetchGithubCrawlStatus).mockResolvedValue(runningCrawlStatus())

    await controller.startGithubCrawl()
    expect(api.crawlGithubProjects).toHaveBeenCalledWith(controller.crawlForm.value)
    expect(controller.crawling.value).toBe(false)
    expect(controller.crawlPolling.value).toBe(true)
    expect(controller.successMsg.value).toBe('GitHub 搜索爬取任务已提交，后台执行中…')

    await vi.advanceTimersByTimeAsync(3000)
    expect(api.fetchGithubCrawlStatus).toHaveBeenCalledWith({
      channel: 'admin_crawl_x', first_seen_after: '2026-08-04T12:30:15+00:00',
    })
    expect(controller.crawlStatus.value).toEqual(runningCrawlStatus())

    // 瞬态故障（如容器重启）不断链，保持轮询且不清空已有计数
    vi.mocked(api.fetchGithubCrawlStatus).mockRejectedValueOnce(new Error('boom'))
    await vi.advanceTimersByTimeAsync(3000)
    expect(controller.crawlPolling.value).toBe(true)
    expect(controller.crawlStatus.value).toEqual(runningCrawlStatus())

    vi.mocked(api.fetchGithubCrawlStatus).mockResolvedValue(runningCrawlStatus({
      task_status: 'success', finished_at: '2026-08-04T12:40:00+00:00',
      candidates_upserted: 12, scope_total: 12, enriched_succeeded: 12,
    }))
    const statusCalls = vi.mocked(api.fetchGithubCrawlStatus).mock.calls.length
    const taskFetches = vi.mocked(api.fetchTasks).mock.calls.length
    await vi.advanceTimersByTimeAsync(3000)
    expect(controller.crawlPolling.value).toBe(false)
    expect(controller.successMsg.value).toBe('本次 GitHub 搜索爬取已完成。')
    expect(vi.mocked(api.fetchTasks).mock.calls.length).toBeGreaterThan(taskFetches)

    await vi.advanceTimersByTimeAsync(9000)
    expect(api.fetchGithubCrawlStatus).toHaveBeenCalledTimes(statusCalls + 1)
  })

  it('surfaces terminal crawl failures with the task error and stops polling', async () => {
    const { api, controller } = createController()
    vi.mocked(api.crawlGithubProjects).mockResolvedValue({
      status: 'queued', message: '', channel: 'admin_crawl_y',
      first_seen_after: '2026-08-04T13:00:00+00:00', result: null,
    })
    await controller.startGithubCrawl()
    vi.mocked(api.fetchGithubCrawlStatus).mockResolvedValue(runningCrawlStatus({
      channel: 'admin_crawl_y', first_seen_after: '2026-08-04T13:00:00+00:00',
      task_status: 'failed', error_msg: 'boom', finished_at: '2026-08-04T13:05:00+00:00',
    }))
    await vi.advanceTimersByTimeAsync(3000)
    expect(controller.crawlPolling.value).toBe(false)
    expect(controller.errorMsg.value).toBe('本次 GitHub 搜索爬取失败：boom')
    const statusCalls = vi.mocked(api.fetchGithubCrawlStatus).mock.calls.length
    await vi.advanceTimersByTimeAsync(9000)
    expect(api.fetchGithubCrawlStatus).toHaveBeenCalledTimes(statusCalls)
  })

  it('reports dry-run counts without starting polling', async () => {
    const { api, controller } = createController()
    controller.crawlForm.value = { ...controller.crawlForm.value, dryRun: true }
    vi.mocked(api.crawlGithubProjects).mockResolvedValue({
      status: 'dry_run', message: '', channel: '', first_seen_after: '',
      result: { shards: { shard_a: 800, shard_b: 700 }, total_available: 42 },
    })
    await controller.startGithubCrawl()
    expect(controller.successMsg.value).toBe('Dry-run 完成：分片 2 个，可抓取约 42 个仓库。')
    expect(controller.crawling.value).toBe(false)
    expect(controller.crawlPolling.value).toBe(false)
    await vi.advanceTimersByTimeAsync(9000)
    expect(api.fetchGithubCrawlStatus).not.toHaveBeenCalled()
  })

  it('maps a 409 conflict to the dedicated message and does not poll', async () => {
    const { api, controller } = createController()
    vi.mocked(api.crawlGithubProjects).mockRejectedValue({ response: { status: 409 } })
    await controller.startGithubCrawl()
    expect(controller.errorMsg.value).toBe('已有 GitHub 搜索爬取任务在执行中，请等待完成后再试。')
    expect(controller.crawling.value).toBe(false)
    expect(controller.crawlPolling.value).toBe(false)
    await vi.advanceTimersByTimeAsync(9000)
    expect(api.fetchGithubCrawlStatus).not.toHaveBeenCalled()
  })

  it('rejects invalid crawl windows client-side without calling the API', async () => {
    const { api, controller } = createController()
    controller.crawlForm.value = { ...controller.crawlForm.value, minStars: 500, maxStars: 400 }
    await controller.startGithubCrawl()
    expect(controller.errorMsg.value).toBe('最高 Stars 不能低于最低 Stars')

    controller.clearMessages()
    controller.crawlForm.value = {
      ...controller.crawlForm.value, maxStars: 0, createdStart: '2026-08-01', createdEnd: '2026-07-01',
    }
    await controller.startGithubCrawl()
    expect(controller.errorMsg.value).toBe('创建时间止不能早于创建时间起')
    expect(api.crawlGithubProjects).not.toHaveBeenCalled()
  })

  it('resumes polling from refreshData while a crawl run is still active', async () => {
    const { api, controller } = createController()
    vi.mocked(api.fetchGithubCrawlStatus).mockResolvedValue(runningCrawlStatus())
    await controller.refreshData()
    expect(api.fetchGithubCrawlStatus).toHaveBeenCalledWith()
    expect(controller.crawlPolling.value).toBe(true)
    expect(controller.crawlStatus.value?.channel).toBe('admin_crawl_x')

    vi.mocked(api.fetchGithubCrawlStatus).mockClear()
    vi.mocked(api.fetchGithubCrawlStatus).mockResolvedValue(runningCrawlStatus({ candidates_upserted: 9 }))
    await vi.advanceTimersByTimeAsync(3000)
    expect(api.fetchGithubCrawlStatus).toHaveBeenCalledWith({
      channel: 'admin_crawl_x', first_seen_after: '2026-08-04T12:30:15+00:00',
    })
    expect(controller.crawlStatus.value?.candidates_upserted).toBe(9)
    expect(controller.crawlPolling.value).toBe(true)
  })
})
