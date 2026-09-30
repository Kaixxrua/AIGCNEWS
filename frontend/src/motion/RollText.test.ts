import { enableAutoUnmount, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { morphSize } from './morph'
import RollText from './RollText.vue'

vi.mock('./morph', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./morph')>()),
  morphSize: vi.fn(),
}))

enableAutoUnmount(afterEach)

describe('RollText', () => {
  beforeEach(() => {
    vi.mocked(morphSize).mockClear()
  })

  it('显示 value，滚动方向与延迟写成样式变量', () => {
    const wrapper = mount(RollText, { props: { value: '¥19', direction: -1, delay: 60 } })
    expect(wrapper.text()).toBe('¥19')
    expect(wrapper.attributes('style')).toContain('--roll-dir: -1')
    expect(wrapper.attributes('style')).toContain('--roll-delay: 60ms')
    expect(wrapper.classes()).toContain('roll-text--morph')
  })

  it('value 变了就换一个新节点滚入，外框宽度交给 morphSize 过渡', async () => {
    const wrapper = mount(RollText, { props: { value: '改为年付', delay: 60 } })
    const before = wrapper.get('.roll-text-value').element
    await wrapper.setProps({ value: '改为月付' })
    expect(wrapper.get('.roll-text-value').element).not.toBe(before)
    expect(wrapper.text()).toBe('改为月付')
    expect(morphSize).toHaveBeenCalledWith(wrapper.element, { width: 0, height: 0 }, { delay: 60, clip: false })
  })

  it('morph=false 时宽度交给外层，自己不过渡', async () => {
    const wrapper = mount(RollText, { props: { value: 1, morph: false } })
    await wrapper.setProps({ value: 2 })
    expect(wrapper.text()).toBe('2')
    expect(wrapper.classes()).not.toContain('roll-text--morph')
    expect(morphSize).not.toHaveBeenCalled()
  })

  it('插槽放带样式的内容时，value 只是换没换的判据', async () => {
    const wrapper = mount(RollText, {
      props: { value: '¥19 /月' },
      slots: { default: '<b class="amount">¥19</b><i>/月</i>' },
    })
    const before = wrapper.get('.roll-text-value').element
    expect(wrapper.get('.amount').text()).toBe('¥19')
    await wrapper.setProps({ value: '¥19 /月' })
    expect(wrapper.get('.roll-text-value').element).toBe(before)
  })
})
