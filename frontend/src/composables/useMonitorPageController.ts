import { computed, ref, watch, type ComputedRef } from 'vue'
import { monitorApi, type MonitorApi } from '@/services/monitor/monitorApi'
import { i18n } from '@/i18n'
import {
  createEmptyMcpForm, createGithubCrawlForm, createMcpForm, createProviderForm, removeMcpServer, replaceMcpServer, upsertMcpServer,
  createEmptySchedulerJobConfigForm, normalizeEnrichmentConcurrency, normalizeReasoningEffort,
  type McpServerConfig, type McpToolCallMetricsSnapshot, type SchedulerJobConfig, type SchedulerJobConfigForm, type SourceKey,
} from '@/features/monitor/monitorModel'
import { useGithubCrawlPolling } from './useGithubCrawlPolling'
import { ENRICHMENT_POLL_INTERVAL, useEnrichmentPolling } from './useEnrichmentPolling'

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
  const testingProvider = ref(false)
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
  const loadingEnrichmentStatus = ref(false)
  const retryingEnrichment = ref(false)
  const backfillingEnrichment = ref(false)
  const cancellingEnrichment = ref(false)
  const enrichmentConcurrency = ref(3)
  // 富化专用推理强度：空串=跟随模型服务配置；effective 为后端解析的当前生效档位
  const enrichmentReasoningEffort = ref('')
  const enrichmentEffectiveReasoningEffort = ref('')
  const savingEnrichmentReasoningEffort = ref(false)
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
  const setSuccessMessage = (message: string) => { successMsg.value = message }
  const setErrorMessage = (message: string) => { errorMsg.value = message }
  const { crawlPolling, crawlStatus, beginCrawlPolling, resumeGithubCrawlPolling } = useGithubCrawlPolling({
    api, isAdmin, schedule,
    setSuccess: setSuccessMessage,
    setError: setErrorMessage,
    refreshTasks: fetchTasks,
  })
  const { enrichmentStatus, enrichmentPolling, beginEnrichmentPolling, stopEnrichmentPolling } = useEnrichmentPolling({
    api, schedule, setSuccess: setSuccessMessage,
  })
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
  const fetchGithubEnrichmentConfig = async () => {
    if (!isAdmin.value) return
    try {
      const config = await api.fetchGithubEnrichmentConfig()
      enrichmentReasoningEffort.value = config.reasoning_effort
      enrichmentEffectiveReasoningEffort.value = config.effective_reasoning_effort
    } catch (error) { console.error('Failed to fetch GitHub enrichment config', error) }
  }
  const saveEnrichmentReasoningEffort = async (value: string) => {
    if (savingEnrichmentReasoningEffort.value) return
    const normalized = normalizeReasoningEffort(value)
    // 失焦未改动时不重复写库
    if (normalized === enrichmentReasoningEffort.value) return
    clearMessages()
    savingEnrichmentReasoningEffort.value = true
    try {
      const config = await api.saveGithubEnrichmentConfig(normalized)
      enrichmentReasoningEffort.value = config.reasoning_effort
      enrichmentEffectiveReasoningEffort.value = config.effective_reasoning_effort
      successMsg.value = i18n.global.t('monitor.enrichment.reasoningEffortSaved')
    } catch (error) { errorMsg.value = detail(error) }
    finally { savingEnrichmentReasoningEffort.value = false }
  }
  const refreshData = async () => {
    loading.value = true
    await Promise.all([fetchTasks(), fetchSchedulerStatus(), fetchSchedulerConfigs(), fetchMcpToolCalls(), fetchProviderConfig(), fetchMcpServers(), fetchGithubEnrichmentStatus(), fetchGithubEnrichmentConfig(), resumeGithubCrawlPolling()])
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
      successMsg.value = i18n.global.t('monitor.savedProvider')
    } catch (error) { errorMsg.value = detail(error) }
    finally { savingProviderConfig.value = false }
  }
  const testProviderConnection = async () => {
    if (testingProvider.value) return
    clearMessages(); testingProvider.value = true
    try {
      // 测试的是已保存的配置；表单里未保存的修改不生效，先保存再测试
      const result = await api.testProviderConnection()
      if (String(result.status || '').toLowerCase() === 'success') successMsg.value = result.message || i18n.global.t('monitor.testPassed')
      else errorMsg.value = result.message || i18n.global.t('monitor.testFailed')
    } catch (error) { errorMsg.value = detail(error) }
    finally { testingProvider.value = false }
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
    if (!form.job_id) { errorMsg.value = i18n.global.t('monitor.schedulerConfig.chooseJob'); return }
    if (form.start_time >= form.end_time) { errorMsg.value = i18n.global.t('monitor.schedulerConfig.invalidWindow'); return }
    if (form.interval_minutes <= 0) { errorMsg.value = i18n.global.t('monitor.schedulerConfig.invalidInterval'); return }
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
      successMsg.value = result?.message || i18n.global.t('monitor.schedulerConfig.saved', { name: form.name || form.job_id })
    } catch (error) { errorMsg.value = detail(error) }
    finally { savingSchedulerConfig.value = false }
  }
  const resetMcpForm = () => { mcpForm.value = createEmptyMcpForm() }
  const editMcpServer = (server: McpServerConfig) => { clearMessages(); mcpForm.value = createMcpForm(server) }
  const saveMcpServer = async () => {
    if (savingMcpServer.value) return
    clearMessages()
    const form = mcpForm.value
    if (!form.server_key.trim()) { errorMsg.value = i18n.global.t('monitor.serverKeyRequired'); return }
    if (!form.display_name.trim()) { errorMsg.value = i18n.global.t('monitor.serverNameRequired'); return }
    if (!form.url.trim()) { errorMsg.value = i18n.global.t('monitor.serverUrlRequired'); return }
    savingMcpServer.value = true
    try {
      mcpServers.value = upsertMcpServer(mcpServers.value, await api.saveMcpServer(form))
      resetMcpForm(); successMsg.value = i18n.global.t('monitor.serverSaved')
    } catch (error) { errorMsg.value = detail(error) }
    finally { savingMcpServer.value = false }
  }
  const testMcpServer = async (server: McpServerConfig) => {
    if (testingMcpServerId.value) return
    clearMessages()
    if (!server.enabled) { errorMsg.value = i18n.global.t('monitor.serverDisabled'); return }
    testingMcpServerId.value = server.id
    try {
      const result = await api.testMcpServer(server.id)
      mcpServers.value = replaceMcpServer(mcpServers.value, result.server)
      const message = result.message || i18n.global.t('monitor.serverTestDone')
      if (String(result.status || '').toLowerCase() === 'success') successMsg.value = message
      else errorMsg.value = message || i18n.global.t('monitor.serverTestFailed')
    } catch (error) { errorMsg.value = detail(error) }
    finally { testingMcpServerId.value = null }
  }
  const deleteMcpServer = async (server: McpServerConfig) => {
    if (deletingMcpServerId.value || !confirm(i18n.global.t('monitor.deleteServerConfirm', { name: server.display_name || server.server_key }))) return
    clearMessages(); deletingMcpServerId.value = server.id
    try {
      const result = await api.deleteMcpServer(server.id)
      mcpServers.value = removeMcpServer(mcpServers.value, server.id)
      if (mcpForm.value.id === server.id) resetMcpForm()
      successMsg.value = result.message || i18n.global.t('monitor.serverDeleted')
    } catch (error) { errorMsg.value = detail(error) }
    finally { deletingMcpServerId.value = null }
  }
  const delayedRefresh = (secondDelay: number) => { schedule(fetchTasks, 1000); schedule(fetchTasks, secondDelay) }
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
  const cancelEnrichment = async () => {
    if (cancellingEnrichment.value) return
    // 本地轮询中或服务端标记 running 时才有可终止的批次；其余情况视为无操作
    if (!enrichmentPolling.value && !enrichmentStatus.value?.running) return
    clearMessages()
    cancellingEnrichment.value = true
    try {
      const result = await api.cancelGithubEnrichment()
      // 终止信号已发出：停掉本地轮询；进行中的条目仍会跑完，
      // 稍候补拉一次状态让面板反映本批部分进度
      stopEnrichmentPolling(result.message || i18n.global.t('monitor.enrichment.cancelRequested'))
      schedule(() => { void fetchGithubEnrichmentStatus() }, ENRICHMENT_POLL_INTERVAL)
    } catch (error) { errorMsg.value = detail(error) }
    finally { cancellingEnrichment.value = false }
  }
  const ingestSingleSource = async (source: SourceKey) => {
    if (ingestingSource.value) return
    clearMessages(); ingestingSource.value = source
    try { const result = await api.ingestSource(source); successMsg.value = result.message || i18n.global.t('monitor.sourceSubmitted', { source }); delayedRefresh(4000) }
    catch (error) { const status = statusOf(error); errorMsg.value = status === 409 ? i18n.global.t('monitor.taskConflict') : status === 400 ? detail(error) || i18n.global.t('monitor.unknownSource') : detail(error) }
    finally { ingestingSource.value = null }
  }
  const generateAllBriefings = async (forceRegenerate = true) => {
    if (generatingBriefing.value) return
    clearMessages(); generatingBriefing.value = true
    try { const result = await api.generateAllBriefings(forceRegenerate); successMsg.value = result.message || i18n.global.t('monitor.briefingSubmitted') }
    catch (error) { errorMsg.value = detail(error) }
    finally { generatingBriefing.value = false }
  }
  const clearDashboardCache = async () => {
    if (clearingCache.value) return
    clearMessages(); clearingCache.value = true
    try { const result = await api.clearDashboardCache(); successMsg.value = result.message || i18n.global.t('monitor.cacheCleared') }
    catch (error) { errorMsg.value = detail(error) }
    finally { clearingCache.value = false }
  }
  const syncDataNow = async (force = false) => {
    if (syncing.value || isTaskRunning.value) return
    clearMessages(); syncing.value = true
    try { await api.syncData(force); successMsg.value = force ? i18n.global.t('monitor.forceSubmitted') : i18n.global.t('monitor.smartSubmitted'); delayedRefresh(3000) }
    catch (error) { errorMsg.value = statusOf(error) === 409 ? i18n.global.t('monitor.taskConflict') : detail(error) }
    finally { syncing.value = false }
  }
  const ingestByDate = async () => {
    if (ingestingByDate.value) return
    if (!targetDate.value) { errorMsg.value = i18n.global.t('monitor.chooseDate'); return }
    clearMessages(); ingestingByDate.value = true
    try { const result = await api.ingestByDate(targetDate.value); successMsg.value = result.message || i18n.global.t('monitor.dateSubmitted', { date: targetDate.value }); delayedRefresh(4000) }
    catch (error) { const status = statusOf(error); errorMsg.value = status === 409 ? i18n.global.t('monitor.taskConflict') : status === 400 ? detail(error) || i18n.global.t('monitor.invalidDate') : detail(error) }
    finally { ingestingByDate.value = false }
  }
  const clearAllData = async () => {
    showClearConfirm.value = false; clearMessages(); clearing.value = true
    try { const result = await api.clearAllData(); successMsg.value = result.message || i18n.global.t('monitor.dataCleared'); await refreshData() }
    catch (error) { errorMsg.value = detail(error) }
    finally { clearing.value = false }
  }

  // 刷新页面时 main.ts 异步恢复登录态，onMounted 触发 refreshData 时 isAdmin 仍为 false，
  // admin 接口会被静默跳过；待恢复出管理员身份后补拉一次，避免配置面板空数据。
  watch(isAdmin, (admin, wasAdmin) => {
    if (!admin || wasAdmin) return
    void Promise.all([fetchSchedulerConfigs(), fetchProviderConfig(), fetchMcpServers(), fetchGithubEnrichmentStatus(), fetchGithubEnrichmentConfig(), resumeGithubCrawlPolling()])
  })

  return {
    tasks, total, page, pageSize, schedulerStatus, schedulerConfigs, schedulerConfigForm, loadingSchedulerConfigs, savingSchedulerConfig, editingSchedulerJobId, mcpToolCalls, loading, errorMsg, successMsg, providerConfig, providerForm,
    loadingProviderConfig, savingProviderConfig, testingProvider, mcpServers, mcpForm, loadingMcpServers, savingMcpServer,
    testingMcpServerId, deletingMcpServerId, isTaskRunning, totalPages, syncing, generatingBriefing, clearingCache,
    targetDate, maxTargetDate, ingestingByDate, ingestingSource, clearing, showClearConfirm, clearMessages, fetchTasks,
    fetchSchedulerStatus, fetchSchedulerConfigs, fetchMcpToolCalls, fetchProviderConfig, fetchMcpServers, refreshData, goPage, saveProviderConfig, testProviderConnection,
    editSchedulerConfig, cancelSchedulerConfigEdit, saveSchedulerConfig,
    resetMcpForm, editMcpServer, saveMcpServer, testMcpServer, deleteMcpServer, ingestSingleSource, generateAllBriefings,
    clearDashboardCache, syncDataNow, ingestByDate, clearAllData,
    crawlForm, crawling, crawlPolling, crawlStatus, startGithubCrawl,
    enrichmentStatus, loadingEnrichmentStatus, retryingEnrichment, backfillingEnrichment, cancellingEnrichment, enrichmentConcurrency, enrichmentPolling,
    enrichmentReasoningEffort, enrichmentEffectiveReasoningEffort, savingEnrichmentReasoningEffort,
    fetchGithubEnrichmentStatus, fetchGithubEnrichmentConfig, saveEnrichmentReasoningEffort, retryFailedEnrichments, backfillPendingEnrichments, cancelEnrichment,
  }
}
