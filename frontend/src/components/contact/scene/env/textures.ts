/**
 * 环境纹理烘焙（HD-2D 复刻的手绘层）：全部纹理为本文件程序化生成的原创数据，
 * 不含任何外部图片、AI 生成素材或八方旅人（Octopath Traveler）等既有游戏资产。
 *
 * 结构：纯数据生成器（mulberry32 种子 → Uint8ClampedArray RGBA，jsdom 可测）
 * + 薄 canvas blit 层（putImageData → CanvasTexture，无 2D 上下文返回 null）。
 * 纹理为「昼间手绘稿」；夜间经材质 color 乘法罩色（PaletteRegistry 驱动）。
 * 明暗方向感在烘焙期画入（八方式左上光）：亮部偏上左、暗部偏下右。
 */
import * as THREE from 'three'
import { mulberry32 } from '../events'

export interface RgbaImage {
  data: Uint8ClampedArray
  width: number
  height: number
}

export const makeImage = (width: number, height: number): RgbaImage => ({
  data: new Uint8ClampedArray(width * height * 4),
  width,
  height,
})

const put = (img: RgbaImage, x: number, y: number, r: number, g: number, b: number, a: number): void => {
  if (x < 0 || y < 0 || x >= img.width || y >= img.height) return
  const i = (y * img.width + x) * 4
  img.data[i] = r
  img.data[i + 1] = g
  img.data[i + 2] = b
  img.data[i + 3] = a
}

const get = (img: RgbaImage, x: number, y: number): [number, number, number, number] => {
  const i = (y * img.width + x) * 4
  return [img.data[i]!, img.data[i + 1]!, img.data[i + 2]!, img.data[i + 3]!]
}

const hex = (color: string): [number, number, number] => {
  const n = parseInt(color.slice(1), 16)
  return [(n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff]
}

const mix3 = (a: [number, number, number], b: [number, number, number], t: number): [number, number, number] => [
  Math.round(a[0] + (b[0] - a[0]) * t),
  Math.round(a[1] + (b[1] - a[1]) * t),
  Math.round(a[2] + (b[2] - a[2]) * t),
]

/** 2D 值噪声：格点随机 + 双 smoothstep 插值（确定性，同种子同图） */
const valueNoise2d = (seed: number): ((x: number, y: number) => number) => {
  const lattice = new Map<number, number>()
  const at = (ix: number, iy: number): number => {
    const key = ((ix * 73856093) ^ (iy * 19349663) ^ seed) >>> 0
    let value = lattice.get(key)
    if (value === undefined) {
      // Map 查询顺序不定 → 用 key 再喂一个轻量 hash 保证与遍历顺序无关；
      // 种子必须异或进 key，否则所有种子共享同一组格点（曾致 farHills 种子失效）
      value = mulberry32(key)()
      lattice.set(key, value)
    }
    return value
  }
  return (x, y) => {
    const ix = Math.floor(x)
    const iy = Math.floor(y)
    const fx = x - ix
    const fy = y - iy
    const ux = fx * fx * (3 - 2 * fx)
    const uy = fy * fy * (3 - 2 * fy)
    const a = at(ix, iy)
    const b = at(ix + 1, iy)
    const c = at(ix, iy + 1)
    const d = at(ix + 1, iy + 1)
    return a + (b - a) * ux + (c - a) * uy + (a - b - c + d) * ux * uy
  }
}

const fbm2 = (seed: number, octaves = 3): ((x: number, y: number) => number) => {
  const noises = Array.from({ length: octaves }, (_, i) => valueNoise2d(seed + i * 101))
  return (x, y) => {
    let v = 0
    let amp = 0.5
    let freq = 1
    for (const noise of noises) {
      v += noise(x * freq, y * freq) * amp
      freq *= 2.03
      amp *= 0.5
    }
    return v
  }
}

/* ── 草地：底色斑驳 + 草茎刻痕 + 稀疏碎花 ─────────────────── */

const GRASS_BASE = hex('#7db35e')
const GRASS_DARK = hex('#5f9e4f')
const GRASS_LIGHT = hex('#98cc72')
const GRASS_BLADE = hex('#6aa654')
const FLOWER_WHITE = hex('#fff6e0')
const FLOWER_GOLD = hex('#ffd96a')

export const grassField = (seed: number, width: number, height: number): RgbaImage => {
  const img = makeImage(width, height)
  const rng = mulberry32(seed)
  const mottle = fbm2(seed ^ 0x51, 3)
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const n = mottle(x / 46, y / 46) // 大尺度斑块
      const t = Math.min(1, Math.max(0, (n - 0.32) * 2.2))
      const color = t < 0.5 ? mix3(GRASS_DARK, GRASS_BASE, t * 2) : mix3(GRASS_BASE, GRASS_LIGHT, (t - 0.5) * 2)
      put(img, x, y, color[0], color[1], color[2], 255)
    }
  }
  // 草茎刻痕：短竖线，随机深浅
  const blades = Math.round((width * height) / 110)
  for (let i = 0; i < blades; i++) {
    const x = Math.floor(rng() * width)
    const y = Math.floor(rng() * (height - 3))
    const len = 1 + Math.floor(rng() * 2)
    const light = rng() < 0.4
    const color = light ? GRASS_LIGHT : GRASS_BLADE
    for (let k = 0; k < len; k++) {
      const fade = k === len - 1 ? 0.55 : 1
      const [, , , a] = get(img, x, y + k)
      if (a > 0) {
        const base = get(img, x, y + k)
        const mixed = mix3([base[0], base[1], base[2]], color, 0.55 * fade)
        put(img, x, y + k, mixed[0], mixed[1], mixed[2], 255)
      }
    }
  }
  // 碎花：白/金 1-2px
  const flowers = Math.round(width / 14)
  for (let i = 0; i < flowers; i++) {
    const x = Math.floor(rng() * (width - 1))
    const y = Math.floor(rng() * (height - 1))
    const color = rng() < 0.6 ? FLOWER_WHITE : FLOWER_GOLD
    put(img, x, y, color[0], color[1], color[2], 255)
    if (rng() < 0.5) put(img, x + 1, y, color[0], color[1], color[2], 255)
  }
  return img
}

