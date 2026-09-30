import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, withDirectives, type PropType } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { vSwap } from './swap'
import { installFakeAnimations, stubReducedMotion, type FakeAnimations } from './testing'

enableAutoUnmount(afterEach)

const List = defineComponent({
  props: {
    swapKey: { type: String as PropType<string | null>, default: null },
    count: { type: Number, default: 3 },
    stagger: Boolean,
    x: { type: Number, default: undefined },
    y: { type: Number, default: undefined },
  },
  setup(props) {
    return () => withDirectives(
      h('ul', Array.from({ length: props.count }, (_, index) => h('li', { key: index }, `${index}`))),
      [[vSwap, { key: props.swapKey, stagger: props.stagger, x: props.x, y: props.y }]],
    )
  },
})

let fakes: FakeAnimations

describe('v-swap', () => {
  beforeEach(() => {
    fakes = installFakeAnimations()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    fakes.restore()
  })

  it('key 变了时新内容淡入浮现', async () => {
    const wrapper = mount(List, { props: { swapKey: 'a' } })
    await wrapper.setProps({ swapKey: 'b' })
    await flushPromises()
    const [swap] = fakes.on(wrapper.element, 'swap')
    expect(swap?.keyframes).toEqual([{ opacity: 0, translate: '0px 10px' }, { opacity: 1, translate: '0 0' }])
    expect(swap?.options).toMatchObject({ duration: 340, delay: 0, fill: 'backwards' })
  })

  it('x/y 决定从哪个方向进来（比如翻月）', async () => {
    const wrapper = mount(List, { props: { swapKey: '2026-09', x: -18, y: 0 } })
    await wrapper.setProps({ swapKey: '2026-08' })
    expect(fakes.on(wrapper.element, 'swap')[0]?.frame(0)).toEqual({ opacity: 0, translate: '-18px 0px' })
  })

  it('stagger：直接子元素依次入场，间隔封顶，太长的列表只动前 36 项', async () => {
    const wrapper = mount(List, { props: { swapKey: 'a', count: 40, stagger: true } })
    await wrapper.setProps({ swapKey: 'b' })
    const items = wrapper.findAll('li').map((item) => item.element)
    expect(fakes.on(wrapper.element)).toHaveLength(0)
    expect(fakes.on(items[0]!, 'swap')[0]?.options.delay).toBe(0)
    expect(fakes.on(items[5]!, 'swap')[0]?.options.delay).toBe(130)
    expect(fakes.on(items[20]!, 'swap')[0]?.options.delay).toBe(312)
    expect(fakes.on(items[35]!, 'swap')).toHaveLength(1)
    expect(fakes.on(items[36]!, 'swap')).toHaveLength(0)
  })

  it('加载中（key 为空）不播，加载完回到有值时再播；key 不变的重渲染不播', async () => {
    const wrapper = mount(List, { props: { swapKey: 'a' } })
    await wrapper.setProps({ swapKey: null })
    expect(fakes.all).toHaveLength(0)
    await wrapper.setProps({ count: 5 })
    expect(fakes.all).toHaveLength(0)
    await wrapper.setProps({ swapKey: 'b' })
    expect(fakes.on(wrapper.element, 'swap')).toHaveLength(1)
  })

  it('连着切换时停掉上一段，从头再播', async () => {
    const wrapper = mount(List, { props: { swapKey: 'a' } })
    await wrapper.setProps({ swapKey: 'b' })
    const [first] = fakes.on(wrapper.element, 'swap')
    await wrapper.setProps({ swapKey: 'c' })
    expect(first?.playState).toBe('idle')
    expect(fakes.on(wrapper.element, 'swap')).toHaveLength(2)
  })

  it('用户偏好减少动态时直接换', async () => {
    stubReducedMotion()
    const wrapper = mount(List, { props: { swapKey: 'a' } })
    await wrapper.setProps({ swapKey: 'b' })
    expect(fakes.all).toHaveLength(0)
  })
})
