import { computed, onMounted, onUnmounted, ref, watch, type Ref } from 'vue'
import {
  isActiveSubscription,
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
import { copySensitiveToClipboard } from '@/composables/useClipboard'
import type { FeedTokenInfo } from '@/services/auth/feedTokenApi'
import { i18n } from '@/i18n'

interface ReportSubscriptionOperations {
  loadPlan: () => Promise<SubscriptionPlan | undefined>
  loadSubscriptions: () => Promise<SubscriptionListResponse | undefined>
  applyPlan: (payload: {
    sources: ReportKey[]
    deliveries: PlanDeliveryRequest[]
    idempotency_key: string
    sync: boolean
  }) => Promise<SubscriptionPlanApplyResponse | undefined>
  getFeedToken: () => Promise<FeedTokenInfo>
  rotateFeedToken: () => Promise<FeedTokenInfo>
  sendToEmail: (payload: { source: ReportKey; date: string; locale: string }) => Promise<ReportMessageResponse | undefined>
}

interface UseReportSubscriptionsOptions {
  isLoggedIn: Readonly<Ref<boolean>>
  /** 当前认证用户 ID；用于隔离账号级异步结果和 RSS token 缓存。 */
  userId: Readonly<Ref<number | null>>
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

/** 订阅相关错误统一映射为 i18n 文案；detail 是运营口径中文，不做多语言透传。 */
const getSubscriptionErrorMessage = (error: unknown, fallback: string): string =>
  getApiErrorDetail(error) || getApiErrorMessage(error) || fallback

const generateIdempotencyKey = (): string => {
  try {
    return crypto.randomUUID()
  } catch {
    return `${Date.now()}-${Math.random().toString(36).slice(2)}`
  }
}

export const useReportSubscriptions = ({
  isLoggedIn,
  userId,
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

  // 完整 RSS token 仅保存在 composable 闭包内存，绝不进入模板、持久化存储或日志。
  // 绑定当前认证主体；登出或切换账号时必须清空，避免跨账号复用 bearer token。
  let feedToken = ''
  let feedTokenOwner: number | string | null = null
  const isRssBusy = ref(false)
  const rssNotice = ref('')
  // RSS 是 virtual delivery，后端不会返回 active；此状态仅代表本次账号会话最近应用的计划。
  const rssSubscribed = ref(false)
  const emailSubscribed = ref(false)

  // 延时回调统一登记，卸载时集中清理
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

  let disposed = false
  let accountGeneration = 0
  let requestGeneration = 0
  const isCurrent = (generation: number, request?: number): boolean =>
    !disposed
    && generation === accountGeneration
    && (request === undefined || request === requestGeneration)
    && isLoggedIn.value
    && Number.isInteger(userId.value)
    && (userId.value ?? 0) > 0

  const clearAccountState = () => {
    subscriptions.value = []
    plan.value = null
    selectedSources.value = []
    selectedDeliveryKeys.value = []
    feedToken = ''
    feedTokenOwner = null
    rssNotice.value = ''
    rssSubscribed.value = false
    emailSubscribed.value = false
  }

  const invalidateAccount = () => {
    accountGeneration += 1
    requestGeneration += 1
    clearAccountState()
    isLoadingPlan.value = false
    isSubscribing.value = false
    isSendingEmail.value = false
    isRssBusy.value = false
  }

  const resetWizard = () => {
    step.value = 1
    plan.value = null
    selectedSources.value = []
    selectedDeliveryKeys.value = []
    isLoadingPlan.value = false
    rssNotice.value = ''
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
    if (!isLoggedIn.value || !Number.isInteger(userId.value) || (userId.value ?? 0) <= 0) return
    const generation = accountGeneration
    const request = ++requestGeneration
    try {
      const data = await operations.loadSubscriptions()
      if (isCurrent(generation, request)) subscriptions.value = data?.items ?? []
    } catch {
      if (isCurrent(generation, request)) subscriptions.value = []
    }
  }

  const loadPlan = async () => {
    if (!isLoggedIn.value || !Number.isInteger(userId.value) || (userId.value ?? 0) <= 0) return
    const generation = accountGeneration
    const request = ++requestGeneration
    isLoadingPlan.value = true
    try {
      const data = await operations.loadPlan()
      if (data && isCurrent(generation, request)) {
        plan.value = data
        const active = data.active_sources.filter(isReportKey)
        selectedSources.value = active.length ? active : [selectedSource.value]
        // 后端为无状态 RSS 固定 active=false；这里只预选真实仍在生效的投递方式。
        selectedDeliveryKeys.value = data.capabilities
          .filter(cap => cap.selectable && cap.active === true)
          .map(cap => cap.key)
        // account_email 是服务端持久化的真实 delivery；RSS 则是无状态 virtual delivery。
        emailSubscribed.value = data.capabilities.some(
          cap => cap.kind === 'account_email' && cap.active === true,
        )
      }
    } catch (error: unknown) {
      if (isCurrent(generation, request)) {
        setError(getApiErrorDetail(error) || i18n.global.t('report.wizard.errorLoadPlan'))
      }
    } finally {
      if (isCurrent(generation, request)) isLoadingPlan.value = false
    }
  }

  const toggleSubscribeSource = (source: ReportKey) => {
    const current = selectedSources.value
    if (current.includes(source)) {
      selectedSources.value = current.filter(item => item !== source)
    } else if (canSelectMultipleSources.value) {
      selectedSources.value = [...current, source]
    } else {
      // plan 未放开多选时单选：新选择直接替换，避免「超上限 403」的可预见失败
      selectedSources.value = [source]
    }
  }

  const goToDeliveryStep = () => {
    // 已有计划的用户需要能清空模块并进入第二步完成全量退订；新用户仍需至少选一个模块。
    if (!selectedSources.value.length && !hasExistingPlan.value) {
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
    if (result.removed_sources?.length && !result.deliveries.length) {
      return i18n.global.t('report.wizard.resultUnsubscribed')
    }
    const hasApplied = result.deliveries.some(d => d.status === 'applied')
    return hasApplied
      ? i18n.global.t('report.wizard.resultSuccess')
      : i18n.global.t('report.wizard.resultAlreadyActive')
  }

  const hasExistingPlan = computed(() => Boolean(
    subscriptions.value.some(isActiveSubscription)
      || plan.value?.active_sources.length
      || deliveryCapabilities.value.some(cap => cap.active === true),
  ))

  const confirm = (message: string): boolean =>
    typeof window === 'undefined' ? false : window.confirm(message)

  const confirmSubscriptionPlan = async () => {
    if (isSubscribing.value || !isLoggedIn.value || !Number.isInteger(userId.value) || (userId.value ?? 0) <= 0) return
    const generation = accountGeneration

    const nextSources = [...selectedSources.value]
    const nextDeliveries = [...selectedDeliveryKeys.value]
    const selectedCapabilities = selectedDeliveryCapabilities.value
    const rssSelected = selectedCapabilities.some(cap => cap.kind === 'rss')
    const emailSelected = selectedCapabilities.some(cap => cap.kind === 'account_email')
    const isEmptyPlan = !nextSources.length && !nextDeliveries.length
    const removesAny = <T>(before: readonly T[], after: readonly T[]): boolean => {
      const afterSet = new Set(after)
      return before.some(item => !afterSet.has(item))
    }
    const activeDeliveryKeys = deliveryCapabilities.value
      .filter(cap => cap.active === true)
      .map(cap => cap.key)
    const hasReduction = hasExistingPlan.value && (
      removesAny(plan.value?.active_sources ?? [], nextSources)
      || removesAny(activeDeliveryKeys, nextDeliveries)
    )

    if ((!nextSources.length || !nextDeliveries.length) && !isEmptyPlan) {
      setError(i18n.global.t('report.wizard.errorPlanMustBeTogether'))
      return
    }
    if (!hasExistingPlan.value && isEmptyPlan) {
      setError(i18n.global.t('report.wizard.errorNoSource'))
      return
    }
    if (isEmptyPlan && !confirm(i18n.global.t('report.wizard.unsubscribeConfirm'))) return
    if (hasReduction && !isEmptyPlan && !confirm(i18n.global.t('report.wizard.reductionConfirm'))) return

    isSubscribing.value = true
    setError('')
    try {
      const data = await operations.applyPlan({
        sources: nextSources,
        deliveries: buildDeliveryRequests(),
        idempotency_key: generateIdempotencyKey(),
        sync: true,
      })
      if (!isCurrent(generation)) return
      await loadSubscriptions()
      if (!isCurrent(generation)) return
      rssSubscribed.value = rssSelected
      emailSubscribed.value = emailSelected
      let successMessage = getSuccessMessage(data ?? { sources: nextSources, deliveries: [] })
      if (rssSelected) {
        const copied = await copyRssLink()
        if (!isCurrent(generation)) return
        if (copied) {
          successMessage = i18n.global.t('report.wizard.subscriptionAndRssCopied')
        } else {
          // 订阅已保存，但复制失败时不显示“已复制”的成功反馈。
          successMessage = ''
        }
      }
      emailSentMsg.value = successMessage
      if (successMessage) scheduleTracked(() => {
        if (generation === accountGeneration && !disposed) emailSentMsg.value = ''
      }, 4000)
      closeSubscribePanel()
    } catch (error: unknown) {
      if (isCurrent(generation)) setError(getSubscriptionErrorMessage(error, i18n.global.t('report.wizard.errorSubmit')))
    } finally {
      if (generation === accountGeneration && !disposed) isSubscribing.value = false
    }
  }

  const ensureFeedToken = async (generation: number): Promise<string> => {
    const owner = userId.value
    if (!isCurrent(generation) || owner === null) throw new Error('Authentication changed')
    if (feedToken && feedTokenOwner === owner) return feedToken
    const info = await operations.getFeedToken()
    if (!isCurrent(generation) || userId.value !== owner) throw new Error('Authentication changed')
    feedToken = info.token
    feedTokenOwner = owner
    return feedToken
  }

  // 速览 RSS 已对所有注册用户免费开放：统一复制带 token 的 briefing-digest.xml
  // （token 属敏感凭证，走 sensitive 剪贴板路径）。英文界面复制英文版（locale=en）。
  const copyRssLink = async (): Promise<boolean> => {
    if (isRssBusy.value || !isLoggedIn.value || !Number.isInteger(userId.value) || (userId.value ?? 0) <= 0) return false
    const generation = accountGeneration
    isRssBusy.value = true
    rssNotice.value = ''
    try {
      const token = encodeURIComponent(await ensureFeedToken(generation))
      if (!isCurrent(generation)) return false
      const origin = typeof window === 'undefined' ? '' : window.location.origin
      const localeParam = locale.value.toLowerCase().startsWith('en') ? '&locale=en' : ''
      const url = `${origin}/api/feeds/briefing-digest.xml?token=${token}${localeParam}`
      await copySensitiveToClipboard(url)
      if (!isCurrent(generation)) return false
      rssNotice.value = 'rss-copied'
      return true
    } catch (error: unknown) {
      if (isCurrent(generation)) {
        rssNotice.value = ''
        setError(getSubscriptionErrorMessage(error, i18n.global.t('report.wizard.errorRss')))
      }
      return false
    } finally {
      if (generation === accountGeneration && !disposed) isRssBusy.value = false
    }
  }

  const copySubscribedRss = async (): Promise<boolean> => {
    if (!rssSubscribed.value) return false
    return copyRssLink()
  }

  const rotateRssToken = async (): Promise<boolean> => {
    if (isRssBusy.value || !isLoggedIn.value || !Number.isInteger(userId.value) || (userId.value ?? 0) <= 0) return false
    if (!confirm(i18n.global.t('report.wizard.rssResetConfirm'))) return false
    const generation = accountGeneration
    const owner = userId.value
    isRssBusy.value = true
    rssNotice.value = ''
    try {
      const info = await operations.rotateFeedToken()
      if (!isCurrent(generation) || userId.value !== owner) return false
      feedToken = info.token
      feedTokenOwner = owner
      rssNotice.value = 'rss-rotated'
      return true
    } catch (error: unknown) {
      if (isCurrent(generation)) {
        rssNotice.value = ''
        setError(getSubscriptionErrorMessage(error, i18n.global.t('report.wizard.errorRss')))
      }
      return false
    } finally {
      if (generation === accountGeneration && !disposed) isRssBusy.value = false
    }
  }

  // 旧单条订阅入口保留为打开向导，不再通过此处取消
  const toggleSubscribe = () => {
    openSubscribePanel()
  }

  const sendToEmail = async () => {
    if (isSendingEmail.value || !isLoggedIn.value || !Number.isInteger(userId.value) || (userId.value ?? 0) <= 0) return
    const generation = accountGeneration
    isSendingEmail.value = true
    emailSentMsg.value = ''
    try {
      const data = await operations.sendToEmail({
        source: selectedSource.value,
        date: selectedDate.value,
        locale: locale.value,
      })
      if (!isCurrent(generation)) return
      emailSentMsg.value = data?.message || i18n.global.t('report.wizard.sent')
      scheduleTracked(() => {
        if (generation === accountGeneration && !disposed) emailSentMsg.value = ''
      }, 4000)
    } catch (error: unknown) {
      if (isCurrent(generation)) setError(getApiErrorMessage(error) || i18n.global.t('report.wizard.sendFailed'))
    } finally {
      if (generation === accountGeneration && !disposed) isSendingEmail.value = false
    }
  }

  watch(
    [isLoggedIn, userId],
    ([loggedIn, currentUserId], [previousLoggedIn, previousUserId]) => {
      if (loggedIn === previousLoggedIn && currentUserId === previousUserId) return
      invalidateAccount()
      if (loggedIn && Number.isInteger(currentUserId) && (currentUserId ?? 0) > 0) void loadSubscriptions()
    },
    { flush: 'sync' },
  )

  onMounted(() => {
    void loadSubscriptions()
  })

  onUnmounted(() => {
    disposed = true
    accountGeneration += 1
    requestGeneration += 1
    clearAccountState()
    clearPendingTimers()
  })

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
    hasExistingPlan,
    isRssBusy,
    rssNotice,
    rssSubscribed,
    emailSubscribed,
    copySubscribedRss,
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
    copyRssLink,
    rotateRssToken,
    toggleSubscribe,
    sendToEmail,
  }
}