/* ── 土径：夯土底 + 车辙两道 + 碎石；上下缘透明抖动 ───────── */

const PATH_BASE = hex('#d9c9a8')
const PATH_RUT = hex('#b8a888')
const PATH_STONE_A = hex('#c9b898')
const PATH_STONE_B = hex('#e8dcc0')

export const dirtPath = (seed: number, width: number, height: number): RgbaImage => {
  const img = makeImage(width, height)
  const rng = mulberry32(seed)
  const wobbleA = fbm2(seed ^ 0x77, 2)
  const wobbleB = fbm2(seed ^ 0x99, 2)
  for (let x = 0; x < width; x++) {
    // 车辙中线随 x 轻微摆动
    const rutA = height * 0.38 + (wobbleA(x / 60, 0) - 0.5) * height * 0.12
    const rutB = height * 0.66 + (wobbleB(x / 60, 5) - 0.5) * height * 0.12
    for (let y = 0; y < height; y++) {
      const edgeTop = 1 + Math.floor(wobbleA(x / 24, 9) * 3)
      const edgeBottom = height - 2 - Math.floor(wobbleB(x / 24, 13) * 3)
      if (y < edgeTop || y > edgeBottom) {
        // 边缘透明抖动：隔列漏出
        if ((x + y) % 2 === 0 && (y === edgeTop - 1 || y === edgeBottom + 1)) {
          put(img, x, y, PATH_BASE[0], PATH_BASE[1], PATH_BASE[2], 110)
        }
        continue
      }
      let color = PATH_BASE
      const n = fbm2(seed ^ 0x23, 2)(x / 18, y / 18)
      if (n > 0.62) color = PATH_STONE_B
      else if (n < 0.4) color = PATH_STONE_A
      const distRut = Math.min(Math.abs(y - rutA), Math.abs(y - rutB))
      if (distRut < 1.6) color = mix3(color, PATH_RUT, 0.72)
      else if (distRut < 3) color = mix3(color, PATH_RUT, 0.28)
      put(img, x, y, color[0], color[1], color[2], 255)
    }
  }
  // 碎石亮点
  for (let i = 0; i < width / 3; i++) {
    const x = Math.floor(rng() * width)
    const y = Math.floor(height * 0.15 + rng() * height * 0.7)
    put(img, x, y, PATH_STONE_B[0], PATH_STONE_B[1], PATH_STONE_B[2], 255)
  }
  return img
}

/* ── 远山：双层山脊（后浅前深），顶部软 alpha ─────────────── */

const HILL_BACK = hex('#a8c8a0')
const HILL_FRONT = hex('#8ab488')

