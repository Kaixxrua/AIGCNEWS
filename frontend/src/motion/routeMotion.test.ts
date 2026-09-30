import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createRouteTransition, routeAxis, type RouteAxis } from './routeMotion'
import { installFakeAnimations, stubLayout, stubReducedMotion, type FakeAnimations } from './testing'

let fakes: FakeAnimations
let restoreLayout: () => void
let page: HTMLElement

describe('routeAxis', () => {
  it('沿 dock 顺序前进/后退横向滑动，dock 之外或原地刷新从下方浮起', () => {
    expect(routeAxis(0, 2)).toBe('forward')
    expect(routeAxis(3, 1)).toBe('backward')
    expect(routeAxis(-1, 2)).toBe('rise')
    expect(routeAxis(2, -1)).toBe('rise')
    expect(routeAxis(1, 1)).toBe('rise')
  })
})

describe('createRouteTransition', () => {
  let axis: RouteAxis

  beforeEach(() => {
    fakes = installFakeAnimations()
    restoreLayout = stubLayout()
    axis = 'forward'
    document.body.innerHTML = '<main data-box="0 0 1200 900"><section id="page" data-box="0 64 1200 800"></section></main>'
    page = document.getElementById('page')!
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    fakes.restore()
    restoreLayout()
    document.body.innerHTML = ''
  })

  it('离开页钉在原位垫在底层，朝反方向略移并快速淡出；离开结束撤掉钉位', () => {
    const hooks = createRouteTransition(() => axis)
    hooks.onBeforeLeave(page)
    expect(page.style).toMatchObject({ position: 'absolute', top: '64px', left: '0px', width: '1200px', height: '800px', zIndex: '-1', pointerEvents: 'none' })
    const done = vi.fn()
    hooks.onLeave(page, done)
    const [leave] = fakes.on(page)
    expect(leave?.keyframes).toEqual([{ opacity: 0, translate: '-11.2px 0px' }])
    expect(leave?.options).toMatchObject({ duration: 120, fill: 'forwards' })
    leave!.finish()
    expect(done).toHaveBeenCalledOnce()
    hooks.onAfterLeave(page)
    expect(leave?.playState).toBe('idle')
    // jsdom 的 removeProperty('margin') 不连带删四个分量（浏览器会），这里只核对钉位的几项。
    expect(page.style).toMatchObject({ position: '', top: '', left: '', width: '', height: '', zIndex: '', pointerEvents: '' })
  })

  it('本身已脱离文档流的页面（固定定位的场景页）不钉', () => {
    page.style.position = 'fixed'
    createRouteTransition(() => axis).onBeforeLeave(page)
    expect(page.style.top).toBe('')
    expect(page.style.zIndex).toBe('')
  })

  it('新页面从行进方向滑入；后退时从左边，dock 之外从下方', () => {
    const hooks = createRouteTransition(() => axis)
    const done = vi.fn()
    hooks.onEnter(page, done)
    axis = 'backward'
    hooks.onEnter(page, vi.fn())
    axis = 'rise'
    hooks.onEnter(page, vi.fn())
    const [forward, backward, rise] = fakes.on(page)
    expect(forward?.frame(0)).toEqual({ opacity: 0, translate: '32px 0px' })
    expect(forward?.options).toMatchObject({ duration: 380, delay: 50, fill: 'backwards' })
    expect(backward?.frame(0)).toEqual({ opacity: 0, translate: '-32px 0px' })
    expect(rise?.frame(0)).toEqual({ opacity: 0, translate: '0px 16px' })
    forward!.finish()
    expect(done).toHaveBeenCalledOnce()
  })

  it('进入还没播完又被切走：先把此刻的样子写回，再从这里淡出', () => {
    const hooks = createRouteTransition(() => axis)
    hooks.onEnter(page, vi.fn())
    const [entering] = fakes.on(page)
    hooks.onBeforeLeave(page)
    hooks.onLeave(page, vi.fn())
    expect(entering?.commitStyles).toHaveBeenCalledOnce()
    expect(entering?.playState).toBe('idle')
    expect(fakes.on(page)).toHaveLength(2)
  })

  it('偏好减少动态时直接交还', () => {
    stubReducedMotion()
    const hooks = createRouteTransition(() => axis)
    const leave = vi.fn()
    const enter = vi.fn()
    hooks.onLeave(page, leave)
    hooks.onEnter(page, enter)
    expect(leave).toHaveBeenCalledOnce()
    expect(enter).toHaveBeenCalledOnce()
    expect(fakes.all).toHaveLength(0)
  })
})
