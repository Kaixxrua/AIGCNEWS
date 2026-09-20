import { mount } from '@vue/test-utils'
import { computed, ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { useMediaQuery } from '@vueuse/core'
import DashboardView from './DashboardView.vue'

vi.mock('@vueuse/core', async (original) => ({
  ...await original<typeof import('@vueuse/core')>(),
  useMediaQuery: vi.fn(),
}))

describe('dashboard responsive rendering', () => {
  it('keeps the existing mobile view and mounts only one dashboard across breakpoint changes', async () => {
    const desktop = ref(false)
    vi.mocked(useMediaQuery).mockReturnValue(computed(() => desktop.value))
    const wrapper = mount(DashboardView, {
      global: {
        stubs: {
          DesktopDashboardView: { template: '<div data-dashboard="desktop" />' },
          MobileDashboardView: { template: '<div data-dashboard="mobile" />' },
        },
      },
    })
    expect(useMediaQuery).toHaveBeenCalledWith('(min-width: 1024px)')
    expect(wrapper.findAll('[data-dashboard]')).toHaveLength(1)
    expect(wrapper.get('[data-dashboard]').attributes('data-dashboard')).toBe('mobile')
    desktop.value = true
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll('[data-dashboard]')).toHaveLength(1)
    expect(wrapper.get('[data-dashboard]').attributes('data-dashboard')).toBe('desktop')
    desktop.value = false
    await wrapper.vm.$nextTick()
    expect(wrapper.get('[data-dashboard]').attributes('data-dashboard')).toBe('mobile')
    wrapper.unmount()
  })
})
