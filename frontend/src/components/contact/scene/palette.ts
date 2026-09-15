/**
 * 像素原野昼夜调色板（纯 TS，不引 three，jsdom 可测）。
 * 全部色值为手工编写的原创 sRGB 色板；夜版遵循 pixel-art 色相偏移纪律
 * （暗部偏蓝紫、亮部保暖），昼夜色对显式成对给出，不做程序化压暗。
 * 消费方式：PaletteRegistry 登记 { target: 带 set(hex) 的颜色对象（THREE.Color 兼容）、
 * day/night 色 }，仅在 uDay 变化时重算并写入（一次主题切换 ~25 次颜色写）。
 */

/** 昼=1 夜=0 的插值参数取值域 */
export const DAY_MIN = 0
export const DAY_MAX = 1

export interface DayNightColor {
  day: string
  night: string
}

/**
 * 场景环境色板（25 色 ≤ 32 上限）。
 * 天空/天体/剪影层/道具各配昼夜双色；气泡为「被照亮的 UI」，两主题恒定。
 */
export const FIELD_PALETTE = {
  skyTop: { day: '#7ec8e3', night: '#101830' },
  skyHorizon: { day: '#d9eec9', night: '#2b3a55' },
  duskBand: { day: '#f0a35e', night: '#f0a35e' },
  sunCore: { day: '#fff3b0', night: '#fff3b0' },
  sunGlow: { day: '#ffe9a3', night: '#ffe9a3' },
  moonCore: { day: '#e8f0ff', night: '#e8f0ff' },
  moonGlow: { day: '#b8c8e8', night: '#b8c8e8' },
  star: { day: '#f5f7ff', night: '#f5f7ff' },
  cloud: { day: '#ffffff', night: '#232c44' },
  farHill: { day: '#a8c8a0', night: '#1c2a48' },
  treeLine: { day: '#7aa878', night: '#16223a' },
  groundFar: { day: '#b8d498', night: '#22304c' },
  path: { day: '#d9c9a8', night: '#3a3f58' },
  groundNear: { day: '#98c078', night: '#18243c' },
  grass: { day: '#7db35e', night: '#14203a' },
  grassFg: { day: '#5a9448', night: '#0f1830' },
  treeTrunk: { day: '#8a6844', night: '#1e2030' },
  treeLeaf: { day: '#5f9e4f', night: '#142640' },
  lampPost: { day: '#3a3630', night: '#0e1220' },
  lampCore: { day: '#ffca7a', night: '#ffca7a' },
  lampPool: { day: '#ffca7a', night: '#ffca7a' },
  shadowBlob: { day: '#2c4a28', night: '#060a16' },
  /** 罩在角色/动物/道具整体材质上的乘法色：昼纯白不动，夜罩蓝影 */
  actorNightTint: { day: '#ffffff', night: '#aab8d6' },
  bubbleFill: { day: '#fffdf6', night: '#fffdf6' },
  bubbleInk: { day: '#23211d', night: '#23211d' },
} as const satisfies Record<string, DayNightColor>

export type PaletteKey = keyof typeof FIELD_PALETTE

/** 黄昏强度：昼夜中点为 1，两端为 0 */
export const duskAmount = (day: number): number => 1 - Math.abs(day * 2 - 1)

/** sRGB 分量直接插值（色板为手工 sRGB，不在线性空间混色以保持两端精确） */
export const lerpHex = (from: string, to: string, t: number): string => {
  const clampT = Math.min(DAY_MAX, Math.max(DAY_MIN, t))
  const a = parseInt(from.slice(1), 16)
  const b = parseInt(to.slice(1), 16)
  const ar = (a >> 16) & 0xff
  const ag = (a >> 8) & 0xff
  const ab = a & 0xff
  const br = (b >> 16) & 0xff
  const bg = (b >> 8) & 0xff
  const bb = b & 0xff
  const r = Math.round(ar + (br - ar) * clampT)
  const g = Math.round(ag + (bg - ag) * clampT)
  const bl = Math.round(ab + (bb - ab) * clampT)
  return `#${((r << 16) | (g << 8) | bl).toString(16).padStart(6, '0')}`
}

/** 解析某个色板键在指定昼夜参数下的颜色 */
export const paletteColor = (key: PaletteKey, day: number): string =>
  lerpHex(FIELD_PALETTE[key].night, FIELD_PALETTE[key].day, day)

/** 带 set(hex) 方法的颜色目标（THREE.Color 结构兼容，本模块不引 three） */
export interface ColorTarget {
  set(color: string): ColorTarget | void
}

interface PaletteBinding {
  target: ColorTarget
  day: string
  night: string
}

/**
 * 调色注册表：编排器把天空 uniform、剪影层 material.color、角色罩色等
 * 全部登记进来；apply(day) 只在 day 变化时重算（apply-on-change）。
 */
export class PaletteRegistry {
  private bindings: PaletteBinding[] = []
  private lastDay = Number.NaN

  register(target: ColorTarget, colors: DayNightColor): void {
    this.bindings.push({ target, day: colors.day, night: colors.night })
  }

  registerKey(target: ColorTarget, key: PaletteKey): void {
    this.register(target, FIELD_PALETTE[key])
  }

  get size(): number {
    return this.bindings.length
  }

  /** day 与上次相同则跳过；返回是否发生了写入 */
  apply(day: number): boolean {
    if (day === this.lastDay) return false
    this.lastDay = day
    for (const binding of this.bindings) {
      binding.target.set(lerpHex(binding.night, binding.day, day))
    }
    return true
  }

  dispose(): void {
    this.bindings.length = 0
    this.lastDay = Number.NaN
  }
}
