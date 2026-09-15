import { describe, expect, it } from 'vitest'
import {
  computePixelScale,
  EDGE_BLEND_RATIO,
  PIXEL_SCALE_MAX,
  PIXEL_SCALE_MIN,
  PIXEL_TARGET_HEIGHT,
} from './pixelPipeline'

describe('computePixelScale 整数倍率锁定', () => {
  it('按目标低分高取整并钳制到 [2, 6]', () => {
    expect(computePixelScale(PIXEL_TARGET_HEIGHT)).toBe(2) // 230 → round(1) → 下限 2
    expect(computePixelScale(460)).toBe(2)
    expect(computePixelScale(690)).toBe(3)
    expect(computePixelScale(920)).toBe(4)
    expect(computePixelScale(1440)).toBe(6)
  })

  it('小容器与非法输入回退下限 2', () => {
    expect(computePixelScale(320)).toBe(2)
    expect(computePixelScale(375)).toBe(2)
    expect(computePixelScale(0)).toBe(PIXEL_SCALE_MIN)
    expect(computePixelScale(-5)).toBe(PIXEL_SCALE_MIN)
    expect(computePixelScale(Number.NaN)).toBe(PIXEL_SCALE_MIN)
    expect(computePixelScale(Number.POSITIVE_INFINITY)).toBe(PIXEL_SCALE_MIN)
  })

  it('超高容器封顶 6（DPR 上限保护）', () => {
    expect(computePixelScale(3000)).toBe(PIXEL_SCALE_MAX)
  })

  it('产出恒为整数（像素画红线：小数倍率会打出脏像素）', () => {
    for (const h of [414, 768, 834, 1080, 1152]) {
      expect(Number.isInteger(computePixelScale(h))).toBe(true)
    }
  })
})

describe('pixelPipeline 常量契约', () => {
  it('边缘融合宽度在合理区间（不至于吃掉画面主体）', () => {
    expect(EDGE_BLEND_RATIO).toBeGreaterThan(0)
    expect(EDGE_BLEND_RATIO).toBeLessThanOrEqual(0.2)
  })
})
