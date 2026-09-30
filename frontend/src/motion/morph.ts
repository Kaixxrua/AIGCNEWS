import type { Directive } from 'vue'
import { EASE_OUT, canAnimate } from './motion'

/**
 * 尺寸过渡：内容一换（按钮换了文案、多了或少了一个标签、一行排不下换成两行）元素的宽高随之变化时，
 * 宽高从旧值平滑走到新值，不再一帧跳变。动画期间只在变化的方向上裁掉溢出的内容（宽度裁右缘、高度裁下缘），
 * 结束即撤，不改元素自己的样式。同一轮更新里的尺寸过渡一起起步，同一行里此消彼长的几项始终排得下；
 * 按起点尺寸仍会落到另一行的元素不走尺寸过渡（免得中途跳行），尺寸直接取新值，从原处滑到新的一行。
 */
const MORPH_MS = 420
// 裁切边留出的余量：手绘框、描边外溢的几像素不被裁掉；不变的方向完全不裁。
const SLACK = '-3px'
const OPEN = '-100vmax'

export interface Size { width: number; height: number }

/** 换之前的样子：尺寸之外再记下屏幕上的位置（含进行中的滑动），换了行时从这里滑过去。 */
export interface Snapshot extends Size { rect: DOMRect }

export function sizeOf(el: HTMLElement): Size {
  const style = getComputedStyle(el)
  return { width: parseFloat(style.width) || 0, height: parseFloat(style.height) || 0 }
}

export function snapshotOf(el: HTMLElement): Snapshot {
  return { ...sizeOf(el), rect: el.getBoundingClientRect() }
}

export interface MorphOptions {
  delay?: number
  /** 由调用方自己裁切溢出时传 false。 */
  clip?: boolean
}

interface Job {
  el: HTMLElement
  from: Size | Snapshot
  clip: boolean
  timing: KeyframeAnimationOptions
}

interface Morph {
  el: HTMLElement
  /** 换之前在屏幕上的位置；没有就不滑。 */
  rect?: DOMRect
  /** 新内容自然排下来所在的行。 */
  line: number
  keyframes: Keyframe[]
  clipPath: string | null
  timing: KeyframeAnimationOptions
}

let queued: Job[] = []

/**
 * 元素已经换成新内容后调用：from 是换之前量到的尺寸（含进行中的过渡），带上位置才会在换行时滑过去。
 * 同一轮更新里的调用攒到本轮末尾一起起步。
 */
export function morphSize(el: HTMLElement, from: Size | Snapshot, { delay = 0, clip = true }: MorphOptions = {}): void {
  if (!canAnimate(el)) return
  if (!queued.length) queueMicrotask(flush)
  queued.push({ el, from, clip, timing: { duration: MORPH_MS, delay, easing: EASE_OUT, fill: 'backwards' } })
}

function stop(el: HTMLElement): void {
  for (const running of el.getAnimations()) if (running.id === 'morph') running.cancel()
}

function flush(): void {
  const jobs = queued.filter(({ el }) => el.isConnected)
  queued = []
  jobs.forEach(({ el }) => stop(el))
  // 此刻这一轮的过渡都还没起步：先按新内容的自然尺寸和所在的行把每一项怎么走定下来。
  const morphs = jobs.flatMap((job) => plan(job) ?? [])
  // 再一起按起点尺寸排开：同一行里此消彼长的几项始终排得下；仍被挤到别的行的，尺寸直接取新值，改为从原处滑过去。
  morphs.forEach(({ el, keyframes, timing }) => {
    el.animate(keyframes, timing).id = 'morph'
  })
  const moved = morphs.filter(({ el, line }) => Math.abs(el.offsetTop - line) > 1)
  moved.forEach(({ el }) => stop(el))
  moved.forEach(glide)
}

function plan({ el, from, clip, timing }: Job): Morph | null {
  const to = sizeOf(el)
  const wide = Math.abs(from.width - to.width) >= 0.5
  const tall = Math.abs(from.height - to.height) >= 0.5
  if (!wide && !tall) return null
  const clipPath = clip ? `inset(${OPEN} ${wide ? SLACK : OPEN} ${tall ? SLACK : OPEN} ${OPEN})` : null
  const frame = (size: Size): Keyframe => ({
    ...(wide ? { width: `${size.width}px` } : {}),
    ...(tall ? { height: `${size.height}px` } : {}),
    ...(clipPath ? { clipPath } : {}),
  })
  const rect = 'rect' in from ? from.rect : undefined
  return { el, rect, line: el.offsetTop, keyframes: [frame(from), frame(to)], clipPath, timing }
}

/** 从旧的屏幕位置滑到现在的位置：横竖各按离得近的那条边对齐，比如右对齐的按钮换行时只上下走。 */
function glide({ el, rect, clipPath, timing }: Morph): void {
  if (!rect) return
  const to = el.getBoundingClientRect()
  const nearer = (a: number, b: number) => (Math.abs(a) <= Math.abs(b) ? a : b)
  const dx = nearer(rect.left - to.left, rect.right - to.right)
  const dy = nearer(rect.top - to.top, rect.bottom - to.bottom)
  if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return
  // 叠加在元素自己的位移上，不顶掉它。
  el.animate([{ translate: `${dx}px ${dy}px` }, { translate: '0 0' }], { ...timing, composite: 'add' }).id = 'morph'
  // 尺寸已经一步到位，原来放得下、现在放不下的内容（比如正在淡出的标签）照样裁掉。
  if (clipPath) el.animate([{ clipPath }, { clipPath }], timing).id = 'morph'
}

const pending = new WeakMap<HTMLElement, Snapshot>()
const mounted = new Set<HTMLElement>()
// 这一轮更新里外层替里层先记下的样子，本轮结束即清。
const early = new Map<HTMLElement, Snapshot>()

function remember(el: HTMLElement): void {
  if (early.has(el)) return
  if (!early.size) queueMicrotask(() => early.clear())
  early.set(el, snapshotOf(el))
}

/** v-morph="key"：key 变了的那次更新里，元素的宽高若随之变化就平滑过渡，换了行就从原处滑过去。 */
export const vMorph: Directive<HTMLElement, unknown> = {
  mounted(el) {
    mounted.add(el)
  },
  beforeUnmount(el) {
    mounted.delete(el)
  },
  beforeUpdate(el, { value, oldValue }) {
    if (Object.is(value, oldValue) || !canAnimate(el)) return
    // 外层先走到这里；里层轮到时兄弟节点可能已经换了内容、把它挤到了别处，所以外层替里层把换之前的样子一并记下。
    for (const other of mounted) if (el.contains(other)) remember(other)
    pending.set(el, early.get(el) ?? snapshotOf(el))
  },
  updated(el) {
    const from = pending.get(el)
    if (!from) return
    pending.delete(el)
    morphSize(el, from)
  },
}
