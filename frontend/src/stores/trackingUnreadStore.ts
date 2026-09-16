import { computed, onScopeDispose, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import { useAuthStore } from '@/stores/authStore'
import { trackingApi } from '@/services/tracking/trackingApi'
import type { TrackingUnread } from '@/features/tracking/trackingModel'

export const useTrackingUnreadStore = defineStore('trackingUnread', () => {
  const auth = useAuthStore()
  const latest = ref(0)
  const read = ref(0)
  const hasUnread = computed(() => latest.value > read.value)
  let generation = 0
  let polling = false
  let timer: ReturnType<typeof setInterval> | undefined
  const pendingReads = new Set<number>()
  const identity = () => JSON.stringify([auth.token, auth.userId, auth.isLoggedIn])

  function merge(status: TrackingUnread) {
    // Late polls must not resurrect an already acknowledged issue.
    latest.value = Math.max(latest.value, status.latest_digest_id)
    read.value = Math.max(read.value, status.last_read_digest_id)
  }

  async function refresh() {
    if (!auth.isLoggedIn || document.hidden || polling) return
    const owner = identity()
    const revision = generation
    polling = true
    try {
      const status = await trackingApi.unread()
      if (revision === generation && owner === identity()) merge(status)
    } catch {
      // A transient failure never clears a known unread notification.
    } finally {
      if (revision === generation) polling = false
    }
  }

  async function markRead(id: number) {
    if (!auth.isLoggedIn || document.hidden || !Number.isSafeInteger(id) || id <= 0) return
    if (id <= read.value || pendingReads.has(id)) return
    const owner = identity()
    const revision = generation
    latest.value = Math.max(latest.value, id)
    pendingReads.add(id)
    try {
      const status = await trackingApi.markRead(id)
      if (revision === generation && owner === identity()) merge(status)
    } catch {
      // Keep the dot; the visible results will retry their receipt.
    } finally {
      if (revision === generation) pendingReads.delete(id)
    }
  }

  watch(identity, () => {
    generation++
    polling = false
    latest.value = read.value = 0
    pendingReads.clear()
    clearInterval(timer)
    timer = undefined
    if (auth.isLoggedIn) {
      void refresh()
      timer = setInterval(() => { void refresh() }, 60_000)
    }
  }, { immediate: true, flush: 'sync' })

  const onVisible = () => { void refresh() }
  document.addEventListener('visibilitychange', onVisible)
  window.addEventListener('focus', onVisible)
  onScopeDispose(() => {
    generation++
    clearInterval(timer)
    document.removeEventListener('visibilitychange', onVisible)
    window.removeEventListener('focus', onVisible)
  })
  return { hasUnread, refresh, markRead }
})
