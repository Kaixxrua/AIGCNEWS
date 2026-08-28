import { createApp } from 'vue'
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
