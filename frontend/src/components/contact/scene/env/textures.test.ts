/**
 * 纹理数据生成器单测：纯数据层在 jsdom 可测。
 * 红线：同种子逐字节确定性、请求尺寸精确、alpha 通道确实出现（剪影类不是全不透明）。
 */
import { describe, expect, it } from 'vitest'
import {
  bushBlob,
  dirtPath,
  farHills,
  foregroundGrass,
  grassField,
  makeImage,
  radialGlow,
  rockChunk,
  treeLineStrip,
  villageSkyline,
} from './textures'
import type { RgbaImage } from './textures'

const alphaValues = (img: RgbaImage): Set<number> => {
  const set = new Set<number>()
  for (let i = 3; i < img.data.length; i += 4) set.add(img.data[i]!)
  return set
}

const hasVisiblePixel = (img: RgbaImage): boolean => {
  for (let i = 3; i < img.data.length; i += 4) {
    if (img.data[i]! > 0) return true
  }
  return false
}

describe('makeImage', () => {
  it('按请求尺寸分配零值 RGBA 缓冲', () => {
    const img = makeImage(7, 5)
    expect(img.width).toBe(7)
    expect(img.height).toBe(5)
    expect(img.data.length).toBe(7 * 5 * 4)
    expect(img.data.every((v) => v === 0)).toBe(true)
  })
})

describe('环境纹理生成器', () => {
  const generators: Array<[string, (seed: number) => RgbaImage]> = [
    ['grassField', (seed) => grassField(seed, 128, 64)],
    ['dirtPath', (seed) => dirtPath(seed, 128, 24)],
    ['farHills', (seed) => farHills(seed, 128, 40)],
    ['treeLineStrip', (seed) => treeLineStrip(seed, 128, 32)],
    ['bushBlob', (seed) => bushBlob(seed, 24, 16)],
    ['rockChunk', (seed) => rockChunk(seed, 20, 14)],
    ['foregroundGrass', (seed) => foregroundGrass(seed, 128, 48)],
    ['radialGlow', () => radialGlow(32)],
  ]

  it.each(generators)('%s：同种子逐字节确定', (_name, make) => {
    const a = make(42)
    const b = make(42)
    expect(Array.from(a.data)).toEqual(Array.from(b.data))
  })

  it.each(generators)('%s：尺寸精确且含可见像素', (_name, make) => {
    const img = make(7)
    expect(img.data.length).toBe(img.width * img.height * 4)
    expect(hasVisiblePixel(img)).toBe(true)
  })

  it.each([
    ['grassField', (seed: number) => grassField(seed, 96, 48)],
    ['farHills', (seed: number) => farHills(seed, 96, 32)],
    ['treeLineStrip', (seed: number) => treeLineStrip(seed, 96, 28)],
    ['village', (seed: number) => villageSkyline(seed, 96, 40).silhouette],
  ] as Array<[string, (seed: number) => RgbaImage]>)('%s：不同种子产出不同纹理', (_name, make) => {
    const a = make(1)
    const b = make(2)
    expect(Array.from(a.data)).not.toEqual(Array.from(b.data))
  })

  it('径向光斑：中心不透明、四角全透明（halo 底图契约）', () => {
    const img = radialGlow(32)
    const cx = 16
    const cy = 16
    expect(img.data[(cy * 32 + cx) * 4 + 3]).toBeGreaterThan(200)
    expect(img.data[3]).toBe(0)
    expect(img.data[(31 * 32 + 31) * 4 + 3]).toBe(0)
  })
})

describe('剪影类纹理的 alpha 边缘', () => {
  it('远山/树线/村庄存在软边或镂空（非全不透明）', () => {
    for (const img of [
      farHills(5, 128, 40),
      treeLineStrip(5, 128, 32),
      villageSkyline(5, 128, 40).silhouette,
      foregroundGrass(5, 128, 48),
      bushBlob(5, 24, 16),
    ]) {
      const alphas = alphaValues(img)
      expect(alphas.has(0)).toBe(true)
    }
  })

  it('村庄窗洞层独立于剪影且为暖色', () => {
    const { silhouette, windows } = villageSkyline(11, 128, 40)
    expect(hasVisiblePixel(windows)).toBe(true)
    expect(silhouette.width).toBe(windows.width)
    // 找到第一个可见窗像素，确认偏暖（R > B）
    for (let i = 3; i < windows.data.length; i += 4) {
      if (windows.data[i]! > 0) {
        expect(windows.data[i - 3]!).toBeGreaterThan(windows.data[i - 1]!)
        return
      }
    }
  })
})
