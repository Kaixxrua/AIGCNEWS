/**
 * 角色状态机（纯 TS，不引 three；mesh 绑定在编排器侧）。
 * IDLE（2–8s 种子随机）→ WALK（26 美术像素/秒，亚像素浮点累积、渲染取整）→ IDLE；
 * REACT 打断一切，结束后回到被打断前的意图；flee 供动物受惊逃窜（短时提速）。
 * 所有时间参数显式传入（now/dt 秒），控制器自身不读时钟 → 完全可测。
 */

export type ActorState = 'idle' | 'walk' | 'react'
export type Facing = 1 | -1
export type BubbleKind = 'exclaim' | 'dots' | 'note'

export interface ActorBounds {
  min: number
  max: number
}

export interface ActorSpec {
  idleFrameCount: number
  walkFrameCount: number
  reactFrameCount?: number
  /** 美术像素/秒，默认 26 */
  walkSpeed?: number
  /** 逃窜速度，默认 walkSpeed × 3 */
  fleeSpeed?: number
  idleFrameMs?: number
  walkFrameMs?: number
  reactFrameMs?: number
  /** react() 未显式给时长时的默认毫秒数 */
  defaultReactMs?: number
  /** 决定性随机源（mulberry32）；缺省为恒定 0.5（测试外不应缺省） */
  rng?: () => number
}

export interface ActorSnapshot {
  /** 渲染用整数美术像素坐标 */
  x: number
  facing: Facing
  state: ActorState
  frame: number
  bubble: BubbleKind | null
}

const DEFAULTS = {
  walkSpeed: 26,
  idleFrameMs: 240,
  walkFrameMs: 130,
  reactFrameMs: 350,
  reactFrameCount: 2,
  defaultReactMs: 700,
  fleeMs: 1200,
} as const

export class ActorController {
  private xFloat: number
  private facing: Facing = 1
  private current: ActorState = 'idle'
  private idleUntil: number
  private walkTarget: number | null = null
  private reactUntil = -1
  private fleeUntil = -1
  private frameClockMs = 0
  private bubbleKind: BubbleKind | null = null
  private bubbleUntil = -1
  private readonly rng: () => number
  private readonly spec: ActorSpec

  constructor(startX: number, spec: ActorSpec, now = 0) {
    this.spec = spec
    this.xFloat = startX
    this.rng = spec.rng ?? (() => 0.5)
    this.idleUntil = now + this.nextIdleSpan()
  }

  get state(): ActorState {
    return this.current
  }

  get renderX(): number {
    return Math.floor(this.xFloat)
  }

  get facingSign(): Facing {
    return this.facing
  }

  private nextIdleSpan(): number {
    return 2 + this.rng() * 6
  }

  /** 命令：走向目标 x（react 期间只记目标不打断演出） */
  walkTo(x: number): void {
    this.walkTarget = x
    if (this.current !== 'react') this.current = 'walk'
  }

  /** 命令：原地反应（hover 小跳/点击挥手），可带气泡 */
  react(now: number, durationMs?: number, bubble?: BubbleKind): void {
    this.current = 'react'
    const ms = durationMs ?? this.spec.defaultReactMs ?? DEFAULTS.defaultReactMs
    this.reactUntil = now + ms / 1000
    this.frameClockMs = 0
    if (bubble) this.showBubble(now, bubble, ms + 400)
  }

  /** 命令：朝向某个 x（hover 时先转身再小跳） */
  faceTowards(x: number): void {
    if (Math.abs(x - this.xFloat) < 0.5) return
    this.facing = x > this.xFloat ? 1 : -1
  }

  /** 命令：受惊逃窜——背向威胁短距提速跑 */
  fleeFrom(x: number, now: number, distance = 34): void {
    const dir: Facing = this.xFloat >= x ? 1 : -1
    this.facing = dir
    this.walkTarget = this.xFloat + dir * distance
    this.current = 'walk'
    this.fleeUntil = now + DEFAULTS.fleeMs / 1000
    this.frameClockMs = 0
  }

  showBubble(now: number, kind: BubbleKind, durationMs = 1400): void {
    this.bubbleKind = kind
    this.bubbleUntil = now + durationMs / 1000
  }

  teleport(x: number, now: number): void {
    this.xFloat = x
    this.walkTarget = null
    this.fleeUntil = -1
    if (this.current !== 'react') {
      this.current = 'idle'
      this.idleUntil = now + this.nextIdleSpan()
    }
  }

  update(now: number, dt: number, bounds: ActorBounds): ActorSnapshot {
    const spec = this.spec

    if (this.current === 'react' && now >= this.reactUntil) {
      this.current = this.walkTarget !== null ? 'walk' : 'idle'
      this.frameClockMs = 0
      if (this.current === 'idle') this.idleUntil = now + 1.5 + this.rng() * 4
    }

    if (this.current === 'walk' && this.walkTarget !== null) {
      const fleeing = now < this.fleeUntil
      const speed = fleeing
        ? (spec.fleeSpeed ?? (spec.walkSpeed ?? DEFAULTS.walkSpeed) * 3)
        : (spec.walkSpeed ?? DEFAULTS.walkSpeed)
      const delta = this.walkTarget - this.xFloat
      const dir: Facing = delta >= 0 ? 1 : -1
      this.facing = dir
      const step = speed * dt
      if (Math.abs(delta) <= step) {
        this.xFloat = this.walkTarget
        this.walkTarget = null
        this.fleeUntil = -1
        this.current = 'idle'
        this.idleUntil = now + this.nextIdleSpan()
      } else {
        this.xFloat += dir * step
      }
      if (this.xFloat <= bounds.min || this.xFloat >= bounds.max) {
        this.xFloat = Math.min(bounds.max, Math.max(bounds.min, this.xFloat))
        this.walkTarget = null
        this.fleeUntil = -1
        this.current = 'idle'
        this.idleUntil = now + this.nextIdleSpan()
      }
    }

    if (this.current === 'idle' && now >= this.idleUntil) {
      const span = bounds.max - bounds.min
      const target = bounds.min + this.rng() * span
      if (Math.abs(target - this.xFloat) > 4) {
        this.walkTarget = target
        this.current = 'walk'
      } else {
        this.idleUntil = now + this.nextIdleSpan()
      }
    }

    const frameCount =
      this.current === 'walk'
        ? spec.walkFrameCount
        : this.current === 'react'
          ? (spec.reactFrameCount ?? DEFAULTS.reactFrameCount)
          : spec.idleFrameCount
    const frameMs =
      this.current === 'walk'
        ? (spec.walkFrameMs ?? DEFAULTS.walkFrameMs)
        : this.current === 'react'
          ? (spec.reactFrameMs ?? DEFAULTS.reactFrameMs)
          : (spec.idleFrameMs ?? DEFAULTS.idleFrameMs)

    this.frameClockMs += dt * 1000
    const cycleMs = frameMs * frameCount
    if (this.frameClockMs >= cycleMs) this.frameClockMs %= cycleMs
    const frame = Math.floor(this.frameClockMs / frameMs) % frameCount

    return {
      x: Math.floor(this.xFloat),
      facing: this.facing,
      state: this.current,
      frame,
      bubble: now < this.bubbleUntil ? this.bubbleKind : null,
    }
  }
}
