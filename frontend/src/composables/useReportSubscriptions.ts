import { computed, onMounted, onUnmounted, ref, type Ref } from 'vue'
import {
  isReportKey,
  isSourceSubscribed as hasSourceSubscription,
  type PlanDeliveryRequest,
  type ReportKey,
  type ReportMessageResponse,
  type Subscription,
  type SubscriptionListResponse,
  type SubscriptionPlan,
  type SubscriptionPlanApplyResponse,
} from '@/features/report/reportViewModel'
import { i18n } from '@/i18n'

interface ReportSubscriptionOperations {
  loadPlan: () => Promise<SubscriptionPlan | undefined>
  loadSubscriptions: () => Promise<SubscriptionListResponse | undefined>
  applyPlan: (payload: {
    sources: ReportKey[]
    deliveries: PlanDeliveryRequest[]
    idempotency_key: string
  }) => Promise<SubscriptionPlanApplyResponse | undefined>
  sendToEmail: (payload: { source: ReportKey; date: string; locale: string }) => Promise<ReportMessageResponse | undefined>
}

interface UseReportSubscriptionsOptions {
  isLoggedIn: Readonly<Ref<boolean>>
  /** 会员档位：订阅面板按后端 plan.can_select_multiple_sources 决定单/多选 */
  isMember: Readonly<Ref<boolean>>
  selectedSource: Ref<ReportKey>
  selectedDate: Ref<string>
  locale: Ref<string>
  operations: ReportSubscriptionOperations
  redirectToLogin: () => void
  setError: (message: string) => void
}

const getApiErrorMessage = (error: unknown): string | undefined =>
  (error as { response?: { data?: { detail?: string | { message?: string } } } })?.response?.data?.detail as string | undefined

const getApiErrorDetail = (error: unknown): string => {
  const detail = (error as { response?: { data?: { detail?: string | { message?: string; code?: string } } } })?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object') return detail.message ?? ''
  return ''
}

const getErrorCode = (error: unknown): string | undefined => {
  const detail = (error as { response?: { data?: { detail?: string | { code?: string } } } })?.response?.data?.detail
  if (detail && typeof detail === 'object') return detail.code
  return undefined
}

/** 订阅相关错误统一映射为 i18n 文案；detail 是运营口径中文，不做多语言透传。 */
const getSubscriptionErrorMessage = (error: unknown, fallback: string): string => {
  const status = (error as { response?: { status?: number } })?.response?.status
  const code = getErrorCode(error)
  if (status === 403) {
    if (code === 'vip-required') return i18n.global.t('report.wizard.errorVipRequired')
    return i18n.global.t('report.wizard.errorQuotaExceeded')
  }
  return getApiErrorDetail(error) || getApiErrorMessage(error) || fallback
}

const generateIdempotencyKey = (): string => {
  try {
    return crypto.randomUUID()
  } catch {
    return `${Date.now()}-${Math.random().toString(36).slice(2)}`
  }
}

