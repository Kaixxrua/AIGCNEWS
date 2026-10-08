import { mount } from '@vue/test-utils'
import { computed, defineComponent, onMounted, ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { useMediaQuery } from '@vueuse/core'
import DashboardView from './DashboardView.vue'

vi.mock('@vueuse/core', async (original) => ({
  ...await original<typeof import('@vueuse/core')>(),
  useMediaQuery: vi.fn(),
}))

describe('dashboard responsive rendering', () => {
  it('preserves the selected date and dashboard instance when the screen crosses the desktop breakpoint', async () => {
    const desktop = ref(false)
    const mounted = vi.fn()
    vi.mocked(useMediaQuery).mockReturnValue(computed(() => desktop.value))
    const content = defineComponent({
      setup() {
        onMounted(mounted)
        return { date: ref('2026-10-07') }
      },
      template: '<div data-dashboard><input v-model="date" type="date" aria-label="Date" /></div>',
    })
    const wrapper = mount(DashboardView, {
      global: {
        stubs: {
          DashboardContent: content,
        },
      },
    })
    const input = wrapper.get('input')
    await input.setValue('2026-10-01')
    desktop.value = true
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll('[data-dashboard]')).toHaveLength(1)
    expect(wrapper.get('input').element).toBe(input.element)
    expect((wrapper.get('input').element as HTMLInputElement).value).toBe('2026-10-01')
    desktop.value = false
    await wrapper.vm.$nextTick()
    expect((wrapper.get('input').element as HTMLInputElement).value).toBe('2026-10-01')
    expect(mounted).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
})
