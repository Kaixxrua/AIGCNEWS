/**
 * 像素原野角色/道具美术数据（HD-2D 复刻版）。
 *
 * 精灵层卡司（SWORDSMAN/SCHOLAR_F/SCHOLAR_M/KNIGHT/CLOAK/CAT/DOG）：
 * 原创角色设计提示词的 AI 抽卡原图 → 离线管线（rowcrop2 色谱抠像裁帧 →
 * normalize 脚底锚点归一 → free-tex-packer 图集打包）→ cast.png + 烤入清单
 * castManifest.ts；运行期播帧只重写精灵 quad 的 UV（全场共享一次纹理上传），
 * 色彩与源卡逐像素一致，无任何量化/转写损耗。
 * 飞鸟/蝴蝶/气泡/路灯/树为手工逐格编写的原创 DSL 点阵（'.' 透明）。
 * 仅借鉴 HD-2D 的公开技法与氛围，不含八方旅人（Octopath Traveler）等
 * 既有游戏的资产或逐像素设计。
 *
 * 环境大纹理（草地/远山/村庄/前景草）在 env/textures.ts；本文件只保留精灵层美术。
 */
import * as THREE from 'three'
import type { PixelFrame } from './sprites'
import { mulberry32 } from './events'
import type { SpriteHandle } from './spriteStage'
import {
  CAST_ART,
  CAST_ATLAS_HEIGHT,
  CAST_ATLAS_WIDTH,
  CAST_FRAMES,
  type CastFrameRect,
} from './castManifest'
import castAtlasUrl from './assets/cast.png?url'

/* ── 卡司图集 ─────────────────────────────────────────────── */

/** 图集动画帧集：等格 cell 序列（离线归一保证同组同尺寸），播帧只给矩形 */
export class CastFrameSet {
  readonly width: number
  readonly height: number
  private readonly rects: CastFrameRect[]

  constructor(keys: readonly string[]) {
    if (!keys.length) throw new Error('CastFrameSet: 至少需要一帧')
    this.rects = keys.map((key) => {
      const rect = CAST_FRAMES[key]
      if (!rect) throw new Error(`CastFrameSet: 图集缺帧 ${key}`)
      return rect
    })
    this.width = this.rects[0]!.w
    this.height = this.rects[0]!.h
    for (const rect of this.rects) {
      if (rect.w !== this.width || rect.h !== this.height) {
        throw new Error('CastFrameSet: 动画帧 cell 尺寸不一致')
      }
    }
  }

  get frameCount(): number {
    return this.rects.length
  }

  frameAt(index: number): CastFrameRect {
    return this.rects[((index % this.rects.length) + this.rects.length) % this.rects.length]!
  }
}

export interface CastActorArt {
  idle: CastFrameSet
  walk: CastFrameSet
  react: CastFrameSet
}

export interface CastArt {
  /** 全卡司共享的图集纹理（模块级缓存，页面生命周期内只解码/上传一次） */
  texture: THREE.Texture
  swordsman: CastActorArt
  scholarF: CastActorArt
  scholarM: CastActorArt
  knight: CastActorArt
  cloak: CastActorArt
  cat: CastActorArt
  dog: CastActorArt
}

let castCache: Promise<CastArt> | null = null

/** 加载卡司图集（清单已烤入 JS，仅异步解码 PNG）；重复调用共享同一 Promise，失败后可重试 */
export const loadCastArt = (): Promise<CastArt> => {
  if (!castCache) {
    castCache = (async () => {
      const image = new Image()
      image.src = castAtlasUrl
      await image.decode()
      const texture = new THREE.Texture(image)
      texture.magFilter = THREE.NearestFilter
      texture.minFilter = THREE.NearestFilter
      texture.generateMipmaps = false
      texture.colorSpace = THREE.SRGBColorSpace
      texture.needsUpdate = true
      const actor = (art: {
        readonly idle: readonly string[]
        readonly walk: readonly string[]
        readonly react: readonly string[]
      }): CastActorArt => ({
        idle: new CastFrameSet(art.idle),
        walk: new CastFrameSet(art.walk),
        react: new CastFrameSet(art.react),
      })
      return {
        texture,
        swordsman: actor(CAST_ART.swordK),
        scholarF: actor(CAST_ART.scholarF),
        scholarM: actor(CAST_ART.scholarM),
        knight: actor(CAST_ART.knightR),
        cloak: actor(CAST_ART.cloakP),
        cat: actor(CAST_ART.petcat),
        dog: actor(CAST_ART.petdog),
      }
    })()
    castCache.catch(() => {
      castCache = null
    })
  }
  return castCache
}

