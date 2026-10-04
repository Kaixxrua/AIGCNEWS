import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import ForgotPasswordDialog from './ForgotPasswordDialog.vue'
import { i18n } from '@/i18n'

vi.mock('@/services/http/apiClient', () => ({ api: { post: vi.fn().mockResolvedValue({}) } }))

describe('ForgotPasswordDialog', () => {
  it('is named by its title, takes focus and closes on Escape', async () => {
    const wrapper = mount(ForgotPasswordDialog, {
      attachTo: document.body,
      props: { modelValue: true },
      global: { plugins: [i18n] },
    })
    await flushPromises()
    const dialog = document.body.querySelector('[role="dialog"]') as HTMLElement
    expect(document.getElementById(dialog.getAttribute('aria-labelledby') ?? '')?.textContent).toBe('AIGC 资讯 · 重置密码')
    expect(dialog.contains(document.activeElement)).toBe(true)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
    wrapper.unmount()
  })
})
