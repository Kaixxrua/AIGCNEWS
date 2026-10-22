import { onActivated, onBeforeUnmount, onDeactivated, ref, watch, type Ref } from 'vue'
import { useEventListener } from '@vueuse/core'

const CONCURRENCY = 2
/** 每页只预取屏幕附近至多十二项，避免把整份目录的 GitHub 配额花在猜测上。 */
export const PEEK_WARMUP_LIMIT = 12

interface Options {
  enabled: Ref<boolean>
  rows: Ref<HTMLElement | null>
  keys: Ref<readonly string[]>
  repoOf: (key: string) => string
  load: (repoId: string) => Promise<unknown> | undefined
}

/** 进入列表就取可见行；队列随视口和翻页更新，悬停取数与它共用去重缓存。 */
export function useProjectPeekWarmup({ enabled, rows, keys, repoOf, load }: Options) {
  const live = ref(true)
  const visible = new Set<string>()
  const attempted = new Set<string>()
  let observer: IntersectionObserver | undefined
  let page = ''
  let running = 0
  let stopped = false
  const usable = () => !stopped && live.value && enabled.value && !document.hidden
  const drain = () => {
    if (!usable()) return
    for (const repoId of visible) {
      if (running >= CONCURRENCY || attempted.size >= PEEK_WARMUP_LIMIT) break
      if (attempted.has(repoId)) continue
      attempted.add(repoId)
      running++
      Promise.resolve(load(repoId)).catch(() => {}).finally(() => {
        running--
        drain()
      })
    }
  }
  const track = () => {
    observer?.disconnect()
    observer = undefined
    visible.clear()
    const nextPage = keys.value.join('\n')
    if (nextPage !== page) {
      page = nextPage
      attempted.clear()
    }
    if (!usable() || !rows.value || typeof IntersectionObserver === 'undefined') return
    const active = new IntersectionObserver((entries) => {
      if (observer !== active) return
      for (const entry of entries) {
        const key = (entry.target as HTMLElement).dataset.listKey
        const id = key ? repoOf(key) : ''
        if (!id) continue
        if (entry.isIntersecting) visible.add(id)
        else visible.delete(id)
      }
      drain()
    }, { rootMargin: '160px 0px', threshold: 0 })
    observer = active
    for (const row of rows.value.querySelectorAll<HTMLElement>('[data-list-key]')) {
      if (row.dataset.listKey && repoOf(row.dataset.listKey)) observer.observe(row)
    }
  }
  watch([enabled, live, rows, () => keys.value.join('\n')], track, { immediate: true, flush: 'post' })
  useEventListener(document, 'visibilitychange', track)
  onActivated(() => { live.value = true })
  onDeactivated(() => { live.value = false })
  onBeforeUnmount(() => {
    stopped = true
    observer?.disconnect()
    visible.clear()
  })
}
