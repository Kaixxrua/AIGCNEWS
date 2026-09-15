/**
 * 精灵层场景图（HD-2D 复刻的像素清晰层）：
 * 正交相机覆盖低分整数美术格（y 自底向上），所有 quad 以固定美术像素尺寸摆放、
 * 坐标恒为整数（像素对齐红线由编排器经 project.worldToArt 保证），
 * 层内画家算法（renderOrder = painterOrder(artY, layer)，材质 depthTest:false）。
 * 本层不含任何世界空间几何——世界锚点→整数格的换算全部在 project.ts。
 * 网格几何为 sprites.ts 的共享 unitPlane（脚底锚点），dispose 只清材质不碰几何。
 */
import * as THREE from 'three'
import { createSpriteMesh } from './sprites'
import { makeArtGrid, painterOrder } from './project'
import type { ArtGrid } from './project'
import type { PaletteKey, PaletteRegistry } from './palette'

/** 精灵层内的画家层（同层按 artY 排，远先近后） */
export const SPRITE_LAYER = {
  props: 1, // 灯柱/树干（远道具）
  actors: 2, // 角色/动物
  canopies: 3, // 近树树冠（可罩住角色）
  bubbles: 4, // 气泡恒在最上
} as const

export interface SpriteHandle {
  readonly mesh: THREE.Mesh
  readonly material: THREE.MeshBasicMaterial
  readonly artW: number
  readonly artH: number
  /** 换帧（FrameSet.textureAt 产物，帧尺寸必须与本 quad 一致） */
  setFrame(texture: THREE.Texture): void
  /** 摆放：整数美术格坐标（x 中心，y 底边自底向上） */
  setPosition(artX: number, artYBottom: number): void
  /** 画家排序键 */
  setOrder(artY: number, layer: number): void
  /** 水平镜像（朝向） */
  setFlip(flip: boolean): void
  setVisible(visible: boolean): void
  dispose(): void
}

export interface SpriteStage {
  scene: THREE.Scene
  camera: THREE.OrthographicCamera
  /** 当前美术格布局（resize 后更新） */
  readonly grid: ArtGrid
  addSprite(texture: THREE.Texture, artW: number, artH: number, tintKey?: PaletteKey): SpriteHandle
  resize(cssWidth: number, cssHeight: number, scale: number): void
  dispose(): void
}

export const createSpriteStage = (palette: PaletteRegistry): SpriteStage => {
  const scene = new THREE.Scene()
  let grid = makeArtGrid(960, 540, 3)
  const camera = new THREE.OrthographicCamera(0, grid.lowW, grid.lowH, 0, 0.01, 10)
  camera.position.z = 1

  const handles = new Set<SpriteHandle>()

  const addSprite = (
    texture: THREE.Texture,
    artW: number,
    artH: number,
    tintKey?: PaletteKey,
  ): SpriteHandle => {
    const mesh = createSpriteMesh(texture, artW, artH)
    const material = mesh.material as THREE.MeshBasicMaterial
    if (tintKey) palette.registerKey(material.color, tintKey)
    scene.add(mesh)

    let flipped = false
    const handle: SpriteHandle = {
      mesh,
      material,
      artW,
      artH,
      setFrame(next) {
        if (material.map === next) return
        material.map = next
      },
      setPosition(artX, artYBottom) {
        mesh.position.set(Math.round(artX), Math.round(artYBottom), 0)
      },
      setOrder(artY, layer) {
        mesh.renderOrder = painterOrder(artY, layer)
      },
      setFlip(flip) {
        if (flip === flipped) return
        flipped = flip
        mesh.scale.x = flip ? -artW : artW
      },
      setVisible(visible) {
        mesh.visible = visible
      },
      dispose() {
        scene.remove(mesh)
        material.dispose()
        handles.delete(handle)
      },
    }
    handles.add(handle)
    return handle
  }

  const resize = (cssWidth: number, cssHeight: number, scale: number): void => {
    grid = makeArtGrid(cssWidth, cssHeight, scale)
    camera.right = grid.lowW
    camera.top = grid.lowH
    camera.updateProjectionMatrix()
  }

  const dispose = (): void => {
    for (const handle of Array.from(handles)) handle.dispose()
    scene.clear()
  }

  return {
    scene,
    camera,
    get grid() {
      return grid
    },
    addSprite,
    resize,
    dispose,
  }
}
