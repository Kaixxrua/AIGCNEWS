import { vi } from 'vitest'

/**
 * src/motion 单元测试共用的替身，只给测试用：jsdom 既没有 Web Animations，也不排版。
 * - installFakeAnimations：Element.animate / getAnimations 记下每一段动画，由测试手动 finish / cancel；
 * - stubLayout：按元素上的 data-box="x y w h" 给出 offset*、client* 与屏幕矩形；
 * - stubReducedMotion：matchMedia 报告用户偏好减少动态。
 */

type Listener = () => void

export class FakeAnimation {
  id = ''
  playState: AnimationPlayState = 'running'
  currentTime: number | null = 0
  readonly commitStyles = vi.fn()
  readonly target: Element
  readonly keyframes: Keyframe[] | PropertyIndexedKeyframes
  readonly options: KeyframeAnimationOptions
  private readonly listeners = new Map<string, Listener[]>()

  constructor(target: Element, keyframes: Keyframe[] | PropertyIndexedKeyframes, options: KeyframeAnimationOptions) {
    this.target = target
    this.keyframes = keyframes
    this.options = options
  }

  /** 播完后仍停在终态（fill forwards）的动画照样算在 getAnimations 里，和浏览器一致。 */
  get relevant(): boolean {
    if (this.playState === 'running' || this.playState === 'paused') return true
    return this.playState === 'finished' && (this.options.fill === 'forwards' || this.options.fill === 'both')
  }

  /** 第 i 帧关键帧（数组形式）。 */
  frame(index: number): Keyframe {
    return (this.keyframes as Keyframe[])[index] ?? {}
  }

  addEventListener(type: string, listener: Listener): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener])
  }

  removeEventListener(type: string, listener: Listener): void {
    this.listeners.set(type, (this.listeners.get(type) ?? []).filter((item) => item !== listener))
  }

  finish(): void {
    if (this.playState === 'finished' || this.playState === 'idle') return
    this.playState = 'finished'
    this.emit('finish')
  }

  cancel(): void {
    if (this.playState === 'idle') return
    this.playState = 'idle'
    this.emit('cancel')
  }

  pause(): void {
    this.playState = 'paused'
  }

  play(): void {
    this.playState = 'running'
  }

  private emit(type: string): void {
    for (const listener of this.listeners.get(type) ?? []) listener()
  }
}

export interface FakeAnimations {
  /** 按创建顺序记下的全部动画。 */
  all: FakeAnimation[]
  /** 某个元素上（可按 id 过滤）的全部动画，含已结束的。 */
  on(el: Element, id?: string): FakeAnimation[]
  /** 把此刻还在播的动画全部播完。 */
  finishAll(): void
  restore(): void
}

export function installFakeAnimations(): FakeAnimations {
  const all: FakeAnimation[] = []
  const proto = Element.prototype as unknown as Record<string, unknown>
  proto.animate = function animate(this: Element, keyframes: Keyframe[] | PropertyIndexedKeyframes, options?: number | KeyframeAnimationOptions) {
    const animation = new FakeAnimation(this, keyframes, typeof options === 'number' ? { duration: options } : options ?? {})
    all.push(animation)
    return animation
  }
  proto.getAnimations = function getAnimations(this: Element) {
    return all.filter((animation) => animation.target === this && animation.relevant)
  }
  return {
    all,
    on: (el, id) => all.filter((animation) => animation.target === el && (id === undefined || animation.id === id)),
    finishAll: () => [...all].forEach((animation) => animation.finish()),
    restore: () => {
      delete proto.animate
      delete proto.getAnimations
    },
  }
}

interface Box { x: number; y: number; w: number; h: number }

/** data-box="x y w h"：相对最近一个带 data-box 的祖先摆放；带 data-static 的元素不充当定位父级。 */
export function boxOf(el: Element): Box | null {
  const raw = el.getAttribute('data-box')
  if (!raw) return null
  const [x = 0, y = 0, w = 0, h = 0] = raw.trim().split(/\s+/).map(Number)
  return { x, y, w, h }
}

function positionedParent(el: Element): HTMLElement | null {
  for (let node = el.parentElement; node; node = node.parentElement) {
    if (node.hasAttribute('data-box') && !node.hasAttribute('data-static')) return node
  }
  return null
}

/** 相对 parent 的偏移：一路累加中间各层的摆放位置。 */
function offsetWithin(el: Element, parent: Element | null): { x: number; y: number } {
  let x = 0
  let y = 0
  for (let node: Element | null = el; node && node !== parent; node = node.parentElement) {
    const box = boxOf(node)
    if (box) {
      x += box.x
      y += box.y
    }
  }
  return { x, y }
}

/** 屏幕矩形：累加全部祖先的摆放位置，减去祖先的滚动距离。没有 data-box 的元素视为没有渲染。 */
function screenRect(el: Element): DOMRect | null {
  const own = boxOf(el)
  if (!own) return null
  let { x, y } = offsetWithin(el, null)
  for (let node = el.parentElement; node; node = node.parentElement) {
    x -= node.scrollLeft
    y -= node.scrollTop
  }
  return { x, y, left: x, top: y, width: own.w, height: own.h, right: x + own.w, bottom: y + own.h, toJSON: () => ({}) } as DOMRect
}

const EMPTY_RECT = { x: 0, y: 0, left: 0, top: 0, width: 0, height: 0, right: 0, bottom: 0, toJSON: () => ({}) } as DOMRect

export function stubLayout(): () => void {
  const saved: Array<[object, string, PropertyDescriptor | undefined]> = []
  const define = (target: object, name: string, descriptor: PropertyDescriptor) => {
    saved.push([target, name, Object.getOwnPropertyDescriptor(target, name)])
    Object.defineProperty(target, name, { configurable: true, ...descriptor })
  }
  const html = HTMLElement.prototype
  define(html, 'offsetParent', { get(this: HTMLElement) { return positionedParent(this) } })
  define(html, 'offsetLeft', { get(this: HTMLElement) { return offsetWithin(this, positionedParent(this)).x } })
  define(html, 'offsetTop', { get(this: HTMLElement) { return offsetWithin(this, positionedParent(this)).y } })
  define(html, 'offsetWidth', { get(this: HTMLElement) { return boxOf(this)?.w ?? 0 } })
  define(html, 'offsetHeight', { get(this: HTMLElement) { return boxOf(this)?.h ?? 0 } })
  define(html, 'clientWidth', { get(this: HTMLElement) { return boxOf(this)?.w ?? 0 } })
  define(html, 'clientHeight', { get(this: HTMLElement) { return boxOf(this)?.h ?? 0 } })
  define(html, 'getBoundingClientRect', { value(this: HTMLElement) { return screenRect(this) ?? EMPTY_RECT } })
  define(html, 'getClientRects', { value(this: HTMLElement) { const rect = screenRect(this); return rect ? [rect] : [] } })
  return () => {
    for (const [target, name, descriptor] of saved.reverse()) {
      if (descriptor) Object.defineProperty(target, name, descriptor)
      else delete (target as Record<string, unknown>)[name]
    }
  }
}

/** 让 prefers-reduced-motion 生效；配合 vi.unstubAllGlobals() 还原。 */
export function stubReducedMotion(reduce = true): void {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: reduce && query.includes('prefers-reduced-motion: reduce'),
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }))
}
