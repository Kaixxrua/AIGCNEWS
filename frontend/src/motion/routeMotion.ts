import { EASE_OUT, canAnimate } from './motion'

/** 页面切换方向：沿 dock 顺序前进/后退时横向滑动，dock 之外的页面从下方浮起。 */
export type RouteAxis = 'forward' | 'backward' | 'rise'

const ENTER_MS = 380
const ENTER_DELAY_MS = 50
const LEAVE_MS = 120
const SHIFT_X = 32
const SHIFT_Y = 16
// 钉位样式，以及中途被切走时 commitStyles 留下的透明度/位移。
const PINNED = ['position', 'top', 'left', 'width', 'height', 'margin', 'pointer-events', 'z-index', 'opacity', 'translate'] as const

export function routeAxis(from: number, to: number): RouteAxis {
  if (from < 0 || to < 0 || from === to) return 'rise'
  return to > from ? 'forward' : 'backward'
}

function shift(axis: RouteAxis): [number, number] {
  if (axis === 'forward') return [SHIFT_X, 0]
  if (axis === 'backward') return [-SHIFT_X, 0]
  return [0, SHIFT_Y]
}

/** 进入动画：同一实例只换查询参数（如项目库 ↔ 我的网页收藏）时也直接调用。 */
export function playEnter(el: Element, axis: RouteAxis): Animation | null {
  if (!canAnimate(el)) return null
  const [x, y] = shift(axis)
  return el.animate(
    [{ opacity: 0, translate: `${x}px ${y}px` }, { opacity: 1, translate: '0 0' }],
    { duration: ENTER_MS, delay: ENTER_DELAY_MS, easing: EASE_OUT, fill: 'backwards' },
  )
}

/**
 * <Transition :css="false"> 的钩子：离开页钉在原位快速淡出并朝反方向略移，新页面同时从行进方向滑入。
 * KeepAlive 缓存的页面离开后会被原样放回，所以钉位样式在离开结束或取消时必须清掉。
 */
export function createRouteTransition(axis: () => RouteAxis) {
  const running = new WeakMap<Element, Animation>()

  const settle = (el: Element) => {
    running.get(el)?.cancel()
    running.delete(el)
  }
  const unpin = (el: Element) => {
    const { style } = el as HTMLElement
    for (const property of PINNED) style.removeProperty(property)
  }
  const track = (el: Element, animation: Animation | null, done: () => void) => {
    if (!animation) return done()
    running.set(el, animation)
    animation.addEventListener('finish', () => done())
  }

  return {
    onBeforeLeave(el: Element) {
      const page = el as HTMLElement
      // 本身已脱离文档流的页面（固定定位的场景页）不用钉。
      if (['absolute', 'fixed'].includes(getComputedStyle(page).position)) return
      const { offsetTop, offsetLeft, offsetWidth, offsetHeight } = page
      Object.assign(page.style, {
        position: 'absolute',
        top: `${offsetTop}px`,
        left: `${offsetLeft}px`,
        width: `${offsetWidth}px`,
        height: `${offsetHeight}px`,
        margin: '0',
        pointerEvents: 'none',
        zIndex: '-1',
      })
    },
    onLeave(el: Element, done: () => void) {
      // 进入动画还没播完就又被切走：从当前透明度接着淡出，不闪回不透明。
      const entering = running.get(el)
      if (entering) {
        try {
          entering.commitStyles()
        } catch {
          // 元素未渲染时 commitStyles 会抛错，直接从当前样式淡出即可。
        }
        entering.cancel()
      }
      if (!canAnimate(el)) return done()
      const [x, y] = shift(axis())
      const animation = el.animate(
        [{ opacity: 0, translate: `${-x * 0.35}px ${-y * 0.35}px` }],
        { duration: LEAVE_MS, easing: 'cubic-bezier(.4, 0, 1, 1)', fill: 'forwards' },
      )
      track(el, animation, done)
    },
    onAfterLeave(el: Element) {
      settle(el)
      unpin(el)
    },
    onLeaveCancelled(el: Element) {
      settle(el)
      unpin(el)
    },
    onEnter(el: Element, done: () => void) {
      unpin(el)
      track(el, playEnter(el, axis()), done)
    },
    onEnterCancelled(el: Element) {
      settle(el)
    },
  }
}
