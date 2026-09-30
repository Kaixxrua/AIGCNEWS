import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { burstPolygon, revealTheme } from './themeReveal'
import { installFakeAnimations, stubReducedMotion, type FakeAnimations } from './testing'

type Update = () => Promise<void> | void

const fakeTransition = () => vi.fn((update: Update) => {
  void update()
  return { ready: Promise.resolve(), finished: Promise.resolve() }
})

const points = (polygon: string) => polygon.slice('polygon('.length, -1).split(', ').map((point) => point.split(' ').map((value) => parseFloat(value)))

describe('burstPolygon', () => {
  it('内外半径交替的 16 角爆炸框', () => {
    const corners = points(burstPolygon(10, 20, 100))
    expect(corners).toHaveLength(32)
    corners.forEach(([x = 0, y = 0], index) => {
      expect(Math.hypot(x - 10, y - 20)).toBeCloseTo(index % 2 ? 78 : 100, 0)
    })
    expect(corners[0]).toEqual([110, 20])
  })
})

describe('revealTheme', () => {
  let fakes: FakeAnimations
  let startViewTransition: ReturnType<typeof fakeTransition>

  beforeEach(() => {
    fakes = installFakeAnimations()
    startViewTransition = fakeTransition()
    Object.assign(document, { startViewTransition })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    fakes.restore()
    delete (document as { startViewTransition?: unknown }).startViewTransition
    document.documentElement.classList.remove('theme-transitioning')
  })

  it('新主题的快照以按钮为中心炸开，炸完撤掉过渡标记', async () => {
    const apply = vi.fn()
    revealTheme({ x: 100, y: 50 }, apply)
    expect(apply).toHaveBeenCalledOnce()
    expect(document.documentElement.classList.contains('theme-transitioning')).toBe(true)
    await flushPromises()
    const [reveal] = fakes.on(document.documentElement)
    const frames = (reveal?.keyframes as PropertyIndexedKeyframes).clipPath as string[]
    expect(frames).toHaveLength(3)
    expect(frames[0]).toBe(burstPolygon(100, 50, 18))
    expect(reveal?.options).toMatchObject({ duration: 580, pseudoElement: '::view-transition-new(root)' })
    // 内圈也要盖住离按钮最远的视口角（jsdom 视口 1024×768）。
    const [x = 0, y = 0] = points(frames[2]!)[1]!
    expect(Math.hypot(x - 100, y - 50)).toBeGreaterThan(Math.hypot(1024 - 100, 768 - 50))
    expect(document.documentElement.classList.contains('theme-transitioning')).toBe(false)
  })

  it('拿不到按钮位置、浏览器不支持或偏好减少动态时直接切换', () => {
    const apply = vi.fn()
    revealTheme(null, apply)
    stubReducedMotion()
    revealTheme({ x: 0, y: 0 }, apply)
    delete (document as { startViewTransition?: unknown }).startViewTransition
    vi.unstubAllGlobals()
    revealTheme({ x: 0, y: 0 }, apply)
    expect(apply).toHaveBeenCalledTimes(3)
    expect(startViewTransition).not.toHaveBeenCalled()
    expect(document.documentElement.classList.contains('theme-transitioning')).toBe(false)
  })
})