export const farHills = (seed: number, width: number, height: number): RgbaImage => {
  const img = makeImage(width, height)
  const ridgeA = fbm2(seed, 2)
  const ridgeB = fbm2(seed ^ 0x3d, 3)
  for (let x = 0; x < width; x++) {
    const lineA = height * (0.34 + (ridgeA(x / 90, 0) - 0.5) * 0.5)
    const lineB = height * (0.52 + (ridgeB(x / 46, 3) - 0.5) * 0.42)
    for (let y = 0; y < height; y++) {
      if (y >= lineB) {
        const shade = Math.min(1, (y - lineB) / (height - lineB))
        const color = mix3(HILL_FRONT, mix3(HILL_FRONT, hex('#5f8a5c'), 0.5), shade)
        put(img, x, y, color[0], color[1], color[2], 255)
      } else if (y >= lineA) {
        const shade = Math.min(1, (y - lineA) / Math.max(1, lineB - lineA))
        const color = mix3(mix3(HILL_BACK, HILL_FRONT, 0.35), HILL_BACK, 1 - shade)
        put(img, x, y, color[0], color[1], color[2], 255)
      } else if (y >= lineA - 2) {
        // 山顶软边
        put(img, x, y, HILL_BACK[0], HILL_BACK[1], HILL_BACK[2], y >= lineA - 1 ? 160 : 70)
      }
    }
  }
  return img
}

/* ── 树线：针叶/阔叶混合的连绵剪影，顶部抖动 alpha ────────── */

const TREELINE_A = hex('#5f9e4f')
const TREELINE_B = hex('#4a8448')

export const treeLineStrip = (seed: number, width: number, height: number): RgbaImage => {
  const img = makeImage(width, height)
  const rng = mulberry32(seed)
  const drift = fbm2(seed ^ 0x1f, 2)
  // 逐树：每 7-13px 一棵树，圆锥/圆顶交替
  let x = 0
  const treeTops: Array<{ cx: number; top: number; half: number; round: boolean }> = []
  while (x < width) {
    const wTree = 7 + Math.floor(rng() * 6)
    const cx = x + wTree / 2
    const top = height * (0.08 + drift(x / 80, 2) * 0.34) + rng() * height * 0.1
    treeTops.push({ cx, top, half: wTree / 2, round: rng() < 0.55 })
    x += wTree - 1 - Math.floor(rng() * 3) // 略微交叠
  }
  for (let px = 0; px < width; px++) {
    let skyline = height // 默认无底
    let round = false
    for (const tree of treeTops) {
      const d = Math.abs(px - tree.cx) / tree.half
      if (d > 1) continue
      const line = tree.round
        ? tree.top + d * d * tree.half * 1.1
        : tree.top + d * (height - tree.top) * 0.92
      if (line < skyline) {
        skyline = line
        round = tree.round
      }
    }
    if (skyline >= height) continue
    for (let y = 0; y < height; y++) {
      if (y < skyline - 1) continue
      if (y < skyline + 1) {
        const alpha = (px + y) % 2 === 0 ? 190 : 255
        put(img, px, y, TREELINE_A[0], TREELINE_A[1], TREELINE_A[2], alpha)
        continue
      }
      const shade = Math.min(1, (y - skyline) / (height - skyline))
      const base = round ? TREELINE_A : TREELINE_B
      const color = mix3(base, hex('#3a6a3c'), shade * 0.7)
      put(img, px, y, color[0], color[1], color[2], 255)
    }
  }
  return img
}

/* ── 村庄剪影：坡屋顶小屋群 + 一座塔楼；窗洞单独成层（夜里暖窗） ── */

const VILLAGE_SIL = hex('#6a5a48')
const VILLAGE_ROOF = hex('#4f4438')
const VILLAGE_WINDOW = hex('#ffca7a')

