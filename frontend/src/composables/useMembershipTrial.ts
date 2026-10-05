import { computed, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/authStore'
import { membershipTrialApi, type MembershipTrialApi } from '@/services/membership/membershipTrialApi'
import {
  trialErrorKey,
  trialOffer,
  type MembershipTrialStatus,
} from '@/features/membership/membershipTrial'

/**
 * 会员页的试用入口：登录后读试用状态，点按钮开通，开通后刷新右上角身份（会员身份以 /auth/me 为准）。
 * 读不到状态（旧后端没有这个接口、网络出错）时不显示入口，开通按钮照常。
 */
export function useMembershipTrial(api: MembershipTrialApi = membershipTrialApi) {
  const authStore = useAuthStore()
  const status = ref<MembershipTrialStatus | null>(null)
  const starting = ref(false)
  const messageKey = ref<string | null>(null)
  // 换了账号或开通之后，较早发出的读状态请求晚回来时丢掉，免得旧结果盖掉新的。
  let generation = 0

  const load = async () => {
    const current = ++generation
    if (authStore.status !== 'authenticated') {
      status.value = null
      return
    }
    try {
      const next = await api.getStatus()
      if (current === generation) status.value = next
    } catch {
      if (current === generation) status.value = null
    }
  }

  watch(
    () => [authStore.status, authStore.userId] as const,
    () => {
      messageKey.value = null
      void load()
    },
    { immediate: true },
  )

  const offer = computed(() => trialOffer(authStore.status, status.value))

  const start = async () => {
    if (starting.value || offer.value !== 'available') return
    starting.value = true
    messageKey.value = null
    const current = ++generation
    let refreshIdentity = true
    try {
      const next = await api.start()
      if (current === generation) status.value = next
    } catch (error) {
      messageKey.value = trialErrorKey(error)
      // 409 说明页面落后于服务端（别处已领过、已经是会员）：重读一次让入口跟上；别的失败留着按钮再试。
      refreshIdentity = messageKey.value !== 'membership.trial.failed'
      if (refreshIdentity) await load()
    } finally {
      starting.value = false
    }
    if (refreshIdentity) await authStore.fetchMe().catch(() => undefined)
  }

  return { offer, status, starting, messageKey, start }
}
