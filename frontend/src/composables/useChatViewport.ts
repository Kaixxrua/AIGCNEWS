import { nextTick, onMounted, onUnmounted, ref, watch, type Ref } from 'vue'
import type { ChatMessage } from '../stores/chatStore'

export const useChatViewport = (
  listRef: Ref<HTMLElement | null>,
  messages: Ref<ChatMessage[]>,
) => {
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

  let boundElement: HTMLElement | null = null
  onMounted(() => {
    boundElement = listRef.value
    boundElement?.addEventListener('wheel', onWheelHandler, { passive: true })
    boundElement?.addEventListener('touchstart', onTouchStart, { passive: true })
    boundElement?.addEventListener('touchmove', onTouchMoveHandler, { passive: true })
  })

  const scrollToBottom = async () => {
    if (!autoScroll.value) return
    await nextTick()
    const element = listRef.value
    if (!element) return
    element.scrollTop = element.scrollHeight
  }

  let scrollRafId: number | null = null
  const scheduleScroll = () => {
    if (!autoScroll.value || scrollRafId !== null) return
    scrollRafId = requestAnimationFrame(async () => {
      scrollRafId = null
      await scrollToBottom()
    })
  }

  const resumeAutoScroll = () => {
    autoScroll.value = true
    void scrollToBottom()
  }

  watch(
    () => messages.value.map((message) => `${message.role}:${message.content.length}:${message.thinking.length}`).join('|'),
    scheduleScroll,
  )

  onUnmounted(() => {
    boundElement?.removeEventListener('wheel', onWheelHandler)
    boundElement?.removeEventListener('touchstart', onTouchStart)
    boundElement?.removeEventListener('touchmove', onTouchMoveHandler)
    if (scrollRafId !== null) cancelAnimationFrame(scrollRafId)
  })

  return {
    autoScroll,
    scrollToBottom,
    resumeAutoScroll,
  }
}