export const villageSkyline = (
  seed: number,
  width: number,
  height: number,
): { silhouette: RgbaImage; windows: RgbaImage } => {
  const silhouette = makeImage(width, height)
  const windows = makeImage(width, height)
  const rng = mulberry32(seed)
  let x = 2
  let houseCount = 0
  while (x < width - 8) {
    const wHouse = 10 + Math.floor(rng() * 14)
    const hHouse = Math.round(height * (0.3 + rng() * 0.28))
    const roofH = 3 + Math.floor(rng() * 4)
    const base = height - 1
    // 墙体
    for (let dx = 0; dx < wHouse; dx++) {
      for (let dy = 0; dy < hHouse; dy++) {
        put(silhouette, x + dx, base - dy, VILLAGE_SIL[0], VILLAGE_SIL[1], VILLAGE_SIL[2], 255)
      }
    }
    // 坡屋顶（三角）
    for (let dy = 0; dy < roofH; dy++) {
      const half = Math.ceil(((roofH - dy) / roofH) * (wHouse / 2 + 1))
      const cx = x + Math.floor(wHouse / 2)
      for (let dx = -half; dx <= half; dx++) {
        put(silhouette, cx + dx, base - hHouse - dy, VILLAGE_ROOF[0], VILLAGE_ROOF[1], VILLAGE_ROOF[2], 255)
      }
    }
    // 烟囱
    if (rng() < 0.5) {
      const cx = x + 2 + Math.floor(rng() * (wHouse - 4))
      for (let dy = 0; dy < roofH + 2; dy++) {
        put(silhouette, cx, base - hHouse - dy + 1, VILLAGE_ROOF[0], VILLAGE_ROOF[1], VILLAGE_ROOF[2], 255)
      }
    }
    // 窗洞 2×3，1-3 扇
    const winCount = 1 + Math.floor(rng() * 3)
    for (let w = 0; w < winCount; w++) {
      const wx = x + 1 + Math.floor(rng() * Math.max(1, wHouse - 3))
      const wy = base - 2 - Math.floor(rng() * Math.max(1, hHouse - 4))
      for (let dx = 0; dx < 2; dx++) {
        for (let dy = 0; dy < 3; dy++) {
          put(windows, wx + dx, wy - dy, VILLAGE_WINDOW[0], VILLAGE_WINDOW[1], VILLAGE_WINDOW[2], 255)
        }
      }
    }
    houseCount++
    x += wHouse + 2 + Math.floor(rng() * 6)
  }
  // 塔楼：画面 2/3 处，细高 + 尖顶
  const tx = Math.floor(width * 0.66)
  const towerW = 7
  const towerH = Math.round(height * 0.86)
  for (let dx = 0; dx < towerW; dx++) {
    for (let dy = 0; dy < towerH; dy++) {
      put(silhouette, tx + dx, height - 1 - dy, VILLAGE_SIL[0], VILLAGE_SIL[1], VILLAGE_SIL[2], 255)
    }
  }
  for (let dy = 0; dy < 6; dy++) {
    const half = Math.ceil(((6 - dy) / 6) * (towerW / 2 + 1))
    for (let dx = -half; dx <= half; dx++) {
      put(silhouette, tx + Math.floor(towerW / 2) + dx, height - 1 - towerH - dy, VILLAGE_ROOF[0], VILLAGE_ROOF[1], VILLAGE_ROOF[2], 255)
    }
  }
  // 塔窗两扇
  for (const dy of [Math.round(towerH * 0.4), Math.round(towerH * 0.62)]) {
    for (let dx = 0; dx < 2; dx++) {
      for (let k = 0; k < 3; k++) {
        put(windows, tx + 2 + dx, height - 1 - dy - k, VILLAGE_WINDOW[0], VILLAGE_WINDOW[1], VILLAGE_WINDOW[2], 255)
      }
    }
  }
  void houseCount
  return { silhouette, windows }
}

/* ── 灌木 / 岩石（中景点缀 billboard） ────────────────────── */

const BUSH_A = hex('#5f9e4f')
const BUSH_B = hex('#48793d')
const BUSH_HI = hex('#8cc06a')

export const bushBlob = (seed: number, width: number, height: number): RgbaImage => {
  const img = makeImage(width, height)
  const rng = mulberry32(seed)
  const cx = width / 2
  const cy = height * 0.56
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const dx = (x - cx) / (width * 0.46)
      const dy = (y - cy) / (height * 0.5)
      const d = dx * dx + dy * dy
      if (d > 1) continue
      // 左上光：亮部偏上左
      const light = Math.min(1, Math.max(0, 0.5 - dx * 0.45 - dy * 0.55 + (rng() - 0.5) * 0.22))
      const color = light > 0.62 ? BUSH_HI : light > 0.34 ? BUSH_A : BUSH_B
      const edge = d > 0.72
      const alpha = edge ? ((x + y) % 2 === 0 ? 255 : 150) : 255
      put(img, x, y, color[0], color[1], color[2], alpha)
    }
  }
  return img
}

const ROCK_A = hex('#9a948a')
const ROCK_B = hex('#6f6a62')
const ROCK_HI = hex('#c4beb2')

