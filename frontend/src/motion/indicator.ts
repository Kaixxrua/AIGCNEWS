import type { Directive } from 'vue'
import { popSpring, prefersReducedMotion, spring } from './motion'

/**
 * v-indicator：给一组切换按钮（导航 dock、tab、分段按钮）加一枚会滑动的选中标记。
 *
 * 当前项由选择器决定，组内第一个实际渲染的匹配项即当前项。指令监听组内 class / aria 状态变化，
 * 用弹簧把标记从旧项推到新项：位置约 5% 回弹，移动时沿行进方向拖出一截“墨迹”尾巴，落定后收回。
 * 标记本身画在组的伪元素上（motion.css 统一几何，各组只管外观），指令只写
 * --indicator-x/y/w/h 与 data-indicator、data-indicator-mark 两个属性；JS 不可用时各项保留自身的选中样式。
 *
 * 各项自带手绘框、选中与未选中是两套框的组，标记滑过会被框挡住，改用 pop：新选中项像盖章一样从略小处
 * 带回弹落定。pop 只在组上没画标记时生效（mark: false，或样式把标记伪元素设成 content: none），
 * 所以同一组可以在一套样式里滑动、在另一套里盖章，由 CSS 决定。
 */
export interface IndicatorOptions {
  /** 当前项选择器。 */
  active: string
  /** 标记画在组的哪个伪元素上，默认 before；false 不画滑动标记（配合 pop 使用）。 */
  mark?: 'before' | 'after' | false
  /** 当前项变化会让组内各项重排（如选中项字号更大）时，对组的直接子元素做 FLIP 过渡。 */
  flip?: boolean
  /**
   * 点击即出发：匹配此选择器的项（通常是路由链接）被点击时标记立刻滑过去，不等异步路由切换完成；
   * 若一段时间内当前项没有跟着变（导航被取消或重定向），标记再滑回当前项。
   */
  follow?: string
  /** 组上没画滑动标记时，新选中项盖章式弹入。 */
  pop?: boolean
}
export type IndicatorValue = string | IndicatorOptions

interface Box { x: number; y: number; w: number; h: number }
interface Spring { p: number; v: number }
interface Snapshot extends Box { fontSize: number }

interface IndicatorState {
  options: IndicatorOptions
  active: HTMLElement | null
  pending: HTMLElement | null
  pendingTimer: ReturnType<typeof setTimeout> | undefined
  shown: boolean
  // x/y 是标记中心；w/h 是尺寸。
  x: Spring
  y: Spring
  w: Spring
  h: Spring
  frame: number
  lastTime: number
  flipping: number
  snapshots: WeakMap<Element, Snapshot>
  mutations?: MutationObserver
  resizes?: ResizeObserver
  observed: WeakSet<Element>
  capture: () => void
  follow: (event: MouseEvent) => void
}

// 固有频率 24 rad/s、阻尼 0.74：约 350ms 落定、5% 回弹；尺寸用更高阻尼，宽窄变化不晃。
const OMEGA = 24
const ZETA = 0.74
const SIZE_ZETA = 0.9
const STEP = 1 / 240
// 拖尾：速度约 1400px/s 时接近最长，最长为标记自身尺寸的一半且不超过 40px。
const TAIL_SPEED = 1400
const TAIL_RATIO = 0.5
const TAIL_MAX = 40
const FLIP_MS = 460
// 盖章：起始比原尺寸小约 10px（按长边折算，最多 14%），小按钮明显、大卡片只轻轻一顿。
const POP_MS = 520
const POP_PX = 10
const POP_MAX = 0.14
const FOLLOW_TIMEOUT_MS = 1500
const WATCHED_ATTRIBUTES = ['class', 'aria-selected', 'aria-pressed', 'aria-current', 'aria-expanded']

const states = new WeakMap<HTMLElement, IndicatorState>()

