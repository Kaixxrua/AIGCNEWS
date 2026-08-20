import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { nextTick } from 'vue'
import { describe, expect, it } from 'vitest'
import LoginDialog from './LoginDialog.vue'
import LoginForm from './LoginForm.vue'

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': { common: { close: '关闭' } } } })
const mountDialog = () => mount(LoginDialog, {
  attachTo: document.body,
  props: { modelValue: true, redirect: '/dsh' },
  global: {
    plugins: [i18n],
    stubs: { LoginForm: { props: ['redirect', 'dialog'], emits: ['success', 'close'], template: '<button class="login-form" @click="$emit(\'success\')">登录</button>' } },
  },
})

describe('LoginDialog', () => {
  it('renders as a modal and closes when the form emits close', async () => {
    const wrapper = mountDialog()
    expect(document.body.querySelector('[role="dialog"]')?.getAttribute('aria-modal')).toBe('true')
    wrapper.findComponent(LoginForm).vm.$emit('close')
    await nextTick()
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
    wrapper.unmount()
  })

  it('closes from a backdrop click outside the card', async () => {
    const wrapper = mountDialog()
    ;(document.body.querySelector('[role="dialog"]') as HTMLElement).click()
    await nextTick()
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
    wrapper.unmount()
  })

  it('emits success and closes when the form succeeds', async () => {
    const wrapper = mountDialog()
    wrapper.findComponent(LoginForm).vm.$emit('success')
    await nextTick()
    expect(wrapper.emitted('success')).toHaveLength(1)
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
    wrapper.unmount()
  })
})
