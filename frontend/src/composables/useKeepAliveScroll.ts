import { nextTick, onActivated, onBeforeUnmount, onDeactivated, type Ref } from 'vue'
import { useEventListener } from '@vueuse/core'

/** Remember nested scroll containers while a cached view is detached from the document. */
export function useKeepAliveScroll(root: Ref<HTMLElement | null>) {
  const positions = new Map<HTMLElement, { top: number; left: number }>()
  let active = true
  useEventListener(root, 'scroll', (event: Event) => {
    const element = event.target
    if (!active || !(element instanceof HTMLElement) || !element.isConnected) return
    for (const saved of positions.keys()) if (!root.value?.contains(saved)) positions.delete(saved)
    positions.set(element, { top: element.scrollTop, left: element.scrollLeft })
  }, { capture: true, passive: true })
  onDeactivated(() => { active = false })
  onActivated(() => {
    active = true
    void nextTick(() => {
      if (!active) return
      for (const [element, position] of positions) {
        if (!root.value?.contains(element)) {
          positions.delete(element)
          continue
        }
        element.scrollTop = position.top
        element.scrollLeft = position.left
      }
    })
  })
  onBeforeUnmount(() => positions.clear())
}
