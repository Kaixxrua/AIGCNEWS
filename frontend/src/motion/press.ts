import { EASE_OUT, popSpring, prefersReducedMotion } from './motion'

/**
 * 全站按钮的按压反馈：按下时轻轻缩一下，松手带回弹复位。用 WAAPI 的独立 scale 属性，
 * 和各按钮自己的 transform（悬停上浮、手绘错位）、CSS 过渡互不覆盖；卡片等大块元素不参与。
 */
const PRESSABLE = 'button, [role="button"], [role="tab"], [role="menuitem"], summary, .btn, .dock-item, .mobile-nav__item'
// 按下深度约 3px（按长边折算），最多缩 6%。
const PRESS_PX = 3
const PRESS_MAX = 0.06
const PRESS_MS = 110
const RELEASE_MS = 460
const MAX_AREA = 160_000

interface Pressed { el: HTMLElement; animation: Animation }

let pressed: Pressed | null = null
let installed = false

function pressable(target: EventTarget | null): HTMLElement | null {
  const el = target instanceof Element ? target.closest<HTMLElement>(PRESSABLE) : null
  if (!el || el.matches(':disabled, [aria-disabled="true"]') || el.closest('[data-no-press]')) return null
  const { offsetWidth: w, offsetHeight: h } = el
  if (!w || !h || w * h > MAX_AREA) return null
  return el
}

const depthOf = (el: HTMLElement) => 1 - Math.min(PRESS_MAX, PRESS_PX / Math.max(el.offsetWidth, el.offsetHeight))

function currentScale(el: HTMLElement): number {
  const value = parseFloat(getComputedStyle(el).scale)
  return Number.isFinite(value) ? value : 1
}

function release() {
  if (!pressed) return
  const { el, animation } = pressed
  pressed = null
  const from = currentScale(el)
  animation.cancel()
  if (Math.abs(from - 1) < 0.002) return
  const back = el.animate([{ scale: `${from}` }, { scale: '1' }], { duration: RELEASE_MS, easing: popSpring() })
  back.id = 'press'
}

function press(el: HTMLElement) {
  release()
  const animation = el.animate([{ scale: '1' }, { scale: `${depthOf(el)}` }], { duration: PRESS_MS, easing: EASE_OUT, fill: 'forwards' })
  animation.id = 'press'
  pressed = { el, animation }
}

function onPointerDown(event: PointerEvent) {
  if (event.button !== 0 || !event.isPrimary || prefersReducedMotion()) return
  const el = pressable(event.target)
  if (el) press(el)
}

// 键盘触发（Enter / 空格）没有按住的过程，直接按一下再弹回。
function onKeyDown(event: KeyboardEvent) {
  if (event.repeat || (event.key !== 'Enter' && event.key !== ' ') || prefersReducedMotion()) return
  const el = pressable(event.target)
  if (!el || el !== event.target) return
  const depth = depthOf(el)
  const pulse = el.animate([{ scale: '1' }, { scale: `${depth}`, offset: 0.25 }, { scale: '1' }], { duration: RELEASE_MS, easing: 'ease-out' })
  pulse.id = 'press'
}

export function installPressFeedback(root: Document = document): void {
  if (installed || typeof Element === 'undefined' || typeof Element.prototype.animate !== 'function') return
  installed = true
  root.addEventListener('pointerdown', onPointerDown, { capture: true, passive: true })
  root.addEventListener('pointerup', release, { capture: true, passive: true })
  root.addEventListener('pointercancel', release, { capture: true, passive: true })
  root.addEventListener('dragstart', release, { capture: true, passive: true })
  root.addEventListener('keydown', onKeyDown, { capture: true, passive: true })
  window.addEventListener('blur', release)
}