export interface CastSpriteBinding {
  /** 播帧：重写本 quad 克隆几何的 UV；cell 尺寸跨动作不同时同步 quad 缩放（脚底锚点不动） */
  setFrame(rect: CastFrameRect): void
  /** 水平镜像（朝向） */
  setFlip(flip: boolean): void
  /** 当前帧 cell 宽（美术像素） */
  readonly frameW: number
  /** 当前帧 cell 高（美术像素） */
  readonly frameH: number
  /** 释放克隆几何（材质由 spriteStage 的 handle.dispose 负责；图集纹理模块级共享不释放） */
  dispose(): void
}

/**
 * 把图集帧绑到精灵 quad：共享 unitPlane 几何不可逐帧改写（道具/气泡在用），
 * 故克隆一份 4 顶点几何专供本精灵；material.map 恒为同一张图集纹理，
 * 播帧只重写 UV attribute，不触发着色器重编译也不重复上传纹理。
 */
export const bindCastSprite = (
  sprite: SpriteHandle,
  initial: CastFrameRect,
): CastSpriteBinding => {
  const mesh = sprite.mesh
  const geometry = (mesh.geometry as THREE.PlaneGeometry).clone()
  mesh.geometry = geometry
  const uv = geometry.getAttribute('uv') as THREE.BufferAttribute

  let flipped = false
  let frameW = initial.w
  let frameH = initial.h

  const applyScale = (): void => {
    mesh.scale.set(flipped ? -frameW : frameW, frameH, 1)
  }
  const applyUv = (rect: CastFrameRect): void => {
    const u0 = rect.x / CAST_ATLAS_WIDTH
    const u1 = (rect.x + rect.w) / CAST_ATLAS_WIDTH
    const vTop = 1 - rect.y / CAST_ATLAS_HEIGHT
    const vBottom = 1 - (rect.y + rect.h) / CAST_ATLAS_HEIGHT
    // PlaneGeometry 顶点序（translate(0,0.5,0) 后）：0 左上 1 右上 2 左下 3 右下
    uv.setXY(0, u0, vTop)
    uv.setXY(1, u1, vTop)
    uv.setXY(2, u0, vBottom)
    uv.setXY(3, u1, vBottom)
    uv.needsUpdate = true
  }

  applyUv(initial)
  applyScale()

  return {
    setFrame(rect) {
      if (rect.w !== frameW || rect.h !== frameH) {
        frameW = rect.w
        frameH = rect.h
        applyScale()
      }
      applyUv(rect)
    },
    setFlip(flip) {
      if (flip === flipped) return
      flipped = flip
      applyScale()
    },
    get frameW() {
      return frameW
    },
    get frameH() {
      return frameH
    },
    dispose() {
      geometry.dispose()
    },
  }
}

/* ── 组装辅助（道具 DSL 用） ────────────────────────────────── */

/** 点阵块 → PixelFrame：行右补 '.' 到块内最长行（右侧皆为透明像素） */
const mk = (block: string, palette: Record<string, string>): PixelFrame => {
  const rows = block.replace(/^\n+/, '').replace(/\s+$/, '').split('\n')
  const width = Math.max(...rows.map((row) => row.length))
  return { rows: rows.map((row) => row.padEnd(width, '.')), palette }
}

/* ── 飞鸟（12×7，两帧振翅） ───────────────────────────────── */

const BIRD_PALETTE = {
  o: '#26231f',
  f: '#7a9ab8',
  F: '#5a7a98',
  w: '#e8ecf0',
  e: '#26231f',
  a: '#e8a83a', // 喙
}

const BIRD_FLY_A = mk(`
...oo.......
..offfo.....
.oofffefao..
offffffwwo..
.ooFFFoo....
...ooo......
............
`, BIRD_PALETTE)

const BIRD_FLY_B = mk(`
............
............
.oofffefao..
offffffwwo..
.ooofffo....
..ooFFoo....
...oooo.....
`, BIRD_PALETTE)

export const BIRD = { fly: [BIRD_FLY_A, BIRD_FLY_B], width: 12, height: 7 }

/* ── 蝴蝶（6×5，两帧扇翅） ────────────────────────────────── */

const BUTTERFLY_PALETTE = {
  w: '#f0a8c8',
  W: '#d888a8',
  o: '#3a3030',
}

const BUTTERFLY_A = mk(`
ww..ww
wWooWw
.wWwW.
..oo..
...o..
`, BUTTERFLY_PALETTE)

const BUTTERFLY_B = mk(`
.wWWw.
.wWWw.
..oo..
...o..
...o..
`, BUTTERFLY_PALETTE)

