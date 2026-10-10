import { onBeforeUnmount, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import { createAccountVisitTracker } from '@/services/visit/accountVisit'

export function useAccountVisit(): void {
  const auth = useAuthStore()
  const route = useRoute()
  const record = createAccountVisitTracker()
  let timer: ReturnType<typeof setTimeout> | undefined
  let disposed = false
  const tick = async () => {
    clearTimeout(timer)
    const delay = await record(
      auth.isLoggedIn ? auth.userId : null, auth.token, document.visibilityState === 'visible',
    )
    if (!disposed) {
      clearTimeout(timer)
      timer = setTimeout(() => { void tick() }, Math.max(50, Math.min(delay, 30_000)))
    }
  }
  const stop = watch(
    () => [auth.isLoggedIn, auth.userId, auth.token, route.fullPath],
    () => { void tick() }, { immediate: true },
  )
  document.addEventListener('visibilitychange', tick)
  window.addEventListener('online', tick)
  onBeforeUnmount(() => {
    disposed = true
    stop()
    clearTimeout(timer)
    document.removeEventListener('visibilitychange', tick)
    window.removeEventListener('online', tick)
  })
}
