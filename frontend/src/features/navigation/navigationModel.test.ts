import { describe, expect, it } from 'vitest'
import { NAV_ITEMS, isNavigationItemFeatureEnabled } from './navigationModel'

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
