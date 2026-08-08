import { computed, onMounted, onUnmounted, ref, type Ref } from 'vue'
import {
  isSourceSubscribed as hasSourceSubscription,
  selectActiveDailySources,
  type BatchSubscriptionResponse,
  type PeriodKey,
  type ReportKey,
  type ReportMessageResponse,
  type Subscription,
  type SubscriptionListResponse,
} from '@/features/report/reportViewModel'
import { i18n } from '@/i18n'

interface ReportSubscriptionOperations {
  loadSubscriptions: () => Promise<SubscriptionListResponse | undefined>
  subscribeSources: (payload: { sources: ReportKey[]; period: 'daily' }) => Promise<BatchSubscriptionResponse | undefined>
  unsubscribe: (payload: { source: ReportKey; period: 'daily' }) => Promise<void>
  sendToEmail: (payload: { source: ReportKey; period: PeriodKey; date: string; locale: string }) => Promise<ReportMessageResponse | undefined>
}

interface UseReportSubscriptionsOptions {
  isLoggedIn: Readonly<Ref<boolean>>
  selectedSource: Ref<ReportKey>
  selectedPeriod: Ref<PeriodKey>
  selectedDate: Ref<string>
  locale: Ref<string>
  operations: ReportSubscriptionOperations
  redirectToLogin: () => void
  setError: (message: string) => void
}

const getApiErrorMessage = (error: unknown): string | undefined =>
  (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail

export const useReportSubscriptions = ({
  isLoggedIn,
  selectedSource,
  selectedPeriod,
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
  const selectedSubscribeSources = ref<ReportKey[]>([])

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

  const isSourceSubscribed = (source: ReportKey): boolean =>
    hasSourceSubscription(subscriptions.value, source)

  const isCurrentSubscribed = computed(() => isSourceSubscribed(selectedSource.value))

  const openSubscribePanel = () => {
    const currentDaily = selectActiveDailySources(subscriptions.value)
    selectedSubscribeSources.value = currentDaily.length ? [...currentDaily] : [selectedSource.value]
    showSubscribePanel.value = true
    setError('')
  }

  const promptLoginForSubscribe = () => {
    showLoginPrompt.value = true
    setError('请先登录后再订阅简报')
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

  const handleManageSubscriptions = () => {
    if (!isLoggedIn.value) {
      promptLoginForSubscribe()
      return
    }
    openSubscribePanel()
  }

  const closeSubscribePanel = () => {
    showSubscribePanel.value = false
  }

  const toggleSubscribeSource = (source: ReportKey) => {
    if (selectedSubscribeSources.value.includes(source)) {
      selectedSubscribeSources.value = selectedSubscribeSources.value.filter(item => item !== source)
    } else {
      selectedSubscribeSources.value = [...selectedSubscribeSources.value, source]
    }
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

  const confirmSubscribeSources = async () => {
    if (isSubscribing.value || !isLoggedIn.value || !selectedSubscribeSources.value.length) return
    isSubscribing.value = true
    setError('')
    try {
      const data = await operations.subscribeSources({
        sources: selectedSubscribeSources.value,
        period: 'daily',
      })
      const subscribedSources = new Set(data?.sources ?? selectedSubscribeSources.value)
      await loadSubscriptions()
      subscriptions.value = [
        ...subscriptions.value.filter(s => s.period !== 'daily' || !subscribedSources.has(s.source)),
        ...Array.from(subscribedSources).map(source => ({
          source,
          period: 'daily',
          is_active: true,
        })),
      ]
      emailSentMsg.value = data?.message || '订阅成功，日报生成后会自动推送到邮箱'
      scheduleTracked(() => { emailSentMsg.value = '' }, 4000)
      showSubscribePanel.value = false
    } catch (error: unknown) {
      setError(getApiErrorMessage(error) || '订阅操作失败')
    } finally {
      isSubscribing.value = false
    }
  }

  const toggleSubscribe = async () => {
    if (isSubscribing.value) return
    if (!isLoggedIn.value) {
      promptLoginForSubscribe()
      return
    }
    if (!isCurrentSubscribed.value) {
      openSubscribePanel()
      return
    }
    isSubscribing.value = true
    setError('')
    try {
      await operations.unsubscribe({ source: selectedSource.value, period: 'daily' })
      await loadSubscriptions()
      subscriptions.value = subscriptions.value.filter(
        s => !(s.source === selectedSource.value && s.period === 'daily'),
      )
      emailSentMsg.value = i18n.global.t('report.unsubscribeSuccess')
      scheduleTracked(() => { emailSentMsg.value = '' }, 4000)
    } catch (error: unknown) {
      setError(getApiErrorMessage(error) || '订阅操作失败')
    } finally {
      isSubscribing.value = false
    }
  }

  const sendToEmail = async () => {
    if (isSendingEmail.value || !isLoggedIn.value) return
    isSendingEmail.value = true
    emailSentMsg.value = ''
    try {
      const data = await operations.sendToEmail({
        source: selectedSource.value,
        period: selectedPeriod.value,
        date: selectedDate.value,
        locale: locale.value,
      })
      emailSentMsg.value = data?.message || '已发送'
      scheduleTracked(() => { emailSentMsg.value = '' }, 4000)
    } catch (error: unknown) {
      setError(getApiErrorMessage(error) || '发送失败')
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
    selectedSubscribeSources,
    isSourceSubscribed,
    isCurrentSubscribed,
    promptLoginForSubscribe,
    closeLoginPrompt,
    handleLoginAndRedirect,
    handleManageSubscriptions,
    closeSubscribePanel,
    toggleSubscribeSource,
    confirmSubscribeSources,
    toggleSubscribe,
    sendToEmail,
  }
}
