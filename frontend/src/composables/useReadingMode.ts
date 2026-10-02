import { onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { useEventListener } from '@vueuse/core'

/** 读报态的判定尺度（px / ms）。 */
export const READING_MODE = {
  /** 连续往下滚这么多才收起 dock。 */
  hideAfter: 48,
  /** 离顶部不到这么远时不收。 */
  hideFrom: 96,
  /** 可滚距离不到这么多的页面不收：收起后画板变高，短页面会一下子滚不动、停在收起的状态。 */
  minRoom: 240,
  /** 连续往上滚这么多就回来。 */
  revealAfter: 32,
  /** 切换后画板高度跟着变，浏览器会把滚到底的位置往回夹；这段时间里的滚动只记位置、不算方向。 */
  settleMs: 320,
  /** 屏幕底边的感应带。 */
  edge: 12,
  /** 只认占视口高度至少这么多的滚动容器（页面的主栏），侧栏、代码块之类的小滚动区不算。 */
  minScroller: 0.45,
}

/**
 * 读报态：桌面内页往下读时 dock 和页脚让出屏幕；往上滚、滚回顶部、鼠标碰到屏幕底边、按 Esc、
 * 键盘焦点走进 dock 或页脚时回来（底部拉手由调用方接 reveal）。
 * 各页面自己管滚动容器，这里在 document 上用捕获阶段统一听滚动，只认 scope 里的主滚动容器。
 */
export function useReadingMode(options: { enabled: Ref<boolean>; scope: Ref<HTMLElement | null> }) {
  const hidden = ref(false)
  const lastTop = new WeakMap<Element, number>()
  let lastScroller: Element | null = null
  let travel = 0
  let settling = false
  let settleTimer: ReturnType<typeof setTimeout> | undefined
  let pointerY: number | null = null

  const settle = () => {
    travel = 0
    settling = true
    clearTimeout(settleTimer)
    settleTimer = setTimeout(() => { settling = false }, READING_MODE.settleMs)
  }
  const hide = () => {
    if (hidden.value) return
    hidden.value = true
    pointerY = null
    settle()
  }
  const reveal = () => {
    if (!hidden.value) return
    hidden.value = false
    settle()
  }

  const onScroll = (event: Event) => {
    const scroller = event.target
    const scope = options.scope.value
    if (!options.enabled.value || !scope || !(scroller instanceof Element) || !scope.contains(scroller)) return
    if (scroller.clientHeight < window.innerHeight * READING_MODE.minScroller) return
    const top = scroller.scrollTop
    const previous = lastTop.get(scroller)
    lastTop.set(scroller, top)
    if (previous === undefined || scroller !== lastScroller || settling) {
      lastScroller = scroller
      travel = 0
      return
    }
    const delta = top - previous
    if (delta === 0) return
    travel = Math.sign(delta) === Math.sign(travel) ? travel + delta : delta
    if (hidden.value) {
      if (travel <= -READING_MODE.revealAfter || top <= 4) reveal()
    } else if (travel >= READING_MODE.hideAfter && top > READING_MODE.hideFrom
      && scroller.scrollHeight - scroller.clientHeight >= READING_MODE.minRoom) {
      hide()
    }
  }

  // 只认「从上面移进底边感应带」这一下：滚动时浏览器会给停着不动的鼠标补发 mousemove，收起前鼠标就停在底边也不算。
  const onPointerMove = (event: PointerEvent) => {
    if (!hidden.value || event.pointerType === 'touch') return
    const zone = window.innerHeight - READING_MODE.edge
    const previous = pointerY
    pointerY = event.clientY
    if (previous !== null && previous < zone && event.clientY >= zone) reveal()
  }
  // 屏幕底下还有任务栏时，鼠标会从窗口底边直接移出去，也算碰到了底边。
  const onPointerOut = (event: PointerEvent) => {
    if (hidden.value && event.relatedTarget === null && event.pointerType !== 'touch'
      && event.clientY >= window.innerHeight - READING_MODE.edge) reveal()
  }
  const onKeydown = (event: KeyboardEvent) => {
    if (event.key === 'Escape') reveal()
  }
  const onFocusIn = (event: FocusEvent) => {
    if (event.target instanceof Element && event.target.closest('.dock, .dock-footer')) reveal()
  }

  useEventListener(document, 'scroll', onScroll, { capture: true, passive: true })
  useEventListener(document, 'pointermove', onPointerMove, { passive: true })
  useEventListener(document, 'pointerout', onPointerOut, { passive: true })
  useEventListener(document, 'keydown', onKeydown)
  useEventListener(document, 'focusin', onFocusIn)
  watch(options.enabled, (enabled) => { if (!enabled) reveal() })
  onBeforeUnmount(() => clearTimeout(settleTimer))

  return { hidden, reveal }
}
