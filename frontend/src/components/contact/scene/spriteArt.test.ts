import { describe, expect, it } from 'vitest'
import { validateFrame } from './sprites'
import {
  BIRD,
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
  ])('%s：idle×4 / walk×4 / react×2，统一 22×38', (_name, art) => {
    expect(art.idle).toHaveLength(4)
    expect(art.walk).toHaveLength(4)
    expect(art.react).toHaveLength(2)
    expectFrames([...art.idle, ...art.walk, ...art.react], 22, 38)
    expect(art.width).toBe(22)
    expect(art.height).toBe(38)
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

  it('剪影区分：帽/杖/围裙/草帽件各归其主', () => {
    // 小孩帽扣 'a' 在身体块；老人手杖 'c'；商人围裙 'a'；旅人包带 'a' + 帽带
    expect(KID.idle[0]!.rows.join('')).toContain('a')
    expect(ELDER.idle[0]!.rows.join('')).toContain('c')
    expect(MERCHANT.idle[0]!.rows.join('')).toContain('a')
    expect(TRAVELER.idle[0]!.rows.join('')).toContain('a')
  })
})

describe('spriteArt 动物与点缀', () => {
  it('猫：groom/walk/scurry ×2，16×12', () => {
    expectFrames([...CAT.groom, ...CAT.walk, ...CAT.scurry], 16, 12)
  })

  it('狗：walk×4 / sit×2，20×14', () => {
    expectFrames([...DOG.walk, ...DOG.sit], 20, 14)
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
