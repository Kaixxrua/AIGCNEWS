import { computed, ref, watch, type ComputedRef } from 'vue'
import { monitorApi, type MonitorApi } from '@/services/monitor/monitorApi'
import { i18n } from '@/i18n'
import {
  createEmptyMcpForm, createGithubCrawlForm, createMcpForm, createProviderForm, createSiteContactPageForm, createSmtpForm, removeMcpServer, replaceMcpServer, upsertMcpServer,
  createEmptySchedulerJobConfigForm, normalizeEnrichmentConcurrency, normalizeReasoningEffort,
  type McpServerConfig, type McpToolCallMetricsSnapshot, type SchedulerJobConfig, type SchedulerJobConfigForm, type SourceKey,
} from '@/features/monitor/monitorModel'
import { useGithubCrawlPolling } from './useGithubCrawlPolling'
import { ENRICHMENT_POLL_INTERVAL, useEnrichmentPolling } from './useEnrichmentPolling'
import { refreshContactPageConfig } from './useContactPageConfig'

interface MonitorPageControllerOptions {
  isAdmin: ComputedRef<boolean>
  api?: MonitorApi
  schedule?: (callback: () => void, delay: number) => ReturnType<typeof setTimeout>
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
  // 错误日志面板：独立分页状态，与任务历史互不干扰
  const errorLogs = ref<Awaited<ReturnType<MonitorApi['fetchErrorLogs']>>['items']>([])
  const errorLogsTotal = ref(0)
  const errorLogsPage = ref(1)
  const errorLogsPageSize = ref(10)
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
  const smtpConfig = ref<Awaited<ReturnType<MonitorApi['fetchSmtpConfig']>> | null>(null)
  const smtpForm = ref(createSmtpForm())
  const loadingSmtpConfig = ref(false)
  const savingSmtpConfig = ref(false)
  const testingSmtp = ref(false)
  const siteContactPageConfig = ref<Awaited<ReturnType<MonitorApi['fetchSiteContactPageConfig']>> | null>(null)
  const siteContactPageForm = ref(createSiteContactPageForm())
  const loadingSiteContactPage = ref(false)
  const savingSiteContactPage = ref(false)
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
  // 终止观望期：取消信号发出后轮询到服务端 running 清零才解锁按钮，
  // 否则服务端稍后的 running→false 翻转永远到不了面板，按钮一直可点
  const enrichmentCancelWatching = ref(false)
  const enrichmentConcurrency = ref(3)
  // 富化专用推理强度：空串=跟随模型服务配置；effective 为后端解析的当前生效档位
  const enrichmentReasoningEffort = ref('')
  const enrichmentEffectiveReasoningEffort = ref('')
  const savingEnrichmentReasoningEffort = ref(false)
  const isTaskRunning = computed(() => tasks.value.length > 0 && tasks.value[0]?.status === 'running')
  const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
  const errorLogsTotalPages = computed(() => Math.max(1, Math.ceil(errorLogsTotal.value / errorLogsPageSize.value)))
  const clearMessages = () => { errorMsg.value = ''; successMsg.value = '' }

