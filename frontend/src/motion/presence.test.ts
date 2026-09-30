import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { popIn, popOut, slideIn, slideOut } from './presence'
import { installFakeAnimations, stubLayout, stubReducedMotion, type FakeAnimations } from './testing'

let fakes: FakeAnimations
let restoreLayout: () => void
let panel: HTMLElement

describe('presence', () => {
  beforeEach(() => {
    fakes = installFakeAnimations()
    restoreLayout = stubLayout()
    document.body.innerHTML = '<div data-box="0 0 400 300"><aside id="panel" data-box="30 40 120 200" style="width: 50%; z-index: 3"></aside></div>'
    panel = document.getElementById('panel')!
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    fakes.restore()
    restoreLayout()
    document.body.innerHTML = ''
  })

  it('popIn：从小处盖章式弹入，可先等一拍，弹完才交还', () => {
    const done = vi.fn()
    popIn(panel, done, { delay: 120 })
    const [fade, grow] = fakes.on(panel, 'presence')
    expect(fade?.keyframes).toEqual([{ opacity: '0' }, { opacity: '1' }])
    expect(grow?.keyframes).toEqual([{ scale: '0.5' }, { scale: '1' }])
    // 等待期间停在起始的样子。
    expect(grow?.options).toMatchObject({ delay: 120, fill: 'backwards' })
    expect(done).not.toHaveBeenCalled()
    grow!.finish()
    expect(done).toHaveBeenCalledOnce()
  })

  it('popOut：钉在原处脱离文档流缩小淡出，播完交还并撤销钉住', () => {
    const done = vi.fn()
    popOut(panel, done)
    expect(panel.style).toMatchObject({ position: 'absolute', left: '30px', top: '40px', width: '120px', pointerEvents: 'none' })
    // 不指定层级时保留元素自己的 z-index。
    expect(panel.style.zIndex).toBe('3')
    const [, shrink] = fakes.on(panel, 'presence')
    expect(shrink?.options.fill).toBe('forwards')
    shrink!.finish()
    expect(done).toHaveBeenCalledOnce()
    expect(panel.style).toMatchObject({ position: '', left: '', top: '', width: '50%', pointerEvents: '', zIndex: '3' })
  })

  it('slideIn：滑动期间叠在兄弟元素之上，落定后还原层级', () => {
    const done = vi.fn()
    slideIn(panel, done, { x: -24 })
    expect(panel.style.zIndex).toBe('1')
    const [fade, move] = fakes.on(panel, 'presence')
    expect(fade?.keyframes).toEqual([{ opacity: '0' }, { opacity: '1' }])
    expect(move?.keyframes).toEqual([{ translate: '-24px 0px' }, { translate: '0px 0px' }])
    move!.finish()
    expect(panel.style.zIndex).toBe('3')
    expect(done).toHaveBeenCalledOnce()
  })

  it('滑出途中又要出现：从此刻的位置和透明度接着滑回来，先回到文档流里', () => {
    const leave = vi.fn()
    slideOut(panel, leave, { x: -24 })
    expect(panel.style).toMatchObject({ position: 'absolute', zIndex: '1' })
    const leaving = fakes.on(panel, 'presence')
    expect(leaving[1]?.keyframes).toEqual([{ translate: '0px 0px' }, { translate: '-24px 0px' }])
    // 行内样式模拟此刻滑到一半的样子（浏览器里是动画写进计算样式的值）。
    panel.style.translate = '-10px 0px'
    panel.style.opacity = '0.4'

    const enter = vi.fn()
    slideIn(panel, enter, { x: -24 })
    expect(leaving.every((animation) => animation.playState === 'idle')).toBe(true)
    expect(panel.style.position).toBe('')
    expect(panel.style.zIndex).toBe('1')
    const [fade, move] = fakes.on(panel, 'presence').slice(2)
    expect(fade?.frame(0)).toEqual({ opacity: '0.4' })
    expect(move?.frame(0)).toEqual({ translate: '-10px 0px' })
    // 被打断的离场由 Vue 自己结算，这里不再交还。
    expect(leave).not.toHaveBeenCalled()
    move!.finish()
    expect(enter).toHaveBeenCalledOnce()
    expect(panel.style.zIndex).toBe('3')
  })

  it('环境不能播动画或偏好减少动态时立即交还，不钉不抬', () => {
    stubReducedMotion()
    const done = vi.fn()
    slideOut(panel, done)
    popOut(panel, done)
    slideIn(panel, done)
    popIn(panel, done)
    expect(done).toHaveBeenCalledTimes(4)
    expect(fakes.all).toHaveLength(0)
    expect(panel.style).toMatchObject({ position: '', zIndex: '3' })
  })
})