export const useReportSubscriptions = ({
  isLoggedIn,
  isMember: _isMember,
  selectedSource,
  selectedDate,
  locale,
  operations,
  redirectToLogin,
  setError,
}: UseReportSubscriptionsOptions) => {
  const subscriptions = ref<Subscription[]>([])
  const isSubscribing = ref(false)
  const isSendingEmail = ref(false)
  const emailSentMsg = ref('')
  const showSubscribePanel = ref(false)
  const showLoginPrompt = ref(false)

  // ── 两步向导状态 ──────────────────────────────────────────────────────
  const step = ref<1 | 2>(1)
  const plan = ref<SubscriptionPlan | null>(null)
  const selectedSources = ref<ReportKey[]>([])
  const selectedDeliveryKeys = ref<string[]>([])
  const isLoadingPlan = ref(false)

  // 延时回调统一登记，卸载时集中清理（对齐 useWechatController dispose 范式）
  const pendingTimers = new Set<ReturnType<typeof setTimeout>>()
  const scheduleTracked = (callback: () => void, delay: number) => {
    const timer = setTimeout(() => {
      pendingTimers.delete(timer)
      callback()
    }, delay)
    pendingTimers.add(timer)
    return timer
  }
  const clearPendingTimers = () => {
    for (const timer of pendingTimers) clearTimeout(timer)
    pendingTimers.clear()
  }

  const canSelectMultipleSources = computed(() => plan.value?.can_select_multiple_sources ?? false)

  const isSourceSubscribed = (source: ReportKey): boolean =>
    hasSourceSubscription(subscriptions.value, source)

  const deliveryCapabilities = computed(() => plan.value?.capabilities ?? [])

  const selectedDeliveryCapabilities = computed(() =>
    deliveryCapabilities.value.filter(cap => selectedDeliveryKeys.value.includes(cap.key))
  )

  const resetWizard = () => {
    step.value = 1
    plan.value = null
    selectedSources.value = []
    selectedDeliveryKeys.value = []
    isLoadingPlan.value = false
  }

  const openSubscribePanel = () => {
    if (!isLoggedIn.value) {
      promptLoginForSubscribe()
      return
    }
    setError('')
    showSubscribePanel.value = true
    resetWizard()
    void loadPlan()
  }

  const promptLoginForSubscribe = () => {
    showLoginPrompt.value = true
    setError(i18n.global.t('report.loginError'))
    scheduleTracked(() => {
      if (showLoginPrompt.value && !isLoggedIn.value) redirectToLogin()
    }, 900)
  }

  const closeLoginPrompt = () => {
    showLoginPrompt.value = false
  }

  const handleLoginAndRedirect = () => {
    showLoginPrompt.value = false
    redirectToLogin()
  }

  const closeSubscribePanel = () => {
    showSubscribePanel.value = false
    resetWizard()
  }

  const loadSubscriptions = async () => {
    if (!isLoggedIn.value) return
    try {
      const data = await operations.loadSubscriptions()
      subscriptions.value = data?.items ?? []
    } catch {
      subscriptions.value = []
    }
  }

  const loadPlan = async () => {
    isLoadingPlan.value = true
    try {
      const data = await operations.loadPlan()
      if (data) {
        plan.value = data
        const active = data.active_sources.filter(isReportKey)
        selectedSources.value = active.length ? active : [selectedSource.value]
        // 若已有活跃 source，默认帮用户勾选注册邮箱（兼容旧 briefing_subscriptions 习惯）
        if (active.length) {
          const emailCap = data.capabilities.find(cap => cap.kind === 'account_email')
          if (emailCap) selectedDeliveryKeys.value = [emailCap.key]
        }
      }
    } catch (error: unknown) {
      setError(getApiErrorDetail(error) || i18n.global.t('report.wizard.errorLoadPlan'))
    } finally {
      isLoadingPlan.value = false
    }
  }

  const toggleSubscribeSource = (source: ReportKey) => {
    const current = selectedSources.value
    if (current.includes(source)) {
      selectedSources.value = current.filter(item => item !== source)
    } else if (canSelectMultipleSources.value) {
      selectedSources.value = [...current, source]
    } else {
      // 免费档单选：新选择直接替换，避免「超上限 403」的可预见失败
      selectedSources.value = [source]
    }
  }

  const goToDeliveryStep = () => {
    if (!selectedSources.value.length) {
      setError(i18n.global.t('report.wizard.errorNoSource'))
      return
    }
    setError('')
    step.value = 2
  }

  const goBackToSourceStep = () => {
    step.value = 1
  }

  const toggleDelivery = (key: string) => {
    const capability = deliveryCapabilities.value.find(cap => cap.key === key)
    if (!capability || !capability.selectable) return
    if (selectedDeliveryKeys.value.includes(key)) {
      selectedDeliveryKeys.value = selectedDeliveryKeys.value.filter(k => k !== key)
    } else {
      selectedDeliveryKeys.value = [...selectedDeliveryKeys.value, key]
    }
  }

  const buildDeliveryRequests = (): PlanDeliveryRequest[] =>
    selectedDeliveryCapabilities.value.map(cap => {
      if (cap.kind === 'rss') return { kind: 'rss', feed: cap.feed ?? 'briefing' }
      if (cap.kind === 'account_email') return { kind: 'account_email' }
      return { kind: 'push_channel', channel_id: cap.channel_id }
    })

  const getSuccessMessage = (result: SubscriptionPlanApplyResponse): string => {
    const hasApplied = result.deliveries.some(d => d.status === 'applied')
    return hasApplied
      ? i18n.global.t('report.wizard.resultSuccess')
      : i18n.global.t('report.wizard.resultAlreadyActive')
  }

  const confirmSubscriptionPlan = async () => {
    if (isSubscribing.value || !isLoggedIn.value || !selectedSources.value.length) return
    if (!selectedDeliveryKeys.value.length) {
      setError(i18n.global.t('report.wizard.errorNoDelivery'))
      return
    }
    isSubscribing.value = true
    setError('')
    try {
      const data = await operations.applyPlan({
        sources: selectedSources.value,
        deliveries: buildDeliveryRequests(),
        idempotency_key: generateIdempotencyKey(),
      })
      await loadSubscriptions()
      emailSentMsg.value = getSuccessMessage(data ?? { sources: selectedSources.value, deliveries: [] })
      scheduleTracked(() => { emailSentMsg.value = '' }, 4000)
      closeSubscribePanel()
    } catch (error: unknown) {
      setError(getSubscriptionErrorMessage(error, i18n.global.t('report.wizard.errorSubmit')))
    } finally {
      isSubscribing.value = false
    }
  }

  // 旧单条订阅入口保留为打开向导，不再通过此处取消
  const toggleSubscribe = () => {
    openSubscribePanel()
  }

  const sendToEmail = async () => {
    if (isSendingEmail.value || !isLoggedIn.value) return
    isSendingEmail.value = true
    emailSentMsg.value = ''
    try {
      const data = await operations.sendToEmail({
        source: selectedSource.value,
        date: selectedDate.value,
        locale: locale.value,
      })
      emailSentMsg.value = data?.message || i18n.global.t('report.wizard.sent')
      scheduleTracked(() => { emailSentMsg.value = '' }, 4000)
    } catch (error: unknown) {
      setError(getApiErrorMessage(error) || i18n.global.t('report.wizard.sendFailed'))
    } finally {
      isSendingEmail.value = false
    }
  }

  onMounted(() => {
    void loadSubscriptions()
  })

  onUnmounted(clearPendingTimers)

  return {
    subscriptions,
    isSubscribing,
    isSendingEmail,
    emailSentMsg,
    showSubscribePanel,
    showLoginPrompt,
    step,
    plan,
    selectedSources,
    selectedDeliveryKeys,
    isLoadingPlan,
    canSelectMultipleSources,
    deliveryCapabilities,
    selectedDeliveryCapabilities,
    isSourceSubscribed,
    promptLoginForSubscribe,
    closeLoginPrompt,
    handleLoginAndRedirect,
    openSubscribePanel,
    closeSubscribePanel,
    toggleSubscribeSource,
    goToDeliveryStep,
    goBackToSourceStep,
    toggleDelivery,
    confirmSubscriptionPlan,
    toggleSubscribe,
    sendToEmail,
  }
}