  const fetchTasks = async () => {
    try {
      const data = await api.fetchTasks(page.value, pageSize.value)
      tasks.value = data.items
      total.value = data.total
    } catch (error) { console.error('Failed to fetch tasks', error) }
  }
  const fetchErrorLogs = async () => {
    // 错误事件含堆栈与 logger 名，仅管理员口径（与后端 RequireAdmin 对齐）
    if (!isAdmin.value) return
    try {
      const data = await api.fetchErrorLogs(errorLogsPage.value, errorLogsPageSize.value)
      errorLogs.value = data.items
      errorLogsTotal.value = data.total
    } catch (error) { console.error('Failed to fetch error logs', error) }
  }
  const setSuccessMessage = (message: string) => { successMsg.value = message }
  const setErrorMessage = (message: string) => { errorMsg.value = message }
  const { crawlPolling, crawlStatus, beginCrawlPolling, resumeGithubCrawlPolling, disposeCrawlPolling } = useGithubCrawlPolling({
    api, isAdmin, schedule,
    setSuccess: setSuccessMessage,
    setError: setErrorMessage,
    refreshTasks: fetchTasks,
  })
  const { enrichmentStatus, enrichmentPolling, beginEnrichmentPolling, stopEnrichmentPolling, disposeEnrichmentPolling } = useEnrichmentPolling({
    api, schedule, setSuccess: setSuccessMessage,
  })
  // 所有一次性延时回调统一登记句柄，卸载时集中清理（对齐 useWechatController dispose 范式）
  const pendingTimers = new Set<ReturnType<typeof setTimeout>>()
  const scheduleTracked = (callback: () => void, delay: number) => {
    const timer = schedule(() => {
      pendingTimers.delete(timer)
      callback()
    }, delay)
    pendingTimers.add(timer)
    return timer
  }
  const dispose = () => {
    for (const timer of pendingTimers) clearTimeout(timer)
    pendingTimers.clear()
    // 终止观望标志复位：watch 链被清定时器截断后，组件重挂不应残留锁定态
    enrichmentCancelWatching.value = false
    disposeCrawlPolling()
    disposeEnrichmentPolling()
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
  const fetchSmtpConfig = async () => {
    if (!isAdmin.value) return
    loadingSmtpConfig.value = true
    try {
      smtpConfig.value = await api.fetchSmtpConfig()
      smtpForm.value = createSmtpForm(smtpConfig.value)
    } catch (error) { console.error('Failed to fetch SMTP config', error) }
    finally { loadingSmtpConfig.value = false }
  }
  const fetchSiteContactPageConfig = async () => {
    if (!isAdmin.value) return
    loadingSiteContactPage.value = true
    try {
      siteContactPageConfig.value = await api.fetchSiteContactPageConfig()
      siteContactPageForm.value = createSiteContactPageForm(siteContactPageConfig.value)
    } catch (error) { console.error('Failed to fetch site contact page config', error) }
    finally { loadingSiteContactPage.value = false }
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
    await Promise.all([fetchTasks(), fetchErrorLogs(), fetchSchedulerStatus(), fetchSchedulerConfigs(), fetchMcpToolCalls(), fetchProviderConfig(), fetchSmtpConfig(), fetchSiteContactPageConfig(), fetchMcpServers(), fetchGithubEnrichmentStatus(), fetchGithubEnrichmentConfig(), resumeGithubCrawlPolling()])
    loading.value = false
  }
  const goPage = async (nextPage: number) => {
    if (nextPage < 1 || nextPage > totalPages.value) return
    page.value = nextPage
    await fetchTasks()
  }
  const goErrorLogsPage = async (nextPage: number) => {
    if (nextPage < 1 || nextPage > errorLogsTotalPages.value) return
    errorLogsPage.value = nextPage
    await fetchErrorLogs()
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
  const SMTP_PORT_MIN = 1
  const SMTP_PORT_MAX = 65535
  const SMTP_FROM_EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/
  const saveSmtpConfig = async () => {
    if (savingSmtpConfig.value) return
    clearMessages()
    const form = smtpForm.value
    const host = form.host.trim()
    // 端口与发件邮箱先做无害前端校验；host 留空为文档化语义（删除 DB
    // 覆盖行回退 env），不视为校验失败
    if (host && (!Number.isInteger(form.port) || form.port < SMTP_PORT_MIN || form.port > SMTP_PORT_MAX)) {
      errorMsg.value = i18n.global.t('monitor.smtpConfig.invalidPort')
      return
    }
    if (host && !SMTP_FROM_EMAIL_PATTERN.test(form.from_email.trim())) {
      errorMsg.value = i18n.global.t('monitor.smtpConfig.invalidFromEmail')
      return
    }
    savingSmtpConfig.value = true
    try {
      smtpConfig.value = await api.saveSmtpConfig({ ...form, host, from_email: form.from_email.trim() })
      smtpForm.value.password = ''; smtpForm.value.clear_password = false
      successMsg.value = i18n.global.t('monitor.smtpConfig.saved')
    } catch (error) { errorMsg.value = detail(error) }
    finally { savingSmtpConfig.value = false }
  }
  const testSmtpConfig = async () => {
    if (testingSmtp.value) return
    clearMessages(); testingSmtp.value = true
    try {
      // 测试按最新生效配置投递（收件人缺省为当前管理员登录邮箱）；
      // 表单里未保存的修改不生效，先保存再测试
      const result = await api.testSmtpConfig()
      if (String(result.status || '').toLowerCase() === 'success') successMsg.value = result.message || i18n.global.t('monitor.smtpConfig.testSent')
      else errorMsg.value = result.message || i18n.global.t('monitor.smtpConfig.testFailed')
    } catch (error) { errorMsg.value = detail(error) }
    finally { testingSmtp.value = false }
  }
  // 与后端 schema_site.py 同规则的前端校验：提前拦截可避免 422/400 往返
  const SITE_CONTACT_HREF_PATTERN = /^(https?:\/\/|mailto:|tel:)/i
  const SITE_CONTACT_QR_PATTERN = /^(https?:\/\/|\/)/i
  const saveSiteContactPageConfig = async () => {
    if (savingSiteContactPage.value) return
    clearMessages()
    const form = siteContactPageForm.value
    if (form.enabled && !form.title.trim()) {
      errorMsg.value = i18n.global.t('monitor.contactPageConfig.titleRequiredWhenEnabled')
      return
    }
    if (form.service_cards.some((card) => !card.title.trim())) {
      errorMsg.value = i18n.global.t('monitor.contactPageConfig.cardTitleRequired')
      return
    }
    if (form.contact_entries.some((entry) => !entry.label.trim())) {
      errorMsg.value = i18n.global.t('monitor.contactPageConfig.entryLabelRequired')
      return
    }
    if (form.contact_entries.some((entry) => entry.href.trim() && !SITE_CONTACT_HREF_PATTERN.test(entry.href.trim()))) {
      errorMsg.value = i18n.global.t('monitor.contactPageConfig.invalidHref')
      return
    }
    if (form.contact_entries.some((entry) => entry.qr_image_url.trim() && !SITE_CONTACT_QR_PATTERN.test(entry.qr_image_url.trim()))) {
      errorMsg.value = i18n.global.t('monitor.contactPageConfig.invalidQrUrl')
      return
    }
    savingSiteContactPage.value = true
    try {
      siteContactPageConfig.value = await api.saveSiteContactPageConfig(form)
      siteContactPageForm.value = createSiteContactPageForm(siteContactPageConfig.value)
      successMsg.value = i18n.global.t('monitor.contactPageConfig.saved')
      // 导航入口显隐/文案读取的是公开端点的进程内缓存，保存后立即重取让 Dock 当会话更新
      void refreshContactPageConfig()
    } catch (error) { errorMsg.value = detail(error) }
    finally { savingSiteContactPage.value = false }
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
  const delayedRefresh = (secondDelay: number) => { scheduleTracked(fetchTasks, 1000); scheduleTracked(fetchTasks, secondDelay) }
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
    // 终止观望期禁止开新批次：新批次的 running=true 会被观望链误读为旧批次未停
    if (retryingEnrichment.value || backfillingEnrichment.value || enrichmentPolling.value || enrichmentCancelWatching.value) return
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
    // 终止观望期禁止开新批次：新批次的 running=true 会被观望链误读为旧批次未停
    if (backfillingEnrichment.value || retryingEnrichment.value || enrichmentPolling.value || enrichmentCancelWatching.value) return
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
  // 终止观望轮询上限：4s × 15 ≈ 60s，覆盖在途条目收尾的超时窗口
  const ENRICHMENT_CANCEL_WATCH_MAX_POLLS = 15
  const watchEnrichmentCancel = async (attempt: number) => {
    if (!enrichmentCancelWatching.value) return
    try { enrichmentStatus.value = await api.fetchGithubEnrichmentStatus() }
    catch (error) { console.error('Failed to watch GitHub enrichment cancel', error) }
    // 在途期间观望已被重置（卸载/离页兜底）：丢弃本次结果
    if (!enrichmentCancelWatching.value) return
    if (!enrichmentStatus.value?.running) {
      enrichmentCancelWatching.value = false
      successMsg.value = i18n.global.t('monitor.enrichment.cancelConfirmed')
      return
    }
    if (attempt >= ENRICHMENT_CANCEL_WATCH_MAX_POLLS) {
      enrichmentCancelWatching.value = false
      successMsg.value = i18n.global.t('monitor.enrichment.cancelWatchTimeout')
      return
    }
    scheduleTracked(() => { void watchEnrichmentCancel(attempt + 1) }, ENRICHMENT_POLL_INTERVAL)
  }
  // 状态自愈：running→false 可能经任意通道送达（观望链/手动刷新/整页刷新/常规轮询），
  // 观望标志不能只靠观望链清除——链被浏览器后台节流或打断时，按钮不应残留「终止中」
  watch(() => enrichmentStatus.value?.running, (running, wasRunning) => {
    if (running || !wasRunning || !enrichmentCancelWatching.value) return
    enrichmentCancelWatching.value = false
    successMsg.value = i18n.global.t('monitor.enrichment.cancelConfirmed')
  })
  const cancelEnrichment = async () => {
    if (cancellingEnrichment.value || enrichmentCancelWatching.value) return
    // 本地轮询中或服务端标记 running 时才有可终止的批次；其余情况视为无操作
    if (!enrichmentPolling.value && !enrichmentStatus.value?.running) return
    clearMessages()
    cancellingEnrichment.value = true
    try {
      const result = await api.cancelGithubEnrichment()
      // 终止信号已发出：停掉本地进度轮询；批次已先于点击结束时无需观望，
      // 直接补拉一次状态让面板立刻反映，避免空闪「终止中」与误报已终止
      stopEnrichmentPolling(result.message || i18n.global.t('monitor.enrichment.cancelRequested'))
      if (result.status === 'not_running') {
        try { enrichmentStatus.value = await api.fetchGithubEnrichmentStatus() }
        catch (error) { console.error('Failed to refresh GitHub enrichment status after idle cancel', error) }
        return
      }
      // 转入终止观望轮询：服务端 running 清零前按钮保持锁定，批次真正结束才解锁刷新
      enrichmentCancelWatching.value = true
      scheduleTracked(() => { void watchEnrichmentCancel(1) }, ENRICHMENT_POLL_INTERVAL)
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
    void Promise.all([fetchSchedulerConfigs(), fetchProviderConfig(), fetchSmtpConfig(), fetchSiteContactPageConfig(), fetchMcpServers(), fetchGithubEnrichmentStatus(), fetchGithubEnrichmentConfig(), fetchErrorLogs(), resumeGithubCrawlPolling()])
  })

  return {
    tasks, total, page, pageSize, errorLogs, errorLogsTotal, errorLogsPage, errorLogsPageSize, errorLogsTotalPages, schedulerStatus, schedulerConfigs, schedulerConfigForm, loadingSchedulerConfigs, savingSchedulerConfig, editingSchedulerJobId, mcpToolCalls, loading, errorMsg, successMsg, providerConfig, providerForm,
    loadingProviderConfig, savingProviderConfig, testingProvider, smtpConfig, smtpForm, loadingSmtpConfig, savingSmtpConfig, testingSmtp, mcpServers, mcpForm, loadingMcpServers, savingMcpServer,
    siteContactPageConfig, siteContactPageForm, loadingSiteContactPage, savingSiteContactPage,
    testingMcpServerId, deletingMcpServerId, isTaskRunning, totalPages, syncing, generatingBriefing, clearingCache,
    targetDate, maxTargetDate, ingestingByDate, ingestingSource, clearing, showClearConfirm, clearMessages, fetchTasks,
    fetchErrorLogs, goErrorLogsPage,
    fetchSchedulerStatus, fetchSchedulerConfigs, fetchMcpToolCalls, fetchProviderConfig, fetchSmtpConfig, fetchMcpServers, refreshData, goPage, saveProviderConfig, testProviderConnection, saveSmtpConfig, testSmtpConfig,
    fetchSiteContactPageConfig, saveSiteContactPageConfig,
    editSchedulerConfig, cancelSchedulerConfigEdit, saveSchedulerConfig,
    resetMcpForm, editMcpServer, saveMcpServer, testMcpServer, deleteMcpServer, ingestSingleSource, generateAllBriefings,
    clearDashboardCache, syncDataNow, ingestByDate, clearAllData,
    crawlForm, crawling, crawlPolling, crawlStatus, startGithubCrawl,
    enrichmentStatus, loadingEnrichmentStatus, retryingEnrichment, backfillingEnrichment, cancellingEnrichment, enrichmentConcurrency, enrichmentPolling,
    enrichmentCancelWatching,
    enrichmentReasoningEffort, enrichmentEffectiveReasoningEffort, savingEnrichmentReasoningEffort,
    fetchGithubEnrichmentStatus, fetchGithubEnrichmentConfig, saveEnrichmentReasoningEffort, retryFailedEnrichments, backfillPendingEnrichments, cancelEnrichment,
    dispose,
  }
}
