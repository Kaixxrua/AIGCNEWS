import { computed, ref } from 'vue'
import type {
  PushChannel,
  SubscriptionFrequency,
  SubscriptionSource,
  UserSubscription,
} from '@/features/subscriptions/subscriptionsModel'
import {
  isChannelBindable,
  isHttpsUrlShape,
  isValidEmailShape,
  isValidOtpCode,
  normalizeEmail,
} from '@/features/subscriptions/subscriptionsModel'
import { subscriptionsApi } from '@/services/subscriptions/subscriptionsApi'
import type { SubscriptionsApi } from '@/services/subscriptions/subscriptionsApi'

interface ApiErrorLike {
  response?: {
    data?: {
      message?: string
      detail?: { message?: string; code?: string } | string
    }
  }
  message?: string
}

export function getErrorMessage(err: unknown, fallback: string): string {
  const e = err as ApiErrorLike
  const data = e.response?.data
  const detail = data?.detail
  const detailMessage = typeof detail === 'string' ? detail : detail?.message
  return data?.message ?? detailMessage ?? e.message ?? fallback
}

export function useSubscriptionsController(
  api: SubscriptionsApi = subscriptionsApi,
) {
  const channels = ref<PushChannel[]>([])
  const subscriptions = ref<UserSubscription[]>([])
  const loading = ref(false)
  const error = ref('')
  const notice = ref('')

  const emailInput = ref('')
  const otpChannelId = ref<number | null>(null)
  const otpCode = ref('')
  const webhookInput = ref('')
  const channelFormBusy = ref(false)

  const newChannelId = ref<number | null>(null)
  const newSource = ref<SubscriptionSource>('all')
  const newFrequency = ref<SubscriptionFrequency>('daily')
  const subscriptionFormBusy = ref(false)

  const busyChannelIds = ref<Set<number>>(new Set())
  const busySubscriptionIds = ref<Set<number>>(new Set())

  const bindableChannels = computed(() => channels.value.filter(isChannelBindable))
  const canSubmitEmail = computed(
    () => isValidEmailShape(emailInput.value) && !channelFormBusy.value,
  )
  const canSubmitOtp = computed(
    () => otpChannelId.value !== null && isValidOtpCode(otpCode.value) && !channelFormBusy.value,
  )
  const canSubmitWebhook = computed(
    () => isHttpsUrlShape(webhookInput.value) && !channelFormBusy.value,
  )
  const canSubmitSubscription = computed(
    () => newChannelId.value !== null && !subscriptionFormBusy.value,
  )

  const loadAll = async (): Promise<void> => {
    loading.value = true
    error.value = ''
    try {
      const [channelRows, subscriptionRows] = await Promise.all([
        api.listChannels(),
        api.listSubscriptions(),
      ])
      channels.value = channelRows
      subscriptions.value = subscriptionRows
      if (
        newChannelId.value !== null &&
        !channelRows.some((row) => row.id === newChannelId.value && isChannelBindable(row))
      ) {
        newChannelId.value = null
      }
      if (newChannelId.value === null) {
        const first = channelRows.find(isChannelBindable)
        newChannelId.value = first ? first.id : null
      }
    } catch (err) {
      error.value = getErrorMessage(err, 'load-failed')
    } finally {
      loading.value = false
    }
  }

  const _run = async (action: () => Promise<void>): Promise<boolean> => {
    error.value = ''
    notice.value = ''
    try {
      await action()
      return true
    } catch (err) {
      error.value = getErrorMessage(err, 'request-failed')
      return false
    }
  }

  const submitEmailChannel = async (): Promise<boolean> => {
    if (!canSubmitEmail.value) return false
    channelFormBusy.value = true
    try {
      return await _run(async () => {
        const channel = await api.createEmailChannel(normalizeEmail(emailInput.value))
        otpChannelId.value = channel.id
        otpCode.value = ''
        notice.value = 'otp-sent'
        await loadAll()
      })
    } finally {
      channelFormBusy.value = false
    }
  }

  const submitOtp = async (): Promise<boolean> => {
    if (!canSubmitOtp.value || otpChannelId.value === null) return false
    channelFormBusy.value = true
    try {
      return await _run(async () => {
        await api.verifyChannel(otpChannelId.value as number, otpCode.value.trim())
        otpChannelId.value = null
        otpCode.value = ''
        emailInput.value = ''
        notice.value = 'channel-verified'
        await loadAll()
      })
    } finally {
      channelFormBusy.value = false
    }
  }

  const submitWebhookChannel = async (): Promise<boolean> => {
    if (!canSubmitWebhook.value) return false
    channelFormBusy.value = true
    try {
      return await _run(async () => {
        await api.createWebhookChannel(webhookInput.value.trim())
        webhookInput.value = ''
        notice.value = 'webhook-created'
        await loadAll()
      })
    } finally {
      channelFormBusy.value = false
    }
  }

  const _markBusy = (box: typeof busyChannelIds, id: number, on: boolean): void => {
    const next = new Set(box.value)
    if (on) next.add(id)
    else next.delete(id)
    box.value = next
  }

  const toggleChannel = async (channel: PushChannel): Promise<void> => {
    _markBusy(busyChannelIds, channel.id, true)
    try {
      await _run(async () => {
        await api.setChannelStatus(
          channel.id,
          channel.status === 'active' ? 'disabled' : 'active',
        )
        await loadAll()
      })
    } finally {
      _markBusy(busyChannelIds, channel.id, false)
    }
  }

  const removeChannel = async (channel: PushChannel): Promise<void> => {
    _markBusy(busyChannelIds, channel.id, true)
    try {
      await _run(async () => {
        await api.deleteChannel(channel.id)
        notice.value = 'channel-deleted'
        await loadAll()
      })
    } finally {
      _markBusy(busyChannelIds, channel.id, false)
    }
  }

  const sendTest = async (channel: PushChannel): Promise<void> => {
    _markBusy(busyChannelIds, channel.id, true)
    try {
      await _run(async () => {
        await api.testChannel(channel.id)
        notice.value = 'test-sent'
      })
    } finally {
      _markBusy(busyChannelIds, channel.id, false)
    }
  }

  const submitSubscription = async (): Promise<boolean> => {
    if (!canSubmitSubscription.value || newChannelId.value === null) return false
    subscriptionFormBusy.value = true
    try {
      return await _run(async () => {
        await api.createSubscription(
          newChannelId.value as number,
          newSource.value,
          newFrequency.value,
        )
        notice.value = 'subscription-created'
        await loadAll()
      })
    } finally {
      subscriptionFormBusy.value = false
    }
  }

  const toggleSubscription = async (subscription: UserSubscription): Promise<void> => {
    _markBusy(busySubscriptionIds, subscription.id, true)
    try {
      await _run(async () => {
        await api.setSubscriptionStatus(
          subscription.id,
          subscription.status === 'active' ? 'paused' : 'active',
        )
        await loadAll()
      })
    } finally {
      _markBusy(busySubscriptionIds, subscription.id, false)
    }
  }

  const removeSubscription = async (subscription: UserSubscription): Promise<void> => {
    _markBusy(busySubscriptionIds, subscription.id, true)
    try {
      await _run(async () => {
        await api.deleteSubscription(subscription.id)
        notice.value = 'subscription-deleted'
        await loadAll()
      })
    } finally {
      _markBusy(busySubscriptionIds, subscription.id, false)
    }
  }

  return {
    channels,
    subscriptions,
    loading,
    error,
    notice,
    emailInput,
    otpChannelId,
    otpCode,
    webhookInput,
    channelFormBusy,
    newChannelId,
    newSource,
    newFrequency,
    subscriptionFormBusy,
    busyChannelIds,
    busySubscriptionIds,
    bindableChannels,
    canSubmitEmail,
    canSubmitOtp,
    canSubmitWebhook,
    canSubmitSubscription,
    loadAll,
    submitEmailChannel,
    submitOtp,
    submitWebhookChannel,
    toggleChannel,
    removeChannel,
    sendTest,
    submitSubscription,
    toggleSubscription,
    removeSubscription,
  }
}

export type SubscriptionsController = ReturnType<typeof useSubscriptionsController>