const normalize = (value: IndicatorValue): IndicatorOptions => (typeof value === 'string' ? { active: value } : value)
const rendered = (el: Element) => el.getClientRects().length > 0
const round = (n: number) => `${Math.round(n * 100) / 100}px`

function findActive(group: HTMLElement, selector: string): HTMLElement | null {
  for (const el of Array.from(group.querySelectorAll<HTMLElement>(selector))) {
    if (rendered(el)) return el
  }
  return null
}

/** 当前项在组内（组的 padding box 坐标）的布局盒子；沿 offsetParent 链累加，不受悬停位移等 transform 影响。 */
export function boxWithin(group: HTMLElement, item: HTMLElement): Box {
  let x = 0
  let y = 0
  let node: HTMLElement = item
  while (node !== group) {
    const parent = node.offsetParent as HTMLElement | null
    if (!parent || (parent !== group && !group.contains(parent))) return rectWithin(group, item)
    x += node.offsetLeft
    y += node.offsetTop
    if (parent !== group) {
      x += parent.clientLeft - parent.scrollLeft
      y += parent.clientTop - parent.scrollTop
    }
    node = parent
  }
  return { x, y, w: item.offsetWidth, h: item.offsetHeight }
}

/** 组本身不是定位元素时退回几何换算（包含 transform）。 */
function rectWithin(group: HTMLElement, item: HTMLElement): Box {
  const outer = group.getBoundingClientRect()
  const inner = item.getBoundingClientRect()
  return {
    x: inner.left - outer.left - group.clientLeft + group.scrollLeft,
    y: inner.top - outer.top - group.clientTop + group.scrollTop,
    w: inner.width,
    h: inner.height,
  }
}

/** 把一段 [start, end] 收进 [lo, hi]，收完为空时退成零长。 */
function clampSpan(start: number, end: number, lo: number, hi: number): [number, number] {
  const from = Math.min(Math.max(start, lo), hi)
  return [from, Math.max(from, Math.min(end, hi))]
}

function paint(group: HTMLElement, state: IndicatorState, target?: Box) {
  const { x, y, w, h } = state
  const tailX = Math.min(TAIL_MAX, w.p * TAIL_RATIO) * Math.tanh(Math.abs(x.v) / TAIL_SPEED)
  const tailY = Math.min(TAIL_MAX, h.p * TAIL_RATIO) * Math.tanh(Math.abs(y.v) / TAIL_SPEED)
  // 尾巴拖在行进方向的反侧：前缘始终贴着弹簧位置。
  const left = x.p - w.p / 2 - (x.v > 0 ? tailX : 0)
  const top = y.p - h.p / 2 - (y.v > 0 ? tailY : 0)
  let [x0, x1] = [left, left + w.p + tailX]
  let [y0, y1] = [top, top + h.p + tailY]
  // 回弹不冲出组外：前缘顶到组的边上就停住，标记被压短一截，像撞上了墙。当前项本身伸出组外（比如横向滚动的组）的部分照画。
  if (target && group.clientWidth > 0 && group.clientHeight > 0) {
    ;[x0, x1] = clampSpan(x0, x1, Math.min(0, target.x), Math.max(group.clientWidth, target.x + target.w))
    ;[y0, y1] = clampSpan(y0, y1, Math.min(0, target.y), Math.max(group.clientHeight, target.y + target.h))
  }
  group.style.setProperty('--indicator-x', round(x0))
  group.style.setProperty('--indicator-y', round(y0))
  group.style.setProperty('--indicator-w', round(x1 - x0))
  group.style.setProperty('--indicator-h', round(y1 - y0))
}

function snap(group: HTMLElement, state: IndicatorState, box: Box) {
  state.x = { p: box.x + box.w / 2, v: 0 }
  state.y = { p: box.y + box.h / 2, v: 0 }
  state.w = { p: box.w, v: 0 }
  state.h = { p: box.h, v: 0 }
  paint(group, state)
}

