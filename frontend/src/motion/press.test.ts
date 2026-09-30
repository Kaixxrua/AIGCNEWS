import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { installPressFeedback } from './press'
import { installFakeAnimations, stubLayout, stubReducedMotion, type FakeAnimations } from './testing'

let fakes: FakeAnimations
let restoreLayout: () => void

const pointer = (type: string, target: Element, init: PointerEventInit = {}) =>
  target.dispatchEvent(new PointerEvent(type, { bubbles: true, button: 0, isPrimary: true, ...init }))

describe('按压反馈', () => {
  beforeAll(() => {
    // 监听装在 document 上，整个文件只装一次；装之前环境里得有 Element.animate。
    fakes = installFakeAnimations()
    installPressFeedback(document)
  })

  afterAll(() => {
    fakes.restore()
  })

  beforeEach(() => {
    fakes.all.length = 0
    restoreLayout = stubLayout()
    document.body.innerHTML = '<div data-box="0 0 800 600">'
      + '<button id="save" data-box="0 0 100 40"><span id="label">保存</span></button>'
      + '<button id="off" data-box="0 50 100 40" disabled>不可用</button>'
      + '<div data-no-press><button id="quiet" data-box="0 100 100 40">安静</button></div>'
      + '<div id="card" role="button" data-box="0 150 500 400">大卡片</div>'
      + '</div>'
  })

  afterEach(() => {
    // 松开进行中的按压，免得带到下一项。
    pointer('pointerup', document.body)
    vi.unstubAllGlobals()
    restoreLayout()
    document.body.innerHTML = ''
  })

  it('按下时轻轻缩一下（约 3px），停在按下的样子', () => {
    pointer('pointerdown', document.getElementById('label')!)
    const [press] = fakes.on(document.getElementById('save')!, 'press')
    expect(press?.keyframes).toEqual([{ scale: '1' }, { scale: '0.97' }])
    expect(press?.options.fill).toBe('forwards')
  })

  it('松手时从此刻的缩放带回弹复位', () => {
    const save = document.getElementById('save')!
    pointer('pointerdown', save)
    const real = window.getComputedStyle.bind(window)
    vi.stubGlobal('getComputedStyle', (el: Element) => (el === save ? ({ scale: '0.98' } as CSSStyleDeclaration) : real(el)))
    pointer('pointerup', save)
    const [press, back] = fakes.on(save, 'press')
    expect(press?.playState).toBe('idle')
    expect(back?.keyframes).toEqual([{ scale: '0.98' }, { scale: '1' }])
    expect(back?.options.duration).toBe(460)
  })

  it('禁用的、声明不要按压反馈的、面积太大的元素不动', () => {
    for (const id of ['off', 'quiet', 'card']) pointer('pointerdown', document.getElementById(id)!)
    expect(fakes.all).toHaveLength(0)
  })

  it('右键、非主指针、偏好减少动态时不动', () => {
    const save = document.getElementById('save')!
    pointer('pointerdown', save, { button: 2 })
    pointer('pointerdown', save, { isPrimary: false })
    stubReducedMotion()
    pointer('pointerdown', save)
    expect(fakes.all).toHaveLength(0)
  })

  it('键盘 Enter / 空格按下时按一下再弹回；长按连发不重复', () => {
    const save = document.getElementById('save')!
    save.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    save.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true, repeat: true }))
    save.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true }))
    const pulses = fakes.on(save, 'press')
    expect(pulses).toHaveLength(1)
    expect(pulses[0]?.keyframes).toEqual([{ scale: '1' }, { scale: '0.97', offset: 0.25 }, { scale: '1' }])
  })
})
