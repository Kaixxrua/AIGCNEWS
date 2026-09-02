/**
 * 场景指针交互（Raycaster 封装）：
 * - hover 重投节流：距上次 ≥90ms 且位移 ≥3px 才发射线；
 * - 命中面由编排器随角色逐帧搬动，本模块只持有引用；
 * - 事件落在联系条目/链接/按钮等 UI 上时跳过（不抢交互）；
 * - hover 命中 → onHover + dom 上 cursor:pointer；pointerdown 命中 → onPress。
 */
import * as THREE from 'three'

export interface FieldInteractionTarget {
  hitArea: THREE.Object3D
  /** 命中点（世界坐标）随回调下发，供角色朝向指针 */
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

const MAX_HITS = 10

export class FieldInteractions {
  private readonly opts: FieldInteractionsOptions
  private readonly targets: FieldInteractionTarget[] = []
  private readonly raycaster = new THREE.Raycaster()
  private readonly ndc = new THREE.Vector2()
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
    this.ndc.set(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -(((event.clientY - rect.top) / rect.height) * 2 - 1),
    )
    this.raycaster.setFromCamera(this.ndc, this.opts.camera)
    const hitAreas = this.targets.map((target) => target.hitArea)
    const hits = this.raycaster.intersectObjects(hitAreas, false).slice(0, MAX_HITS)
    const hit = hits.length
      ? (this.targets.find((target) => target.hitArea === hits[0]!.object) ?? null)
      : null
    if (isPress) {
      if (hit && hits[0]) hit.onPress?.(hits[0].point)
    } else {
      this.setHovered(hit, hits[0]?.point ?? null)
    }
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
