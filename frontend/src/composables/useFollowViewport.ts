import { nextTick, onMounted, onUnmounted, ref, type Ref } from 'vue'

export const useFollowViewport = (viewportRef: Ref<HTMLElement | null>) => {
  const autoScroll = ref(true)

  const onWheelHandler = (event: WheelEvent) => {
    if (event.deltaY < 0) autoScroll.value = false
  }

  let lastTouchY = 0
  const onTouchStart = (event: TouchEvent) => {
    lastTouchY = event.touches[0]?.clientY ?? 0
  }

  const onTouchMoveHandler = (event: TouchEvent) => {
    const currentY = event.touches[0]?.clientY ?? 0
    if (currentY > lastTouchY) autoScroll.value = false
    lastTouchY = currentY
  }

  const scrollToBottom = async () => {
    if (!autoScroll.value) return
    await nextTick()
    const element = viewportRef.value
    if (!element) return
    element.scrollTop = element.scrollHeight
  }

  const resetAutoScroll = () => {
    autoScroll.value = true
  }

  const resumeAutoScroll = () => {
    resetAutoScroll()
    void scrollToBottom()
  }

  onMounted(() => {
    const element = viewportRef.value
    if (element) {
      element.addEventListener('wheel', onWheelHandler, { passive: true })
      element.addEventListener('touchstart', onTouchStart, { passive: true })
      element.addEventListener('touchmove', onTouchMoveHandler, { passive: true })
    }
  })

  onUnmounted(() => {
    const element = viewportRef.value
    if (element) {
      element.removeEventListener('wheel', onWheelHandler)
      element.removeEventListener('touchstart', onTouchStart)
      element.removeEventListener('touchmove', onTouchMoveHandler)
    }
  })

  return {
    autoScroll,
    resetAutoScroll,
    scrollToBottom,
    resumeAutoScroll,
  }
}
