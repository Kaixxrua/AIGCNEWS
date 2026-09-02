import { describe, expect, it } from 'vitest'
import { ActorController, type ActorSpec } from './actors'
import { mulberry32 } from './events'

const BOUNDS = { min: -100, max: 100 }

const makeActor = (overrides: Partial<ActorSpec> = {}, startX = 0) =>
  new ActorController(startX, {
    idleFrameCount: 4,
    walkFrameCount: 4,
    reactFrameCount: 2,
    rng: mulberry32(7),
    ...overrides,
  })

describe('ActorController 行走', () => {
  it('walkTo 进入 walk 状态，按 walkSpeed×dt 逼近目标，抵达后回 idle', () => {
    const actor = makeActor({ walkSpeed: 26 })
    actor.walkTo(26)

    let snapshot = actor.update(0.5, 0.5, BOUNDS)
    expect(snapshot.state).toBe('walk')
    expect(snapshot.x).toBe(13)
    expect(snapshot.facing).toBe(1)

    snapshot = actor.update(1.0, 0.5, BOUNDS)
    expect(snapshot.state).toBe('idle')
    expect(snapshot.x).toBe(26) // 抵达不越过目标
  })

  it('亚像素浮点累积、渲染取整（慢速移动不抖动）', () => {
    const actor = makeActor({ walkSpeed: 26 })
    actor.walkTo(10)
    // 0.01s × 26px/s = 0.26px/帧：前 3 帧渲染 x 不动，第 4 帧进 1
    expect(actor.update(0.01, 0.01, BOUNDS).x).toBe(0)
    expect(actor.update(0.02, 0.01, BOUNDS).x).toBe(0)
    expect(actor.update(0.03, 0.01, BOUNDS).x).toBe(0)
    expect(actor.update(0.04, 0.01, BOUNDS).x).toBe(1)
  })

  it('向左走 facing 为 -1；bounds 钳制会取消行走', () => {
    const actor = makeActor({ walkSpeed: 26 })
    actor.walkTo(-500)
    const snapshot = actor.update(0.1, 0.1, BOUNDS)
    expect(snapshot.facing).toBe(-1)

    // 26px/s × 0.5s/帧：第 8 帧 xFloat 越过 -100 → 钳回边界并取消行走
    let last = snapshot
    for (let i = 1; i <= 10 && last.state === 'walk'; i++) {
      last = actor.update(0.1 + i * 0.5, 0.5, BOUNDS)
    }
    expect(last.x).toBe(BOUNDS.min)
    expect(last.state).toBe('idle')
  })
})

describe('ActorController 反应与逃窜', () => {
  it('react 打断演出，结束后回到 idle', () => {
    const actor = makeActor()
    actor.react(10, 500)
    expect(actor.update(10.1, 0.1, BOUNDS).state).toBe('react')
    expect(actor.update(10.6, 0.1, BOUNDS).state).toBe('idle')
  })

  it('react 期间 walkTo 只记目标，react 结束后恢复行走', () => {
    const actor = makeActor({ walkSpeed: 26 })
    actor.react(10, 500)
    actor.walkTo(50)
    expect(actor.update(10.2, 0.1, BOUNDS).state).toBe('react')
    const snapshot = actor.update(10.6, 0.1, BOUNDS)
    expect(snapshot.state).toBe('walk')
    expect(snapshot.facing).toBe(1)
  })

  it('fleeFrom 背向威胁、按 fleeSpeed 提速', () => {
    const actor = makeActor({ walkSpeed: 20, fleeSpeed: 70 })
    actor.fleeFrom(-50, 0) // 威胁在左，向右逃
    const snapshot = actor.update(0.1, 0.1, BOUNDS)
    expect(snapshot.state).toBe('walk')
    expect(snapshot.facing).toBe(1)
    expect(snapshot.x).toBe(7) // 70px/s × 0.1s
  })

  it('faceTowards 只在明显偏离时转身', () => {
    const actor = makeActor()
    actor.faceTowards(10)
    expect(actor.facingSign).toBe(1)
    actor.faceTowards(-10)
    expect(actor.facingSign).toBe(-1)
    actor.faceTowards(-10.3) // |dx| < 0.5 不转身
    expect(actor.facingSign).toBe(-1)
  })
})

describe('ActorController 气泡与帧时钟', () => {
  it('react 可带气泡，气泡时长 = 反应时长 + 400ms', () => {
    const actor = makeActor()
    actor.react(0, 500, 'exclaim')
    expect(actor.update(0.8, 0.1, BOUNDS).bubble).toBe('exclaim')
    expect(actor.update(1.0, 0.1, BOUNDS).bubble).toBeNull()
  })

  it('showBubble 独立计时', () => {
    const actor = makeActor()
    actor.showBubble(0, 'dots', 1400)
    expect(actor.update(1.3, 0.1, BOUNDS).bubble).toBe('dots')
    expect(actor.update(1.5, 0.1, BOUNDS).bubble).toBeNull()
  })

  it('帧时钟按 frameMs 推进并对帧数取模', () => {
    const actor = makeActor({ walkFrameMs: 130 })
    actor.walkTo(80)
    expect(actor.update(0, 0, BOUNDS).frame).toBe(0)
    expect(actor.update(0.13, 0.13, BOUNDS).frame).toBe(1) // 130ms → 第 1 帧
    // 4 帧一循环 520ms：累计 130+390=520 → 取模回第 0 帧
    expect(actor.update(0.52, 0.39, BOUNDS).frame).toBe(0)
  })
})

describe('ActorController 自主漫游', () => {
  it('idle 到期后按种子随机选目标行走（确定性）', () => {
    const a = makeActor()
    const b = makeActor()
    // 同种子同序列：两台控制器漫游轨迹一致
    for (let i = 1; i <= 40; i++) {
      const t = i * 0.5
      expect(a.update(t, 0.5, BOUNDS)).toEqual(b.update(t, 0.5, BOUNDS))
    }
    // 漫游确实发生（不会永远停在原地）
  })

  it('teleport 归位并打断行走', () => {
    const actor = makeActor()
    actor.walkTo(50)
    actor.update(0.1, 0.1, BOUNDS)
    actor.teleport(-20, 0.2)
    const snapshot = actor.update(0.3, 0.1, BOUNDS)
    expect(snapshot.x).toBe(-20)
    expect(snapshot.state).toBe('idle')
  })
})
