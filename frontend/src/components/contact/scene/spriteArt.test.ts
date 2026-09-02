import { describe, expect, it } from 'vitest'
import { validateFrame } from './sprites'
import {
  BIRD,
  BLOB_SHADOW,
  BUBBLES,
  BUTTERFLY,
  CAT,
  DOG,
  ELDER,
  KID,
  LAMP_POST,
  MERCHANT,
  TRAVELER,
  TREE_LEAF_A,
  TREE_LEAF_B,
  TREE_TRUNK,
  grassStrip,
  groundStrip,
  ridgeStrip,
} from './spriteArt'

/** 所有帧通过 DSL 校验且尺寸一致，返回帧尺寸 */
const expectFrames = (frames: { rows: string[]; palette: Record<string, string> }[], width: number, height: number) => {
  for (const frame of frames) {
    expect(validateFrame(frame)).toEqual({ width, height })
  }
}

describe('spriteArt NPC 帧集', () => {
  it.each([
    ['kid', KID],
    ['elder', ELDER],
    ['merchant', MERCHANT],
    ['traveler', TRAVELER],
  ])('%s：idle×4 / walk×4 / react×2，统一 16×24', (_name, art) => {
    expect(art.idle).toHaveLength(4)
    expect(art.walk).toHaveLength(4)
    expect(art.react).toHaveLength(2)
    expectFrames([...art.idle, ...art.walk, ...art.react], 16, 24)
  })

  it('待机第 3 帧为眨眼帧（无眼睛像素）', () => {
    for (const art of [KID, ELDER, MERCHANT, TRAVELER]) {
      expect(art.idle[2]!.rows.join('')).not.toContain('e')
      expect(art.idle[0]!.rows.join('')).toContain('e')
    }
  })

  it('待机 bob 帧与基础帧同宽且内容上移', () => {
    for (const art of [KID, ELDER, MERCHANT, TRAVELER]) {
      expect(art.idle[1]!.rows[0]!.length).toBe(art.idle[0]!.rows[0]!.length)
      expect(art.idle[1]!.rows).not.toEqual(art.idle[0]!.rows)
    }
  })
})

describe('spriteArt 动物与点缀', () => {
  it('猫：groom/walk/scurry ×2，14×10', () => {
    expectFrames([...CAT.groom, ...CAT.walk, ...CAT.scurry], 14, 10)
  })

  it('狗：walk×4 / sit×2', () => {
    expectFrames(DOG.walk, 16, 12)
    const sitSizes = DOG.sit.map((frame) => validateFrame(frame))
    expect(new Set(sitSizes.map((size) => `${size.width}x${size.height}`)).size).toBe(1)
    expect(sitSizes[0]!.height).toBe(12)
  })

  it('鸟/蝶：fly×2', () => {
    expectFrames(BIRD.fly, 10, 6)
    expectFrames(BUTTERFLY.fly, 5, 4)
  })

  it('气泡三枚同尺寸 14×12', () => {
    expectFrames([BUBBLES.exclaim, BUBBLES.dots, BUBBLES.note], 14, 12)
  })

  it('道具：路灯 12×30、树干 8×18、树冠 28×32、阴影 8×3', () => {
    expect(validateFrame(LAMP_POST)).toEqual({ width: 12, height: 30 })
    expect(validateFrame(TREE_TRUNK)).toEqual({ width: 8, height: 18 })
    expect(validateFrame(TREE_LEAF_A)).toEqual({ width: 28, height: 32 })
    expect(validateFrame(TREE_LEAF_B)).toEqual({ width: 28, height: 32 })
    expect(validateFrame(BLOB_SHADOW)).toEqual({ width: 8, height: 3 })
  })

  it('两棵树的树冠数据不同（确定性种子生成）', () => {
    expect(TREE_LEAF_A.rows).not.toEqual(TREE_LEAF_B.rows)
  })
})

describe('spriteArt 程序化剪影带', () => {
  it('按请求尺寸生成且同种子确定性一致', () => {
    const a = ridgeStrip(120, 24, 7, 0.4, 0.25, 3)
    const b = ridgeStrip(120, 24, 7, 0.4, 0.25, 3)
    expect(validateFrame(a)).toEqual({ width: 120, height: 24 })
    expect(a.rows).toEqual(b.rows)

    const g1 = groundStrip(64, 10, 11, 0.08)
    const g2 = groundStrip(64, 10, 11, 0.08)
    expect(validateFrame(g1)).toEqual({ width: 64, height: 10 })
    expect(g1.rows).toEqual(g2.rows)

    const s1 = grassStrip(64, 8, 13)
    const s2 = grassStrip(64, 8, 13)
    expect(validateFrame(s1)).toEqual({ width: 64, height: 8 })
    expect(s1.rows).toEqual(s2.rows)
  })

  it('不同种子产出不同条带', () => {
    expect(ridgeStrip(120, 24, 7, 0.4, 0.25, 3).rows).not.toEqual(
      ridgeStrip(120, 24, 8, 0.4, 0.25, 3).rows,
    )
  })

  it('山脊带确实包含实心像素（非全空）', () => {
    const strip = ridgeStrip(120, 24, 7, 0.4, 0.25, 3)
    expect(strip.rows.join('')).toContain('x')
  })
})
