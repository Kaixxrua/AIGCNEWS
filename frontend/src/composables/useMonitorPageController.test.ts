import { computed, nextTick, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { MonitorApi } from '@/services/monitor/monitorApi'
import type { GithubCrawlStatus } from '@/features/monitor/monitorModel'
import { i18n } from '@/i18n'
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
  fetchGithubEnrichmentStatus: vi.fn(async () => ({ eligible: 10, succeeded: 9, failed: 1, pending: 0 })),
  triggerGithubEnrichment: vi.fn(async () => ({ status: 'queued', message: '' })),
  cancelGithubEnrichment: vi.fn(async () => ({ status: 'cancelling', message: '' })),
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
    expect(api.fetchGithubEnrichmentStatus).not.toHaveBeenCalled()
    expect(controller.enrichmentStatus.value).toBeNull()
  })

  // 回归：main.ts 异步恢复登录态，刷新后 onMounted 时 isAdmin 仍为 false，
  // admin 接口被跳过；恢复出管理员身份后必须补拉，否则配置面板空数据。
  it('refetches admin-scoped data once admin auth restores after initial refresh', async () => {
    const isAdmin = ref(false)
    const api = createApi()
    const schedule = vi.fn((callback: () => void, delay: number) => setTimeout(callback, delay))
    const controller = useMonitorPageController({ isAdmin: computed(() => isAdmin.value), api, schedule, confirm: () => true })
    await controller.refreshData()
    expect(api.fetchProviderConfig).not.toHaveBeenCalled()
    expect(api.fetchSchedulerConfigs).not.toHaveBeenCalled()

    isAdmin.value = true
    await nextTick()
    expect(api.fetchSchedulerConfigs).toHaveBeenCalledOnce()
    expect(api.fetchProviderConfig).toHaveBeenCalledOnce()
    expect(api.fetchMcpServers).toHaveBeenCalledOnce()
    expect(api.fetchGithubEnrichmentStatus).toHaveBeenCalledOnce()
    expect(api.fetchGithubCrawlStatus).toHaveBeenCalledOnce()
  })

  it('does not duplicate admin fetches when admin auth is already known at mount', async () => {
    const isAdmin = ref(true)
    const api = createApi()
    const schedule = vi.fn((callback: () => void, delay: number) => setTimeout(callback, delay))
    const controller = useMonitorPageController({ isAdmin: computed(() => isAdmin.value), api, schedule, confirm: () => true })
    await controller.refreshData()
    await nextTick()
    expect(api.fetchProviderConfig).toHaveBeenCalledOnce()
    expect(api.fetchSchedulerConfigs).toHaveBeenCalledOnce()
  })

  it('populates provider form reasoning effort from config and forwards it on save', async () => {
    const { api, controller } = createController()
    const config = {
      provider: 'openai' as const, base_url: 'https://api.test', model_name: 'model',
      api_key_configured: true, api_key_masked: 'sk-***', updated_at: null, reasoning_effort: 'high',
    }
    vi.mocked(api.fetchProviderConfig).mockResolvedValue(config)
    await controller.fetchProviderConfig()
    expect(controller.providerForm.value.reasoning_effort).toBe('high')

    vi.mocked(api.saveProviderConfig).mockResolvedValue(config)
    await controller.saveProviderConfig()
    expect(api.saveProviderConfig).toHaveBeenCalledWith(expect.objectContaining({ reasoning_effort: 'high' }))
    expect(controller.providerForm.value.reasoning_effort).toBe('high')
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

    vi.mocked(api.saveSchedulerConfig).mockResolvedValue({ item: job, message: '定时任务 arXiv 配置已保存并即时生效。' })
    controller.schedulerConfigForm.value.interval_minutes = 120
    const payload = controller.schedulerConfigForm.value
    await controller.saveSchedulerConfig()
    expect(api.saveSchedulerConfig).toHaveBeenCalledWith(payload)
    expect(controller.editingSchedulerJobId.value).toBeNull()
    expect(controller.successMsg.value).toBe('定时任务 arXiv 配置已保存并即时生效。')
  })

  it('stores fetched MCP tool call metrics on refresh', async () => {
    const { api, controller } = createController()
    const snapshot = {
      since: '2026-08-04T00:00:00+00:00',
      total_calls: 2,
      tools: { search_github_ai_projects: { calls: 2, last_called_at: '2026-08-04T01:00:00+00:00' } },
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

describe('Monitor GitHub enrichment controls', () => {
  beforeEach(() => vi.useFakeTimers())

  it('loads enrichment status for admins on refresh', async () => {
    const { api, controller } = createController()
    vi.mocked(api.fetchGithubEnrichmentStatus).mockResolvedValue({ eligible: 100, succeeded: 95, failed: 3, pending: 2 })
    await controller.refreshData()
    expect(api.fetchGithubEnrichmentStatus).toHaveBeenCalled()
    expect(controller.enrichmentStatus.value).toEqual({ eligible: 100, succeeded: 95, failed: 3, pending: 2 })
  })

  it('retries failed enrichments capped at 500 and polls progress until failures clear', async () => {
    const { api, controller, schedule } = createController()
    vi.mocked(api.fetchGithubEnrichmentStatus).mockResolvedValue({ eligible: 1000, succeeded: 200, failed: 800, pending: 0 })
    await controller.refreshData()

    vi.mocked(api.triggerGithubEnrichment).mockResolvedValue({ status: 'queued', message: '富化任务已提交' })
    await controller.retryFailedEnrichments()

    expect(api.triggerGithubEnrichment).toHaveBeenCalledWith(500, 3)
    expect(controller.successMsg.value).toBe('富化任务已提交')
    expect(controller.retryingEnrichment.value).toBe(false)
    // 提交后进入 4s 间隔的实时进度轮询
    expect(controller.enrichmentPolling.value).toBe(true)
    expect(schedule).toHaveBeenCalledWith(expect.any(Function), 4000)

    // 轮询期间禁止重复提交
    await controller.retryFailedEnrichments()
    expect(api.triggerGithubEnrichment).toHaveBeenCalledTimes(1)

    // 第一轮轮询：失败 800 → 5，进度推进，轮询继续且不触发面板 loading
    vi.mocked(api.fetchGithubEnrichmentStatus).mockClear()
    vi.mocked(api.fetchGithubEnrichmentStatus).mockResolvedValue({ eligible: 1000, succeeded: 995, failed: 5, pending: 0 })
    await vi.advanceTimersByTimeAsync(4000)
    expect(controller.enrichmentStatus.value?.failed).toBe(5)
    expect(controller.enrichmentPolling.value).toBe(true)
    expect(controller.loadingEnrichmentStatus.value).toBe(false)

    // 第二轮轮询：失败清零 → 停止轮询并提示全部补齐
    vi.mocked(api.fetchGithubEnrichmentStatus).mockResolvedValue({ eligible: 1000, succeeded: 1000, failed: 0, pending: 0 })
    await vi.advanceTimersByTimeAsync(4000)
    expect(controller.enrichmentStatus.value?.failed).toBe(0)
    expect(controller.enrichmentPolling.value).toBe(false)
    expect(controller.successMsg.value).toBe(i18n.global.t('monitor.enrichment.retryDone'))
  })

  it('stops enrichment polling when the status fingerprint stays unchanged', async () => {
    const { api, controller } = createController()
    vi.mocked(api.fetchGithubEnrichmentStatus).mockResolvedValue({ eligible: 10, succeeded: 5, failed: 5, pending: 0 })
    await controller.refreshData()

    await controller.retryFailedEnrichments()
    expect(controller.enrichmentPolling.value).toBe(true)

    // 连续 3 轮（12s）计数指纹无变化 → 判定后台任务停滞，结束轮询并提示部分完成
    await vi.advanceTimersByTimeAsync(4000 * 3)
    expect(controller.enrichmentPolling.value).toBe(false)
    expect(controller.successMsg.value).toBe(i18n.global.t('monitor.enrichment.retryPartial', { count: 5 }))
  })

  it('blocks retry when there are no failures and never calls the API', async () => {
    const { api, controller } = createController()
    vi.mocked(api.fetchGithubEnrichmentStatus).mockResolvedValue({ eligible: 10, succeeded: 10, failed: 0, pending: 0 })
    await controller.refreshData()

    await controller.retryFailedEnrichments()
    expect(api.triggerGithubEnrichment).not.toHaveBeenCalled()
    expect(controller.errorMsg.value).toBeTruthy()
  })

  it('surfaces retry submission errors and resets the pending flag', async () => {
    const { api, controller } = createController()
    vi.mocked(api.fetchGithubEnrichmentStatus).mockResolvedValue({ eligible: 10, succeeded: 9, failed: 1, pending: 0 })
    await controller.refreshData()

    vi.mocked(api.triggerGithubEnrichment).mockRejectedValue({ response: { status: 500, data: { detail: 'queue broken' } } })
    await controller.retryFailedEnrichments()
    expect(controller.errorMsg.value).toBe('queue broken')
    expect(controller.retryingEnrichment.value).toBe(false)
  })

  it('backfills pending plus failed capped at 500 with panel concurrency and polls until drained', async () => {
    const { api, controller, schedule } = createController()
    vi.mocked(api.fetchGithubEnrichmentStatus).mockResolvedValue({ eligible: 1000, succeeded: 200, failed: 50, pending: 750 })
    await controller.refreshData()

    controller.enrichmentConcurrency.value = 8
    vi.mocked(api.triggerGithubEnrichment).mockResolvedValue({ status: 'queued', message: '补跑任务已提交' })
    await controller.backfillPendingEnrichments()

    // 补跑范围 = 待处理 750 + 失败 50，封顶 500；并发取面板输入
    expect(api.triggerGithubEnrichment).toHaveBeenCalledWith(500, 8)
    expect(controller.successMsg.value).toBe('补跑任务已提交')
    expect(controller.backfillingEnrichment.value).toBe(false)
    expect(controller.enrichmentPolling.value).toBe(true)
    expect(schedule).toHaveBeenCalledWith(expect.any(Function), 4000)

    // 补跑模式：失败清零但仍有待处理 → 不停止轮询（区别于重试模式）
    vi.mocked(api.fetchGithubEnrichmentStatus).mockResolvedValue({ eligible: 1000, succeeded: 800, failed: 0, pending: 200 })
    await vi.advanceTimersByTimeAsync(4000)
    expect(controller.enrichmentPolling.value).toBe(true)

    // 待处理与失败全部清零 → 停止并提示补齐
    vi.mocked(api.fetchGithubEnrichmentStatus).mockResolvedValue({ eligible: 1000, succeeded: 1000, failed: 0, pending: 0 })
    await vi.advanceTimersByTimeAsync(4000)
    expect(controller.enrichmentPolling.value).toBe(false)
    expect(controller.successMsg.value).toBe(i18n.global.t('monitor.enrichment.backfillDone'))
  })

  it('keeps backfill polling past the retry stale limit before settling', async () => {
    const { api, controller } = createController()
    vi.mocked(api.fetchGithubEnrichmentStatus).mockResolvedValue({ eligible: 10, succeeded: 5, failed: 0, pending: 5 })
    await controller.refreshData()

    await controller.backfillPendingEnrichments()
    expect(controller.enrichmentPolling.value).toBe(true)

    // 重试模式 3 轮停滞即停止；补跑低并发时富化慢，3 轮无变化仍在轮询
    await vi.advanceTimersByTimeAsync(4000 * 3)
    expect(controller.enrichmentPolling.value).toBe(true)

    // 累计 15 轮（约 60s）指纹无变化 → 判定批次停滞，提示剩余待补齐
    await vi.advanceTimersByTimeAsync(4000 * 12)
    expect(controller.enrichmentPolling.value).toBe(false)
    expect(controller.successMsg.value).toBe(i18n.global.t('monitor.enrichment.backfillSettled', { count: 5 }))
  })

  it('blocks backfill when nothing is outstanding and clamps invalid concurrency', async () => {
    const { api, controller } = createController()
    vi.mocked(api.fetchGithubEnrichmentStatus).mockResolvedValue({ eligible: 10, succeeded: 10, failed: 0, pending: 0 })
    await controller.refreshData()

    await controller.backfillPendingEnrichments()
    expect(api.triggerGithubEnrichment).not.toHaveBeenCalled()
    expect(controller.errorMsg.value).toBe(i18n.global.t('monitor.enrichment.noPending'))

    vi.mocked(api.fetchGithubEnrichmentStatus).mockResolvedValue({ eligible: 10, succeeded: 5, failed: 0, pending: 5 })
    await controller.fetchGithubEnrichmentStatus()
    controller.enrichmentConcurrency.value = 99
    await controller.backfillPendingEnrichments()
    expect(api.triggerGithubEnrichment).toHaveBeenCalledWith(5, 10)
  })

  it('cancels a running batch, stops polling, and refetches status exactly once', async () => {
    const { api, controller, schedule } = createController()
    vi.mocked(api.fetchGithubEnrichmentStatus).mockResolvedValue({ eligible: 10, succeeded: 5, failed: 0, pending: 5 })
    await controller.refreshData()
    await controller.backfillPendingEnrichments()
    expect(controller.enrichmentPolling.value).toBe(true)

    vi.mocked(api.cancelGithubEnrichment).mockResolvedValue({ status: 'cancelling', message: '已请求终止富化' })
    schedule.mockClear()
    await controller.cancelEnrichment()

    expect(api.cancelGithubEnrichment).toHaveBeenCalledOnce()
    expect(controller.enrichmentPolling.value).toBe(false)
    expect(controller.cancellingEnrichment.value).toBe(false)
    expect(controller.successMsg.value).toBe('已请求终止富化')
    // 终止后只安排一次补拉，反映本批部分进度
    expect(schedule).toHaveBeenCalledWith(expect.any(Function), 4000)

    const callsBefore = vi.mocked(api.fetchGithubEnrichmentStatus).mock.calls.length
    await vi.advanceTimersByTimeAsync(4000)
    expect(vi.mocked(api.fetchGithubEnrichmentStatus).mock.calls.length).toBe(callsBefore + 1)
    // 轮询已停：继续推进时间不再拉取状态
    await vi.advanceTimersByTimeAsync(12000)
    expect(vi.mocked(api.fetchGithubEnrichmentStatus).mock.calls.length).toBe(callsBefore + 1)
  })

  it('skips cancel when no batch is running locally or server-side', async () => {
    const { api, controller } = createController()
    vi.mocked(api.fetchGithubEnrichmentStatus).mockResolvedValue({ eligible: 10, succeeded: 10, failed: 0, pending: 0, running: false })
    await controller.refreshData()

    await controller.cancelEnrichment()
    expect(api.cancelGithubEnrichment).not.toHaveBeenCalled()
  })

  it('cancels via the server-side running flag after a page refresh', async () => {
    const { api, controller } = createController()
    // 刷新后本地无轮询，但服务端 running=true 时仍允许终止（例如每日流水线批次）
    vi.mocked(api.fetchGithubEnrichmentStatus).mockResolvedValue({ eligible: 10, succeeded: 5, failed: 0, pending: 5, running: true })
    await controller.refreshData()
    expect(controller.enrichmentPolling.value).toBe(false)

    vi.mocked(api.cancelGithubEnrichment).mockResolvedValue({ status: 'cancelling', message: '' })
    await controller.cancelEnrichment()

    expect(api.cancelGithubEnrichment).toHaveBeenCalledOnce()
    expect(controller.successMsg.value).toBe(i18n.global.t('monitor.enrichment.cancelRequested'))
  })

  it('surfaces cancel errors and resets the cancelling flag', async () => {
    const { api, controller } = createController()
    vi.mocked(api.fetchGithubEnrichmentStatus).mockResolvedValue({ eligible: 10, succeeded: 5, failed: 0, pending: 5, running: true })
    await controller.refreshData()
    vi.mocked(api.cancelGithubEnrichment).mockRejectedValue({ response: { status: 500, data: { detail: 'cancel broken' } } })

    await controller.cancelEnrichment()
    expect(controller.errorMsg.value).toBe('cancel broken')
    expect(controller.cancellingEnrichment.value).toBe(false)
  })
})
