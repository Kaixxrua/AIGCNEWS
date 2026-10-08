import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch, type Ref } from 'vue'
import { isNavigationFailure, NavigationFailureType, useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/authStore'
import { useFeatureFlags } from '@/composables/useFeatureFlags'
import { useContactPageConfig } from '@/composables/useContactPageConfig'
import { useLoginPrompt } from '@/composables/useLoginPrompt'
import { useQuickSearch } from '@/composables/useQuickSearch'
import { showToast } from '@/composables/useToast'
import { fetchOnboarding, updateOnboarding } from '@/services/onboarding/onboardingApi'
import { availableSteps } from './steps'
import { tourActive, tourRequest } from './signals'
import {
  MEMORY_KEY, claimGuest, isTerminal, readProgress, readTerminal, saveProgress, saveTerminal,
  type Owner, type TerminalStatus,
} from './persistence'

export function useTour(blocked: Ref<boolean>) {
  const auth = useAuthStore()
  const router = useRouter()
  const route = useRoute()
  const { t } = useI18n()
  const { featureFlags, ensureFeatureFlags } = useFeatureFlags()
  const { contactPageConfig, ensureContactPageConfig } = useContactPageConfig()
  const login = useLoginPrompt()
  const quickSearch = useQuickSearch()
  const steps = computed(() => availableSteps({ x: featureFlags.value.xSource, contact: contactPageConfig.value.enabled }))
  const phase = ref<'idle' | 'welcome' | 'tour'>('idle')
  const index = ref(0)
  const busy = ref(false)
  const navigationFailed = ref(false)
  const step = computed(() => steps.value[index.value])
  const owner = computed<Owner>(() => auth.isLoggedIn && auth.userId !== null ? `user:${auth.userId}` : 'guest')
  let returnTo = '/'
  let manual = false
  let ready = false
  let alive = true
  let context = 0
  let navigationRevision = 0
  let navigation: Promise<unknown> = Promise.resolve()
  let previousFocus: HTMLElement | null = null
  let syncing = false
  let syncQueued = false
  let returnScroll: Array<{ element: Element; top: number; left: number }> = []
  const canReplay = computed(() => ['authenticated', 'anonymous'].includes(auth.status)
    && !blocked.value && !login.isOpen.value && !login.isResetOpen.value
    && !quickSearch.open.value
    && !['register', 'oauth-callback', 'oauth-action-callback', 'not-found'].includes(String(route.name)))
  const eligible = computed(() => canReplay.value && !route.meta.requiresAdmin && !route.meta.requiresAuth)

  function rememberPlace() {
    returnTo = route.fullPath
    previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    returnScroll = Array.from(document.querySelectorAll('.app-shell, .app-content, .view-container, .view-container *'))
      .filter(element => element.scrollTop || element.scrollLeft)
      .map(element => ({ element, top: element.scrollTop, left: element.scrollLeft }))
  }

  function go(next: number) {
    const target = steps.value[next]
    if (!target) return
    const revision = ++navigationRevision
    phase.value = 'tour'
    index.value = next
    busy.value = true
    navigationFailed.value = false
    saveProgress(owner.value, { step: target.id, returnTo, manual })
    navigation = (async () => {
      try {
        const failure = route.fullPath === router.resolve(target.route).fullPath ? undefined : await router.replace(target.route)
        await nextTick()
        if (alive && revision === navigationRevision) {
          navigationFailed.value = !!failure && !isNavigationFailure(failure, NavigationFailureType.duplicated)
        }
      } catch {
        if (alive && revision === navigationRevision) navigationFailed.value = true
      } finally {
        if (alive && revision === navigationRevision) busy.value = false
      }
    })()
  }

  async function syncAccount(notify = false): Promise<boolean> {
    if (!auth.isLoggedIn || !auth.token) return false
    if (syncing) { if (notify) syncQueued = true; return false }
    const revision = context
    const account = owner.value
    const token = auth.token
    syncing = true
    claimGuest(account)
    try {
      const local = readTerminal(account)
      let status = local?.pending
        ? await updateOnboarding(token, local.status)
        : await fetchOnboarding(token)
      if (!alive || revision !== context) return false
      if (status === 'unseen' && local) status = await updateOnboarding(token, local.status)
      if (!alive || revision !== context) return false
      if (isTerminal(status)) saveTerminal(account, status, false)
      return true
    } catch {
      if (alive && revision === context && notify) showToast(t('onboarding.pendingSync'))
      return false
    } finally {
      if (revision === context) {
        syncing = false
        if (syncQueued) { syncQueued = false; void syncAccount(true) }
      }
    }
  }

  async function finish(status: TerminalStatus, record = true) {
    if (phase.value === 'idle') return
    const account = owner.value
    const destination = returnTo
    const revision = ++navigationRevision
    if (record) saveTerminal(account, status)
    saveProgress(account, null)
    phase.value = 'idle'
    busy.value = true
    if (record) void syncAccount(true)
    await navigation
    if (!alive || revision !== navigationRevision) return
    try {
      if (route.fullPath !== destination) await router.replace(destination)
      await nextTick()
      for (const saved of returnScroll) {
        if (saved.element.isConnected) { saved.element.scrollTop = saved.top; saved.element.scrollLeft = saved.left }
      }
      if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true })
      else document.querySelector<HTMLElement>('[data-tour="help"]')?.focus({ preventScroll: true })
    } finally {
      if (alive && revision === navigationRevision) busy.value = false
    }
  }

  function offer() {
    if (!ready || !alive || !eligible.value || phase.value !== 'idle' || busy.value) return
    if (document.querySelector('dialog[open]')) return
    const progress = readProgress(owner.value)
    if (progress && (progress.manual || !readTerminal(owner.value))) {
      returnTo = progress.returnTo
      manual = progress.manual
      go(Math.max(0, steps.value.findIndex(item => item.id === progress.step)))
    } else if (!readTerminal(owner.value)) {
      rememberPlace()
      manual = false
      phase.value = 'welcome'
    }
  }

  async function initialize() {
    const revision = ++context
    syncing = false
    syncQueued = false
    ready = false
    if (phase.value !== 'idle') { ++navigationRevision; phase.value = 'idle'; busy.value = false }
    if (auth.status !== 'authenticated' && auth.status !== 'anonymous') return
    await Promise.all([ensureFeatureFlags(), ensureContactPageConfig()])
    if (!alive || revision !== context) return
    const synced = owner.value === 'guest' || await syncAccount()
    if (!alive || revision !== context) return
    // On a new device, wait for the account response instead of flashing a
    // welcome dialog before discovering that the tour was already dismissed.
    ready = synced
    offer()
  }

  function replay() {
    if (!canReplay.value || busy.value || phase.value !== 'idle') return
    rememberPlace()
    manual = true
    phase.value = 'welcome'
  }
  async function retrySync() {
    if (auth.isLoggedIn) {
      if (await syncAccount()) {
        ready = true
        if (!manual && phase.value === 'welcome' && readTerminal(owner.value)) phase.value = 'idle'
        offer()
      }
    }
  }
  function storageChanged(event: StorageEvent) {
    if (event.key !== MEMORY_KEY) return
    if (!manual && readTerminal(owner.value) && phase.value !== 'idle') {
      // Another tab already persisted its own choice. Closing this overlay must
      // not create a new guest choice that could be claimed by another account.
      void finish(readTerminal(owner.value)!.status, false)
    }
  }
  watch(() => [auth.status, auth.userId, auth.token], initialize, { immediate: true })
  watch([eligible, () => route.fullPath], offer)
  watch(tourRequest, replay)
  watch(phase, value => { tourActive.value = value !== 'idle' }, { flush: 'sync' })
  onMounted(() => {
    window.addEventListener('online', retrySync)
    window.addEventListener('focus', retrySync)
    window.addEventListener('storage', storageChanged)
  })
  onBeforeUnmount(() => {
    alive = false
    ++context
    ++navigationRevision
    tourActive.value = false
    window.removeEventListener('online', retrySync)
    window.removeEventListener('focus', retrySync)
    window.removeEventListener('storage', storageChanged)
  })
  return {
    phase, index, step, steps, busy, navigationFailed,
    start: () => go(0),
    previous: () => { if (!busy.value) go(index.value - 1) },
    next: () => {
      if (busy.value) return
      if (index.value === steps.value.length - 1) void finish('completed')
      else go(index.value + 1)
    },
    skip: () => { void finish('skipped') },
  }
}
