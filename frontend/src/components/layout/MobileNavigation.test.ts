import { mount, type VueWrapper } from '@vue/test-utils'
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'
import MobileNavigation from './MobileNavigation.vue'
import { NAV_ITEMS } from '@/features/navigation/navigationModel'
import i18n, { setAppLocale } from '@/i18n'

let wrapper: VueWrapper | undefined
const showModal = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'showModal')
const close = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'close')

beforeAll(() => {
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value() { this.setAttribute('open', '') } })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value() { this.removeAttribute('open'); this.dispatchEvent(new Event('close')) } })
})
afterAll(() => {
  for (const [name, descriptor] of [['showModal', showModal], ['close', close]] as const) {
    if (descriptor) Object.defineProperty(HTMLDialogElement.prototype, name, descriptor)
    else Reflect.deleteProperty(HTMLDialogElement.prototype, name)
  }
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined })

function render(extra = {}) {
  setAppLocale('zh-CN')
  wrapper = mount(MobileNavigation, {
    attachTo: document.body,
    props: { items: NAV_ITEMS, currentPath: '/', isAdmin: false, isLoggedIn: false, ...extra },
    global: { plugins: [i18n], stubs: {
      RouterLink: { props: ['to'], template: '<a :href="to"><slot /></a>' },
      PwaInstallLink: { template: '<button type="button" aria-label="安装应用">Install</button>' },
    } },
  })
  return wrapper
}

describe('mobile navigation', () => {
  it('keeps the tracking dot until the supplied unread status clears', async () => {
    const nav = render({ isLoggedIn: true, alertItems: ['/subscriptions'] })
    const dot = 'a[href="/subscriptions"] .mobile-nav__alert'
    expect(nav.get(dot).attributes('aria-label')).toBe('有未读追踪结果，查看结果后清除')
    await nav.setProps({ currentPath: '/subscriptions' })
    expect(nav.find(dot).exists()).toBe(true)
    await nav.setProps({ alertItems: [] })
    expect(nav.find(dot).exists()).toBe(false)
  })
  it('keeps readable primary links including MCP available to guests', () => {
    const nav = render()
    expect(nav.findAll('.mobile-nav > a').map(link => link.attributes('href'))).toEqual(['/', '/projects', '/report', '/mcp', '/subscriptions'])
    expect(nav.get('a[href="/mcp"]').text()).toBe('MCP 接入')
    expect(document.querySelector('dialog a[href="/monitor"]')).toBeNull()
    expect(document.querySelector('dialog a[href="/wechat"]')).toBeNull()
  })

  it('opens additional links and closes the sheet after navigation', async () => {
    const nav = render()
    await nav.get('button[aria-haspopup="dialog"]').trigger('click')
    expect(document.querySelector('dialog')?.hasAttribute('open')).toBe(true)
    expect(nav.get('button[aria-haspopup="dialog"]').attributes('aria-expanded')).toBe('true')
    await nav.setProps({ currentPath: '/dsh' })
    expect(document.querySelector('dialog')?.hasAttribute('open')).toBe(false)
    expect(nav.get('button[aria-haspopup="dialog"]').classes()).toContain('is-active')
  })

  it('preserves query-aware collection navigation', () => {
    const nav = render({ currentPath: '/projects', currentQuery: { source: 'website' } })
    expect(nav.get('a[href="/projects"]').attributes('aria-current')).toBeUndefined()
    expect(document.querySelector('dialog a[href="/projects?source=website"]')?.getAttribute('aria-current')).toBe('page')
    expect(nav.get('button[aria-haspopup="dialog"]').classes()).toContain('is-active')
  })

  it('closes the sheet before handing off to account login', async () => {
    const nav = render()
    await nav.get('button[aria-haspopup="dialog"]').trigger('click')
    ;(document.querySelector('.mobile-menu__account button') as HTMLButtonElement).click()
    expect(nav.emitted('login')).toHaveLength(1)
    expect(document.querySelector('dialog')?.hasAttribute('open')).toBe(false)
  })

  it('keeps administrative alerts available inside More', async () => {
    const nav = render({ isAdmin: true, isLoggedIn: true, alertItems: ['/monitor'] })
    expect(nav.find('.mobile-nav__alert').exists()).toBe(true)
    expect(document.querySelector('dialog a[href="/monitor"] .mobile-menu__alert')).not.toBeNull()
    await nav.setProps({ isAdmin: false })
    expect(document.querySelector('dialog a[href="/monitor"]')).toBeNull()
    expect(nav.find('.mobile-nav__alert').exists()).toBe(false)
  })

  it('releases the modal layer before showing the app installation guide', async () => {
    const nav = render()
    await nav.get('button[aria-haspopup="dialog"]').trigger('click')
    ;(document.querySelector('.mobile-menu__utilities button[aria-label="安装应用"]') as HTMLButtonElement).click()
    expect(document.querySelector('dialog')?.hasAttribute('open')).toBe(false)
  })
})
