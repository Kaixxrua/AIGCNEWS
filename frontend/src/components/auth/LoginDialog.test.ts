import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import LoginDialog from './LoginDialog.vue'
import LoginForm from './LoginForm.vue'

const ensureFeatureFlags = vi.hoisted(() => vi.fn())
vi.mock('@/composables/useFeatureFlags', () => ({ ensureFeatureFlags }))

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': { common: { close: '关闭' } } } })
const mountDialog = () => mount(LoginDialog, {
  attachTo: document.body,
  props: { modelValue: true, redirect: '/dsh' },
  global: {
    plugins: [i18n],
    stubs: { LoginForm: { props: ['redirect'], emits: ['success', 'close', 'switch-to-register'], template: '<button class="login-form" @click="$emit(\'success\')">登录</button>' } },
  },
})
const mountSettled = async () => {
  const wrapper = mountDialog()
  await flushPromises()
  return wrapper
}
const dialog = () => document.body.querySelector('[role="dialog"]')

beforeEach(() => {
  ensureFeatureFlags.mockReset()
  ensureFeatureFlags.mockResolvedValue({ xSource: true, oauthProviders: ['github', 'google'], telegramPushEnabled: true })
})
afterEach(() => { vi.useRealTimers() })

describe('LoginDialog', () => {
  it('passes redirect to the modal-only form without a dialog mode prop', async () => {
    const wrapper = await mountSettled()
    const form = wrapper.findComponent(LoginForm)
    expect(form.props('redirect')).toBe('/dsh')
    expect(form.props()).not.toHaveProperty('dialog')
    wrapper.unmount()
  })

  it('renders as a modal and closes when the form emits close', async () => {
    const wrapper = await mountSettled()
    expect(dialog()?.getAttribute('aria-modal')).toBe('true')
    wrapper.findComponent(LoginForm).vm.$emit('close')
    await nextTick()
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
    wrapper.unmount()
  })

  it('closes from a backdrop click outside the card', async () => {
    const wrapper = await mountSettled()
    ;(dialog() as HTMLElement).click()
    await nextTick()
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
    wrapper.unmount()
  })

  it('emits success and closes when the form succeeds', async () => {
    const wrapper = await mountSettled()
    wrapper.findComponent(LoginForm).vm.$emit('success')
    await nextTick()
    expect(wrapper.emitted('success')).toHaveLength(1)
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
    wrapper.unmount()
  })

  it('forwards switch-to-register without closing itself (LayoutView owns the swap)', async () => {
    const wrapper = await mountSettled()
    wrapper.findComponent(LoginForm).vm.$emit('switch-to-register')
    await nextTick()
    expect(wrapper.emitted('switch-to-register')).toHaveLength(1)
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    wrapper.unmount()
  })

  it('waits for the sign-in options before showing the card, so the card does not grow and jump once open', async () => {
    let settle!: () => void
    ensureFeatureFlags.mockReturnValue(new Promise<void>((resolve) => { settle = resolve }))
    const wrapper = await mountSettled()
    expect(dialog()).toBeNull()
    settle()
    await flushPromises()
    expect(dialog()).not.toBeNull()
    expect(wrapper.findComponent(LoginForm).exists()).toBe(true)
    wrapper.unmount()
  })

  it('opens anyway when the sign-in options take longer than 1.5 seconds', async () => {
    vi.useFakeTimers()
    ensureFeatureFlags.mockReturnValue(new Promise(() => {}))
    const wrapper = mountDialog()
    await nextTick()
    vi.advanceTimersByTime(1499)
    await nextTick()
    expect(dialog()).toBeNull()
    vi.advanceTimersByTime(1)
    await nextTick()
    expect(dialog()).not.toBeNull()
    wrapper.unmount()
  })
})
