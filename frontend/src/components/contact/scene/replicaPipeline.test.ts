/**
 * replicaPipeline 纯函数测试：自适应降级判定（管线本体依赖 WebGL2，jsdom 不测）。
 */
import { describe, expect, it } from 'vitest'
import { shouldDegrade } from './replicaPipeline'

describe('shouldDegrade 自适应降级判定', () => {
  it('预热期内（<60 帧）无论多慢都不降档', () => {
    expect(shouldDegrade(120, 0)).toBe(false)
    expect(shouldDegrade(120, 59)).toBe(false)
  })

  it('预热后只在 45 帧节奏点评估', () => {
    expect(shouldDegrade(120, 60)).toBe(false) // 60 % 45 ≠ 0
    expect(shouldDegrade(120, 90)).toBe(true)
    expect(shouldDegrade(120, 135)).toBe(true)
    expect(shouldDegrade(120, 136)).toBe(false)
  })

  it('节奏点上 EMA 帧耗 >40ms 才降档（边界 40 含）', () => {
    expect(shouldDegrade(41, 90)).toBe(true)
    expect(shouldDegrade(40, 90)).toBe(false)
    expect(shouldDegrade(16.7, 990)).toBe(false)
  })
})
