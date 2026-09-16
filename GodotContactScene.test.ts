import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import GodotContactScene from './GodotContactScene.vue'

describe('GodotContactScene', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    Object.defineProperty(document, 'fullscreenElement', { configurable: true, value: null })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('exposes accessible SVG controls in the scene action group', () => {
    const wrapper = mount(GodotContactScene)
    const buttons = wrapper.findAll('.scene-actions button')

    expect(buttons).toHaveLength(2)
    expect(buttons[0]!.attributes('aria-label')).toBe('全屏显示原野')
    expect(buttons[0]!.find('svg').attributes('aria-hidden')).toBe('true')
    expect(buttons[0]!.text()).toBe('')
    expect(buttons[1]!.attributes('aria-label')).toBe('重新载入原野')
    expect(buttons[1]!.find('svg').attributes('aria-hidden')).toBe('true')
    expect(buttons[1]!.text()).toBe('')
  })

  it('shows a truthful retry state when the bridge never connects', async () => {
    const wrapper = mount(GodotContactScene)
    vi.advanceTimersByTime(30_000)
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.scene-status').text()).toBe('原野暂未连接，可重新载入。')
    expect(wrapper.find('.scene-status').classes()).toContain('scene-status--visible')
  })
})
