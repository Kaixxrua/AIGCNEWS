import type { Directive } from 'vue'
import { boxWithin } from './indicator'
import { EASE_IN, EASE_OUT, canAnimate, glideSpring } from './motion'

/**
 * v-reflow：按内容排布的一面墙（瀑布流、卡片网格）换了一批内容或重新排列时逐项过渡，取代整面墙一帧跳变。
 * 墙刚出现时各项由近及远依次浮现；之后 key 每变一次：
 * - 前后都在的项（按 data-reflow-key 认，换了列被重建的也算）从原来的位置滑到新位置；
 * - 新出现的项从墙上看得见的左上角起由近及远依次浮现，像一道波纹铺开；
 * - 离开的项在原处缩小淡出；整批都换掉时（翻页、换日期）直接撤下，免得新旧两批叠成重影。
 * 墙须是定位元素并自成层叠上下文：离开的项叠在墙的底层淡出，不压住滑过来的项。
 */
export interface ReflowOptions {
  key: unknown
  /** 新项从哪个方向浮现（px），比如翻页时从翻去的一侧进来；默认自下而上。 */
  x?: number
  y?: number
}

interface Place { x: number; y: number; w: number; h: number }
interface Snapshot extends Place { el: HTMLElement }

const ITEM = '[data-reflow-key]'
const GLIDE_MS = 560
const ENTER_MS = 400
const FADE_MS = 260
const LEAVE_MS = 220
const LEAVE_SCALE = '0.94'
// 波纹每毫秒推进的距离（px）与最晚的起步时间：一整屏约 0.2 秒全部起步，不留大片空白等着。
const RIPPLE_SPEED = 6
const RIPPLE_MAX_MS = 200
// 有项留下时，新项等离开的项淡掉一些、留下的项让开位置再进来。
const ENTER_AFTER_LEAVE_MS = 120
// 视口外这么远的项不做过渡：看不见，也省得一面长墙全体起动画。
const OFFSCREEN_PX = 200

const snapshots = new WeakMap<HTMLElement, Map<string, Snapshot>>()

const itemsOf = (wall: HTMLElement) => Array.from(wall.querySelectorAll<HTMLElement>(ITEM))

/** 祖先的缩放（大屏 zoom）：屏幕上的 1px 折合墙自身坐标里的多少。 */
const zoomOf = (wall: HTMLElement, origin: DOMRect) => (wall.offsetWidth ? origin.width / wall.offsetWidth : 1)

/** 各项此刻在屏幕上的位置（含进行中的滑动），换算成墙的内边距盒坐标。 */
function snapshot(wall: HTMLElement): Map<string, Snapshot> {
  const origin = wall.getBoundingClientRect()
  const zoom = zoomOf(wall, origin)
  const places = new Map<string, Snapshot>()
  for (const el of itemsOf(wall)) {
    const key = el.dataset.reflowKey
    if (!key || places.has(key)) continue
    const rect = el.getBoundingClientRect()
    places.set(key, {
      el,
      x: (rect.left - origin.left) / zoom - wall.clientLeft,
      y: (rect.top - origin.top) / zoom - wall.clientTop,
      w: rect.width / zoom,
      h: rect.height / zoom,
    })
  }
  return places
}

/** 墙坐标里的一块是否在视口附近。 */
function onScreen(wall: HTMLElement, origin: DOMRect, zoom: number, place: Place): boolean {
  const top = origin.top + (place.y + wall.clientTop) * zoom
  return top + place.h * zoom > -OFFSCREEN_PX && top < window.innerHeight + OFFSCREEN_PX
}

/** 离开的项：放回墙的底层，钉在原来的位置上缩小淡出，播完摘掉。 */
function leave({ el, x, y, w, h }: Snapshot, wall: HTMLElement): void {
  if (el.isConnected) return
  el.removeAttribute('data-reflow-key')
  el.setAttribute('aria-hidden', 'true')
  el.inert = true
  Object.assign(el.style, {
    position: 'absolute',
    left: `${x}px`,
    top: `${y}px`,
    width: `${w}px`,
    height: `${h}px`,
    margin: '0',
    zIndex: '-1',
    pointerEvents: 'none',
  })
  wall.appendChild(el)
  const out = el.animate(
    [{ opacity: 1, scale: '1' }, { opacity: 0, scale: LEAVE_SCALE }],
    { duration: LEAVE_MS, easing: EASE_IN, fill: 'forwards' },
  )
  out.id = 'reflow-leave'
  const remove = () => el.remove()
  out.addEventListener('finish', remove)
  out.addEventListener('cancel', remove)
}

/** 新项：从墙在视口里露出来的左上角起，离得越远起步越晚。 */
function enter(wall: HTMLElement, items: HTMLElement[], { x = 0, y = 14 }: ReflowOptions, after = 0): void {
  const origin = wall.getBoundingClientRect()
  const zoom = zoomOf(wall, origin)
  const fromX = Math.max(0, -origin.left) / zoom
  const fromY = Math.max(0, -origin.top) / zoom
  for (const el of items) {
    const place = boxWithin(wall, el)
    if (!onScreen(wall, origin, zoom, place)) continue
    const distance = Math.max(0, place.x - fromX) + Math.max(0, place.y - fromY)
    const delay = after + Math.min(RIPPLE_MAX_MS, distance / RIPPLE_SPEED)
    // 淡入与位移分开：下一轮重排只接管位移，淡入照常播完。
    el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: FADE_MS, delay, easing: EASE_OUT, fill: 'backwards' }).id = 'reflow-fade'
    el.animate([{ translate: `${x}px ${y}px` }, { translate: '0px 0px' }], { duration: ENTER_MS, delay, easing: EASE_OUT, fill: 'backwards' }).id = 'reflow-move'
  }
}

export const vReflow: Directive<HTMLElement, ReflowOptions> = {
  mounted(wall, { value }) {
    if (canAnimate(wall)) enter(wall, itemsOf(wall), value)
  },
  beforeUpdate(wall, { value, oldValue }) {
    if (Object.is(value.key, oldValue?.key) || !canAnimate(wall)) return
    snapshots.set(wall, snapshot(wall))
  },
  updated(wall, { value }) {
    const from = snapshots.get(wall)
    if (!from) return
    snapshots.delete(wall)
    const origin = wall.getBoundingClientRect()
    const zoom = zoomOf(wall, origin)
    const items = itemsOf(wall)
    const keys = new Set(items.map((el) => el.dataset.reflowKey))
    const kept = items.some((el) => from.has(el.dataset.reflowKey ?? ''))
    if (kept) for (const [key, old] of from) if (!keys.has(key)) leave(old, wall)
    const glide = glideSpring()
    const added: HTMLElement[] = []
    for (const el of items) {
      const old = from.get(el.dataset.reflowKey ?? '')
      if (!old) {
        added.push(el)
        continue
      }
      // 新位置按布局量（不含进行中的位移），和屏幕上的旧位置之差就是要滑的距离；滑到一半又变时从此刻接着滑。
      const place = boxWithin(wall, el)
      const dx = old.x - place.x
      const dy = old.y - place.y
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) continue
      for (const running of el.getAnimations()) if (running.id === 'reflow-glide' || running.id === 'reflow-move') running.cancel()
      if (!onScreen(wall, origin, zoom, place) && !onScreen(wall, origin, zoom, old)) continue
      el.animate([{ translate: `${dx}px ${dy}px` }, { translate: '0px 0px' }], { duration: GLIDE_MS, easing: glide }).id = 'reflow-glide'
    }
    enter(wall, added, value, kept ? ENTER_AFTER_LEAVE_MS : 0)
  },
}