export const BUTTERFLY = { fly: [BUTTERFLY_A, BUTTERFLY_B], width: 6, height: 5 }

/* ── 对话气泡（16×14：'!' / '…' / '♪'） ───────────────────── */

const BUBBLE_PALETTE = {
  o: '#23211d',
  f: '#fffdf6',
  i: '#23211d',
}

const bubbleRows = (glyph: string[]): PixelFrame => mk(`
.....oooooooo.....
...ooffffffffoo...
..offffffffffffo..
.${glyph[0]}
.${glyph[1]}
.${glyph[2]}
.${glyph[3]}
.${glyph[4]}
..offffffffffffo..
...ooffffffffoo...
....ooo.........
....o...........
.................
................`, BUBBLE_PALETTE)

export const BUBBLE_EXCLAIM = bubbleRows([
  'offffffiffffffo.',
  'offffffiffffffo.',
  'offffffiffffffo.',
  'offfffffffffffo.',
  'offffffiffffffo.',
])

export const BUBBLE_DOTS = bubbleRows([
  'offfffffffffffo.',
  'offfiffiffifffo.',
  'offfffffffffffo.',
  'offfffffffffffo.',
  'offfffffffffffo.',
])

export const BUBBLE_NOTE = bubbleRows([
  'offfffffiiiiffo.',
  'offffffffiffffo.',
  'offffffffiffffo.',
  'offffiiiiiffffo.',
  'offffiiiiiffffo.',
])

export const BUBBLES = { exclaim: BUBBLE_EXCLAIM, dots: BUBBLE_DOTS, note: BUBBLE_NOTE }

/* ── 路灯柱（14×36 白底 alpha 剪影，材质色 = lampPost；灯芯另由环境层 HDR 叠加） ── */

const SILHOUETTE_PALETTE = { x: '#ffffff', d: '#ffffff80' }

export const LAMP_POST: PixelFrame = mk(`
.....xxxx.....
....xxxxxx....
...xxxxxxxx...
...xxxxxxxx...
....xxxxxx....
....xx..xx....
....xx..xx....
....xx..xx....
....xx..xx....
....xxxxxx....
.....xxxx.....
......xx......
......xx......
......xx......
......xx......
......xx......
......xx......
......xx......
......xx......
......xx......
......xx......
......xx......
......xx......
......xx......
......xx......
......xx......
......xx......
......xx......
......xx......
......xx......
......xx......
......xx......
....xxxxxx....
...xxxxxxxx...
...xxxxxxxx...
..xxxxxxxxxx..
`, SILHOUETTE_PALETTE)

/* ── 树（叶 46×56 + 干 10×30，白底 alpha 剪影；边缘 50% 抖动） ── */

export const TREE_TRUNK: PixelFrame = mk(`
....xx......
....xx......
....xxx.....
....xx.x....
....xx..x...
....xx......
....xx......
...xxx......
...xx.......
...xx...x...
...xx..x....
...xx.......
...xx.......
...xx.......
...xxx......
....xx......
....xx......
....xx......
....xx......
....xx......
....xx......
....xx......
....xx......
....xx......
....xxx.....
....xxxxx...
...xxxxxx...
..xxxxxxxx..
..xxxxxxxx..
..xxxxxxxx..
`, SILHOUETTE_PALETTE)

/** 树冠：实心团块 + 底部/右缘有序抖动（50% alpha），内部稀疏抖点模拟叶簇 */
const canopy = (seed: number): PixelFrame => {
  const rng = mulberry32(seed)
  const width = 46
  const height = 56
  const centerX = 22.5
  const rowsOut: string[] = []
  // 每行半宽：顶部窄、中部宽、底部略收
  for (let y = 0; y < height; y++) {
    const t = y / (height - 1)
    const bulge = Math.sin(Math.min(t * 1.35, 1) * Math.PI) // 0→1→(底收)
    let half = Math.round(6 + bulge * 15)
    if (y > height - 9) half = Math.max(3, half - (y - (height - 9)) * 2)
    const left = Math.max(0, Math.round(centerX - half))
    const right = Math.min(width - 1, Math.round(centerX + half))
    let row = ''
    for (let x = 0; x < width; x++) {
      if (x < left || x > right) {
        row += '.'
        continue
      }
      const edge = x === left || x === right || y >= height - 6
      const clump = rng() < 0.09
      row += edge ? ((x + y) % 2 === 0 ? 'd' : 'x') : clump ? 'd' : 'x'
    }
    rowsOut.push(row)
  }
  return { rows: rowsOut, palette: SILHOUETTE_PALETTE }
}

export const TREE_LEAF_A = canopy(0x7a11)
export const TREE_LEAF_B = canopy(0x5e3d)
