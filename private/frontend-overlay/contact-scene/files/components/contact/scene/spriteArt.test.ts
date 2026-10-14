import { describe, expect, it } from 'vitest'
import { validateFrame } from './sprites'
import {
  CAST_ART,
  CAST_ATLAS_HEIGHT,
  CAST_ATLAS_WIDTH,
  CAST_FRAMES,
} from './castManifest'
import {
  BIRD,
  BUBBLES,
  BUTTERFLY,
  CastFrameSet,
  LAMP_POST,
  TREE_LEAF_A,
  TREE_LEAF_B,
  TREE_TRUNK,
} from './spriteArt'

const CAST_MEMBERS = [
  ['swordsman', CAST_ART.swordK, 'human'],
  ['scholarF', CAST_ART.scholarF, 'human'],
  ['scholarM', CAST_ART.scholarM, 'human'],
  ['knight', CAST_ART.knightR, 'human'],
  ['cloak', CAST_ART.cloakP, 'human'],
  ['cat', CAST_ART.petcat, 'pet'],
  ['dog', CAST_ART.petdog, 'pet'],
] as const

const allRects = Object.entries(CAST_FRAMES)

describe('castManifest 图集清单', () => {
  it.each(CAST_MEMBERS)('%s：idle/walk/react 齐备且全部在图集内', (_name, art) => {
    for (const tag of ['idle', 'walk', 'react'] as const) {
      expect(art[tag].length).toBeGreaterThanOrEqual(1)
      for (const key of art[tag]) expect(CAST_FRAMES[key], key).toBeDefined()
    }
  })

  it.each(CAST_MEMBERS)('%s：walk ≥5 帧（locomotion 循环）', (_name, art) => {
    expect(art.walk.length).toBeGreaterThanOrEqual(5)
  })

  it.each(CAST_MEMBERS)('%s：同动作 cell 等宽等高（归一化契约）', (_name, art) => {
    for (const tag of ['idle', 'walk', 'react'] as const) {
      const dims = new Set(art[tag].map((key) => `${CAST_FRAMES[key]!.w}x${CAST_FRAMES[key]!.h}`))
      expect(dims.size).toBe(1)
    }
  })

  it('人类 cell 高 36–52px、宠物 ≤32px（脚底锚点归一后的上屏比例）', () => {
    for (const [_name, art, kind] of CAST_MEMBERS) {
      const idle = CAST_FRAMES[art.idle[0]!]!
      if (kind === 'human') {
        expect(idle.h).toBeGreaterThanOrEqual(36)
        expect(idle.h).toBeLessThanOrEqual(52)
      } else {
        expect(idle.h).toBeLessThanOrEqual(32)
      }
    }
  })

  it('全部帧矩形落在图集边界内且两两不重叠', () => {
    expect(allRects.length).toBeGreaterThanOrEqual(104)
    for (const [key, r] of allRects) {
      expect(r.x, key).toBeGreaterThanOrEqual(0)
      expect(r.y, key).toBeGreaterThanOrEqual(0)
      expect(r.x + r.w, key).toBeLessThanOrEqual(CAST_ATLAS_WIDTH)
      expect(r.y + r.h, key).toBeLessThanOrEqual(CAST_ATLAS_HEIGHT)
    }
    for (let i = 0; i < allRects.length; i++) {
      const [ka, a] = allRects[i]!
      for (let j = i + 1; j < allRects.length; j++) {
        const [kb, b] = allRects[j]!
        const overlap =
          a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h
        expect(overlap, `${ka} ∩ ${kb}`).toBe(false)
      }
    }
  })

  it('CastFrameSet：缺帧即抛错、frameAt 环形取帧', () => {
    expect(() => new CastFrameSet(['swordK/idle-f99'])).toThrow()
    const set = new CastFrameSet(CAST_ART.swordK.walk)
    expect(set.frameCount).toBe(CAST_ART.swordK.walk.length)
    expect(set.frameAt(0)).toEqual(CAST_FRAMES[CAST_ART.swordK.walk[0]!])
    expect(set.frameAt(-1)).toEqual(set.frameAt(set.frameCount - 1))
    expect(set.frameAt(set.frameCount)).toEqual(set.frameAt(0))
  })
})

describe('spriteArt 点缀与道具（DSL 保留）', () => {
  it('鸟/蝶：fly×2', () => {
    for (const frame of BIRD.fly) expect(validateFrame(frame)).toEqual({ width: 12, height: 7 })
    for (const frame of BUTTERFLY.fly)
      expect(validateFrame(frame)).toEqual({ width: 6, height: 5 })
  })

  it('气泡三枚同尺寸 18×14', () => {
    for (const frame of [BUBBLES.exclaim, BUBBLES.dots, BUBBLES.note]) {
      expect(validateFrame(frame)).toEqual({ width: 18, height: 14 })
    }
  })

  it('道具：路灯 14×36、树干 12×30、树冠 46×56', () => {
    expect(validateFrame(LAMP_POST)).toEqual({ width: 14, height: 36 })
    expect(validateFrame(TREE_TRUNK)).toEqual({ width: 12, height: 30 })
    expect(validateFrame(TREE_LEAF_A)).toEqual({ width: 46, height: 56 })
    expect(validateFrame(TREE_LEAF_B)).toEqual({ width: 46, height: 56 })
  })

  it('两棵树的树冠数据不同（确定性种子生成）', () => {
    expect(TREE_LEAF_A.rows).not.toEqual(TREE_LEAF_B.rows)
  })
})
