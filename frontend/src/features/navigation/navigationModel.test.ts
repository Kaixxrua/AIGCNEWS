import { describe, expect, it } from 'vitest'
import { NAV_ITEMS, isNavigationItemFeatureEnabled, isNavigationItemSitePageEnabled } from './navigationModel'

describe('navigation feature gating', () => {
  it('marks the X board item with its feature key', () => {
    expect(NAV_ITEMS.find((item) => item.to === '/x')?.featureKey).toBe('xSource')
  })

  it('hides feature-gated items only when explicitly disabled', () => {
    expect(
      isNavigationItemFeatureEnabled({ featureKey: 'xSource' }, { xSource: false, wechatSource: true }),
    ).toBe(false)
    expect(
      isNavigationItemFeatureEnabled({ featureKey: 'xSource' }, { xSource: true, wechatSource: false }),
    ).toBe(true)
  })

  it('never hides items without a feature key', () => {
    expect(isNavigationItemFeatureEnabled({}, { xSource: false, wechatSource: false })).toBe(true)
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
