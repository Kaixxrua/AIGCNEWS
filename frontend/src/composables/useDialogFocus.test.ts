import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, h, ref } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import { useDialogFocus } from './useDialogFocus'
import { dockSuppressed, useDockSuppression } from './useDockSuppression'

const Dialog = defineComponent({
  props: { open: Boolean, name: { type: String, default: 'dialog' }, hidesDock: Boolean },
  emits: ['close'],
  setup(props, { emit }) {
    const root = ref<HTMLElement | null>(null)
    // 跟真实弹窗一样：先登记打开期间藏起 dock，再接管焦点
    if (props.hidesDock) useDockSuppression(() => props.open)
    useDialogFocus(() => props.open, root, () => emit('close'))
    return () => props.open
      ? h('div', { ref: root, tabindex: -1, 'data-dialog': props.name }, [
        h('button', { class: 'first' }, 'first'),
        h('input', { class: 'middle' }),
        h('button', { class: 'last' }, 'last'),
        h('button', { disabled: true }, 'disabled'),
      ])
      : null
  },
})

// dock 上的登录按钮：有框开着时被藏起来。jsdom 不排版，用 disabled 代替隐藏，同样聚焦不了。
const DockButton = defineComponent({
  setup: () => () => h('button', { class: 'dock-login', disabled: dockSuppressed.value }, 'log in'),
})

const wrappers: VueWrapper[] = []
const track = <T extends VueWrapper>(wrapper: T) => { wrappers.push(wrapper); return wrapper }
const mountDialog = (name: string, open = true, hidesDock = false) =>
  track(mount(Dialog, { attachTo: document.body, props: { open, name, hidesDock } }))
const container = (name: string) => document.querySelector<HTMLElement>(`[data-dialog="${name}"]`)!
const inside = (name: string, selector: string) => container(name).querySelector<HTMLElement>(selector)!
const press = (key: string, init: KeyboardEventInit = {}) => {
  const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init })
  ;(document.activeElement ?? document.body).dispatchEvent(event)
  return event
}
const openerButton = () => {
  const button = document.createElement('button')
  button.textContent = 'open'
  document.body.append(button)
  button.focus()
  return button
}
const dockButton = () => {
  const button = track(mount(DockButton, { attachTo: document.body })).get<HTMLButtonElement>('.dock-login').element
  button.focus()
  return button
}

afterEach(() => {
  // 卸载会归还 dock 的隐藏计数，失败的用例不连累后面的
  for (const wrapper of wrappers.splice(0)) {
    if (wrapper.vm.$.isMounted && !wrapper.vm.$.isUnmounted) wrapper.unmount()
  }
  document.body.innerHTML = ''
})

describe('useDialogFocus', () => {
  it('moves focus in, keeps Tab inside, closes on Escape and gives focus back', async () => {
    const opener = openerButton()
    const wrapper = mountDialog('login', false)
    await wrapper.setProps({ open: true })
    await flushPromises()
    expect(document.activeElement).toBe(container('login'))

    expect(press('Tab').defaultPrevented).toBe(true)
    expect(document.activeElement).toBe(inside('login', '.first'))
    inside('login', '.middle').focus()
    expect(press('Tab').defaultPrevented).toBe(false)
    inside('login', '.last').focus()
    expect(press('Tab').defaultPrevented).toBe(true)
    expect(document.activeElement).toBe(inside('login', '.first'))
    expect(press('Tab', { shiftKey: true }).defaultPrevented).toBe(true)
    expect(document.activeElement).toBe(inside('login', '.last'))

    press('Escape', { isComposing: true })
    expect(wrapper.emitted('close')).toBeUndefined()
    press('Escape')
    expect(wrapper.emitted('close')).toHaveLength(1)

    await wrapper.setProps({ open: false })
    await flushPromises()
    expect(document.activeElement).toBe(opener)
    press('Escape')
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('hands the return position to the next dialog and never steals focus back from it', async () => {
    const opener = openerButton()
    const login = mountDialog('login')
    await flushPromises()
    inside('login', '.last').focus()

    // 登录框里点「去注册」：注册框先开、登录框后关
    const register = mountDialog('register')
    await flushPromises()
    expect(document.activeElement).toBe(container('register'))
    press('Escape')
    expect(register.emitted('close')).toHaveLength(1)
    expect(login.emitted('close')).toBeUndefined()

    await login.setProps({ open: false })
    await flushPromises()
    expect(document.activeElement).toBe(container('register'))

    await register.setProps({ open: false })
    await flushPromises()
    expect(document.activeElement).toBe(opener)
  })

  it('gives focus back when the dialog is removed while open', async () => {
    const opener = openerButton()
    const wrapper = mountDialog('forgot')
    await flushPromises()
    inside('forgot', '.first').focus()
    wrapper.unmount()
    await flushPromises()
    expect(document.activeElement).toBe(opener)
    press('Escape')
    expect(wrapper.emitted('close')).toBeUndefined()
  })

  it('waits until the dock is back before giving focus to the dock button', async () => {
    // 找回密码框关闭即卸载；卸载的那一刻 dock 还藏着，这一轮重绘完才回来
    const opener = dockButton()
    const forgot = mountDialog('forgot', true, true)
    await flushPromises()
    expect(opener.disabled).toBe(true)
    expect(document.activeElement).toBe(container('forgot'))

    forgot.unmount()
    await flushPromises()
    expect(opener.disabled).toBe(false)
    expect(document.activeElement).toBe(opener)
  })

  it('lets a dialog opened right after another was removed take over its return position', async () => {
    // 找回密码切回登录：找回密码框先卸载，登录框随后打开；关掉登录框，焦点回到最初的 dock 按钮
    const opener = dockButton()
    const forgot = mountDialog('forgot', true, true)
    const login = mountDialog('login', false, true)
    await flushPromises()

    forgot.unmount()
    await login.setProps({ open: true })
    await flushPromises()
    expect(document.activeElement).toBe(container('login'))

    press('Escape')
    expect(login.emitted('close')).toHaveLength(1)
    await login.setProps({ open: false })
    await flushPromises()
    expect(document.activeElement).toBe(opener)
  })
})
