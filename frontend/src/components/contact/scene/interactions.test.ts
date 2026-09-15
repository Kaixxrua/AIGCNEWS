/**
 * interactions 矩形命中语义测试：jsdom 无 layout，getBoundingClientRect 手动桩；
 * 相机用与场景同参数的真 PerspectiveCamera（数学类在 jsdom 可实例化）。
 */
import { describe, expect, it } from 'vitest'
import * as THREE from 'three'
import { FieldInteractions, type FieldInteractionTarget } from './interactions'

const makeDom = (): HTMLElement => {
  const dom = document.createElement('div')
  dom.getBoundingClientRect = () =>
    ({ left: 0, top: 0, width: 400, height: 300, right: 400, bottom: 300 }) as DOMRect
  document.body.appendChild(dom)
  return dom
}

const makeCamera = (): THREE.PerspectiveCamera => {
  const camera = new THREE.PerspectiveCamera(30, 400 / 300, 0.5, 80)
  camera.position.set(0, 3.4, 15)
  camera.lookAt(0, 1.0, 0)
  camera.updateMatrixWorld(true)
  return camera
}

const pointer = (type: string, x: number, y: number): Event =>
  Object.assign(new Event(type), { clientX: x, clientY: y })

const rectTarget = (
  rect: FieldInteractionTarget['rect'],
): { target: FieldInteractionTarget; hover: THREE.Vector3[]; press: THREE.Vector3[] } => {
  const hover: THREE.Vector3[] = []
  const press: THREE.Vector3[] = []
  return {
    target: {
      rect,
      onHover: (point) => hover.push(point.clone()),
      onPress: (point) => press.push(point.clone()),
    },
    hover,
    press,
  }
}

describe('FieldInteractions 矩形命中', () => {
  it('hover 命中矩形 → onHover 携带地面（y=0）世界坐标 + cursor:pointer', () => {
    const dom = makeDom()
    const interactions = new FieldInteractions({ camera: makeCamera(), dom })
    const { target, hover } = rectTarget({ left: 100, top: 100, width: 60, height: 80 })
    interactions.register(target)

    dom.dispatchEvent(pointer('pointermove', 130, 140))
    expect(hover).toHaveLength(1)
    expect(hover[0]!.y).toBeCloseTo(0, 5)
    expect(dom.style.cursor).toBe('pointer')
    interactions.dispose()
  })

  it('未命中 → 无回调且无 cursor；移出后 hover 目标清空', () => {
    const dom = makeDom()
    const interactions = new FieldInteractions({ camera: makeCamera(), dom })
    const { target, hover } = rectTarget({ left: 100, top: 100, width: 60, height: 80 })
    interactions.register(target)

    dom.dispatchEvent(pointer('pointermove', 10, 10))
    expect(hover).toHaveLength(0)
    expect(dom.style.cursor).toBe('')

    dom.dispatchEvent(pointer('pointermove', 130, 140))
    dom.dispatchEvent(pointer('pointermove', 20, 20))
    expect(dom.style.cursor).toBe('')
    expect(interactions.hoveredTarget).toBeNull()
    interactions.dispose()
  })

  it('hover 节流：90ms 内或位移 <3px 的重投被跳过', () => {
    const dom = makeDom()
    let now = 1000
    const interactions = new FieldInteractions({ camera: makeCamera(), dom, now: () => now })
    const a = rectTarget({ left: 0, top: 0, width: 50, height: 50 })
    const b = rectTarget({ left: 200, top: 150, width: 50, height: 50 })
    interactions.register(a.target)
    interactions.register(b.target)

    dom.dispatchEvent(pointer('pointermove', 25, 25))
    expect(a.hover).toHaveLength(1)
    // 30ms 后移到另一目标：时间节流拦下（lastX/lastY 不更新，仍以 (25,25) 为参照）
    now += 30
    dom.dispatchEvent(pointer('pointermove', 225, 175))
    expect(b.hover).toHaveLength(0)
    // 120ms 后但距上次被处理位置只有 2px：距离节流拦下
    now += 120
    dom.dispatchEvent(pointer('pointermove', 26, 26))
    expect(a.hover).toHaveLength(1)
    expect(b.hover).toHaveLength(0)
    // 再过 120ms 位移足够：命中 b
    now += 120
    dom.dispatchEvent(pointer('pointermove', 240, 180))
    expect(b.hover).toHaveLength(1)
    interactions.dispose()
  })

  it('press 不受节流限制，命中即 onPress', () => {
    const dom = makeDom()
    let now = 1000
    const interactions = new FieldInteractions({ camera: makeCamera(), dom, now: () => now })
    const { target, press } = rectTarget({ left: 100, top: 100, width: 60, height: 80 })
    interactions.register(target)

    dom.dispatchEvent(pointer('pointerdown', 130, 140))
    now += 5
    dom.dispatchEvent(pointer('pointerdown', 130, 140))
    expect(press).toHaveLength(2)
    expect(press[0]!.y).toBeCloseTo(0, 5)
    interactions.dispose()
  })

  it('重叠矩形取面积最小者（最具体目标优先）', () => {
    const dom = makeDom()
    const interactions = new FieldInteractions({ camera: makeCamera(), dom })
    const big = rectTarget({ left: 0, top: 0, width: 300, height: 300 })
    const small = rectTarget({ left: 100, top: 100, width: 40, height: 40 })
    interactions.register(big.target)
    interactions.register(small.target)

    dom.dispatchEvent(pointer('pointermove', 120, 120))
    expect(small.hover).toHaveLength(1)
    expect(big.hover).toHaveLength(0)
    interactions.dispose()
  })

  it('isUiEvent 命中的事件跳过拾取并清空 hover', () => {
    const dom = makeDom()
    const interactions = new FieldInteractions({
      camera: makeCamera(),
      dom,
      isUiEvent: () => true,
    })
    const { target, hover } = rectTarget({ left: 100, top: 100, width: 60, height: 80 })
    interactions.register(target)

    dom.dispatchEvent(pointer('pointermove', 130, 140))
    expect(hover).toHaveLength(0)
    expect(interactions.hoveredTarget).toBeNull()
    interactions.dispose()
  })

  it('rect 为 null 的目标不可命中；注销后不再命中', () => {
    const dom = makeDom()
    const interactions = new FieldInteractions({ camera: makeCamera(), dom })
    const { target, hover } = rectTarget({ left: 100, top: 100, width: 60, height: 80 })
    const unregister = interactions.register(target)

    target.rect = null
    dom.dispatchEvent(pointer('pointermove', 130, 140))
    expect(hover).toHaveLength(0)

    target.rect = { left: 100, top: 100, width: 60, height: 80 }
    unregister()
    dom.dispatchEvent(pointer('pointermove', 130, 140))
    expect(hover).toHaveLength(0)
    interactions.dispose()
  })
})
