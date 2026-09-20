import { computed, onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

/** Play every visible card and release offscreen decoders immediately. */
export function useViewportPreview(element: Ref<HTMLElement | undefined>, enabled: () => boolean) {
  const visible = ref(false)
  let observer: IntersectionObserver | undefined

  onMounted(() => {
    const target = element.value
    if (!target) return
    // The viewport root also accounts for clipping by the gallery scrollbox.
    observer = new IntersectionObserver(([entry]) => {
      visible.value = Boolean(entry?.isIntersecting && entry.intersectionRatio > 0)
    }, { threshold: [0, 0.001] })
    observer.observe(target)
  })
  onBeforeUnmount(() => {
    observer?.disconnect()
    visible.value = false
  })
  const attached = computed(() => visible.value && enabled())
  return { attached, playing: attached }
}