function advance(s: Spring, target: number, dt: number, zeta: number) {
  s.v += (-OMEGA * OMEGA * (s.p - target) - 2 * zeta * OMEGA * s.v) * dt
  s.p += s.v * dt
}
const settled = (s: Spring, target: number) => Math.abs(s.p - target) < 0.25 && Math.abs(s.v) < 4

function tick(group: HTMLElement, state: IndicatorState, now: number) {
  state.frame = 0
  const active = state.pending && rendered(state.pending) ? state.pending : state.active
  if (!active || !group.isConnected || !rendered(active)) return
  // 每帧重新量目标：动画途中组内重排（FLIP、字体加载、窗口缩放）时标记跟着新位置走。
  const box = boxWithin(group, active)
  const tx = box.x + box.w / 2
  const ty = box.y + box.h / 2
  let dt = Math.min(0.05, Math.max(0, (now - state.lastTime) / 1000))
  state.lastTime = now
  while (dt > 0) {
    const h = Math.min(STEP, dt)
    advance(state.x, tx, h, ZETA)
    advance(state.y, ty, h, ZETA)
    advance(state.w, box.w, h, SIZE_ZETA)
    advance(state.h, box.h, h, SIZE_ZETA)
    dt -= h
  }
  if (settled(state.x, tx) && settled(state.y, ty) && settled(state.w, box.w) && settled(state.h, box.h)) {
    snap(group, state, box)
    return
  }
  paint(group, state, box)
  state.frame = requestAnimationFrame((time) => tick(group, state, time))
}

function run(group: HTMLElement, state: IndicatorState) {
  if (state.frame) return
  state.lastTime = performance.now() - 16
  state.frame = requestAnimationFrame((time) => tick(group, state, time))
}

function stop(state: IndicatorState) {
  if (state.frame) cancelAnimationFrame(state.frame)
  state.frame = 0
}

// 点击出发期间组上挂 data-indicator-pending、目标项挂 data-indicator-target，各组据此提前换字色，
// 深色模式下标记滑走/滑到时文字不会短暂与底色撞色。
function clearPending(group: HTMLElement, state: IndicatorState) {
  state.pending?.removeAttribute('data-indicator-target')
  group.removeAttribute('data-indicator-pending')
  state.pending = null
  clearTimeout(state.pendingTimer)
}

