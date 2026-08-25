import { computed, ref, watch, type ComputedRef } from 'vue'
import { monitorApi, type MonitorApi } from '@/services/monitor/monitorApi'
import { i18n } from '@/i18n'
import {
  createEmailPoolForm, createEmptyMcpForm, createGithubCrawlForm, createMcpForm, createMembershipGrantForm, createOAuthConfigForm, createPaymentConfigForm, createPaymentPlanPricingForm, createProviderForm, createSiteContactPageForm, createSmtpForm, membershipExpiryToFormDate, removeMcpServer, replaceMcpServer, upsertMcpServer,
  buildPaymentPlanPricingPayload,
  createEmptySchedulerJobConfigForm, normalizeEnrichmentConcurrency, normalizeReasoningEffort,
  type McpServerConfig, type McpToolCallMetricsSnapshot, type MembershipGrantResult, type MembershipUserItem, type PaymentPlanPricing, type SchedulerJobConfig, type SchedulerJobConfigForm, type SourceKey, type EmailDeliveryDayStat,
} from '@/features/monitor/monitorModel'
import { useGithubCrawlPolling } from './useGithubCrawlPolling'
import { ENRICHMENT_POLL_INTERVAL, useEnrichmentPolling } from './useEnrichmentPolling'
import { refreshContactPageConfig } from './useContactPageConfig'
import { refreshFeatureFlags } from './useFeatureFlags'

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
  const emailPoolConfig = ref<Awaited<ReturnType<MonitorApi['fetchEmailPoolConfig']>> | null>(null)
  const emailPoolForm = ref(createEmailPoolForm())
  const loadingEmailPoolConfig = ref(false)
  const savingEmailPoolConfig = ref(false)
  const testingEmailPool = ref(false)
  const emailDeliveryStats = ref<EmailDeliveryDayStat[]>([])
  const loadingEmailDeliveryStats = ref(false)
  const siteContactPageConfig = ref<Awaited<ReturnType<MonitorApi['fetchSiteContactPageConfig']>> | null>(null)
  const siteContactPageForm = ref(createSiteContactPageForm())
  const loadingSiteContactPage = ref(false)
  const savingSiteContactPage = ref(false)
  // 用户组（会员档位）授予：表单 + 最近一次操作结果 + 全量用户列表（搜索/分页）
  const membershipForm = ref(createMembershipGrantForm())
  const grantingMembership = ref(false)
  const membershipLastResult = ref<MembershipGrantResult | null>(null)
  const membershipUsers = ref<MembershipUserItem[]>([])
  const membershipUsersTotal = ref(0)
  const membershipUsersPage = ref(1)
  const membershipUsersPageSize = ref(20)
  const membershipUsersQuery = ref('')
  const loadingMembershipUsers = ref(false)
  const membershipUsersTotalPages = computed(() => Math.max(1, Math.ceil(membershipUsersTotal.value / membershipUsersPageSize.value)))
  const paymentOrders = ref<Awaited<ReturnType<MonitorApi['fetchPaymentOrders']>>['items']>([])
  const paymentOrdersTotal = ref(0)
  const paymentOrdersPage = ref(1)
  const paymentOrdersPageSize = ref(20)
  const paymentOrdersFilter = ref({ status: '', channel: '', planCode: '', email: '' })
  const loadingPaymentOrders = ref(false)
  const paymentOrderDetail = ref<Awaited<ReturnType<MonitorApi['fetchPaymentOrderDetail']>> | null>(null)
  const loadingPaymentOrderDetail = ref(false)
  const paymentOrdersTotalPages = computed(() => Math.max(1, Math.ceil(paymentOrdersTotal.value / paymentOrdersPageSize.value)))
  // 支付渠道配置（ADR 0002）：DB 覆盖行优先 env，密文只写入不回填
  const paymentConfig = ref<Awaited<ReturnType<MonitorApi['fetchPaymentConfig']>> | null>(null)
  const paymentForm = ref(createPaymentConfigForm())
  const loadingPaymentConfig = ref(false)
  const savingPaymentConfig = ref(false)
  const resettingPaymentConfig = ref(false)
  // OAuth 快捷登录配置：与支付同语义；保存/重置后刷新 feature flags 让登录按钮即时显隐
  const oauthConfig = ref<Awaited<ReturnType<MonitorApi['fetchOAuthConfig']>> | null>(null)
  const oauthForm = ref(createOAuthConfigForm())
  const loadingOAuthConfig = ref(false)
  const savingOAuthConfig = ref(false)
  const resettingOAuthConfig = ref(false)
  // 套餐定价（运行时调价）：plans.py 默认价 + payment_plan_overrides 覆盖行
  const paymentPricing = ref<PaymentPlanPricing[]>([])
  const paymentPricingForm = ref(createPaymentPlanPricingForm())
  const loadingPaymentPricing = ref(false)
  const savingPaymentPricing = ref(false)
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
  const xTranslationStatus = ref<Awaited<ReturnType<MonitorApi['fetchXTranslationStatus']>> | null>(null)
  const loadingXTranslation = ref(false)
  const retryingXTranslation = ref(false)
  const xTranslationPolling = ref(false)
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
  const fetchPaymentOrders = async () => {
    if (!isAdmin.value) return
    loadingPaymentOrders.value = true
    try {
      const data = await api.fetchPaymentOrders({ ...paymentOrdersFilter.value, page: paymentOrdersPage.value, pageSize: paymentOrdersPageSize.value })
      paymentOrders.value = data.items
      paymentOrdersTotal.value = data.total
    } catch (error) { console.error('Failed to fetch payment orders', error) }
    finally { loadingPaymentOrders.value = false }
  }
  const fetchPaymentOrderDetail = async (orderNo: string) => {
    loadingPaymentOrderDetail.value = true
    try { paymentOrderDetail.value = await api.fetchPaymentOrderDetail(orderNo) }
    catch (error) { console.error('Failed to fetch payment order detail', error) }
    finally { loadingPaymentOrderDetail.value = false }
  }
  const clearPaymentOrderDetail = () => { paymentOrderDetail.value = null }
  const goPaymentOrdersPage = async (targetPage: number) => {
    if (targetPage < 1 || targetPage > paymentOrdersTotalPages.value) return
    paymentOrdersPage.value = targetPage
    await fetchPaymentOrders()
  }
  const markPaymentOrderPaid = async (orderNo: string) => { await api.markPaymentOrderPaid(orderNo); await fetchPaymentOrders() }
  const closePaymentOrder = async (orderNo: string) => { await api.closePaymentOrder(orderNo); await fetchPaymentOrders() }
  const fetchPaymentConfig = async () => {
    if (!isAdmin.value) return
    loadingPaymentConfig.value = true
    try {
      paymentConfig.value = await api.fetchPaymentConfig()
      paymentForm.value = createPaymentConfigForm(paymentConfig.value)
    } catch (error) { console.error('Failed to fetch payment config', error) }
    finally { loadingPaymentConfig.value = false }
  }
  const PAYMENT_TTL_MIN = 5
  const PAYMENT_TTL_MAX = 1440
  const PAYMENT_BASE_URL_PATTERN = /^https?:\/\/\S+$/i
  // 保存成功后归零密文输入态：密文永不回填，下一次保存按留空=保留语义
  const resetPaymentSecretInputs = () => {
    const form = paymentForm.value
    form.wechat_api_v3_key = ''; form.wechat_private_key_pem = ''; form.wechat_public_key_pem = ''
    form.alipay_private_key_pem = ''; form.alipay_public_key_pem = ''
    form.overseas_client_secret = ''; form.overseas_webhook_secret = ''
    form.clear_wechat_api_v3_key = false; form.clear_wechat_private_key_pem = false
    form.clear_wechat_public_key_pem = false
    form.clear_alipay_private_key_pem = false; form.clear_alipay_public_key_pem = false
    form.clear_overseas_client_secret = false; form.clear_overseas_webhook_secret = false
  }
  const savePaymentConfig = async () => {
    if (savingPaymentConfig.value) return
    clearMessages()
    const form = paymentForm.value
    // 与后端同口径的无害前端校验，提前拦截 400 往返
    if (!Number.isInteger(form.order_ttl_minutes) || form.order_ttl_minutes < PAYMENT_TTL_MIN || form.order_ttl_minutes > PAYMENT_TTL_MAX) {
      errorMsg.value = i18n.global.t('monitor.paymentConfig.invalidTtl')
      return
    }
    const baseUrl = form.public_base_url.trim()
    if (baseUrl && !PAYMENT_BASE_URL_PATTERN.test(baseUrl)) {
      errorMsg.value = i18n.global.t('monitor.paymentConfig.invalidBaseUrl')
      return
    }
    savingPaymentConfig.value = true
    try {
      paymentConfig.value = await api.savePaymentConfig({ ...form, public_base_url: baseUrl })
      resetPaymentSecretInputs()
      successMsg.value = i18n.global.t('monitor.paymentConfig.saved')
    } catch (error) { errorMsg.value = detail(error) }
    finally { savingPaymentConfig.value = false }
  }
  const resetPaymentConfig = async () => {
    if (resettingPaymentConfig.value || !confirm(i18n.global.t('monitor.paymentConfig.resetConfirm'))) return
    clearMessages(); resettingPaymentConfig.value = true
    try {
      paymentConfig.value = await api.resetPaymentConfig()
      paymentForm.value = createPaymentConfigForm(paymentConfig.value)
      successMsg.value = i18n.global.t('monitor.paymentConfig.resetDone')
    } catch (error) { errorMsg.value = detail(error) }
    finally { resettingPaymentConfig.value = false }
  }
  const fetchPaymentPlanPricing = async () => {
    if (!isAdmin.value) return
    loadingPaymentPricing.value = true
    try {
      const response = await api.fetchPaymentPlanPricing()
      paymentPricing.value = response.plans
      paymentPricingForm.value = createPaymentPlanPricingForm(response.plans)
    } catch (error) { console.error('Failed to fetch payment plan pricing', error) }
    finally { loadingPaymentPricing.value = false }
  }
  const savePaymentPlanPricing = async () => {
    if (savingPaymentPricing.value) return
    clearMessages()
    // 与后端同口径的前端校验（元、≤2 位小数、1–10000）：非法提前拦截 400 往返
    if (buildPaymentPlanPricingPayload(paymentPricingForm.value) === null) {
      errorMsg.value = i18n.global.t('monitor.paymentPricing.invalidAmount')
      return
    }
    savingPaymentPricing.value = true
    try {
      const response = await api.savePaymentPlanPricing(paymentPricingForm.value)
      paymentPricing.value = response.plans
      paymentPricingForm.value = createPaymentPlanPricingForm(response.plans)
      successMsg.value = i18n.global.t('monitor.paymentPricing.saved')
    } catch (error) { errorMsg.value = detail(error) }
    finally { savingPaymentPricing.value = false }
  }
  const fetchOAuthConfig = async () => {
    if (!isAdmin.value) return
    loadingOAuthConfig.value = true
    try {
      oauthConfig.value = await api.fetchOAuthConfig()
      oauthForm.value = createOAuthConfigForm(oauthConfig.value)
    } catch (error) { console.error('Failed to fetch OAuth config', error) }
    finally { loadingOAuthConfig.value = false }
  }
  const OAUTH_STATE_TTL_MIN = 60
  const OAUTH_STATE_TTL_MAX = 900
  const OAUTH_HANDOFF_TTL_MIN = 30
  const OAUTH_HANDOFF_TTL_MAX = 600
  const OAUTH_BASE_URL_PATTERN = /^https?:\/\/\S+$/i
  // 保存成功后归零密文输入态：密文永不回填，下一次保存按留空=保留语义
  const resetOAuthSecretInputs = () => {
    const form = oauthForm.value
    form.github_client_secret = ''; form.google_client_secret = ''; form.wechat_app_secret = ''
    form.clear_github_client_secret = false; form.clear_google_client_secret = false
    form.clear_wechat_app_secret = false
  }
  const saveOAuthConfig = async () => {
    if (savingOAuthConfig.value) return
    clearMessages()
    const form = oauthForm.value
    // 与后端同口径的无害前端校验，提前拦截 400 往返
    if (!Number.isInteger(form.state_ttl_seconds) || form.state_ttl_seconds < OAUTH_STATE_TTL_MIN || form.state_ttl_seconds > OAUTH_STATE_TTL_MAX) {
      errorMsg.value = i18n.global.t('monitor.oauthConfig.invalidStateTtl')
      return
    }
    if (!Number.isInteger(form.handoff_ttl_seconds) || form.handoff_ttl_seconds < OAUTH_HANDOFF_TTL_MIN || form.handoff_ttl_seconds > OAUTH_HANDOFF_TTL_MAX) {
      errorMsg.value = i18n.global.t('monitor.oauthConfig.invalidHandoffTtl')
      return
    }
    const baseUrl = form.public_base_url.trim()
    if (baseUrl && !OAUTH_BASE_URL_PATTERN.test(baseUrl)) {
      errorMsg.value = i18n.global.t('monitor.oauthConfig.invalidBaseUrl')
      return
    }
    savingOAuthConfig.value = true
    try {
      oauthConfig.value = await api.saveOAuthConfig({ ...form, public_base_url: baseUrl })
      resetOAuthSecretInputs()
      successMsg.value = i18n.global.t('monitor.oauthConfig.saved')
      await refreshFeatureFlags()
    } catch (error) { errorMsg.value = detail(error) }
    finally { savingOAuthConfig.value = false }
  }
  const resetOAuthConfig = async () => {
    if (resettingOAuthConfig.value || !confirm(i18n.global.t('monitor.oauthConfig.resetConfirm'))) return
    clearMessages(); resettingOAuthConfig.value = true
    try {
      oauthConfig.value = await api.resetOAuthConfig()
      oauthForm.value = createOAuthConfigForm(oauthConfig.value)
      successMsg.value = i18n.global.t('monitor.oauthConfig.resetDone')
      await refreshFeatureFlags()
    } catch (error) { errorMsg.value = detail(error) }
    finally { resettingOAuthConfig.value = false }
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
    xTranslationPolling.value = false
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
  const fetchEmailPoolConfig = async () => {
    if (!isAdmin.value) return
    loadingEmailPoolConfig.value = true
    try {
      emailPoolConfig.value = await api.fetchEmailPoolConfig()
      emailPoolForm.value = createEmailPoolForm(emailPoolConfig.value)
    } catch (error) { console.error('Failed to fetch email pool config', error) }
    finally { loadingEmailPoolConfig.value = false }
  }
  const fetchEmailDeliveryStats = async () => {
    if (!isAdmin.value) return
    loadingEmailDeliveryStats.value = true
    try {
      const result = await api.fetchEmailDeliveryStats()
      emailDeliveryStats.value = Array.isArray(result?.days) ? result.days : []
    } catch (error) { console.error('Failed to fetch email delivery stats', error) }
    finally { loadingEmailDeliveryStats.value = false }
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
  const X_TRANSLATION_POLL_INTERVAL = 4000
  const X_TRANSLATION_MAX_POLLS = 150
  const pollXTranslationStatus = async (attempt: number) => {
    if (!xTranslationPolling.value) return
    try { xTranslationStatus.value = await api.fetchXTranslationStatus() }
    catch (error) { console.error('Failed to poll X translation status', error) }
    if (!xTranslationPolling.value) return
    const status = xTranslationStatus.value
    if ((!status?.batch_running && !status?.running) || attempt >= X_TRANSLATION_MAX_POLLS) {
      xTranslationPolling.value = false
      return
    }
    scheduleTracked(() => { void pollXTranslationStatus(attempt + 1) }, X_TRANSLATION_POLL_INTERVAL)
  }
  const beginXTranslationPolling = () => {
    if (xTranslationPolling.value) return
    xTranslationPolling.value = true
    scheduleTracked(() => { void pollXTranslationStatus(1) }, X_TRANSLATION_POLL_INTERVAL)
  }
  const fetchXTranslationStatus = async () => {
    if (!isAdmin.value) return
    loadingXTranslation.value = true
    try {
      xTranslationStatus.value = await api.fetchXTranslationStatus()
      if (xTranslationStatus.value.batch_running || xTranslationStatus.value.running) beginXTranslationPolling()
    } catch (error) { console.error('Failed to fetch X translation status', error) }
    finally { loadingXTranslation.value = false }
  }
  const retryXTranslations = async () => {
    if (retryingXTranslation.value || xTranslationPolling.value || !xTranslationStatus.value?.retryable) return
    clearMessages(); retryingXTranslation.value = true
    try {
      const result = await api.retryXTranslations(200, 3)
      successMsg.value = result.message || i18n.global.t('monitor.xTranslation.queued')
      if (result.status === 'queued') beginXTranslationPolling()
      else await fetchXTranslationStatus()
    } catch (error) { errorMsg.value = detail(error) }
    finally { retryingXTranslation.value = false }
  }
  const refreshData = async () => {
    loading.value = true
    await Promise.all([fetchTasks(), fetchErrorLogs(), fetchPaymentOrders(), fetchMembershipUsers(), fetchSchedulerStatus(), fetchSchedulerConfigs(), fetchMcpToolCalls(), fetchProviderConfig(), fetchSmtpConfig(), fetchEmailPoolConfig(), fetchEmailDeliveryStats(), fetchSiteContactPageConfig(), fetchMcpServers(), fetchGithubEnrichmentStatus(), fetchGithubEnrichmentConfig(), fetchXTranslationStatus(), fetchPaymentConfig(), fetchOAuthConfig(), fetchPaymentPlanPricing(), resumeGithubCrawlPolling()])
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
  const saveEmailPoolConfig = async () => {
    if (savingEmailPoolConfig.value) return
    clearMessages()
    const entries = emailPoolForm.value.entries
    const seenNames = new Set<string>()
    for (const entry of entries) {
      const name = entry.name.trim()
      const host = entry.host.trim()
      // 逐 entry 无害前端校验，与后端 _normalize_entry 同口径，提前拦截 400 往返
      if (!name || !host) {
        errorMsg.value = i18n.global.t('monitor.emailPoolConfig.invalidEntry')
        return
      }
      if (seenNames.has(name)) {
        errorMsg.value = i18n.global.t('monitor.emailPoolConfig.duplicateName', { name })
        return
      }
      seenNames.add(name)
      if (!Number.isInteger(entry.port) || entry.port < SMTP_PORT_MIN || entry.port > SMTP_PORT_MAX) {
        errorMsg.value = i18n.global.t('monitor.emailPoolConfig.invalidPort', { name })
        return
      }
      const fromEmail = entry.from_email.trim()
      if (fromEmail && !SMTP_FROM_EMAIL_PATTERN.test(fromEmail)) {
        errorMsg.value = i18n.global.t('monitor.emailPoolConfig.invalidFromEmail', { name })
        return
      }
    }
    // 空数组为文档化语义：删除 DB 覆盖行回退 env，不视为校验失败
    savingEmailPoolConfig.value = true
    try {
      emailPoolConfig.value = await api.saveEmailPoolConfig(emailPoolForm.value)
      // 用保存响应重建表单：行序与生效 priority 排序一致，且密码输入态归零
      // （下一次保存按 name 保留已存密码）
      emailPoolForm.value = createEmailPoolForm(emailPoolConfig.value)
      successMsg.value = i18n.global.t('monitor.emailPoolConfig.saved')
    } catch (error) { errorMsg.value = detail(error) }
    finally { savingEmailPoolConfig.value = false }
  }
  const testEmailPoolConfig = async () => {
    if (testingEmailPool.value) return
    clearMessages(); testingEmailPool.value = true
    try {
      // 测试走最新生效池（含 failover 与配额计数）；表单未保存修改不生效
      const result = await api.testEmailPoolConfig()
      if (String(result.status || '').toLowerCase() === 'success') successMsg.value = result.message || i18n.global.t('monitor.emailPoolConfig.testSent')
      else errorMsg.value = result.message || i18n.global.t('monitor.emailPoolConfig.testFailed')
    } catch (error) { errorMsg.value = detail(error) }
    finally { testingEmailPool.value = false }
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
  const MEMBERSHIP_EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/
  const fetchMembershipUsers = async () => {
    if (!isAdmin.value) return
    loadingMembershipUsers.value = true
    try {
      const data = await api.listMembershipUsers({ query: membershipUsersQuery.value.trim(), page: membershipUsersPage.value, pageSize: membershipUsersPageSize.value })
      membershipUsers.value = data.items
      membershipUsersTotal.value = data.total
    } catch (error) { console.error('Failed to fetch membership users', error) }
    finally { loadingMembershipUsers.value = false }
  }
  const goMembershipUsersPage = async (targetPage: number) => {
    if (targetPage < 1 || targetPage > membershipUsersTotalPages.value) return
    membershipUsersPage.value = targetPage
    await fetchMembershipUsers()
  }
  // 搜索词变化防抖 300ms 回第 1 页重拉；句柄登记进 pendingTimers 随卸载清理
  const MEMBERSHIP_QUERY_DEBOUNCE_MS = 300
  let membershipQueryTimer: ReturnType<typeof setTimeout> | null = null
  const setMembershipUsersQuery = (value: string) => {
    membershipUsersQuery.value = value
    if (membershipQueryTimer) clearTimeout(membershipQueryTimer)
    membershipQueryTimer = scheduleTracked(() => {
      membershipUsersPage.value = 1
      void fetchMembershipUsers()
    }, MEMBERSHIP_QUERY_DEBOUNCE_MS)
  }
  // 列表「编辑」把行回填到授予表单：邮箱 + 库内档位 + 到期日（北京时间粒度）
  const editMembershipUser = (user: MembershipUserItem) => {
    clearMessages()
    membershipForm.value = {
      email: user.email ?? '',
      tier: user.membership_tier === 'member' ? 'member' : 'free',
      expires_on: membershipExpiryToFormDate(user.membership_expires_at),
    }
  }
  const grantMembership = async () => {
    if (grantingMembership.value) return
    clearMessages()
    const email = membershipForm.value.email.trim()
    // 与 SMTP 发件邮箱同款无害前端校验，提前拦截 422 往返
    if (!MEMBERSHIP_EMAIL_PATTERN.test(email)) {
      errorMsg.value = i18n.global.t('monitor.membership.invalidEmail')
      return
    }
    grantingMembership.value = true
    try {
      const result = await api.grantMembership({ ...membershipForm.value, email })
      membershipLastResult.value = result
      successMsg.value = result.revoked
        ? i18n.global.t('monitor.membership.revoked', { email: result.email || email })
        : i18n.global.t('monitor.membership.granted', { email: result.email || email })
      // 授予/吊销下一请求即生效：列表同步刷新，避免管理员看到陈旧档位
      void fetchMembershipUsers()
    } catch (error) {
      // 后端 404 detail 为「用户不存在」；统一走本地化文案保持口径一致
      errorMsg.value = statusOf(error) === 404 ? i18n.global.t('monitor.membership.userNotFound') : detail(error)
    }
    finally { grantingMembership.value = false }
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
    void Promise.all([fetchSchedulerConfigs(), fetchProviderConfig(), fetchSmtpConfig(), fetchEmailPoolConfig(), fetchEmailDeliveryStats(), fetchSiteContactPageConfig(), fetchMcpServers(), fetchGithubEnrichmentStatus(), fetchGithubEnrichmentConfig(), fetchXTranslationStatus(), fetchErrorLogs(), fetchPaymentConfig(), fetchOAuthConfig(), fetchPaymentPlanPricing(), fetchMembershipUsers(), resumeGithubCrawlPolling()])
  })

  return {
    tasks, total, page, pageSize, errorLogs, errorLogsTotal, errorLogsPage, errorLogsPageSize, errorLogsTotalPages, schedulerStatus, schedulerConfigs, schedulerConfigForm, loadingSchedulerConfigs, savingSchedulerConfig, editingSchedulerJobId, mcpToolCalls, loading, errorMsg, successMsg, providerConfig, providerForm,
    loadingProviderConfig, savingProviderConfig, testingProvider, smtpConfig, smtpForm, loadingSmtpConfig, savingSmtpConfig, testingSmtp,
    emailPoolConfig, emailPoolForm, loadingEmailPoolConfig, savingEmailPoolConfig, testingEmailPool, emailDeliveryStats, loadingEmailDeliveryStats, mcpServers, mcpForm, loadingMcpServers, savingMcpServer,
    siteContactPageConfig, siteContactPageForm, loadingSiteContactPage, savingSiteContactPage,
    paymentOrders, paymentOrdersTotal, paymentOrdersPage, paymentOrdersPageSize, paymentOrdersFilter, loadingPaymentOrders, paymentOrdersTotalPages, paymentOrderDetail, loadingPaymentOrderDetail, fetchPaymentOrders, fetchPaymentOrderDetail, clearPaymentOrderDetail, goPaymentOrdersPage, markPaymentOrderPaid, closePaymentOrder,
    paymentConfig, paymentForm, loadingPaymentConfig, savingPaymentConfig, resettingPaymentConfig, fetchPaymentConfig, savePaymentConfig, resetPaymentConfig,
    oauthConfig, oauthForm, loadingOAuthConfig, savingOAuthConfig, resettingOAuthConfig, fetchOAuthConfig, saveOAuthConfig, resetOAuthConfig,
    paymentPricing, paymentPricingForm, loadingPaymentPricing, savingPaymentPricing, fetchPaymentPlanPricing, savePaymentPlanPricing,
    membershipForm, grantingMembership, membershipLastResult,
    membershipUsers, membershipUsersTotal, membershipUsersPage, membershipUsersTotalPages, membershipUsersQuery, loadingMembershipUsers,
    fetchMembershipUsers, goMembershipUsersPage, setMembershipUsersQuery, editMembershipUser,
    testingMcpServerId, deletingMcpServerId, isTaskRunning, totalPages, syncing, generatingBriefing, clearingCache,
    targetDate, maxTargetDate, ingestingByDate, ingestingSource, clearing, showClearConfirm, clearMessages, fetchTasks,
    fetchErrorLogs, goErrorLogsPage,
    fetchSchedulerStatus, fetchSchedulerConfigs, fetchMcpToolCalls, fetchProviderConfig, fetchSmtpConfig, fetchEmailPoolConfig, fetchEmailDeliveryStats, fetchMcpServers, refreshData, goPage, saveProviderConfig, testProviderConnection, saveSmtpConfig, testSmtpConfig,
    saveEmailPoolConfig, testEmailPoolConfig,
    fetchSiteContactPageConfig, saveSiteContactPageConfig,
    grantMembership,
    editSchedulerConfig, cancelSchedulerConfigEdit, saveSchedulerConfig,
    resetMcpForm, editMcpServer, saveMcpServer, testMcpServer, deleteMcpServer, ingestSingleSource, generateAllBriefings,
    clearDashboardCache, syncDataNow, ingestByDate, clearAllData,
    crawlForm, crawling, crawlPolling, crawlStatus, startGithubCrawl,
    enrichmentStatus, loadingEnrichmentStatus, retryingEnrichment, backfillingEnrichment, cancellingEnrichment, enrichmentConcurrency, enrichmentPolling,
    enrichmentCancelWatching,
    xTranslationStatus, loadingXTranslation, retryingXTranslation, xTranslationPolling, fetchXTranslationStatus, retryXTranslations,
    enrichmentReasoningEffort, enrichmentEffectiveReasoningEffort, savingEnrichmentReasoningEffort,
    fetchGithubEnrichmentStatus, fetchGithubEnrichmentConfig, saveEnrichmentReasoningEffort, retryFailedEnrichments, backfillPendingEnrichments, cancelEnrichment,
    dispose,
  }
}
