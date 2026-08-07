import { computed, ref, watch, type ComputedRef } from 'vue'
import { monitorApi, type MonitorApi } from '@/services/monitor/monitorApi'
import { i18n } from '@/i18n'
import {
  createEmptyMcpForm, createGithubCrawlForm, createMcpForm, createProviderForm, removeMcpServer, replaceMcpServer, upsertMcpServer,
  createEmptySchedulerJobConfigForm, normalizeEnrichmentConcurrency,
  type GithubCrawlStatus, type GithubEnrichmentStatus, type McpServerConfig, type McpToolCallMetricsSnapshot, type SchedulerJobConfig, type SchedulerJobConfigForm, type SourceKey,
} from '@/features/monitor/monitorModel'

interface MonitorPageControllerOptions {
  isAdmin: ComputedRef<boolean>
  api?: MonitorApi
  schedule?: (callback: () => void, delay: number) => unknown
  confirm?: (message: string) => boolean
  now?: () => Date
}

interface AxiosLikeError {
  response?: { status?: number; data?: { detail?: string } }
}

const asAxiosLike = (error: unknown): AxiosLikeError | null =>
  error && typeof error === 'object' && 'response' in error ? (error as AxiosLikeError) : null

const statusOf = (error: unknown) => asAxiosLike(error)?.response?.status
const detail = (error: unknown): string => asAxiosLike(error)?.response?.data?.detail || String(error)