export const rockChunk = (seed: number, width: number, height: number): RgbaImage => {
  const img = makeImage(width, height)
  const rng = mulberry32(seed)
  const cx = width / 2
  const cy = height * 0.58
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const dx = (x - cx) / (width * 0.48)
      const dy = (y - cy) / (height * 0.52)
      const d = dx * dx + dy * dy * 1.2
      if (d > 1) continue
      const facet = fbm2(seed ^ 0x2b, 2)(x / 7, y / 7)
      const light = Math.min(1, Math.max(0, 0.55 - dx * 0.4 - dy * 0.5 + (facet - 0.5) * 0.8))
      const color = light > 0.62 ? ROCK_HI : light > 0.36 ? ROCK_A : ROCK_B
      const alpha = d > 0.78 ? ((x + y) % 2 === 0 ? 255 : 140) : 255
      put(img, x, y, color[0], color[1], color[2], alpha)
    }
  }
  void rng
  return img
}

/* ── 前景草（近镜大叶片，DOF 虚化层） ─────────────────────── */

const FG_A = hex('#5a9448')
const FG_B = hex('#477a3a')
const FG_HI = hex('#7db35e')

export const foregroundGrass = (seed: number, width: number, height: number): RgbaImage => {
  const img = makeImage(width, height)
  const rng = mulberry32(seed)
  // 底部填实带
  for (let y = Math.floor(height * 0.72); y < height; y++) {
    for (let x = 0; x < width; x++) {
      const color = rng() < 0.5 ? FG_A : FG_B
      put(img, x, y, color[0], color[1], color[2], 255)
    }
  }
  // 大叶片：弧形三角簇
  let x = 0
  while (x < width) {
    const clump = 3 + Math.floor(rng() * 4)
    for (let b = 0; b < clump; b++) {
      const bx = x + Math.floor(rng() * 9)
      const bladeH = Math.round(height * (0.34 + rng() * 0.5))
      const lean = (rng() - 0.5) * 8
      const color = rng() < 0.3 ? FG_HI : rng() < 0.5 ? FG_A : FG_B
      for (let i = 0; i < bladeH; i++) {
        const t = i / bladeH
        const px = Math.round(bx + lean * t * t)
        const py = height - 1 - i
        const wBlade = t > 0.82 ? 1 : 2
        const alpha = t > 0.9 ? 170 : 255
        for (let dx = 0; dx < wBlade; dx++) {
          put(img, px + dx, py, color[0], color[1], color[2], alpha)
        }
      }
    }
    x += 10 + Math.floor(rng() * 12)
  }
  return img
}

/* ── 径向光斑（halo / 光池 / 柔和阴影共用） ───────────────── */

/** 白色径向渐变（alpha 由 1→0），材质 color 染色；soft 控制衰减幂次 */
export const radialGlow = (size: number, power = 2.2): RgbaImage => {
  const img = makeImage(size, size)
  const half = size / 2
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const dx = (x - half + 0.5) / half
      const dy = (y - half + 0.5) / half
      const d = Math.sqrt(dx * dx + dy * dy)
      if (d >= 1) continue
      const a = Math.pow(1 - d, power)
      put(img, x, y, 255, 255, 255, Math.round(a * 255))
    }
  }
  return img
}

/* ── blit 层：数据 → CanvasTexture（jsdom 无 2D 返回 null） ── */

export interface BlitOptions {
  /** 默认 LinearFilter（环境平滑层）；像素素材用 NearestFilter */
  nearest?: boolean
  /** 平铺重复（地面/小径）；默认 clamp */
  repeat?: boolean
}

export const rgbaToTexture = (img: RgbaImage, options: BlitOptions = {}): THREE.CanvasTexture | null => {
  const canvas = document.createElement('canvas')
  canvas.width = img.width
  canvas.height = img.height
  const ctx = canvas.getContext('2d')
  if (!ctx) return null
  const imageData = ctx.createImageData(img.width, img.height)
  imageData.data.set(img.data)
  ctx.putImageData(imageData, 0, 0)
  const texture = new THREE.CanvasTexture(canvas)
  const filter = options.nearest ? THREE.NearestFilter : THREE.LinearFilter
  texture.magFilter = filter
  texture.minFilter = options.nearest ? THREE.NearestFilter : THREE.LinearMipmapLinearFilter
  texture.generateMipmaps = !options.nearest
  texture.colorSpace = THREE.SRGBColorSpace
  if (options.repeat) {
    texture.wrapS = THREE.RepeatWrapping
    texture.wrapT = THREE.RepeatWrapping
  }
  return texture
}
