/**
 * project.ts 单测：three 数学类在 jsdom 可实例化（无渲染），用真 PerspectiveCamera
 * 验证投影几何——焦点中心落格、取整为整数、近大远小排序键、可视宽随距离线性。
 */
import { describe, expect, it } from 'vitest'
import * as THREE from 'three'
import {
  artRectToCss,
  makeArtGrid,
  painterOrder,
  visibleHalfWidthAt,
  worldToArt,
} from './project'

const makeCamera = (aspect = 16 / 9): THREE.PerspectiveCamera => {
  const camera = new THREE.PerspectiveCamera(30, aspect, 0.5, 80)
  camera.position.set(0, 10.5, 15.5)
  camera.lookAt(0, 1.2, 0)
  camera.updateMatrixWorld()
  camera.updateProjectionMatrix()
  return camera
}

describe('makeArtGrid', () => {
  it('低分尺寸取整、居中余量非负且恒小于倍率', () => {
    const grid = makeArtGrid(1398, 735, 3)
    expect(grid.lowW).toBe(466)
    expect(grid.lowH).toBe(245)
    expect(grid.offsetX).toBe(0) // 1398 = 466*3 整除
    expect(grid.offsetY).toBe(0)
    const odd = makeArtGrid(1001, 701, 4)
    expect(odd.lowW * odd.scale + odd.offsetX * 2).toBeLessThanOrEqual(1001)
    expect(odd.offsetX).toBeGreaterThanOrEqual(0)
    expect(odd.offsetX).toBeLessThan(odd.scale)
  })

  it('非法倍率回退 1', () => {
    const grid = makeArtGrid(320, 240, 0)
    expect(grid.scale).toBe(1)
    expect(grid.lowW).toBe(320)
  })
})

describe('worldToArt', () => {
  it('相机注视点投影到画面中心格（±1 取整误差）', () => {
    const grid = makeArtGrid(1398, 735, 3)
    const point = worldToArt(makeCamera(), grid, new THREE.Vector3(0, 1.2, 0))
    expect(point.x).toBeGreaterThanOrEqual(Math.floor(grid.lowW / 2) - 1)
    expect(point.x).toBeLessThanOrEqual(Math.ceil(grid.lowW / 2) + 1)
    expect(point.y).toBeGreaterThanOrEqual(Math.floor(grid.lowH / 2) - 1)
    expect(point.y).toBeLessThanOrEqual(Math.ceil(grid.lowH / 2) + 1)
    expect(point.inside).toBe(true)
  })

  it('产出恒为整数（像素对齐红线）', () => {
    const camera = makeCamera()
    const grid = makeArtGrid(1366, 768, 3)
    for (const [x, z] of [[-5, -1], [3.7, 0.4], [0, 2], [-11, -6]] as const) {
      const point = worldToArt(camera, grid, new THREE.Vector3(x, 0, z))
      expect(Number.isInteger(point.x)).toBe(true)
      expect(Number.isInteger(point.y)).toBe(true)
    }
  })

  it('远处（小 z）投影更高：artY 随深度增大', () => {
    const camera = makeCamera()
    const grid = makeArtGrid(1398, 735, 3)
    const near = worldToArt(camera, grid, new THREE.Vector3(0, 0, 2))
    const far = worldToArt(camera, grid, new THREE.Vector3(0, 0, -8))
    expect(far.y).toBeGreaterThan(near.y)
  })
})

describe('artRectToCss', () => {
  it('美术矩形换算到 CSS 像素（左上是屏幕原点）', () => {
    const grid = makeArtGrid(1000, 700, 2) // lowW=500 lowH=350
    const rect = artRectToCss(grid, 10, 20, 22, 38)
    expect(rect).toEqual({ left: 20, top: 700 - 58 * 2, width: 44, height: 76 })
  })
})

describe('visibleHalfWidthAt', () => {
  it('随距离线性放大、随宽高比放大', () => {
    const wide = makeCamera(16 / 9)
    const narrow = makeCamera(0.5)
    const nearW = visibleHalfWidthAt(wide, 10)
    const farW = visibleHalfWidthAt(wide, 20)
    expect(farW / nearW).toBeCloseTo(2, 5)
    expect(visibleHalfWidthAt(narrow, 10)).toBeLessThan(nearW)
  })
})

describe('painterOrder', () => {
  it('同层远处（大 artY）先画；层间互不串序', () => {
    expect(painterOrder(200, 0)).toBeLessThan(painterOrder(50, 0))
    expect(painterOrder(0, 1)).toBeGreaterThan(painterOrder(9999, 0))
  })
})
