import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, withDirectives, type PropType } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { boxWithin, vIndicator, type IndicatorValue } from './indicator'
import { installFakeAnimations, stubLayout, stubReducedMotion, type FakeAnimations } from './testing'

enableAutoUnmount(afterEach)

// 一组 300×40 的按钮条，三个 100px 宽的按钮；lefts 可改，模拟伸出组外的项（横向滚动的组）。
const Tabs = defineComponent({
  props: {
    active: { type: Number, required: true },
    value: { type: [String, Object] as PropType<IndicatorValue>, default: '.on' },
    lefts: { type: Array as PropType<number[]>, default: () => [0, 100, 200] },
  },
  setup(props) {
    return () => withDirectives(
      h('div', { class: 'tabs', 'data-box': '0 0 300 40' }, props.lefts.map((left, index) =>
        h('button', { class: { on: props.active === index }, 'data-box': `${left} 0 100 40` }, `tab ${index}`))),
      [[vIndicator, props.value]],
    )
  },
})

interface Mark { x: number; y: number; w: number; h: number }

const markOf = (group: HTMLElement): Mark => {
  const read = (name: string) => parseFloat(group.style.getPropertyValue(`--indicator-${name}`))
  return { x: read('x'), y: read('y'), w: read('w'), h: read('h') }
}

const last = <T>(list: T[]): T | undefined => list[list.length - 1]

/** 按 60fps 推进时间，记下每一帧画出来的标记。 */
const play = (group: HTMLElement, ms = 1200): Mark[] => {
  const frames: Mark[] = []
  for (let t = 0; t < ms; t += 16) {
    vi.advanceTimersByTime(16)
    frames.push(markOf(group))
  }
  return frames
}

const mountTabs = (props: { active: number; value?: IndicatorValue; lefts?: number[] }) => {
  const wrapper = mount(Tabs, { props, attachTo: document.body })
  return { wrapper, group: wrapper.element as HTMLElement }
}

let fakes: FakeAnimations
let restoreLayout: () => void
// 组上标记伪元素的 content：'none' 表示样式把滑动标记关了。
let markContent = '""'

