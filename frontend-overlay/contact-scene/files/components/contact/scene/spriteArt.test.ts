import { describe, expect, it } from 'vitest'
import { validateFrame } from './sprites'
import {
  BIRD,
  BUBBLES,
  BUTTERFLY,
  CAT,
  CLOAK,
  DOG,
  KNIGHT,
  LAMP_POST,
  SCHOLAR_F,
  SCHOLAR_M,
  SWORDSMAN,
  TREE_LEAF_A,
  TREE_LEAF_B,
  TREE_TRUNK,
} from './spriteArt'

/** 所有帧通过 DSL 校验且尺寸一致，返回帧尺寸 */
const expectFrames = (frames: { rows: string[]; palette: Record<string, string> }[], width: number, height: number) => {
  for (const frame of frames) {
    expect(validateFrame(frame)).toEqual({ width, height })
  }
}

const CHARACTERS = [
  ['swordsman', SWORDSMAN],
  ['scholarF', SCHOLAR_F],
  ['scholarM', SCHOLAR_M],
  ['knight', KNIGHT],
  ['cloak', CLOAK],
] as const

describe('spriteArt NPC 帧集', () => {
  it.each(CHARACTERS)('%s：idle×2 / walk×4 / react×2，统一 24×41', (_name, art) => {
    expect(art.idle).toHaveLength(2)
    expect(art.walk).toHaveLength(4)
    expect(art.react).toHaveLength(2)
    expectFrames([...art.idle, ...art.walk, ...art.react], 24, 41)
    expect(art.width).toBe(24)
    expect(art.height).toBe(41)
  })

  it('待机 bob 帧与基础帧同宽且内容上移（首行留空，shiftUp 不裁头顶）', () => {
    for (const art of [SWORDSMAN, SCHOLAR_F, SCHOLAR_M, KNIGHT, CLOAK, CAT, DOG]) {
      expect(art.idle[0]!.rows[0]).toBe('.'.repeat(art.width))
      expect(art.idle[1]!.rows[0]!.length).toBe(art.idle[0]!.rows[0]!.length)
      expect(art.idle[1]!.rows).not.toEqual(art.idle[0]!.rows)
    }
  })

  it('五名角色剪影互不相同（清洗管线未把底稿串味）', () => {
    const signatures = [SWORDSMAN, SCHOLAR_F, SCHOLAR_M, KNIGHT, CLOAK].map((art) => art.idle[0]!.rows.join('\n'))
    expect(new Set(signatures).size).toBe(5)
  })
})

describe('spriteArt 动物与点缀', () => {
  it('猫：idle×2 / walk×4 / react×1，18×15', () => {
    expect(CAT.idle).toHaveLength(2)
    expect(CAT.walk).toHaveLength(4)
    expect(CAT.react).toHaveLength(1)
    expectFrames([...CAT.idle, ...CAT.walk, ...CAT.react], 18, 15)
    expect(CAT.width).toBe(18)
    expect(CAT.height).toBe(15)
  })

  it('狗：idle×2 / walk×4 / react×1，22×15', () => {
    expect(DOG.idle).toHaveLength(2)
    expect(DOG.walk).toHaveLength(4)
    expect(DOG.react).toHaveLength(1)
    expectFrames([...DOG.idle, ...DOG.walk, ...DOG.react], 22, 15)
    expect(DOG.width).toBe(22)
    expect(DOG.height).toBe(15)
  })

  it('鸟/蝶：fly×2', () => {
    expectFrames(BIRD.fly, 12, 7)
    expectFrames(BUTTERFLY.fly, 6, 5)
  })

  it('气泡三枚同尺寸 18×14', () => {
    expectFrames([BUBBLES.exclaim, BUBBLES.dots, BUBBLES.note], 18, 14)
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
