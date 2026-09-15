import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
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

  it('toggles compact mode (caption hidden) when the card is shorter than the threshold', async () => {
    // jsdom 无 ResizeObserver：打桩捕获回调；clientHeight 恒 0，用 defineProperty 模拟高度
    let roCallback: ResizeObserverCallback | null = null
    class StubRO {
      constructor(cb: ResizeObserverCallback) { roCallback = cb }
      observe() {}
      disconnect() {}
      unobserve() {}
    }
    vi.stubGlobal('ResizeObserver', StubRO)

    const wrapper = mount(DashboardRadarCard, {
      props: { seedDate: '2026-09-03', live: true },
    })
    await flushPromises()
    expect(roCallback).not.toBeNull()
    // jsdom clientHeight = 0 → 守卫视为未知，不进紧凑模式
    expect(wrapper.classes()).not.toContain('radar-card--short')

    const el = wrapper.element as HTMLElement
    const setHeight = (h: number) => Object.defineProperty(el, 'clientHeight', { value: h, configurable: true })
    const fire = async () => {
      roCallback!([] as never[], {} as ResizeObserver)
      await wrapper.vm.$nextTick()
    }

    setHeight(90)
    await fire()
    expect(wrapper.classes()).toContain('radar-card--short')

    setHeight(200)
    await fire()
    expect(wrapper.classes()).not.toContain('radar-card--short')

    vi.unstubAllGlobals()
  })
})