export const useMonitorPageController = ({
  isAdmin,
  api = monitorApi,
  schedule = (callback, delay) => setTimeout(callback, delay),
  confirm = (message) => window.confirm(message),
  now = () => new Date(),
}: MonitorPageControllerOptions) => {
  const tasks = ref<Awaited<ReturnType<MonitorApi['fetchTasks']>>['items']>([])
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(10)
  const schedulerStatus = ref<Awaited<ReturnType<MonitorApi['fetchSchedulerStatus']>> | null>(null)
  const schedulerConfigs = ref<SchedulerJobConfig[]>([])
  const schedulerConfigForm = ref<SchedulerJobConfigForm>(createEmptySchedulerJobConfigForm())
  const loadingSchedulerConfigs = ref(false)
  const savingSchedulerConfig = ref(false)
  const editingSchedulerJobId = ref<string | null>(null)
  const mcpToolCalls = ref<McpToolCallMetricsSnapshot | null>(null)
  const loading = ref(false)
  const errorMsg = ref('')
  const successMsg = ref('')
  const providerConfig = ref<Awaited<ReturnType<MonitorApi['fetchProviderConfig']>> | null>(null)
  const providerForm = ref(createProviderForm())
  const loadingProviderConfig = ref(false)
  const savingProviderConfig = ref(false)
  const mcpServers = ref<McpServerConfig[]>([])
  const mcpForm = ref(createEmptyMcpForm())
  const loadingMcpServers = ref(false)
  const savingMcpServer = ref(false)
  const testingMcpServerId = ref<number | null>(null)
  const deletingMcpServerId = ref<number | null>(null)
  const syncing = ref(false)
  const generatingBriefing = ref(false)
  const clearingCache = ref(false)
  const today = now().toISOString().slice(0, 10)
  const targetDate = ref(today)
  const maxTargetDate = today
  const ingestingByDate = ref(false)
  const ingestingSource = ref<SourceKey | null>(null)
  const clearing = ref(false)
  const showClearConfirm = ref(false)
  const crawlForm = ref(createGithubCrawlForm(today))
  const crawling = ref(false)
  const crawlPolling = ref(false)
  const crawlStatus = ref<GithubCrawlStatus | null>(null)
  const activeCrawlRun = ref<{ channel: string; first_seen_after: string } | null>(null)
  const enrichmentStatus = ref<GithubEnrichmentStatus | null>(null)
  const loadingEnrichmentStatus = ref(false)
  const retryingEnrichment = ref(false)
  const backfillingEnrichment = ref(false)
  const enrichmentConcurrency = ref(3)
  const enrichmentPolling = ref(false)
  const isTaskRunning = computed(() => tasks.value.length > 0 && tasks.value[0]?.status === 'running')
  const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
  const clearMessages = () => { errorMsg.value = ''; successMsg.value = '' }

  const fetchTasks = async () => {
    try {
      const data = await api.fetchTasks(page.value, pageSize.value)
      tasks.value = data.items
      total.value = data.total
    } catch (error) { console.error('Failed to fetch tasks', error) }
  }
  const fetchSchedulerStatus = async () => {
    try { schedulerStatus.value = await api.fetchSchedulerStatus() }
    catch (error) { console.error('Failed to fetch scheduler status', error) }
  }
  const fetchSchedulerConfigs = async () => {
    if (!isAdmin.value) return
    loadingSchedulerConfigs.value = true
    try { schedulerConfigs.value = await api.fetchSchedulerConfigs() }
    catch (error) { console.error('Failed to fetch scheduler configs', error) }
    finally { loadingSchedulerConfigs.value = false }
  }
  const fetchMcpToolCalls = async () => {
    try { mcpToolCalls.value = await api.fetchMcpToolCalls() }
    catch (error) { console.error('Failed to fetch MCP tool call metrics', error) }
  }
  const fetchProviderConfig = async () => {
    if (!isAdmin.value) return
    loadingProviderConfig.value = true
    try {
      providerConfig.value = await api.fetchProviderConfig()
      providerForm.value = createProviderForm(providerConfig.value)
    } catch (error) { console.error('Failed to fetch provider config', error) }
    finally { loadingProviderConfig.value = false }
  }
  const fetchMcpServers = async () => {
    if (!isAdmin.value) return
    loadingMcpServers.value = true
    try { mcpServers.value = await api.fetchMcpServers() }
    catch (error) { console.error('Failed to fetch MCP servers', error) }
    finally { loadingMcpServers.value = false }
  }
  const fetchGithubEnrichmentStatus = async () => {
    if (!isAdmin.value) return
    loadingEnrichmentStatus.value = true
    try { enrichmentStatus.value = await api.fetchGithubEnrichmentStatus() }
    catch (error) { console.error('Failed to fetch GitHub enrichment status', error) }
    finally { loadingEnrichmentStatus.value = false }
  }
  const refreshData = async () => {
    loading.value = true
    await Promise.all([fetchTasks(), fetchSchedulerStatus(), fetchSchedulerConfigs(), fetchMcpToolCalls(), fetchProviderConfig(), fetchMcpServers(), fetchGithubEnrichmentStatus(), resumeGithubCrawlPolling()])
    loading.value = false
  }
  const goPage = async (nextPage: number) => {
    if (nextPage < 1 || nextPage > totalPages.value) return
    page.value = nextPage
    await fetchTasks()
  }
  const saveProviderConfig = async () => {
    if (savingProviderConfig.value) return
    clearMessages(); savingProviderConfig.value = true
    try {
      providerConfig.value = await api.saveProviderConfig(providerForm.value)
      providerForm.value.api_key = ''; providerForm.value.clear_api_key = false
      successMsg.value = '模型服务配置已保存。新建模型实例时会自动使用最新配置。'
    } catch (error) { errorMsg.value = detail(error) }
    finally { savingProviderConfig.value = false }
  }
  const editSchedulerConfig = (job: SchedulerJobConfig) => {
    clearMessages()
    editingSchedulerJobId.value = job.job_id
    schedulerConfigForm.value = createEmptySchedulerJobConfigForm(job)
  }
  const cancelSchedulerConfigEdit = () => {
    editingSchedulerJobId.value = null
    schedulerConfigForm.value = createEmptySchedulerJobConfigForm()
  }
  const saveSchedulerConfig = async () => {
    if (savingSchedulerConfig.value) return
    clearMessages()
    const form = schedulerConfigForm.value
    if (!form.job_id) { errorMsg.value = '请选择要更新的定时任务。'; return }
    if (form.start_time >= form.end_time) { errorMsg.value = '结束时间必须晚于开始时间。'; return }
    if (form.interval_minutes <= 0) { errorMsg.value = '轮询时间必须大于 0。'; return }
    savingSchedulerConfig.value = true
    try {
      const result = await api.saveSchedulerConfig(form)
      const saved = result?.item
      if (saved) {
        const index = schedulerConfigs.value.findIndex((item) => item.job_id === saved.job_id)
        if (index >= 0) schedulerConfigs.value[index] = saved
        else schedulerConfigs.value = [...schedulerConfigs.value, saved]
      }
      editingSchedulerJobId.value = null
      schedulerConfigForm.value = createEmptySchedulerJobConfigForm()
      successMsg.value = result?.message || `定时任务 ${form.name || form.job_id} 配置已保存并即时生效。`
    } catch (error) { errorMsg.value = detail(error) }
    finally { savingSchedulerConfig.value = false }
  }
  const resetMcpForm = () => { mcpForm.value = createEmptyMcpForm() }
  const editMcpServer = (server: McpServerConfig) => { clearMessages(); mcpForm.value = createMcpForm(server) }
  const saveMcpServer = async () => {
    if (savingMcpServer.value) return
    clearMessages()
    const form = mcpForm.value
    if (!form.server_key.trim()) { errorMsg.value = '请填写 MCP Server 标识。'; return }
    if (!form.display_name.trim()) { errorMsg.value = '请填写 MCP Server 名称。'; return }
    if (!form.url.trim()) { errorMsg.value = '请填写 MCP Server URL。'; return }
    savingMcpServer.value = true
    try {
      mcpServers.value = upsertMcpServer(mcpServers.value, await api.saveMcpServer(form))
      resetMcpForm(); successMsg.value = 'MCP Server 配置已保存。'
    } catch (error) { errorMsg.value = detail(error) }
    finally { savingMcpServer.value = false }
  }
  const testMcpServer = async (server: McpServerConfig) => {
    if (testingMcpServerId.value) return
    clearMessages()
    if (!server.enabled) { errorMsg.value = '该 MCP Server 已停用，请先启用后再测试。'; return }
    testingMcpServerId.value = server.id
    try {
      const result = await api.testMcpServer(server.id)
      mcpServers.value = replaceMcpServer(mcpServers.value, result.server)
      const message = result.message || 'MCP Server 测试完成。'
      if (String(result.status || '').toLowerCase() === 'success') successMsg.value = message
      else errorMsg.value = message || 'MCP Server 测试失败。'
    } catch (error) { errorMsg.value = detail(error) }
    finally { testingMcpServerId.value = null }
  }
  const deleteMcpServer = async (server: McpServerConfig) => {
    if (deletingMcpServerId.value || !confirm(`确定删除 MCP Server「${server.display_name || server.server_key}」吗？`)) return
    clearMessages(); deletingMcpServerId.value = server.id
    try {
      const result = await api.deleteMcpServer(server.id)
      mcpServers.value = removeMcpServer(mcpServers.value, server.id)
      if (mcpForm.value.id === server.id) resetMcpForm()
      successMsg.value = result.message || 'MCP Server 配置已删除。'
    } catch (error) { errorMsg.value = detail(error) }
    finally { deletingMcpServerId.value = null }
  }
  const delayedRefresh = (secondDelay: number) => { schedule(fetchTasks, 1000); schedule(fetchTasks, secondDelay) }
  const CRAWL_POLL_INTERVAL = 3000
  const isCrawlTerminal = (status: string) => status === 'success' || status === 'failed'
  const pollGithubCrawlStatus = async () => {
    if (!crawlPolling.value) return
    try {
      const status = await api.fetchGithubCrawlStatus(activeCrawlRun.value || undefined)
      crawlStatus.value = status
      if (isCrawlTerminal(status.task_status)) {
        crawlPolling.value = false
        activeCrawlRun.value = null
        if (status.task_status === 'success') successMsg.value = i18n.global.t('monitor.crawl.runFinished')
        else errorMsg.value = i18n.global.t('monitor.crawl.runFailed', { error: status.error_msg || '' })
        await fetchTasks()
        return
      }
    } catch (error) {
      // 轮询错误容忍：容器重启等瞬态故障不断链
      console.error('Failed to poll GitHub crawl status', error)
    }
    if (crawlPolling.value) schedule(() => { void pollGithubCrawlStatus() }, CRAWL_POLL_INTERVAL)
  }
  const beginCrawlPolling = (run: { channel: string; first_seen_after: string }) => {
    activeCrawlRun.value = run
    crawlPolling.value = true
    schedule(() => { void pollGithubCrawlStatus() }, CRAWL_POLL_INTERVAL)
  }
  const resumeGithubCrawlPolling = async () => {
    if (!isAdmin.value || crawlPolling.value) return
    try {
      const status = await api.fetchGithubCrawlStatus()
      if (!status.task_id) return
      crawlStatus.value = status
      if (status.task_status === 'running') {
        beginCrawlPolling({ channel: status.channel, first_seen_after: status.first_seen_after })
      }
    } catch (error) { console.error('Failed to fetch GitHub crawl status', error) }
  }
  const startGithubCrawl = async () => {
    if (crawling.value || crawlPolling.value) return
    clearMessages()
    const form = crawlForm.value
    if (form.maxStars > 0 && form.maxStars < form.minStars) { errorMsg.value = i18n.global.t('monitor.crawl.invalidWindow'); return }
    if (form.createdStart && form.createdEnd && form.createdEnd < form.createdStart) { errorMsg.value = i18n.global.t('monitor.crawl.invalidDates'); return }
    crawling.value = true
    try {
      const result = await api.crawlGithubProjects(form)
      if (result.status === 'dry_run') {
        successMsg.value = i18n.global.t('monitor.crawl.dryRunDone', {
          shards: Object.keys(result.result?.shards || {}).length,
          total: result.result?.total_available ?? 0,
        })
        return
      }
      successMsg.value = result.message || i18n.global.t('monitor.crawl.submitted')
      delayedRefresh(4000)
      beginCrawlPolling({ channel: result.channel, first_seen_after: result.first_seen_after })
    } catch (error) {
      errorMsg.value = statusOf(error) === 409 ? i18n.global.t('monitor.crawl.conflict') : detail(error)
    } finally { crawling.value = false }
  }
  const ENRICHMENT_POLL_INTERVAL = 4000
  const ENRICHMENT_POLL_STALE_LIMIT = 3
  // 补跑单条富化耗时 15-25s（低并发时指纹变化慢），停滞阈值放宽到 15 次（约 60s）避免误判批次结束
  const ENRICHMENT_BACKFILL_STALE_LIMIT = 15
  const ENRICHMENT_POLL_MAX = 75 // 75 × 4s ≈ 5 分钟上限，防止后台任务挂起时无限轮询
  let enrichmentPollCount = 0
  let enrichmentStalePolls = 0
  let lastEnrichmentFingerprint = ''
  let enrichmentPollMode: 'retry' | 'backfill' = 'retry'
  const enrichmentFingerprint = (status: GithubEnrichmentStatus | null) =>
    status ? `${status.succeeded}:${status.failed}:${status.pending}` : ''
  const stopEnrichmentPolling = (message: string) => {
    enrichmentPolling.value = false
    successMsg.value = message
  }
  const pollGithubEnrichmentStatus = async () => {
    if (!enrichmentPolling.value) return
    enrichmentPollCount += 1
    try {
      // 直接调 api 而非 fetchGithubEnrichmentStatus，避免轮询反复触发面板 loading 闪烁
      enrichmentStatus.value = await api.fetchGithubEnrichmentStatus()
    } catch (error) {
      // 轮询错误容忍：容器重启等瞬态故障不断链
      console.error('Failed to poll GitHub enrichment status', error)
    }
    const failed = enrichmentStatus.value?.failed ?? 0
    const pending = enrichmentStatus.value?.pending ?? 0
    if (enrichmentPollMode === 'retry' && failed <= 0) {
      stopEnrichmentPolling(i18n.global.t('monitor.enrichment.retryDone'))
      return
    }
    if (enrichmentPollMode === 'backfill' && pending <= 0 && failed <= 0) {
      stopEnrichmentPolling(i18n.global.t('monitor.enrichment.backfillDone'))
      return
    }
    const fingerprint = enrichmentFingerprint(enrichmentStatus.value)
    if (fingerprint === lastEnrichmentFingerprint) enrichmentStalePolls += 1
    else { enrichmentStalePolls = 0; lastEnrichmentFingerprint = fingerprint }
    const staleLimit = enrichmentPollMode === 'backfill' ? ENRICHMENT_BACKFILL_STALE_LIMIT : ENRICHMENT_POLL_STALE_LIMIT
    if (enrichmentStalePolls >= staleLimit) {
      stopEnrichmentPolling(enrichmentPollMode === 'backfill'
        ? i18n.global.t('monitor.enrichment.backfillSettled', { count: pending + failed })
        : i18n.global.t('monitor.enrichment.retryPartial', { count: failed }))
      return
    }
    if (enrichmentPollCount >= ENRICHMENT_POLL_MAX) {
      stopEnrichmentPolling(enrichmentPollMode === 'backfill'
        ? i18n.global.t('monitor.enrichment.backfillStillRunning')
        : i18n.global.t('monitor.enrichment.retryPartial', { count: failed }))
      return
    }
    schedule(() => { void pollGithubEnrichmentStatus() }, ENRICHMENT_POLL_INTERVAL)
  }
  const beginEnrichmentPolling = (mode: 'retry' | 'backfill' = 'retry') => {
    if (enrichmentPolling.value) return
    enrichmentPollCount = 0
    enrichmentStalePolls = 0
    lastEnrichmentFingerprint = enrichmentFingerprint(enrichmentStatus.value)
    enrichmentPollMode = mode
    enrichmentPolling.value = true
    schedule(() => { void pollGithubEnrichmentStatus() }, ENRICHMENT_POLL_INTERVAL)
  }
  const retryFailedEnrichments = async () => {
    if (retryingEnrichment.value || backfillingEnrichment.value || enrichmentPolling.value) return
    clearMessages()
    const failed = enrichmentStatus.value?.failed || 0
    if (failed <= 0) { errorMsg.value = i18n.global.t('monitor.enrichment.noFailures'); return }
    retryingEnrichment.value = true
    try {
      // 后端 enrich 上限 500；失败数即本次重试范围，并发度取自面板输入
      const result = await api.triggerGithubEnrichment(
        Math.min(failed, 500),
        normalizeEnrichmentConcurrency(enrichmentConcurrency.value),
      )
      successMsg.value = result.message || i18n.global.t('monitor.enrichment.retrySubmitted')
      beginEnrichmentPolling('retry')
    } catch (error) { errorMsg.value = detail(error) }
    finally { retryingEnrichment.value = false }
  }
  const backfillPendingEnrichments = async () => {
    if (backfillingEnrichment.value || retryingEnrichment.value || enrichmentPolling.value) return
    clearMessages()
    const outstanding = (enrichmentStatus.value?.pending || 0) + (enrichmentStatus.value?.failed || 0)
    if (outstanding <= 0) { errorMsg.value = i18n.global.t('monitor.enrichment.noPending'); return }
    backfillingEnrichment.value = true
    try {
      // 后端 enrich 上限 500；待处理+失败即本次补跑范围，并发度取自面板输入
      const result = await api.triggerGithubEnrichment(
        Math.min(outstanding, 500),
        normalizeEnrichmentConcurrency(enrichmentConcurrency.value),
      )
      successMsg.value = result.message || i18n.global.t('monitor.enrichment.backfillSubmitted')
      beginEnrichmentPolling('backfill')
    } catch (error) { errorMsg.value = detail(error) }
    finally { backfillingEnrichment.value = false }
  }
  const ingestSingleSource = async (source: SourceKey) => {
    if (ingestingSource.value) return
    clearMessages(); ingestingSource.value = source
    try { const result = await api.ingestSource(source); successMsg.value = result.message || `「${source}」采集任务已提交，后台执行中…`; delayedRefresh(4000) }
    catch (error) { const status = statusOf(error); errorMsg.value = status === 409 ? '当前已有任务正在运行，请等待完成后再试。' : status === 400 ? detail(error) || '未知数据源' : detail(error) }
    finally { ingestingSource.value = null }
  }
  const generateAllBriefings = async (forceRegenerate = true) => {
    if (generatingBriefing.value) return
    clearMessages(); generatingBriefing.value = true
    try { const result = await api.generateAllBriefings(forceRegenerate); successMsg.value = result.message || '全维度每日简报生成任务已提交，后台执行中…' }
    catch (error) { errorMsg.value = detail(error) }
    finally { generatingBriefing.value = false }
  }
  const clearDashboardCache = async () => {
    if (clearingCache.value) return
    clearMessages(); clearingCache.value = true
    try { const result = await api.clearDashboardCache(); successMsg.value = result.message || 'Dashboard 缓存已清除，刷新仪表盘即可看到最新数据。' }
    catch (error) { errorMsg.value = detail(error) }
    finally { clearingCache.value = false }
  }
  const syncDataNow = async (force = false) => {
    if (syncing.value || isTaskRunning.value) return
    clearMessages(); syncing.value = true
    try { await api.syncData(force); successMsg.value = force ? '强制采集任务已提交，后台执行中…' : '智能同步任务已提交，后台执行中…'; delayedRefresh(3000) }
    catch (error) { errorMsg.value = statusOf(error) === 409 ? '当前已有任务正在运行，请等待完成后再试。' : detail(error) }
    finally { syncing.value = false }
  }
  const ingestByDate = async () => {
    if (ingestingByDate.value) return
    if (!targetDate.value) { errorMsg.value = '请选择目标日期'; return }
    clearMessages(); ingestingByDate.value = true
    try { const result = await api.ingestByDate(targetDate.value); successMsg.value = result.message || `已提交 ${targetDate.value} 的采集任务，后台执行中…`; delayedRefresh(4000) }
    catch (error) { const status = statusOf(error); errorMsg.value = status === 409 ? '当前已有任务正在运行，请等待完成后再试。' : status === 400 ? detail(error) || '日期格式错误' : detail(error) }
    finally { ingestingByDate.value = false }
  }
  const clearAllData = async () => {
    showClearConfirm.value = false; clearMessages(); clearing.value = true
    try { const result = await api.clearAllData(); successMsg.value = result.message || '数据已清空'; await refreshData() }
    catch (error) { errorMsg.value = detail(error) }
    finally { clearing.value = false }
  }

  // 刷新页面时 main.ts 异步恢复登录态，onMounted 触发 refreshData 时 isAdmin 仍为 false，
  // admin 接口会被静默跳过；待恢复出管理员身份后补拉一次，避免配置面板空数据。
  watch(isAdmin, (admin, wasAdmin) => {
    if (!admin || wasAdmin) return
    void Promise.all([fetchSchedulerConfigs(), fetchProviderConfig(), fetchMcpServers(), fetchGithubEnrichmentStatus(), resumeGithubCrawlPolling()])
  })

  return {
    tasks, total, page, pageSize, schedulerStatus, schedulerConfigs, schedulerConfigForm, loadingSchedulerConfigs, savingSchedulerConfig, editingSchedulerJobId, mcpToolCalls, loading, errorMsg, successMsg, providerConfig, providerForm,
    loadingProviderConfig, savingProviderConfig, mcpServers, mcpForm, loadingMcpServers, savingMcpServer,
    testingMcpServerId, deletingMcpServerId, isTaskRunning, totalPages, syncing, generatingBriefing, clearingCache,
    targetDate, maxTargetDate, ingestingByDate, ingestingSource, clearing, showClearConfirm, clearMessages, fetchTasks,
    fetchSchedulerStatus, fetchSchedulerConfigs, fetchMcpToolCalls, fetchProviderConfig, fetchMcpServers, refreshData, goPage, saveProviderConfig,
    editSchedulerConfig, cancelSchedulerConfigEdit, saveSchedulerConfig,
    resetMcpForm, editMcpServer, saveMcpServer, testMcpServer, deleteMcpServer, ingestSingleSource, generateAllBriefings,
    clearDashboardCache, syncDataNow, ingestByDate, clearAllData,
    crawlForm, crawling, crawlPolling, crawlStatus, startGithubCrawl,
    enrichmentStatus, loadingEnrichmentStatus, retryingEnrichment, backfillingEnrichment, enrichmentConcurrency, enrichmentPolling,
    fetchGithubEnrichmentStatus, retryFailedEnrichments, backfillPendingEnrichments,
  }
}
