import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick, ref, type Component } from 'vue'
import { lazyComponent, preloadWhen } from './lazyComponent'

const Pane = defineComponent({
  props: { label: { type: String, required: true } },
  setup: (props) => () => h('p', { class: 'pane' }, props.label),
})

/** 像 import() 那样在下一个任务才兑现，模块对象带 Module 标记。 */
const fromNetwork = () => vi.fn(() => new Promise<{ default: typeof Pane }>((resolve) => {
  setTimeout(() => resolve({ default: Pane, [Symbol.toStringTag]: 'Module' } as { default: typeof Pane }), 0)
}))

/** 等到下一个任务：fromNetwork 的包此时已到。 */
const nextTask = () => new Promise((resolve) => setTimeout(resolve, 0))

/** 只走微任务，不让出给浏览器绘制。 */
async function microtasks(rounds = 10) {
  for (let i = 0; i < rounds; i += 1) await Promise.resolve()
}

function host(component: Component) {
  const shown = ref(false)
  const wrapper = mount(defineComponent({ setup: () => () => (shown.value ? h(component, { label: 'pane' }) : null) }))
  return { wrapper, show: () => { shown.value = true } }
}

describe('lazyComponent', () => {
  it('draws a preloaded component before the browser gets a chance to paint', async () => {
    const loader = fromNetwork()
    const lazy = lazyComponent(loader)
    lazy.preload()
    lazy.preload()
    await nextTask()

    const { wrapper, show } = host(lazy.component)
    show()
    await microtasks()
    expect(wrapper.find('.pane').text()).toBe('pane')
    expect(loader).toHaveBeenCalledTimes(1)
  })

  it('without a preload the first render waits for the download', async () => {
    const lazy = lazyComponent(fromNetwork())
    const { wrapper, show } = host(lazy.component)
    show()
    await microtasks()
    expect(wrapper.find('.pane').exists()).toBe(false)

    await nextTask()
    await flushPromises()
    expect(wrapper.find('.pane').text()).toBe('pane')
  })

  it('tries again after a failed download', async () => {
    const loader = vi.fn()
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValue({ default: Pane, [Symbol.toStringTag]: 'Module' })
    const lazy = lazyComponent(loader)
    lazy.preload()
    await flushPromises()
    lazy.preload()
    await flushPromises()
    expect(loader).toHaveBeenCalledTimes(2)

    const { wrapper, show } = host(lazy.component)
    show()
    await microtasks()
    expect(wrapper.find('.pane').text()).toBe('pane')
  })
})

describe('preloadWhen', () => {
  it('preloads at once when the condition already holds, otherwise when it first turns true', async () => {
    const wide = ref(false)
    const desktop = ref(true)
    const pane = vi.fn()
    const sheet = vi.fn()
    mount(defineComponent({
      setup() {
        preloadWhen(desktop, sheet)
        preloadWhen(wide, pane)
        return () => null
      },
    }))
    expect(sheet).toHaveBeenCalledTimes(1)
    expect(pane).not.toHaveBeenCalled()

    wide.value = true
    await nextTick()
    expect(pane).toHaveBeenCalledTimes(1)
  })
})
