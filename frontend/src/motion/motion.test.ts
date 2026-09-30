import { afterEach, describe, expect, it, vi } from 'vitest'
import { installFakeAnimations, stubReducedMotion } from './testing'

// 每次重新载入模块：linear() 支不支持在模块里只探测一次。
const load = async (supportsLinear: boolean | null) => {
  vi.unstubAllGlobals()
  vi.resetModules()
  if (supportsLinear !== null) vi.stubGlobal('CSS', { supports: (_property: string, value: string) => supportsLinear && value.startsWith('linear(') })
  return import('./motion')
}

/** linear() 各停靠点的 [输出, 位置%]。 */
const stops = (curve: string) => curve.slice('linear('.length, -1).split(', ').map((stop) => stop.split(' ').map((value) => parseFloat(value)))

describe('缓动', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('支持 linear() 时用弹簧曲线，不支持时退回贝塞尔', async () => {
    const legacy = await load(false)
    expect(legacy.spring()).toMatch(/^cubic-bezier\(/)
    expect(legacy.glideSpring()).toBe(legacy.EASE_OUT)
    expect(legacy.popSpring()).toMatch(/^cubic-bezier\(/)
    const noCss = await load(null)
    expect(noCss.spring()).toMatch(/^cubic-bezier\(/)
    const modern = await load(true)
    for (const curve of [modern.spring(), modern.glideSpring(), modern.popSpring()]) expect(curve).toMatch(/^linear\(0, /)
  })

  it('三条弹簧从 0 起、到 1 止，停靠点位置递增；回弹依次约 1%、6%、15%', async () => {
    const { spring, glideSpring, popSpring } = await load(true)
    const peak = (curve: string) => Math.max(...stops(curve).map(([value = 0]) => value))
    for (const curve of [spring(), glideSpring(), popSpring()]) {
      const points = stops(curve)
      expect(points[0]).toEqual([0])
      expect(points[points.length - 1]).toEqual([1])
      const positions = points.slice(1, -1).map(([, position = 0]) => position)
      expect(positions).toEqual([...positions].sort((a, b) => a - b))
    }
    // 推文墙跨列滑动用 glideSpring：几百像素的位移也只冲出不到 1%。
    expect(peak(glideSpring())).toBeLessThan(1.01)
    expect(peak(spring())).toBeCloseTo(1.062, 3)
    expect(peak(popSpring())).toBeCloseTo(1.152, 3)
  })
})

describe('canAnimate', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('有 Web Animations 且未偏好减少动态时才播', async () => {
    const { canAnimate } = await load(false)
    const el = document.createElement('div')
    expect(canAnimate(el)).toBe(false)
    const fakes = installFakeAnimations()
    try {
      expect(canAnimate(el)).toBe(true)
      stubReducedMotion()
      expect(canAnimate(el)).toBe(false)
    } finally {
      fakes.restore()
    }
  })
})
