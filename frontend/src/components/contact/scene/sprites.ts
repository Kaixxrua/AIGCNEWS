/**
 * 像素图 DSL → three.js 纹理/网格工厂。
 * DSL：PixelFrame { rows, palette }，rows 为等长字符串数组，'.' 透明，
 * 其余字符在 palette 中查色。逐像素写入 Canvas2D → CanvasTexture
 * （NearestFilter + SRGBColorSpace + 无 mipmap——SRGB 标记缺失会让角色洗白）。
 * jsdom 等无 Canvas 2D 环境返回 null，调用方（编排器）据此中止并露出静态兜底。
 */
import * as THREE from 'three'

export interface PixelFrame {
  rows: string[]
  palette: Record<string, string>
}

export interface FrameSize {
  width: number
  height: number
}

/** 校验 DSL：所有行等长、字符均在调色板内（'.' 除外）。不合法抛错——数据错误应在启动即暴露 */
export const validateFrame = (frame: PixelFrame): FrameSize => {
  if (!frame.rows.length) throw new Error('PixelFrame: rows 为空')
  const width = frame.rows[0]!.length
  if (!width) throw new Error('PixelFrame: 行宽为 0')
  for (const row of frame.rows) {
    if (row.length !== width) throw new Error(`PixelFrame: 行宽不一致（期望 ${width}，实得 ${row.length}）`)
    for (const ch of row) {
      if (ch !== '.' && !(ch in frame.palette)) {
        throw new Error(`PixelFrame: 字符 '${ch}' 不在调色板中`)
      }
    }
  }
  return { width, height: frame.rows.length }
}

/** 把一帧画到 canvas；无 2D 上下文返回 null */
export const frameToCanvas = (frame: PixelFrame): HTMLCanvasElement | null => {
  const { width, height } = validateFrame(frame)
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  if (!ctx) return null
  for (let y = 0; y < height; y++) {
    const row = frame.rows[y]!
    for (let x = 0; x < width; x++) {
      const ch = row[x]!
      if (ch === '.') continue
      ctx.fillStyle = frame.palette[ch]!
      ctx.fillRect(x, y, 1, 1)
    }
  }
  return canvas
}

export const frameToTexture = (frame: PixelFrame): THREE.CanvasTexture | null => {
  const canvas = frameToCanvas(frame)
  if (!canvas) return null
  const texture = new THREE.CanvasTexture(canvas)
  texture.magFilter = THREE.NearestFilter
  texture.minFilter = THREE.NearestFilter
  texture.generateMipmaps = false
  texture.colorSpace = THREE.SRGBColorSpace
  return texture
}

/** 底边中点为锚点的共享单位平面：网格 scale 即美术像素尺寸，脚底对齐 y=0 */
let sharedUnitPlane: THREE.PlaneGeometry | null = null
export const unitPlaneGeometry = (): THREE.PlaneGeometry => {
  if (!sharedUnitPlane) {
    sharedUnitPlane = new THREE.PlaneGeometry(1, 1)
    sharedUnitPlane.translate(0, 0.5, 0)
  }
  return sharedUnitPlane
}
export const disposeUnitPlane = (): void => {
  sharedUnitPlane?.dispose()
  sharedUnitPlane = null
}

export interface SpriteMeshOptions {
  renderOrder?: number
  opacity?: number
}

/** 标准角色/道具网格：无光照无深度，画家算法全靠 renderOrder */
export const createSpriteMesh = (
  texture: THREE.Texture,
  width: number,
  height: number,
  options: SpriteMeshOptions = {},
): THREE.Mesh => {
  const material = new THREE.MeshBasicMaterial({
    map: texture,
    transparent: true,
    depthTest: false,
    depthWrite: false,
  })
  if (options.opacity !== undefined) material.opacity = options.opacity
  const mesh = new THREE.Mesh(unitPlaneGeometry(), material)
  mesh.scale.set(width, height, 1)
  if (options.renderOrder !== undefined) mesh.renderOrder = options.renderOrder
  return mesh
}

/**
 * 多帧动画纹理集：预建全部帧纹理，播帧只换 material.map（map 始终非空，
 * 不触发着色器重编译）。frames 内所有帧尺寸必须与首帧一致。
 */
export class FrameSet {
  readonly textures: THREE.Texture[] = []
  readonly width: number
  readonly height: number

  constructor(frames: PixelFrame[]) {
    if (!frames.length) throw new Error('FrameSet: 至少需要一帧')
    const first = validateFrame(frames[0]!)
    this.width = first.width
    this.height = first.height
    for (const frame of frames) {
      const size = validateFrame(frame)
      if (size.width !== this.width || size.height !== this.height) {
        throw new Error('FrameSet: 动画帧尺寸不一致')
      }
      const texture = frameToTexture(frame)
      if (!texture) throw new Error('FrameSet: Canvas 2D 不可用')
      this.textures.push(texture)
    }
  }

  get frameCount(): number {
    return this.textures.length
  }

  textureAt(index: number): THREE.Texture {
    return this.textures[((index % this.textures.length) + this.textures.length) % this.textures.length]!
  }

  dispose(): void {
    for (const texture of this.textures) texture.dispose()
    this.textures.length = 0
  }
}
