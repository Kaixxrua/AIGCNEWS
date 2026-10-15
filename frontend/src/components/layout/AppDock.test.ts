import { createApp, nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import AppDock from './AppDock.vue'
import i18n, { setAppLocale } from '@/i18n'
import { NAV_ITEMS } from '@/features/navigation/navigationModel'

let unmount: (() => void) | undefined

const mountDock = (alertItems: string[] = [], currentPath = '/', currentQuery: Record<string, unknown> = {}) => {
  const host = document.createElement('div')
  document.body.appendChild(host)
  const app = createApp(AppDock, {
    items: NAV_ITEMS,
    currentPath,
    currentQuery,
    isAdmin: true,
    isLoggedIn: true,
    alertItems,
  })
  app.use(i18n)
  // RouterLink 由 router 插件全局注册，测试环境用锚点替身
  app.component('RouterLink', {
    inheritAttrs: true,
    props: ['to'],
    template: '<a :href="to"><slot /></a>',
  })
  app.mount(host)
  unmount = () => { app.unmount(); host.remove() }
  return host
}

describe('AppDock enrichment alert dot', () => {
  afterEach(() => {
    unmount?.()
    unmount = undefined
  })

  it('shows the red dot only on the alerted navigation item', () => {
    setAppLocale('zh-CN')
    const host = mountDock(['/monitor'])

    const monitorLink = host.querySelector('a[href="/monitor"]')
    expect(monitorLink?.querySelector('.dock-alert-dot')).not.toBeNull()
    expect(monitorLink?.querySelector('.dock-alert-dot')?.getAttribute('aria-label')).toBe('GitHub 项目库存在富化失败，请到监控页处理')

    const dashboardLink = host.querySelector('a[href="/"]')
    expect(dashboardLink?.querySelector('.dock-alert-dot')).toBeNull()
  })

  it('renders no alert dots when the alert list is empty', () => {
    setAppLocale('zh-CN')
    const host = mountDock([])
    expect(host.querySelector('.dock-alert-dot')).toBeNull()
  })

  it('labels tracking updates independently from administrative failures', () => {
    setAppLocale('zh-CN')
    const host = mountDock(['/subscriptions', '/monitor'])
    const tracking = host.querySelector('a[href="/subscriptions"]')
    expect(tracking?.querySelector('.dock-alert-dot')?.getAttribute('aria-label')).toBe('有未读追踪结果，查看结果后清除')
    expect(tracking?.getAttribute('aria-label')).toContain('未读追踪结果')
    expect(host.querySelector('a[href="/monitor"] .dock-alert-dot')?.getAttribute('aria-label')).toContain('富化失败')
  })

  it('exposes the website collection link and keeps its active state query-aware', () => {
    setAppLocale('zh-CN')
    const host = mountDock([], '/projects', { source: 'website' })

    const websiteLink = host.querySelector('a[href="/projects?source=website"]')
    expect(websiteLink).not.toBeNull()
    expect(websiteLink?.getAttribute('aria-label')).toBe('我的网页')
    expect(websiteLink?.getAttribute('aria-current')).toBe('page')
    expect(host.querySelector('a[href="/projects"]')?.getAttribute('aria-current')).toBeNull()
  })
})

describe('AppDock account settings entry', () => {
  afterEach(() => {
    unmount?.()
    unmount = undefined
  })

  it('renders the account-settings button for logged-in users and emits accountSettings on click', () => {
    setAppLocale('zh-CN')
    const events: string[] = []
    const host = document.createElement('div')
    document.body.appendChild(host)
    // createApp 场景下 emit 侦听器以 on<Emit> prop 传入
    const app = createApp(AppDock, {
      items: NAV_ITEMS,
      currentPath: '/',
      currentQuery: {},
      isAdmin: true,
      isLoggedIn: true,
      alertItems: [],
      onAccountSettings: () => events.push('accountSettings'),
    })
    app.use(i18n)
    app.component('RouterLink', {
      inheritAttrs: true,
      props: ['to'],
      template: '<a :href="to"><slot /></a>',
    })
    app.mount(host)
    unmount = () => { app.unmount(); host.remove() }

    const button = host.querySelector('button[aria-label="账户设置"]') as HTMLButtonElement | null
    expect(button).not.toBeNull()
    button!.click()
    expect(events).toEqual(['accountSettings'])
  })

  it('updates visible captions and accessible names when switching languages without remounting', async () => {
    setAppLocale('zh-CN')
    const host = mountDock()
    const captions = () => [...host.querySelectorAll('.dock-label')].map(label => label.textContent)
    const chineseCaptions = captions()
    expect(chineseCaptions).toEqual([
      '首页', '项目库', 'UI库', '网页', '简报', 'X动态', 'MCP', 'DSH', '情报追踪', '联系我们', '监控', '账户', '退出', '更多',
    ])

    setAppLocale('en-US')
    await nextTick()
    expect(captions()).toEqual([
      'Home', 'Projects', 'UI Library', 'Websites', 'Briefing', 'X Feed', 'MCP', 'DSH', 'Tracking', 'Contact', 'Monitor', 'Account', 'Log out', 'More',
    ])
    const projects = host.querySelector('a[href="/projects"]')!
    expect(projects.getAttribute('title')).toBe('Projects')
    expect(projects.getAttribute('aria-label')).toBe('Projects')
    expect(host.querySelector('.dock-item--account')?.getAttribute('aria-label')).toBe('Account settings')

    setAppLocale('zh-CN')
    await nextTick()
    expect(captions()).toEqual(chineseCaptions)
    expect(projects.getAttribute('aria-label')).toBe('项目')
  })

  it('translates the guest login caption and switches to account and logout after sign-in', async () => {
    setAppLocale('en-US')
    const wrapper = mount(AppDock, {
      props: { items: [], currentPath: '/', isAdmin: false, isLoggedIn: false },
      global: { plugins: [i18n] },
    })
    unmount = () => wrapper.unmount()
    expect(wrapper.get('.dock-item--account .dock-label').text()).toBe('Log in')
    expect(wrapper.find('.dock-item--logout').exists()).toBe(false)

    setAppLocale('zh-CN')
    await nextTick()
    expect(wrapper.get('.dock-item--account .dock-label').text()).toBe('登录')

    setAppLocale('en-US')
    await wrapper.setProps({ isLoggedIn: true })
    expect(wrapper.get('.dock-item--account .dock-label').text()).toBe('Account')
    expect(wrapper.get('.dock-item--logout .dock-label').text()).toBe('Log out')
  })

  it('labels the entry in English under the en-US locale', () => {
    setAppLocale('en-US')
    const host = mountDock()

    expect(host.querySelector('button[aria-label="Account settings"]')).not.toBeNull()
  })
})

describe('AppDock full bar', () => {
  afterEach(() => {
    unmount?.()
    unmount = undefined
  })

  // 桌面坞站保留全部入口与退出键；「更多」只在 1023px 以下由 CSS 显示
  it('renders every visible destination plus account and sign-out in the bar itself', () => {
    setAppLocale('zh-CN')
    const host = mountDock()

    expect([...host.querySelectorAll('.dock > a')].map(link => link.getAttribute('href'))).toEqual(NAV_ITEMS.map(item => item.to))
    expect([...host.querySelectorAll('.dock > button')].map(button => button.querySelector('.dock-label')?.textContent)).toEqual(['账户', '退出', '更多'])
    expect(host.querySelector('.dock-item--logout')?.classList.contains('dock-item--secondary')).toBe(true)
  })
})

describe('AppDock more menu', () => {
  afterEach(() => {
    unmount?.()
    unmount = undefined
  })

  const mountMenu = (isAdmin = false) => {
    setAppLocale('zh-CN')
    const wrapper = mount(AppDock, {
      attachTo: document.body,
      props: { items: NAV_ITEMS, currentPath: '/', isAdmin, isLoggedIn: false },
      global: {
        plugins: [i18n],
        stubs: { RouterLink: { props: ['to'], template: '<a :href="to" @click.prevent><slot /></a>' } },
      },
    })
    // jsdom does not implement the native dialog methods; focus and Escape are
    // checked in the browser alongside this component's open/close wiring.
    const dialog = wrapper.get('dialog').element as HTMLDialogElement
    Object.defineProperties(dialog, {
      showModal: { value: () => { dialog.open = true } },
      close: { value: () => { dialog.open = false; dialog.dispatchEvent(new Event('close')) } },
    })
    unmount = () => wrapper.unmount()
    return wrapper
  }

  it('opens a modal menu and closes it when a destination is selected', async () => {
    const wrapper = mountMenu()
    const more = wrapper.get('button.dock-item--more')
    const dialog = wrapper.get('dialog').element as HTMLDialogElement
    await more.trigger('click')
    expect(dialog.open).toBe(true)
    expect(more.attributes('aria-expanded')).toBe('true')
    await wrapper.get('.dock-more a[href="/mcp"]').trigger('click')
    expect(dialog.open).toBe(false)
    expect(more.attributes('aria-expanded')).toBe('false')
  })

  it('closes on route changes and marks collection pages as active in More', async () => {
    const wrapper = mountMenu()
    await wrapper.get('button.dock-item--more').trigger('click')
    await wrapper.setProps({ currentPath: '/projects', currentQuery: { source: 'website' } })
    expect((wrapper.get('dialog').element as HTMLDialogElement).open).toBe(false)
    expect(wrapper.get('button.dock-item--more').classes()).toContain('dock-item--active')
    expect(wrapper.get('.dock-more a[href="/projects?source=website"]').attributes('aria-current')).toBe('page')
    expect(wrapper.get('.dock a[href="/projects"]').attributes('aria-current')).toBeUndefined()
  })

  it('preserves permission gates and the direct login entry for guests', async () => {
    const wrapper = mountMenu()
    expect(wrapper.find('a[href="/monitor"]').exists()).toBe(false)
    await wrapper.get('button.dock-item--account').trigger('click')
    expect(wrapper.emitted('login')).toHaveLength(1)
    await wrapper.setProps({ isAdmin: true, isLoggedIn: true, alertItems: ['/monitor'] })
    expect(wrapper.find('.dock-more a[href="/monitor"]').exists()).toBe(true)
    expect(wrapper.find('.dock-item--more .dock-alert-dot').exists()).toBe(true)
  })
})
