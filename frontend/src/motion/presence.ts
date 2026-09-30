import { EASE_IN, EASE_OUT, canAnimate, popSpring, spring } from './motion'

/**
 * 元素的出现与消失，给 <Transition @enter="popIn" @leave="popOut"> 一类用：
 * - popIn / popOut：小件（折扣标、徽标、计数角标）出现时盖章式从小处弹入，消失时在原处缩小淡出；
 * - slideIn / slideOut：大块面板（侧栏、抽屉）从一侧滑入，消失时朝那一侧滑出。
 * 离场时先按此刻的位置钉成绝对定位、脱离文档流，周围立即按新布局排（外层可配合 v-morph、v-reflow 平滑过渡），
 * 不必等它播完；它的父级须是定位元素。中途反向切换时从此刻的大小、位置、透明度接着走。
 */
const POP_IN_MS = 520
const FADE_IN_MS = 160
const POP_OUT_MS = 200
const FADE_OUT_MS = 140
const HIDDEN_SCALE = '0.5'
const SLIDE_IN_MS = 520
const SLIDE_FADE_IN_MS = 220
const SLIDE_OUT_MS = 240
const SLIDE_FADE_OUT_MS = 180

interface Look { opacity: string; scale: string; translate: string }

export interface PresenceOptions {
  /** 出现前先等一拍（ms），比如等外层的尺寸过渡把位置让出来，免得从还没撑开的边上探出去。 */
  delay?: number
}

export interface SlideOptions {
  /** 从哪个方向滑进来、往哪个方向滑出去（px）。 */
  x?: number
  y?: number
}

function lookOf(el: HTMLElement): Look {
  const style = getComputedStyle(el)
  return {
    opacity: style.opacity,
    scale: style.scale === 'none' ? '1' : style.scale,
    translate: style.translate === 'none' ? '0px 0px' : style.translate,
  }
}

// 钉住或抬高元素前它自己的行内样式，撤销时还原。
const pins = new WeakMap<HTMLElement, () => void>()

function unpin(el: HTMLElement): void {
  pins.get(el)?.()
  pins.delete(el)
}

/** 接管进行中的出现/消失：记下此刻的样子再停掉；离场途中又要出现（v-show）时先回到文档流里。 */
function takeOver(el: HTMLElement): Look | null {
  const running = el.getAnimations().filter((animation) => animation.id === 'presence')
  const look = running.length ? lookOf(el) : null
  running.forEach((animation) => animation.cancel())
  unpin(el)
  return look
}

export function popIn(el: Element, done: () => void, { delay = 0 }: PresenceOptions = {}): void {
  const node = el as HTMLElement
  if (!canAnimate(node)) {
    done()
    return
  }
  const from = takeOver(node) ?? { opacity: '0', scale: HIDDEN_SCALE }
  // 等待期间停在起始的样子。
  const fade = node.animate([{ opacity: from.opacity }, { opacity: '1' }], { duration: FADE_IN_MS, delay, easing: EASE_OUT, fill: 'backwards' })
  const grow = node.animate([{ scale: from.scale }, { scale: '1' }], { duration: POP_IN_MS, delay, easing: popSpring(), fill: 'backwards' })
  fade.id = 'presence'
  grow.id = 'presence'
  grow.addEventListener('finish', () => done())
}

/**
 * 按此刻的位置钉成绝对定位、脱离文档流。offset* 是相对定位父级的布局坐标（含吸顶偏移），不受旋转、按压缩放等
 * transform 影响；定宽免得脱离文档流后重新折行。v-show 藏起之后撤销，下次出现照常排版。
 */
function pin(node: HTMLElement, zIndex?: string): void {
  const { offsetLeft, offsetTop, offsetWidth } = node
  const pinned: Partial<CSSStyleDeclaration> = {
    position: 'absolute',
    left: `${offsetLeft}px`,
    top: `${offsetTop}px`,
    width: `${offsetWidth}px`,
    margin: '0',
    pointerEvents: 'none',
    // 不指定层级时保留元素自己的 z-index。
    ...(zIndex === undefined ? {} : { zIndex }),
  }
  const saved = Object.fromEntries(Object.keys(pinned).map((name) => [name, node.style[name as keyof typeof pinned]]))
  Object.assign(node.style, pinned)
  pins.set(node, () => { Object.assign(node.style, saved) })
}

/** 滑动期间叠在兄弟元素之上（z-index 对定位元素和弹性布局的子项都生效），落定后还原。 */
function raise(node: HTMLElement): void {
  const saved = node.style.zIndex
  node.style.zIndex = '1'
  pins.set(node, () => { node.style.zIndex = saved })
}

/** 离场播完：交给 Vue 摘掉（v-if）或藏起（v-show），再撤销钉住。 */
function settle(node: HTMLElement, last: Animation, done: () => void): void {
  last.addEventListener('finish', () => {
    done()
    if (node.isConnected) unpin(node)
  })
}

export function popOut(el: Element, done: () => void): void {
  const node = el as HTMLElement
  if (!canAnimate(node)) {
    done()
    return
  }
  const from = takeOver(node) ?? lookOf(node)
  pin(node)
  // 一离场就开始变淡，缩小则越缩越快；停在终态直到 Vue 把它摘掉。
  const fade = node.animate([{ opacity: from.opacity }, { opacity: '0' }], { duration: FADE_OUT_MS, easing: EASE_OUT, fill: 'forwards' })
  const shrink = node.animate([{ scale: from.scale }, { scale: HIDDEN_SCALE }], { duration: POP_OUT_MS, easing: EASE_IN, fill: 'forwards' })
  fade.id = 'presence'
  shrink.id = 'presence'
  settle(node, shrink, done)
}

export function slideIn(el: Element, done: () => void, { x = 0, y = 0 }: SlideOptions = {}): void {
  const node = el as HTMLElement
  if (!canAnimate(node)) {
    done()
    return
  }
  const from = takeOver(node) ?? { opacity: '0', scale: '1', translate: `${x}px ${y}px` }
  // 盖过正给它让位的内容滑进来：很快显形，位移带弹簧落定。
  raise(node)
  const fade = node.animate([{ opacity: from.opacity }, { opacity: '1' }], { duration: SLIDE_FADE_IN_MS, easing: EASE_OUT })
  const move = node.animate([{ translate: from.translate }, { translate: '0px 0px' }], { duration: SLIDE_IN_MS, easing: spring() })
  fade.id = 'presence'
  move.id = 'presence'
  move.addEventListener('finish', () => {
    unpin(node)
    done()
  })
}

export function slideOut(el: Element, done: () => void, { x = 0, y = 0 }: SlideOptions = {}): void {
  const node = el as HTMLElement
  if (!canAnimate(node)) {
    done()
    return
  }
  const from = takeOver(node) ?? lookOf(node)
  // 叠在让出位置后涌过来的内容之上滑走。
  pin(node, '1')
  const fade = node.animate([{ opacity: from.opacity }, { opacity: '0' }], { duration: SLIDE_FADE_OUT_MS, easing: EASE_OUT, fill: 'forwards' })
  const move = node.animate([{ translate: from.translate }, { translate: `${x}px ${y}px` }], { duration: SLIDE_OUT_MS, easing: EASE_IN, fill: 'forwards' })
  fade.id = 'presence'
  move.id = 'presence'
  settle(node, move, done)
}
