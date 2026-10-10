import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '@/i18n'
import McpEndpointCard from './McpEndpointCard.vue'

const copyToClipboard = vi.hoisted(() => vi.fn())
const showToast = vi.hoisted(() => vi.fn())
vi.mock('@/composables/useClipboard', () => ({ copyToClipboard }))
vi.mock('@/composables/useToast', () => ({ showToast }))

beforeEach(() => {
  i18n.global.locale.value = 'zh-CN'
  copyToClipboard.mockReset().mockResolvedValue(undefined)
  showToast.mockReset()
})

describe('McpEndpointCard', () => {
  it('shows the OAuth address, breaking only after its last slash', () => {
    const wrapper = mount(McpEndpointCard, { global: { plugins: [i18n] } })
    const endpoint = wrapper.get('.agent-endpoint')
    expect(endpoint.text()).toBe('https://aigcnews.cn/api/mcp/oauth')
    expect(endpoint.html()).toContain('https://aigcnews.cn/api/mcp/<wbr>oauth')
    expect(endpoint.attributes('translate')).toBe('no')
  })

  it('copies the address and says so', async () => {
    const wrapper = mount(McpEndpointCard, { global: { plugins: [i18n] } })
    await wrapper.get('.agent-btn').trigger('click')
    await flushPromises()

    expect(copyToClipboard).toHaveBeenCalledWith('https://aigcnews.cn/api/mcp/oauth')
    expect(wrapper.get('.agent-btn').text()).toBe('已复制')
    wrapper.unmount()
  })

  it('tells the reader when the clipboard refuses', async () => {
    copyToClipboard.mockRejectedValueOnce(new Error('denied'))
    const wrapper = mount(McpEndpointCard, { global: { plugins: [i18n] } })
    await wrapper.get('.agent-btn').trigger('click')
    await flushPromises()

    expect(showToast).toHaveBeenCalledWith(i18n.global.t('mcp.copyFailed'))
    expect(wrapper.get('.agent-btn').text()).toBe('复制地址')
    wrapper.unmount()
  })
})
