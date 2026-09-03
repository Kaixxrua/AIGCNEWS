import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import DashboardRadarCard from './DashboardRadarCard.vue'

describe('DashboardRadarCard', () => {
  it('stays on the static fallback in jsdom (no WebGL2) and shows LIVE caption for today', async () => {
    const wrapper = mount(DashboardRadarCard, {
      props: { seedDate: '2026-09-03', live: true },
    })
    await flushPromises()

    expect(wrapper.attributes('aria-hidden')).toBe('true')
    expect(wrapper.text()).toContain('AIGC RADAR · LIVE')
    expect(wrapper.find('.radar-fallback').exists()).toBe(true)
    expect(wrapper.find('canvas').exists()).toBe(true)
    // jsdom 没有 WebGL2：canvas 永不淡入，兜底层保留
    expect(wrapper.classes()).not.toContain('radar-card--live')
  })

  it('derives MM/DD caption from seedDate when viewing history', () => {
    const wrapper = mount(DashboardRadarCard, {
      props: { seedDate: '2026-01-05', live: false },
    })
    expect(wrapper.text()).toContain('AIGC RADAR · 01/05')
  })

  it('tolerates pointer interaction before/without WebGL boot', async () => {
    const wrapper = mount(DashboardRadarCard, {
      props: { seedDate: '2026-09-03', live: true },
    })
    await flushPromises()
    // 监听器只在 WebGL 启动成功后注册；未启动时交互必须静默无异常
    wrapper.element.dispatchEvent(new Event('pointermove'))
    wrapper.element.dispatchEvent(new Event('pointerdown'))
    expect(wrapper.find('.radar-fallback').exists()).toBe(true)
  })
})