function follow(group: HTMLElement, state: IndicatorState, event: MouseEvent) {
  const selector = state.options.follow
  if (!selector || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
  const item = (event.target as Element | null)?.closest<HTMLElement>(selector)
  if (!item || !group.contains(item) || item === state.active || !state.shown || prefersReducedMotion()) return
  clearPending(group, state)
  state.pending = item
  item.setAttribute('data-indicator-target', '')
  group.setAttribute('data-indicator-pending', '')
  state.pendingTimer = setTimeout(() => {
    clearPending(group, state)
    run(group, state)
  }, FOLLOW_TIMEOUT_MS)
  run(group, state)
}

function show(group: HTMLElement, state: IndicatorState, visible: boolean) {
  state.shown = visible
  group.setAttribute('data-indicator', visible ? 'on' : 'off')
}

/** 本帧内关掉标记的出现/消失过渡（初次定位、从隐藏的 KeepAlive 页面回来）。 */
function still(group: HTMLElement) {
  group.setAttribute('data-indicator-still', '')
  const release = () => group.removeAttribute('data-indicator-still')
  if (typeof requestAnimationFrame === 'function') requestAnimationFrame(() => requestAnimationFrame(release))
  else release()
}

const flipItems = (group: HTMLElement) => Array.from(group.children).filter(
  (child): child is HTMLElement => child instanceof HTMLElement && rendered(child),
)

/** 记录各项此刻的视觉位置（含进行中的 FLIP）；在点击/按键之前拍下，作为 FLIP 的起点。 */
function capture(group: HTMLElement, state: IndicatorState) {
  const origin = group.getBoundingClientRect()
  for (const item of flipItems(group)) {
    const rect = item.getBoundingClientRect()
    const scale = item.offsetHeight ? rect.height / item.offsetHeight : 1
    state.snapshots.set(item, {
      x: rect.left - origin.left,
      y: rect.top - origin.top,
      w: rect.width,
      h: rect.height,
      fontSize: (parseFloat(getComputedStyle(item).fontSize) || 0) * scale,
    })
  }
}

function flip(group: HTMLElement, state: IndicatorState) {
  const origin = group.getBoundingClientRect()
  // 祖先的缩放（首页大屏 zoom、transform scale）换算回元素自身坐标。
  const zoom = group.offsetWidth ? origin.width / group.offsetWidth : 1
  const easing = spring()
  for (const item of flipItems(group)) {
    const first = state.snapshots.get(item)
    if (!first) continue
    for (const running of item.getAnimations()) if (running.id === 'indicator-flip') running.cancel()
    const rect = item.getBoundingClientRect()
    const fontSize = parseFloat(getComputedStyle(item).fontSize) || 0
    const scale = first.fontSize && fontSize ? first.fontSize / fontSize : 1
    const dx = (first.x + first.w / 2 - (rect.left - origin.left + rect.width / 2)) / zoom
    const dy = (first.y + first.h / 2 - (rect.top - origin.top + rect.height / 2)) / zoom
    const scaled = Math.abs(scale - 1) >= 0.01
    if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5 && !scaled) continue
    // 字号没变的项只补位移，不占 scale，免得盖掉同一项上的盖章弹入。
    const keyframes: Keyframe[] = scaled
      ? [{ translate: `${dx}px ${dy}px`, scale: `${scale}` }, { translate: '0 0', scale: '1' }]
      : [{ translate: `${dx}px ${dy}px` }, { translate: '0 0' }]
    const animation = item.animate(keyframes, { duration: FLIP_MS, easing })
    animation.id = 'indicator-flip'
    state.flipping += 1
    const done = () => {
      state.flipping = Math.max(0, state.flipping - 1)
      if (!state.flipping) capture(group, state)
    }
    animation.addEventListener('finish', done)
    animation.addEventListener('cancel', done)
  }
}

function pop(item: HTMLElement) {
  if (typeof item.animate !== 'function') return
  const size = Math.max(item.offsetWidth, item.offsetHeight)
  if (!size) return
  for (const running of item.getAnimations()) if (running.id === 'indicator-pop') running.cancel()
  const from = 1 - Math.min(POP_MAX, POP_PX / size)
  const animation = item.animate([{ scale: `${from}` }, { scale: '1' }], { duration: POP_MS, easing: popSpring() })
  animation.id = 'indicator-pop'
}

/** 组上此刻是否真的画着滑动标记。 */
function markDrawn(group: HTMLElement, state: IndicatorState): boolean {
  const { mark } = state.options
  return mark !== false && getComputedStyle(group, `::${mark ?? 'before'}`).content !== 'none'
}

// 看边框盒：标记量的是各项的边框盒、坐标从组的内边距起算，只改内边距或边框时内容盒不变，按默认的内容盒看会漏报。
// 比如从窄屏拉宽到桌面时漫画版样式表晚到几帧，组多出内边距和边框、各项整体挪位，组与各项的内容尺寸都没变。
function watchSizes(group: HTMLElement, state: IndicatorState, active: HTMLElement) {
  const observer = state.resizes
  if (!observer) return
  for (const target of [group, active, ...Array.from(group.children)]) {
    if (state.observed.has(target)) continue
    state.observed.add(target)
    observer.observe(target, { box: 'border-box' })
  }
}

