import { computed, onBeforeUnmount, onMounted, ref, watch, type Ref } from 'vue'

const MAX_ACTIVE_PREVIEWS = 3

type Candidate = {
  element: Ref<HTMLElement | undefined>
  enabled: () => boolean
  attached: Ref<boolean>
  visible: Ref<boolean>
  nearby: boolean
  root?: HTMLElement | null
  order: number
}

const candidates = new Set<Candidate>()
let nextOrder = 0
let frame = 0

function rebalance() {
  frame = 0
  const ranked = [...candidates].flatMap(candidate => {
    const element = candidate.element.value
    if (!element || !candidate.enabled() || !candidate.nearby) return []
    const bounds = element.getBoundingClientRect()
    const viewport = candidate.root?.getBoundingClientRect() ?? { top: 0, right: innerWidth, bottom: innerHeight, left: 0 }
    const onScreen = bounds.bottom > viewport.top && bounds.top < viewport.bottom
      && bounds.right > viewport.left && bounds.left < viewport.right
    const center = Math.max(viewport.top, Math.min(viewport.bottom, (bounds.top + bounds.bottom) / 2))
    return [{ candidate, onScreen, distance: Math.abs(center - (viewport.top + viewport.bottom) / 2) }]
  }).sort((a, b) => Number(b.onScreen) - Number(a.onScreen) || a.distance - b.distance || a.candidate.order - b.candidate.order)

  const active = new Set(ranked.slice(0, MAX_ACTIVE_PREVIEWS).map(entry => entry.candidate))
  const onScreen = new Map(ranked.map(entry => [entry.candidate, entry.onScreen]))
  for (const candidate of candidates) {
    candidate.attached.value = active.has(candidate)
    candidate.visible.value = active.has(candidate) && Boolean(onScreen.get(candidate))
  }
}

function scheduleRebalance() {
  if (!frame) frame = requestAnimationFrame(rebalance)
}

/**
 * Keep a hard cap on active media elements. Some mobile browsers only grant a
 * few simultaneous video decoder slots; leaving every visited clip mounted can
 * make later cards wait forever in `play()`. The three cards closest to the
 * viewport centre win, and media is released as soon as it leaves the queue.
 */
export function useViewportPreview(element: Ref<HTMLElement | undefined>, enabled: () => boolean) {
  const attached = ref(false)
  const visible = ref(false)
  let observer: IntersectionObserver | undefined
  let scrollRoot: HTMLElement | undefined
  const candidate: Candidate = { element, enabled, attached, visible, nearby: false, order: nextOrder++ }

  onMounted(() => {
    const target = element.value!
    candidate.root = target.closest('.ui-library') as HTMLElement | null
    scrollRoot = candidate.root ?? undefined
    candidates.add(candidate)
    observer = new IntersectionObserver(([entry]) => {
      candidate.nearby = entry?.isIntersecting ?? false
      scheduleRebalance()
    }, { root: candidate.root, rootMargin: '240px 0px', threshold: 0 })
    observer.observe(target)
    scrollRoot?.addEventListener('scroll', scheduleRebalance, { passive: true })
    scheduleRebalance()
  })
  watch(enabled, scheduleRebalance)
  onBeforeUnmount(() => {
    observer?.disconnect()
    scrollRoot?.removeEventListener('scroll', scheduleRebalance)
    candidates.delete(candidate)
    attached.value = false
    visible.value = false
    scheduleRebalance()
  })
  return { attached, playing: computed(() => attached.value && visible.value && enabled()) }
}
