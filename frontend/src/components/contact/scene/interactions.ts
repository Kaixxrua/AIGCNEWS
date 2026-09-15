/**
 * 场景指针交互（屏幕矩形命中 + 地面反投影）：
 * - 精灵在 HD-2D 管线里已不在世界空间（屏幕整数格摆放），Raycaster 无的放矢——
 *   编排器每帧把精灵的 CSS 矩形写入 target.rect，本模块做包含测试，
 *   命中多个时取面积最小者（最具体目标优先）；
 * - 回调携带指针在地面（y=0 平面）的世界坐标（透视相机射线 ∩ 地平面），
 *   供编排器换算成角色控制器域的虚拟像素（朝向/走位/flee）；
 * - hover 重投节流：距上次 ≥90ms 且位移 ≥3px；事件落在联系条目/链接/按钮等
 *   UI 上时跳过（不抢交互）；hover 命中 → dom 上 cursor:pointer。
 */
import * as THREE from 'three'
import type { CssRect } from './project'

export interface FieldInteractionTarget {
  /** 当前命中矩形（CSS px，相对 dom 左上角），由编排器逐帧覆写；null = 本帧不可命中 */
  rect: CssRect | null
  /** 命中点（地面世界坐标）随回调下发，供角色朝向指针 */
  onHover: ((point: THREE.Vector3) => void) | null
  onPress: ((point: THREE.Vector3) => void) | null
}

export interface FieldInteractionsOptions {
  camera: THREE.Camera
  dom: HTMLElement
  /** 返回 true 表示事件落在交互 UI 上，应跳过场景拾取 */
  isUiEvent?: (event: PointerEvent) => boolean
  minIntervalMs?: number
  minDeltaPx?: number
  now?: () => number
}

export class FieldInteractions {
  private readonly opts: FieldInteractionsOptions
  private readonly targets: FieldInteractionTarget[] = []
  private readonly raycaster = new THREE.Raycaster()
  private readonly groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0)
  private readonly ndc = new THREE.Vector2()
  private readonly groundPoint = new THREE.Vector3()
  private hovered: FieldInteractionTarget | null = null
  private lastAt = Number.NEGATIVE_INFINITY
  private lastX = Number.NaN
  private lastY = Number.NaN
  private readonly disposers: Array<() => void> = []

  constructor(opts: FieldInteractionsOptions) {
    this.opts = opts
    const onMove = (event: Event) => this.handle(event as PointerEvent, false)
    const onDown = (event: Event) => this.handle(event as PointerEvent, true)
    opts.dom.addEventListener('pointermove', onMove, { passive: true })
    opts.dom.addEventListener('pointerdown', onDown, { passive: true })
    this.disposers.push(() => {
      opts.dom.removeEventListener('pointermove', onMove)
      opts.dom.removeEventListener('pointerdown', onDown)
    })
  }

  /** 注册命中目标；返回注销函数 */
  register(target: FieldInteractionTarget): () => void {
    this.targets.push(target)
    return () => {
      const index = this.targets.indexOf(target)
      if (index >= 0) this.targets.splice(index, 1)
      if (this.hovered === target) this.setHovered(null)
    }
  }

  get hoveredTarget(): FieldInteractionTarget | null {
    return this.hovered
  }

  private handle(event: PointerEvent, isPress: boolean): void {
    const { dom, isUiEvent } = this.opts
    if (isUiEvent?.(event)) {
      if (!isPress) this.setHovered(null)
      return
    }
    const now = (this.opts.now ?? (() => performance.now()))()
    if (!isPress) {
      const minInterval = this.opts.minIntervalMs ?? 90
      const minDelta = this.opts.minDeltaPx ?? 3
      if (now - this.lastAt < minInterval) return
      const dx = event.clientX - this.lastX
      const dy = event.clientY - this.lastY
      if (Number.isFinite(this.lastX) && dx * dx + dy * dy < minDelta * minDelta) return
    }
    this.lastAt = now
    this.lastX = event.clientX
    this.lastY = event.clientY

    const rect = dom.getBoundingClientRect()
    if (rect.width <= 0 || rect.height <= 0) return
    const px = event.clientX - rect.left
    const py = event.clientY - rect.top

    let hit: FieldInteractionTarget | null = null
    let hitArea = Number.POSITIVE_INFINITY
    for (const target of this.targets) {
      const box = target.rect
      if (!box) continue
      if (px < box.left || px >= box.left + box.width) continue
      if (py < box.top || py >= box.top + box.height) continue
      const area = box.width * box.height
      if (area < hitArea) {
        hit = target
        hitArea = area
      }
    }

    const point = this.pointerGroundPoint(px, py, rect.width, rect.height)
    if (isPress) {
      if (hit) hit.onPress?.(point)
    } else {
      this.setHovered(hit, point)
    }
  }

  /** 指针位置 → 透视相机射线 ∩ 地面（y=0），供角色朝向/走位换算 */
  private pointerGroundPoint(px: number, py: number, width: number, height: number): THREE.Vector3 {
    this.ndc.set((px / width) * 2 - 1, -((py / height) * 2 - 1))
    this.raycaster.setFromCamera(this.ndc, this.opts.camera)
    const ray = this.raycaster.ray
    const point = ray.intersectPlane(this.groundPlane, this.groundPoint)
    if (point) return point
    // 视线朝天（理论上俯角相机不会）：退化为前方 10u 处
    return this.groundPoint.copy(ray.origin).addScaledVector(ray.direction, 10)
  }

  private setHovered(next: FieldInteractionTarget | null, point: THREE.Vector3 | null = null): void {
    if (next === this.hovered) return
    this.hovered = next
    if (next && point) next.onHover?.(point)
    this.opts.dom.style.cursor = next ? 'pointer' : ''
  }

  dispose(): void {
    for (const dispose of this.disposers.splice(0)) dispose()
    this.targets.length = 0
    this.setHovered(null)
  }
}
