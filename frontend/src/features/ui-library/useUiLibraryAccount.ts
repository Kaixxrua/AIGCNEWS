import { computed, inject, onBeforeUnmount, provide, ref, watch, type InjectionKey, type Ref } from 'vue'
import { useAuthStore } from '@/stores/authStore'
import { useLoginPrompt } from '@/composables/useLoginPrompt'
import { api } from '@/services/http/apiClient'
import type { UiLanguage } from './catalog'

export interface Engagement { template_id: string; likes: number; score: number; liked: boolean }
interface Quota { limit: number | null; remaining: number | null; resets_at: string }
export type Ranking = 'all' | 'new' | 'daily' | 'weekly' | 'monthly' | 'liked'
const key: InjectionKey<ReturnType<typeof createAccount>> = Symbol('ui-library-account')

function createAccount(lang: Ref<UiLanguage>, ranking: Ref<Ranking>, beforeLogin: () => Promise<void>) {
  const auth = useAuthStore()
  const stats = ref<Record<string, Engagement>>({})
  const quota = ref<Quota | null>(null)
  const loadError = ref(false)
  const quotaError = ref(false)
  const liking = ref(new Set<string>())
  const zh = computed(() => lang.value === 'zh')
  let generation = 0
  let stopped = false
  // Reuse a receipt after a clipboard/network failure; a retry must not cost twice.
  const pending = new Map<string, string>()
  async function requireAccount() {
    await auth.ensureInitialized()
    if (auth.isLoggedIn) return true
    const target = `${window.location.pathname}${window.location.search}`
    await beforeLogin()
    useLoginPrompt().requestLogin(target)
    return false
  }
  async function refresh() {
    const current = ++generation
    const period = ['daily', 'weekly', 'monthly'].includes(ranking.value) ? ranking.value : 'daily'
    const results = await Promise.allSettled([
      api.get<{ items: Engagement[] }>('/ui-library/engagement', { params: { period } }),
      auth.isLoggedIn ? api.get<Quota>('/ui-library/copy-quota') : Promise.resolve(null),
    ])
    if (stopped || current !== generation) return
    const [engagement, allowance] = results
    loadError.value = engagement.status === 'rejected' || !Array.isArray(engagement.value.data?.items)
    if (engagement.status === 'fulfilled' && !loadError.value) stats.value = Object.fromEntries(engagement.value.data.items.map(item => [item.template_id, item]))
    else stats.value = {}
    quotaError.value = allowance.status === 'rejected'
    quota.value = allowance.status === 'fulfilled' && allowance.value ? allowance.value.data : null
  }
  async function like(id: string) {
    if (liking.value.has(id) || !await requireAccount()) return
    liking.value.add(id)
    try {
      await api.put(`/ui-library/${id}/like`, { liked: !stats.value[id]?.liked })
      await refresh()
    } finally { liking.value.delete(id) }
  }
  async function copyValue(id: string, kind: 'source' | 'prompt', value: string) {
    if (!await requireAccount()) return false
    const userId = auth.userId
    const action = `${userId}:${id}:${kind}`
    generation++
    const requestId = pending.get(action) ?? crypto.randomUUID()
    pending.set(action, requestId)
    try {
      const result = await api.post<Quota>(`/ui-library/${id}/copy`, { kind, request_id: requestId })
      if (auth.userId !== userId) throw new Error('Authentication changed')
      quota.value = result.data
      quotaError.value = false
    } catch (error) {
      const status = (error as { response?: { status?: number } }).response?.status
      if (status === 429) {
        pending.delete(action)
        await refresh()
        throw new Error(zh.value ? '今日 5 次复制额度已用完，明日恢复；VIP 不限次数。' : 'Your 5 daily copies are used. Resets tomorrow; VIP has unlimited copies.')
      }
      throw new Error(zh.value ? '暂时无法确认复制额度，请重试。' : 'Could not verify your copy allowance. Please retry.')
    }
    try { await navigator.clipboard.writeText(value) }
    catch { throw new Error(zh.value ? '剪贴板写入失败，请重试；本次重试不重复扣额度。' : 'Clipboard access failed. Retry without another charge.') }
    pending.delete(action)
    return true
  }
  const quotaText = computed(() => {
    if (!auth.isLoggedIn) return zh.value ? '登录后每天免费复制 5 次' : 'Sign in for 5 free copies per day'
    if (quotaError.value) return zh.value ? '复制额度暂不可用，请稍后重试' : 'Copy allowance unavailable. Please retry later.'
    if (!quota.value) return zh.value ? '正在确认复制额度' : 'Checking copy allowance'
    if (quota.value.limit === null) return zh.value ? 'VIP · 复制不限次数' : 'VIP · Unlimited copies'
    return zh.value ? `今日剩余 ${quota.value.remaining} / 5 次 · 源码与提示词共用` : `${quota.value.remaining} / 5 copies left today · Source + prompt`
  })
  watch(() => [ranking.value, auth.userId, auth.status, auth.user?.membership_tier], () => {
    quota.value = null
    stats.value = {}
    void refresh()
  }, { immediate: true })
  watch(() => auth.userId, () => pending.clear())
  const timer = setInterval(() => { if (document.visibilityState === 'visible') void refresh() }, 60_000)
  onBeforeUnmount(() => { stopped = true; generation++; clearInterval(timer) })
  return { stats, quotaText, loadError, liking, requireAccount, refresh, like, copyValue }
}

export function provideUiLibraryAccount(lang: Ref<UiLanguage>, ranking: Ref<Ranking>, beforeLogin: () => Promise<void>) {
  const account = createAccount(lang, ranking, beforeLogin)
  provide(key, account)
  return account
}
export function useUiLibraryAccount() {
  const account = inject(key)
  if (!account) throw new Error('UI library account context missing')
  return account
}
