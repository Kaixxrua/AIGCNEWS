import { describe, expect, it } from 'vitest'
import {
  duskAmount,
  FIELD_PALETTE,
  lerpHex,
  paletteColor,
  PaletteRegistry,
  type ColorTarget,
} from './palette'

const makeTarget = () => {
  const writes: string[] = []
  const target: ColorTarget = {
    set(color: string) {
      writes.push(color)
    },
  }
  return { target, writes }
}

describe('palette lerpHex', () => {
  it('端点精确命中手工 sRGB 色板（不漂色）', () => {
    expect(lerpHex('#101830', '#7ec8e3', 0)).toBe('#101830')
    expect(lerpHex('#101830', '#7ec8e3', 1)).toBe('#7ec8e3')
  })

  it('中点为逐通道插值', () => {
    expect(lerpHex('#000000', '#ffffff', 0.5)).toBe('#808080')
    expect(lerpHex('#101830', '#7ec8e3', 0.5)).toBe('#47708a')
  })

  it('越界参数钳制到端点', () => {
    expect(lerpHex('#101830', '#7ec8e3', -1)).toBe('#101830')
    expect(lerpHex('#101830', '#7ec8e3', 2)).toBe('#7ec8e3')
  })
})

describe('palette 查表与黄昏强度', () => {
  it('paletteColor 昼=日色 夜=夜色', () => {
    expect(paletteColor('skyTop', 1)).toBe(FIELD_PALETTE.skyTop.day)
    expect(paletteColor('skyTop', 0)).toBe(FIELD_PALETTE.skyTop.night)
  })

  it('夜版暗部偏蓝紫（色相偏移纪律，不做程序化压暗）', () => {
    // 夜色亮度显著低于日色，且蓝色通道不弱于红通道
    for (const key of ['farHill', 'groundNear', 'treeLeaf'] as const) {
      const night = FIELD_PALETTE[key].night
      const r = parseInt(night.slice(1, 3), 16)
      const b = parseInt(night.slice(5, 7), 16)
      expect(b).toBeGreaterThanOrEqual(r)
    }
  })

  it('duskAmount 中点为 1、两端为 0', () => {
    expect(duskAmount(0)).toBe(0)
    expect(duskAmount(0.5)).toBe(1)
    expect(duskAmount(1)).toBe(0)
  })
})

describe('PaletteRegistry apply-on-change', () => {
  it('day 未变化时不重写目标色', () => {
    const registry = new PaletteRegistry()
    const { target, writes } = makeTarget()
    registry.registerKey(target, 'skyTop')

    expect(registry.apply(1)).toBe(true)
    expect(writes).toEqual([FIELD_PALETTE.skyTop.day])
    expect(registry.apply(1)).toBe(false)
    expect(writes).toHaveLength(1)
    expect(registry.apply(0)).toBe(true)
    expect(writes).toEqual([FIELD_PALETTE.skyTop.day, FIELD_PALETTE.skyTop.night])
  })

  it('register 支持自定义昼夜色对；dispose 清空绑定', () => {
    const registry = new PaletteRegistry()
    const { target, writes } = makeTarget()
    registry.register(target, { day: '#ffffff', night: '#000000' })
    expect(registry.size).toBe(1)
    registry.apply(0)
    expect(writes).toEqual(['#000000'])
    registry.dispose()
    expect(registry.size).toBe(0)
  })
})