describe('v-indicator', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    fakes = installFakeAnimations()
    restoreLayout = stubLayout()
    markContent = '""'
    const real = window.getComputedStyle.bind(window)
    vi.stubGlobal('getComputedStyle', (el: Element, pseudo?: string | null) =>
      pseudo ? ({ content: markContent } as CSSStyleDeclaration) : real(el))
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    fakes.restore()
    restoreLayout()
  })

  it('挂载时直接对齐当前项，不播动画', () => {
    const { group } = mountTabs({ active: 1 })
    expect(markOf(group)).toEqual({ x: 100, y: 0, w: 100, h: 40 })
    expect(group.dataset.indicator).toBe('on')
    expect(group.dataset.indicatorMark).toBe('before')
  })

  it('挂载时没有当前项就标 off，标记不在组的左上角露出来；有了当前项再亮', async () => {
    const { wrapper, group } = mountTabs({ active: -1 })
    expect(group.dataset.indicator).toBe('off')
    await wrapper.setProps({ active: 1 })
    await flushPromises()
    expect(group.dataset.indicator).toBe('on')
    expect(markOf(group)).toEqual({ x: 100, y: 0, w: 100, h: 40 })
  })

  it('换当前项时弹簧滑过去，最后精确落在新项上', async () => {
    const { wrapper, group } = mountTabs({ active: 0 })
    await wrapper.setProps({ active: 1 })
    await flushPromises()
    const frames = play(group)
    // 途中有过渡帧，不是一帧跳到位。
    expect(frames.some((frame) => frame.x > 5 && frame.x < 95)).toBe(true)
    // 组内的回弹照常：前缘冲过新项的右缘。
    expect(Math.max(...frames.map((frame) => frame.x + frame.w))).toBeGreaterThan(201)
    expect(last(frames)).toEqual({ x: 100, y: 0, w: 100, h: 40 })
  })

  it('滑到组的边上时回弹不冲出组外，而是被压短一截', async () => {
    const { wrapper, group } = mountTabs({ active: 0 })
    await wrapper.setProps({ active: 2 })
    await flushPromises()
    const frames = play(group)
    const rightEdges = frames.map((frame) => frame.x + frame.w)
    expect(Math.max(...rightEdges)).toBeLessThanOrEqual(300.01)
    expect(Math.min(...frames.map((frame) => frame.x))).toBeGreaterThanOrEqual(0)
    // 顶到墙的那几帧：右缘贴着组的边，宽度被压得比按钮窄。
    expect(frames.some((frame) => frame.w < 99 && frame.x + frame.w > 299.99)).toBe(true)
    expect(last(frames)).toEqual({ x: 200, y: 0, w: 100, h: 40 })
  })

  it('当前项本身伸出组外时照画整块，不被组的边裁掉', async () => {
    const { wrapper, group } = mountTabs({ active: 0, lefts: [0, 150, 250] })
    await wrapper.setProps({ active: 2 })
    await flushPromises()
    const frames = play(group)
    expect(Math.max(...frames.map((frame) => frame.x + frame.w))).toBeLessThanOrEqual(350.01)
    expect(last(frames)).toEqual({ x: 250, y: 0, w: 100, h: 40 })
  })

  it('pop：不画滑动标记，新选中项盖章式弹入', async () => {
    const { wrapper, group } = mountTabs({ active: 0, value: { active: '.on', mark: false, pop: true } })
    await wrapper.setProps({ active: 2 })
    await flushPromises()
    const target = group.querySelectorAll('button')[2]!
    const [stamp] = fakes.on(target, 'indicator-pop')
    expect(stamp?.keyframes).toEqual([{ scale: '0.9' }, { scale: '1' }])
    expect(group.style.getPropertyValue('--indicator-x')).toBe('')
    expect(group.hasAttribute('data-indicator-mark')).toBe(false)
  })

  it('样式把标记关掉（content: none）时改为盖章，标记位置直接对齐', async () => {
    markContent = 'none'
    const { wrapper, group } = mountTabs({ active: 0, value: { active: '.on', pop: true } })
    await wrapper.setProps({ active: 2 })
    await flushPromises()
    expect(fakes.on(group.querySelectorAll('button')[2]!, 'indicator-pop')).toHaveLength(1)
    expect(markOf(group).x).toBe(200)
  })

  it('用户偏好减少动态时一步到位，也不盖章', async () => {
    stubReducedMotion()
    const { wrapper, group } = mountTabs({ active: 0, value: { active: '.on', pop: true } })
    await wrapper.setProps({ active: 2 })
    await flushPromises()
    expect(markOf(group)).toEqual({ x: 200, y: 0, w: 100, h: 40 })
    expect(fakes.all.filter((animation) => animation.id === 'indicator-pop')).toHaveLength(0)
  })

  it('follow：点击即出发；当前项迟迟不变时滑回原处', async () => {
    const { group } = mountTabs({ active: 0, value: { active: '.on', follow: 'button' } })
    const target = group.querySelectorAll('button')[2]!
    target.dispatchEvent(new MouseEvent('click', { bubbles: true, button: 0 }))
    expect(group.hasAttribute('data-indicator-pending')).toBe(true)
    expect(target.hasAttribute('data-indicator-target')).toBe(true)
    expect(last(play(group, 800))?.x).toBe(200)
    // 1.5 秒内当前项没有跟着变（导航被取消）：撤掉点击出发，滑回当前项。
    vi.advanceTimersByTime(800)
    expect(group.hasAttribute('data-indicator-pending')).toBe(false)
    expect(target.hasAttribute('data-indicator-target')).toBe(false)
    expect(last(play(group, 800))?.x).toBe(0)
  })

  it('只改了内边距或边框、内容尺寸不变时也重新对齐：尺寸按边框盒观察', () => {
    // jsdom 没有 ResizeObserver：换成一个记下观察方式、可以手动通知的替身。
    const boxes: (string | undefined)[] = []
    let notify = () => {}
    vi.stubGlobal('ResizeObserver', class {
      constructor(callback: ResizeObserverCallback) {
        notify = () => callback([], this as unknown as ResizeObserver)
      }
      observe(_target: Element, options?: ResizeObserverOptions) { boxes.push(options?.box) }
      unobserve() {}
      disconnect() {}
    })
    const { group } = mountTabs({ active: 1 })
    expect(boxes.length).toBeGreaterThan(0)
    expect(boxes.every((box) => box === 'border-box')).toBe(true)

    // 从窄屏拉宽时漫画版样式表晚到：组多出 3px 内边距，各项整体挪位，组与各项的内容尺寸都没变。
    group.querySelectorAll('button').forEach((button, index) => button.setAttribute('data-box', `${index * 100 + 3} 3 100 40`))
    notify()
    expect(markOf(group)).toEqual({ x: 103, y: 3, w: 100, h: 40 })
  })
})

describe('boxWithin', () => {
  let restoreLayout: () => void
  beforeEach(() => {
    restoreLayout = stubLayout()
  })
  afterEach(() => {
    restoreLayout()
    document.body.innerHTML = ''
  })

  it('沿定位父级链累加布局偏移，扣掉中间容器的滚动距离', () => {
    document.body.innerHTML = '<div id="group" data-box="10 10 300 200"><div id="inner" data-box="20 30 200 100"><span id="item" data-box="5 6 40 20"></span></div></div>'
    const group = document.getElementById('group')!
    const inner = document.getElementById('inner')!
    const item = document.getElementById('item')!
    expect(boxWithin(group, item)).toEqual({ x: 25, y: 36, w: 40, h: 20 })
    Object.defineProperty(inner, 'scrollLeft', { configurable: true, value: 12 })
    expect(boxWithin(group, item)).toEqual({ x: 13, y: 36, w: 40, h: 20 })
  })

  it('组本身不是定位元素时退回屏幕矩形换算', () => {
    document.body.innerHTML = '<div data-box="0 0 800 600"><div id="group" data-static data-box="10 10 300 200"><span id="item" data-box="5 6 40 20"></span></div></div>'
    expect(boxWithin(document.getElementById('group')!, document.getElementById('item')!)).toEqual({ x: 5, y: 6, w: 40, h: 20 })
  })
})
