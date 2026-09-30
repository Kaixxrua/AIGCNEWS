import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, withDirectives } from 'vue'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { morphSize, vMorph } from './morph'
import { installFakeAnimations, stubLayout, type FakeAnimations } from './testing'

enableAutoUnmount(afterEach)

// 换文案的按钮：宽高写在行内样式里（jsdom 的计算样式只认它），box 是排版后的位置。
const Chip = defineComponent({
  props: {
    label: { type: String, required: true },
    width: { type: Number, required: true },
    height: { type: Number, default: 30 },
    box: { type: String, default: '' },
  },
  setup(props) {
    return () => h('div', { 'data-box': '0 0 300 100' }, [
      withDirectives(
        h('button', { style: { width: `${props.width}px`, height: `${props.height}px` }, 'data-box': props.box || `0 0 ${props.width} ${props.height}` }, props.label),
        [[vMorph, props.label]],
      ),
    ])
  },
})

let fakes: FakeAnimations
let restoreLayout: () => void

const mountChip = (props: { label: string; width: number; height?: number; box?: string }) => {
  const wrapper = mount(Chip, { props, attachTo: document.body })
  return { wrapper, button: wrapper.get('button').element as HTMLElement }
}

describe('v-morph', () => {
  beforeEach(() => {
    fakes = installFakeAnimations()
    restoreLayout = stubLayout()
  })

  afterEach(() => {
    fakes.restore()
    restoreLayout()
  })

  it('换了文案、宽度变了：宽度从旧值平滑走到新值，只裁右缘', async () => {
    const { wrapper, button } = mountChip({ label: '月付', width: 80 })
    await wrapper.setProps({ label: '改为年付', width: 120 })
    await flushPromises()
    const [morph] = fakes.on(button, 'morph')
    const clipPath = 'inset(-100vmax -3px -100vmax -100vmax)'
    expect(morph?.keyframes).toEqual([{ width: '80px', clipPath }, { width: '120px', clipPath }])
    expect(morph?.options).toMatchObject({ duration: 420, fill: 'backwards' })
  })

  it('只有高度变时只过渡高度、只裁下缘', async () => {
    const { wrapper, button } = mountChip({ label: '一行', width: 120 })
    await wrapper.setProps({ label: '换成两行', height: 52 })
    await flushPromises()
    const clipPath = 'inset(-100vmax -100vmax -3px -100vmax)'
    expect(fakes.on(button, 'morph')[0]?.keyframes).toEqual([{ height: '30px', clipPath }, { height: '52px', clipPath }])
  })

  it('key 没变或尺寸没变都不过渡', async () => {
    const { wrapper, button } = mountChip({ label: '月付', width: 80 })
    await wrapper.setProps({ width: 120 })
    await wrapper.setProps({ label: '年付' })
    await flushPromises()
    expect(fakes.on(button)).toHaveLength(0)
  })

  it('按起点尺寸会落到另一行时不走尺寸过渡，尺寸一步到位，从原处滑到新的一行', async () => {
    const { wrapper, button } = mountChip({ label: '月付', width: 80, box: '200 0 80 30' })
    // 起点宽度还放得下第一行：尺寸过渡一开始就会把按钮挤回第一行（接着又跳到第二行）。
    const animate = Element.prototype.animate
    button.animate = function (this: HTMLElement, keyframes, options) {
      const animation = animate.call(this, keyframes, options)
      if (Array.isArray(keyframes) && keyframes[0] && 'width' in keyframes[0]) {
        this.dataset.box = '200 0 80 30'
        animation.addEventListener('cancel', () => { this.dataset.box = '0 40 120 30' })
      }
      return animation
    }
    await wrapper.setProps({ label: '改为年付', width: 120, box: '0 40 120 30' })
    await flushPromises()
    const [resize, glide, clip] = fakes.on(button, 'morph')
    expect(resize?.playState).toBe('idle')
    // 横竖各按离得近的那条边对齐：右缘 280 → 120，上缘 0 → 40。
    expect(glide?.keyframes).toEqual([{ translate: '160px -40px' }, { translate: '0 0' }])
    expect(glide?.options.composite).toBe('add')
    expect(clip?.keyframes).toEqual([{ clipPath: 'inset(-100vmax -3px -100vmax -100vmax)' }, { clipPath: 'inset(-100vmax -3px -100vmax -100vmax)' }])
  })
})

describe('morphSize', () => {
  beforeEach(() => {
    fakes = installFakeAnimations()
  })

  afterEach(() => {
    fakes.restore()
    document.body.innerHTML = ''
  })

  it('同一轮里的调用攒到本轮末尾一起起步', async () => {
    document.body.innerHTML = '<span id="a" style="width: 60px; height: 20px"></span><span id="b" style="width: 40px; height: 20px"></span>'
    const a = document.getElementById('a')!
    const b = document.getElementById('b')!
    morphSize(a, { width: 30, height: 20 }, { delay: 60 })
    morphSize(b, { width: 90, height: 20 }, { clip: false })
    expect(fakes.all).toHaveLength(0)
    await Promise.resolve()
    expect(fakes.on(a, 'morph')[0]?.options.delay).toBe(60)
    expect(fakes.on(b, 'morph')[0]?.keyframes).toEqual([{ width: '90px' }, { width: '40px' }])
  })
})
