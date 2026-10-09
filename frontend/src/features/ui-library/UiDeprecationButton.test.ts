import { flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import UiDeprecationButton from './UiDeprecationButton.vue'

const mocks = vi.hoisted(() => ({ put: vi.fn(), auth: { isAdmin: false } }))
vi.mock('@/services/http/apiClient', () => ({ api: { put: mocks.put } }))
vi.mock('@/stores/authStore', () => ({ useAuthStore: () => mocks.auth }))

beforeEach(() => {
  mocks.put.mockReset()
  mocks.auth = reactive({ isAdmin: true })
})

describe('UI material moderation', () => {
  it('only shows the control to administrators', async () => {
    mocks.auth.isAdmin = false
    const wrapper = mount(UiDeprecationButton, { props: { id: 'demo:one', lang: 'zh' } })
    expect(wrapper.find('button').exists()).toBe(false)
    expect(mocks.put).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('persists deprecation, allows restoration, and keeps the existing state on failure', async () => {
    const wrapper = mount(UiDeprecationButton, { props: { id: 'demo:one', lang: 'zh' } })
    let resolve!: (value: { data: { deprecated: boolean } }) => void
    mocks.put.mockReturnValueOnce(new Promise(done => { resolve = done }))
    await wrapper.get('button').trigger('click')
    expect(wrapper.get('button').attributes('disabled')).toBeDefined()
    await wrapper.get('button').trigger('click')
    expect(mocks.put).toHaveBeenCalledTimes(1)
    resolve({ data: { deprecated: true } })
    await flushPromises()
    expect(mocks.put).toHaveBeenCalledWith('/ops/ui-library/demo%3Aone/visibility', { deprecated: true })
    expect(wrapper.emitted('changed')).toEqual([[true]])
    await wrapper.setProps({ deprecated: true })
    expect(wrapper.get('button').text()).toBe('已废弃 · 恢复')
    mocks.put.mockRejectedValueOnce(new Error('unavailable'))
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role=alert]').text()).toContain('操作失败')
    expect(wrapper.emitted('changed')).toHaveLength(1)
    mocks.put.mockResolvedValueOnce({ data: { deprecated: false } })
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(wrapper.emitted('changed')).toEqual([[true], [false]])
    wrapper.unmount()
  })

  it('ignores a late admin response after logout', async () => {
    let resolve!: (value: { data: { deprecated: boolean } }) => void
    mocks.put.mockReturnValueOnce(new Promise(done => { resolve = done }))
    const wrapper = mount(UiDeprecationButton, { props: { id: 'demo', lang: 'en' } })
    await wrapper.get('button').trigger('click')
    mocks.auth.isAdmin = false
    resolve({ data: { deprecated: true } })
    await flushPromises()
    expect(wrapper.find('button').exists()).toBe(false)
    expect(wrapper.emitted('changed')).toBeUndefined()
    wrapper.unmount()
  })
})
