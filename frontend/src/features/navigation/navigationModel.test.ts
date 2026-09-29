import { describe, expect, it } from 'vitest'
import { NAV_ITEMS, isNavigationItemActive, isNavigationItemFeatureEnabled, isNavigationItemSitePageEnabled } from './navigationModel'

describe('navigation feature gating', () => {
  it('marks the X board item with its feature key', () => {
    expect(NAV_ITEMS.find((item) => item.to === '/x')?.featureKey).toBe('xSource')
  })

  it('hides feature-gated items only when explicitly disabled', () => {
    expect(
      isNavigationItemFeatureEnabled({ featureKey: 'xSource' }, { xSource: false }),
    ).toBe(false)
    expect(
      isNavigationItemFeatureEnabled({ featureKey: 'xSource' }, { xSource: true }),
    ).toBe(true)
  })

  it('never hides items without a feature key', () => {
    expect(isNavigationItemFeatureEnabled({}, { xSource: false })).toBe(true)
  })
})

describe('navigation site page gating', () => {
  it('marks the contact item with its site page key', () => {
    expect(NAV_ITEMS.find((item) => item.to === '/contact')?.sitePageKey).toBe('contactPage')
  })

  it('hides site-page items unless the page is explicitly enabled (fail-closed)', () => {
    // 与特性门控相反：缺省/显式 false 都隐藏，仅 true 显示
    expect(isNavigationItemSitePageEnabled({ sitePageKey: 'contactPage' }, { contactPage: true })).toBe(true)
    expect(isNavigationItemSitePageEnabled({ sitePageKey: 'contactPage' }, { contactPage: false })).toBe(false)
  })

  it('never hides items without a site page key', () => {
    expect(isNavigationItemSitePageEnabled({}, { contactPage: false })).toBe(true)
  })
})

describe('dsh navigation item', () => {
  it('exposes a public entry immediately after MCP', () => {
    const mcpIndex = NAV_ITEMS.findIndex((item) => item.to === '/mcp')
    const item = NAV_ITEMS[mcpIndex + 1]!
    expect(item.to).toBe('/dsh')
    expect(item.labelKey).toBe('navigation.dsh')
    expect(item.requiresAuth).toBeUndefined()
    expect(item.requiresAdmin).toBeUndefined()
    expect(item.featureKey).toBeUndefined()
    expect(item.sitePageKey).toBeUndefined()
    expect(isNavigationItemActive(item, '/dsh')).toBe(true)
    expect(isNavigationItemActive(item, '/mcp')).toBe(false)
    expect(isNavigationItemActive({ to: '/example', exact: true }, '/example')).toBe(true)
    expect(isNavigationItemActive({ to: '/example', exact: true }, '/example', { source: 'website' })).toBe(true)
  })
})

describe('website collection navigation item', () => {
  it('moves the personal website collection into the shared dock', () => {
    const item = NAV_ITEMS.find((entry) => entry.to === '/projects?source=website')
    expect(item).toBeDefined()
    expect(item?.labelKey).toBe('navigation.websiteCollection')
    expect(item?.exact).toBe(true)
    expect(item?.requiresAuth).toBeUndefined()
    expect(isNavigationItemActive(item!, '/projects', { source: 'website' })).toBe(true)
    expect(isNavigationItemActive(item!, '/projects', { source: 'favorites' })).toBe(false)
    expect(isNavigationItemActive(item!, '/projects', {})).toBe(false)
    expect(isNavigationItemActive(item!, '/websites')).toBe(true)
  })

  it('keeps the general projects item inactive for the website collection', () => {
    const item = NAV_ITEMS.find((entry) => entry.to === '/projects')!
    expect(isNavigationItemActive(item, '/projects', { source: 'website' })).toBe(false)
    expect(isNavigationItemActive(item, '/projects', { source: 'favorites' })).toBe(true)
    expect(isNavigationItemActive(item, '/projects', {})).toBe(true)
    expect(isNavigationItemActive(item, '/websites')).toBe(false)
  })
})

describe('subscriptions navigation item', () => {
  it('exposes tracking to guests while the route handles login', () => {
    const item = NAV_ITEMS.find((entry) => entry.to === '/subscriptions')!
    expect(item.labelKey).toBe('navigation.tracking')
    expect(item.requiresAuth).toBeUndefined()
    expect(item.requiresAdmin).toBeUndefined()
    expect(isNavigationItemActive(item, '/subscriptions')).toBe(true)
  })
})

describe('membership navigation item', () => {
  it('exposes an ungated membership entry right before the contact item', () => {
    const index = NAV_ITEMS.findIndex((item) => item.to === '/membership')
    expect(index).toBeGreaterThan(-1)
    const item = NAV_ITEMS[index]!
    expect(item.labelKey).toBe('navigation.membership')
    // 获客入口：匿名可见，不受特性开关 / 站点页面 / 登录 / 管理员门控
    expect(item.featureKey).toBeUndefined()
    expect(item.sitePageKey).toBeUndefined()
    expect(item.requiresAuth).toBeUndefined()
    expect(item.requiresAdmin).toBeUndefined()
    expect(NAV_ITEMS.findIndex((entry) => entry.to === '/contact')).toBe(index + 1)
  })
})
