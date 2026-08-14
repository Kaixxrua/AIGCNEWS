import { mount } from '@vue/test-utils'
import { defineComponent, nextTick, ref } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import { dockSuppressed, useDockSuppression } from './useDockSuppression'

const mountHolder = (source: () => boolean) => {
  const Probe = defineComponent({
    setup() {
      useDockSuppression(source)
      return () => null
    },
  })
  return mount(Probe, { attachTo: document.body })
}

describe('useDockSuppression', () => {
  afterEach(() => {
    // 模块级计数须归零：holder 均已在用例内卸载
    expect(dockSuppressed.value).toBe(false)
  })

  it('源为 true 期间抑制 dock，翻回 false 恢复', async () => {
    const open = ref(false)
    const wrapper = mountHolder(() => open.value)
    expect(dockSuppressed.value).toBe(false)

    open.value = true
    await nextTick()
    expect(dockSuppressed.value).toBe(true)

    open.value = false
    await nextTick()
    expect(dockSuppressed.value).toBe(false)
    wrapper.unmount()
  })

  it('组件卸载时仍占用则自动归还', async () => {
    const open = ref(true)
    const wrapper = mountHolder(() => open.value)
    await nextTick()
    expect(dockSuppressed.value).toBe(true)

    wrapper.unmount()
    expect(dockSuppressed.value).toBe(false)
  })

  it('多 holder 叠加计数：后关者不抢回先开者的隐藏态', async () => {
    const openA = ref(true)
    const openB = ref(true)
    const wrapperA = mountHolder(() => openA.value)
    const wrapperB = mountHolder(() => openB.value)
    await nextTick()
    expect(dockSuppressed.value).toBe(true)

    openA.value = false
    await nextTick()
    // B 仍开着：保持隐藏
    expect(dockSuppressed.value).toBe(true)

    openB.value = false
    await nextTick()
    expect(dockSuppressed.value).toBe(false)
    wrapperA.unmount()
    wrapperB.unmount()
  })

  it('重复开合不重复计数', async () => {
    const open = ref(false)
    const wrapper = mountHolder(() => open.value)
    open.value = true
    await nextTick()
    open.value = true
    await nextTick()
    open.value = false
    await nextTick()
    expect(dockSuppressed.value).toBe(false)
    wrapper.unmount()
  })
})