function sync(group: HTMLElement, state: IndicatorState, animate: boolean) {
  // 被 KeepAlive 摘下或 display:none 时不量，回来时 ResizeObserver 会再触发一次。
  if (!group.isConnected || !rendered(group)) return
  const active = findActive(group, state.options.active)
  if (!active) {
    state.active = null
    clearPending(group, state)
    stop(state)
    // 一开始就没有当前项（列表光标还没亮）也标成 off，免得标记停在组的左上角露出一截。
    if (state.shown || !group.hasAttribute('data-indicator')) show(group, state, false)
    return
  }
  const previous = state.active
  state.active = active
  const moved = active !== previous
  if (moved) clearPending(group, state)
  const lively = moved && animate && previous !== null && state.shown && !prefersReducedMotion()
  // 标记没画出来时（当前样式把它关了）只把位置对齐，不空跑弹簧。
  const sliding = lively && markDrawn(group, state)
  if (lively && !sliding && state.options.pop) pop(active)
  if (lively && state.options.flip && typeof active.animate === 'function') flip(group, state)
  if (state.options.mark !== false) {
    if (sliding && typeof requestAnimationFrame === 'function') run(group, state)
    else if (!state.frame) snap(group, state, boxWithin(group, active))
  }
  if (!state.shown) show(group, state, true)
  // FLIP 进行中不刷新起点：此刻量到的是动画首帧（旧位置），落定后由 finish 回调补拍。
  if (state.options.flip && !state.flipping) capture(group, state)
  watchSizes(group, state, active)
}

function setMark(group: HTMLElement, options: IndicatorOptions) {
  if (options.mark === false) group.removeAttribute('data-indicator-mark')
  else group.setAttribute('data-indicator-mark', options.mark ?? 'before')
}

export const vIndicator: Directive<HTMLElement, IndicatorValue> = {
  mounted(group, binding) {
    const options = normalize(binding.value)
    const state: IndicatorState = {
      options,
      active: null,
      pending: null,
      pendingTimer: undefined,
      shown: false,
      x: { p: 0, v: 0 },
      y: { p: 0, v: 0 },
      w: { p: 0, v: 0 },
      h: { p: 0, v: 0 },
      frame: 0,
      lastTime: 0,
      flipping: 0,
      snapshots: new WeakMap(),
      observed: new WeakSet(),
      capture: () => {
        if (state.options.flip) capture(group, state)
      },
      follow: (event) => follow(group, state, event),
    }
    states.set(group, state)
    setMark(group, options)
    if (typeof MutationObserver === 'function') {
      state.mutations = new MutationObserver(() => sync(group, state, true))
      state.mutations.observe(group, {
        subtree: true,
        childList: true,
        characterData: true,
        attributes: true,
        attributeFilter: WATCHED_ATTRIBUTES,
      })
    }
    if (typeof ResizeObserver === 'function') {
      state.resizes = new ResizeObserver(() => {
        const wasHidden = !state.shown
        sync(group, state, false)
        if (wasHidden && state.shown) still(group)
      })
    }
    group.addEventListener('pointerdown', state.capture, true)
    group.addEventListener('keydown', state.capture, true)
    group.addEventListener('click', state.follow, true)
    still(group)
    sync(group, state, false)
  },
  updated(group, binding) {
    const state = states.get(group)
    if (!state) return
    const next = normalize(binding.value)
    if (next.active === state.options.active && next.mark === state.options.mark
      && next.flip === state.options.flip && next.follow === state.options.follow && next.pop === state.options.pop) return
    state.options = next
    setMark(group, next)
    sync(group, state, true)
  },
  beforeUnmount(group) {
    const state = states.get(group)
    if (!state) return
    stop(state)
    clearPending(group, state)
    state.mutations?.disconnect()
    state.resizes?.disconnect()
    group.removeEventListener('pointerdown', state.capture, true)
    group.removeEventListener('keydown', state.capture, true)
    group.removeEventListener('click', state.follow, true)
    states.delete(group)
  },
}
