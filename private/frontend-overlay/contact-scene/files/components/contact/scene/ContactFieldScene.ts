/**
 * HD-2D 透视原野编排器（八方旅人技法复刻的组装层；仅复刻技法与氛围，
 * 全部精灵/纹理/代码均为本项目原创，无任何原作资产）。
 *
 * 架构：环境层（透视相机真深度 + bokeh 景深 + bloom，见 env/envStage）
 * 与精灵层（低分整数美术格，见 spriteStage）由 replicaPipeline 双通道合成；
 * 本层只回答「谁在哪、何时演什么」：
 * - 卡司为 AI 抽卡原图经离线管线打包的图集（cast.png + castManifest.ts，见 spriteArt），
 *   异步解码完成后登场（环境层/道具/鸟蝶先行上屏；加载失败静默降级为无卡司场景），
 *   播帧 = 重写精灵 quad 克隆几何的 UV，全场共享一次图集纹理上传；
 * - 角色控制器域沿用旧正交版的虚拟像素语义（±(lowW/2−26)、26px/s、
 *   startXRatio×lowW），经 k = 焦点深度可视半宽/(lowW/2) 映射成世界单位，
 *   再投影回整数美术格摆放精灵——actors/events 两纯模块零改动；
 * - 昼夜：uDay 恒速 1.8s 扫掠，env.setDay + 精灵 PaletteRegistry 双路应用；
 * - 事件时间线/点灯闪烁/环境鸟蝶/hover·press 反应与旧版逐一对应（行为零回归）；
 * - 指针视差 = 相机微移（±0.45u），投影在相机更新之后逐帧重算，
 *   静态道具（灯/树）精灵因此每帧随相机重投影而不与环境层脱节。
 */
import * as THREE from 'three'
import { ActorController, type BubbleKind } from './actors'
import { DAY_NIGHT_THRESHOLD, FieldEventScheduler, mulberry32 } from './events'
import { FieldInteractions, type FieldInteractionTarget } from './interactions'
import { PaletteRegistry } from './palette'
import { computePixelScale } from './pixelPipeline'
import { createReplicaPipeline, shouldDegrade, type ReplicaPipeline } from './replicaPipeline'
import { disposeUnitPlane, FrameSet, frameToTexture, validateFrame } from './sprites'
import { createSpriteStage, SPRITE_LAYER, type SpriteHandle } from './spriteStage'
import {
  createEnvStage,
  ENV_CAMERA,
  FOCUS_DISTANCE,
  STAGE_Z,
  type LampEnvHandle,
} from './env/envStage'
import { artRectToCss, visibleHalfWidthAt, worldToArt, type CssRect } from './project'
import {
  BIRD,
  BUBBLES,
  BUTTERFLY,
  LAMP_POST,
  bindCastSprite,
  loadCastArt,
  type CastActorArt,
  type CastSpriteBinding,
} from './spriteArt'
import { loadEnvArt } from './env/envArt'

/** 主题切换扫掠时长（秒），恒定速率 */
export const DAY_SWEEP_SECONDS = 1.8

const BLOOM_DAY = 0.15
const BLOOM_NIGHT = 0.55

/** 行走域边距（虚拟像素，沿用旧版数值） */
const WALK_MARGIN = 26

/* ── 类型 ── */

export type FieldTheme = 'light' | 'dark'

export interface FieldSceneOptions {
  canvas: HTMLCanvasElement
  /** 指针交互附着点（.contact-hero） */
  host: HTMLElement
  /** 边缘融合目标色（--contact-scene-bg 解析值） */
  paper: string
  theme: FieldTheme
  reducedMotion: boolean
}

export interface FieldSceneHandle {
  /** 切换主题（触发 1.8s 恒速扫掠）与纸色（边缘融合/清屏） */
  setTheme(theme: FieldTheme, paper: string): void
  /** 指针视差，归一化 -1..1 */
  setPointer(nx: number, ny: number): void
  resize(cssWidth: number, cssHeight: number): void
  start(): void
  stop(): void
  /** reduced-motion 用：静态渲染单帧 */
  renderOnce(): void
  dispose(): void
  readonly running: boolean
}

interface ActorVisual {
  controller: ActorController
  sprite: SpriteHandle
  /** 图集帧绑定（UV 播帧 + 朝向镜像 + 跨动作 cell 尺寸同步） */
  binding: CastSpriteBinding
  frames: CastActorArt
  /** 行走带内的世界深度（决定投影缩放的唯一纵深量） */
  z: number
  shadowScale: number
  shadow: THREE.Mesh
  bubble: SpriteHandle
  bubbleShownAt: number
  lastBubble: BubbleKind | null
  /** 交互命中矩形（逐帧原地覆写，见 interactions） */
  hitRect: CssRect
  target: FieldInteractionTarget
}

interface LampVisual {
  env: LampEnvHandle
  sprite: SpriteHandle
  shadow: THREE.Mesh
  ratio: number
  /** 灯的世界 x（resize 重算） */
  worldX: number
  /** 事件域（虚拟像素）x = worldX / k */
  virtualX: number
  lit: number
  flickerAt: number | null
  fadeOutAt: number | null
}

/**
 * 中景树（私有 overlay）：本体是环境层 AI 纹理 billboard（见 envStage），
 * 精灵层 DSL 干/冠已退役；这里只保留地面方向影，位置须与 envStage 的
 * 树槽位 ratio/z 一致
 */
interface TreeShadowVisual {
  ratio: number
  z: number
  shadow: THREE.Mesh
  shadowScale: number
}

export const createFieldScene = (opts: FieldSceneOptions): FieldSceneHandle | null => {
  const disposables: Array<{ dispose(): void }> = []
  let pipeline: ReplicaPipeline | null = null
  try {
    return boot(opts, disposables, (created) => {
      pipeline = created
    })
  } catch {
    // Canvas 2D / WebGL2 不可用、纹理创建失败等：清理后回退静态兜底
    for (const disposable of disposables.splice(0)) disposable.dispose()
    if (pipeline) (pipeline as ReplicaPipeline).renderer.forceContextLoss()
    disposeUnitPlane()
    return null
  }
}

const boot = (
  opts: FieldSceneOptions,
  disposables: Array<{ dispose(): void }>,
  onPipeline: (pipeline: ReplicaPipeline) => void,
): FieldSceneHandle => {
  const env = createEnvStage()
  disposables.push(env)

  const spritePalette = new PaletteRegistry()
  disposables.push(spritePalette)
  const sprites = createSpriteStage(spritePalette)
  disposables.push(sprites)

  /* 移动端/窄屏降质（弱散景、低环境分辨率） */
  const initialWidth = opts.host.clientWidth || opts.canvas.clientWidth || 320
  const initialHeight = opts.host.clientHeight || opts.canvas.clientHeight || 240
  const coarsePointer =
    typeof window.matchMedia === 'function' && window.matchMedia('(pointer: coarse)').matches
  const quality: 'high' | 'low' = coarsePointer || initialWidth < 640 ? 'low' : 'high'

  const pipeline = createReplicaPipeline({
    canvas: opts.canvas,
    envScene: env.scene,
    envCamera: env.camera,
    spriteScene: sprites.scene,
    spriteCamera: sprites.camera,
    paper: opts.paper,
    focus: FOCUS_DISTANCE,
    quality,
  })
  disposables.push(pipeline)
  onPipeline(pipeline)

  const scheduler = new FieldEventScheduler()
  const rng = mulberry32(0xa16d)

  /* ── 状态 ── */
  let uDay = opts.theme === 'dark' ? 0 : 1
  let targetDay = uDay
  /** 虚拟像素 → 世界单位（焦点深度可视半宽 / 虚拟半宽） */
  let worldPerVirtual = 0.05
  /** 焦点深度的 美术像素/世界单位（resize 重算；精灵随纵深透视缩放的基准） */
  let artPerWorldFocus = 1
  const pointer = { x: 0, y: 0 }
  const pointerTarget = { x: 0, y: 0 }
  let elapsed = 0
  let lastFrameAt: number | null = null
  let rafId: number | null = null
  let running = false
  /** dispose 后图集才解码完成时禁止再生成卡司（材质/几何会漏进已销毁的舞台） */
  let disposed = false
  // 自适应降级状态：EMA 帧耗（未钳制的真实 RAF 间隔）与已见帧数
  let frameEmaMs = 0
  let framesSeen = 0
  let nextAmbientBirdAt = 12

  const scratchWorld = new THREE.Vector3()

  /** 世界锚点 → 整数美术格（相机视差微移后调用） */
  const projectFeet = (worldX: number, z: number): { x: number; y: number; inside: boolean } => {
    scratchWorld.set(worldX, 0, z)
    return worldToArt(env.camera, sprites.grid, scratchWorld)
  }

  /* ── 气泡纹理（三枚共用，逐 actor 一个精灵） ── */
  const bubbleTextures: Record<BubbleKind, THREE.Texture> = {
    exclaim: frameToTexture(BUBBLES.exclaim) as THREE.Texture,
    dots: frameToTexture(BUBBLES.dots) as THREE.Texture,
    note: frameToTexture(BUBBLES.note) as THREE.Texture,
  }
  for (const texture of Object.values(bubbleTextures)) {
    if (!texture) throw new Error('Canvas 2D 不可用')
    disposables.push(texture)
  }
  const bubbleSize = validateFrame(BUBBLES.dots)

  /* ── 道具：路灯 ×3（环境层光晕/灯芯/光池 + 精灵层柱身 + 方向影） ── */
  const lamps: LampVisual[] = []
  const lampSize = validateFrame(LAMP_POST)
  const lampTexture = frameToTexture(LAMP_POST)
  if (!lampTexture) throw new Error('Canvas 2D 不可用')
  disposables.push(lampTexture)

  for (const ratio of [-0.28, 0.03, 0.31]) {
    const envLamp = env.addLamp(ratio)
    const sprite = sprites.addSprite(lampTexture, lampSize.width, lampSize.height, 'lampPost')
    const shadow = env.acquireShadow()
    lamps.push({
      env: envLamp,
      sprite,
      shadow,
      ratio,
      worldX: 0,
      virtualX: 0,
      lit: uDay >= DAY_NIGHT_THRESHOLD ? 0 : 1,
      flickerAt: null,
      fadeOutAt: null,
    })
  }

  /* ── 中景树地面影（树本体 = 环境层 AI billboard，位置镜像 envStage 槽位） ── */
  const treeShadows: TreeShadowVisual[] = [
    { ratio: -0.4, z: -4.5, shadowScale: 1.9 },
    { ratio: 0.44, z: -3.2, shadowScale: 1.5 },
    { ratio: 0.8, z: -6.5, shadowScale: 1.3 },
  ].map((spec) => ({ ...spec, shadow: env.acquireShadow() }))

  /* ── 角色 ── */
  const actors: ActorVisual[] = []
  /** 卡司名册：图集解码完成后填充；事件/点灯回调须防御卡司未登场（或加载失败） */
  const cast: Partial<
    Record<
      'knight' | 'scholarM' | 'swordsman' | 'cloak' | 'scholarF' | 'cat' | 'dog',
      ActorVisual
    >
  > = {}

  const spawnActor = (
    art: CastActorArt,
    castTexture: THREE.Texture,
    startXRatio: number,
    z: number,
    shadowScale: number,
    spec: {
      walkSpeed?: number
      fleeSpeed?: number
      idleFrameMs?: number
      walkFrameMs?: number
      reactFrameMs?: number
    } = {},
  ): ActorVisual => {
    const sprite = sprites.addSprite(
      castTexture,
      art.idle.width,
      art.idle.height,
      'actorNightTint',
    )
    const binding = bindCastSprite(sprite, art.idle.frameAt(0))
    disposables.push(binding)
    const bubble = sprites.addSprite(bubbleTextures.dots, bubbleSize.width, bubbleSize.height)
    bubble.setVisible(false)
    const shadow = env.acquireShadow()

    const controller = new ActorController(0, {
      idleFrameCount: art.idle.frameCount,
      walkFrameCount: art.walk.frameCount,
      reactFrameCount: art.react.frameCount,
      walkSpeed: spec.walkSpeed,
      fleeSpeed: spec.fleeSpeed,
      idleFrameMs: spec.idleFrameMs,
      walkFrameMs: spec.walkFrameMs,
      reactFrameMs: spec.reactFrameMs,
      rng,
    })
    controller.teleport(startXRatio * sprites.grid.lowW, 0)

    const visual: ActorVisual = {
      controller,
      sprite,
      binding,
      frames: art,
      z,
      shadowScale,
      shadow,
      bubble,
      bubbleShownAt: -1,
      lastBubble: null,
      hitRect: { left: 0, top: 0, width: 0, height: 0 },
      target: { rect: null, onHover: null, onPress: null },
    }
    visual.target.rect = visual.hitRect
    actors.push(visual)
    return visual
  }

  /* ── 飞鸟（事件生成，平时隐藏）与蝴蝶（常驻 8 字舞），纯美术格坐标 ── */
  const birdFrames = new FrameSet(BIRD.fly)
  disposables.push(birdFrames)
  const bird = sprites.addSprite(
    birdFrames.textureAt(0),
    birdFrames.width,
    birdFrames.height,
    'actorNightTint',
  )
  bird.setVisible(false)
  const birdState = { active: false, x: 0, y: 0, vx: 0 }

  const butterflyFrames = new FrameSet(BUTTERFLY.fly)
  disposables.push(butterflyFrames)
  const butterfly = sprites.addSprite(
    butterflyFrames.textureAt(0),
    butterflyFrames.width,
    butterflyFrames.height,
    'actorNightTint',
  )
  const butterflyState = { x: 0, fleeUntil: -1, fleeDir: 1 as 1 | -1 }

  /** 精灵在当前深度的透视缩放：该深度 美术像素/世界单位 ÷ 焦点深度基准（钳制防极端视口失真） */
  const depthScale = (worldX: number, z: number, artYGround: number): number => {
    const oneUp = worldToArt(env.camera, sprites.grid, scratchWorld.set(worldX, 1, z))
    const k = (oneUp.y - artYGround) / artPerWorldFocus
    return Math.min(1.35, Math.max(0.7, k))
  }

  /* ── 摆位：静态道具逐帧随相机视差重投影 ── */
  const placeLamp = (lamp: LampVisual): void => {
    const art = projectFeet(lamp.worldX, STAGE_Z.lamp)
    const k = depthScale(lamp.worldX, STAGE_Z.lamp, art.y)
    lamp.sprite.setPosition(art.x, art.y)
    lamp.sprite.setOrder(art.y, SPRITE_LAYER.props)
    // 灯柱精灵随所在深度缩放（与角色同一透视规律）；无翻转，直写 scale
    lamp.sprite.mesh.scale.set(lampSize.width * k, lampSize.height * k, 1)
    env.placeShadow(lamp.shadow, lamp.worldX, STAGE_Z.lamp, 0.7)
  }

  const placeStatics = (): void => {
    for (const lamp of lamps) placeLamp(lamp)
    for (const tree of treeShadows) {
      env.placeShadow(tree.shadow, env.worldXAt(tree.ratio, tree.z), tree.z, tree.shadowScale)
    }
  }

  /* ── 相机视差微移（投影之前调用；lookAt 随动保持俯角） ── */
  const applyCameraNudge = (): void => {
    env.camera.position.set(
      ENV_CAMERA.position.x + pointer.x * 0.45,
      ENV_CAMERA.position.y + pointer.y * 0.18,
      ENV_CAMERA.position.z,
    )
    env.camera.lookAt(
      ENV_CAMERA.lookAt.x + pointer.x * 0.9,
      ENV_CAMERA.lookAt.y,
      ENV_CAMERA.lookAt.z,
    )
    env.camera.updateMatrixWorld(true)
  }

  /* ── 帧同步 ── */
  const walkBounds = (): { min: number; max: number } => ({
    min: -(sprites.grid.lowW / 2 - WALK_MARGIN),
    max: sprites.grid.lowW / 2 - WALK_MARGIN,
  })

  const syncActor = (visual: ActorVisual, now: number, dt: number): void => {
    const snapshot = visual.controller.update(now, dt, walkBounds())
    const frames =
      snapshot.state === 'walk'
        ? visual.frames.walk
        : snapshot.state === 'react'
          ? visual.frames.react
          : visual.frames.idle
    visual.binding.setFrame(frames.frameAt(snapshot.frame))
    // 图集帧全部面朝左（抽卡素材原生朝向），向右走须水平镜像——
    // 与 DSL 道具（蝴蝶等面朝右）的翻转极性相反，勿对齐
    visual.binding.setFlip(snapshot.facing > 0)

    const worldX = snapshot.x * worldPerVirtual
    const art = projectFeet(worldX, visual.z)
    visual.sprite.setPosition(art.x, art.y)
    visual.sprite.setOrder(art.y, SPRITE_LAYER.actors)
    env.placeShadow(visual.shadow, worldX, visual.z, visual.shadowScale)

    // 透视缩放：同一行走带上近大远小（八方式地面纵深的关键信号）。
    // binding 的 applyScale 只写未缩放 cell 尺寸，这里在其后覆写为 cell×zScale
    // （含朝向镜像的负 x），脚底锚点由几何 translate 保证不动
    const zScale = depthScale(worldX, visual.z, art.y)
    const scaledW = visual.binding.frameW * zScale
    const scaledH = visual.binding.frameH * zScale
    visual.sprite.mesh.scale.set(snapshot.facing > 0 ? -scaledW : scaledW, scaledH, 1)

    // 命中矩形（≥18 美术像素，底部对齐脚部锚点；跟随当前帧 cell 尺寸与透视缩放）
    const hitW = Math.max(scaledW, 18)
    const hitH = Math.max(scaledH, 18)
    const css = artRectToCss(sprites.grid, art.x - hitW / 2, art.y, hitW, hitH)
    visual.hitRect.left = css.left
    visual.hitRect.top = css.top
    visual.hitRect.width = css.width
    visual.hitRect.height = css.height

    if (snapshot.bubble) {
      if (snapshot.bubble !== visual.lastBubble) {
        visual.lastBubble = snapshot.bubble
        visual.bubble.setFrame(bubbleTextures[snapshot.bubble])
        visual.bubbleShownAt = now
      }
      visual.bubble.setVisible(true)
      // 弹出动画：120ms 内 0.75 → 1（气泡永不翻转，直接改 mesh.scale）
      const pop = now - visual.bubbleShownAt < 0.12 ? 0.75 : 1
      visual.bubble.mesh.scale.set(bubbleSize.width * pop, bubbleSize.height * pop, 1)
      const bx = art.x + snapshot.facing * 4 * zScale
      const by = art.y + scaledH + 2
      visual.bubble.setPosition(bx, by)
      visual.bubble.setOrder(by, SPRITE_LAYER.bubbles)
    } else {
      visual.bubble.setVisible(false)
      visual.lastBubble = null
    }
  }

  const placeButterfly = (now: number): void => {
    const lowW = sprites.grid.lowW
    const lowH = sprites.grid.lowH
    const fleeActive = now < butterflyState.fleeUntil
    const fleeOffset = fleeActive ? butterflyState.fleeDir * 10 : 0
    // 域与旧版一致：中心坐标系（±lowW/2），与猫控制器同域；上屏时 +lowW/2 换到美术格
    const prevX = butterflyState.x
    const bx = 0.16 * lowW + Math.sin(now * 0.7) * 12 + fleeOffset
    butterflyState.x = bx
    const by = 0.3 * lowH + Math.sin(now * 1.4) * 5
    butterfly.setPosition(bx + lowW / 2, by)
    butterfly.setFlip(bx < prevX)
    butterfly.setFrame(butterflyFrames.textureAt(Math.floor(now * 10) % 2))
    butterfly.setOrder(by, SPRITE_LAYER.actors)
  }

  const spawnBird = (): void => {
    const lowW = sprites.grid.lowW
    const lowH = sprites.grid.lowH
    birdState.active = true
    birdState.x = -(lowW / 2) - 12
    birdState.y = lowH * (0.6 + rng() * 0.15)
    birdState.vx = 26 + rng() * 10
    bird.setVisible(true)
  }

  const syncBird = (dt: number): void => {
    if (!birdState.active) return
    birdState.x += birdState.vx * dt
    const lowW = sprites.grid.lowW
    const y = birdState.y + Math.sin(elapsed * 3) * 2
    bird.setPosition(birdState.x + lowW / 2, y)
    bird.setFrame(birdFrames.textureAt(Math.floor(elapsed * 8) % 2))
    bird.setOrder(y, SPRITE_LAYER.actors)
    if (birdState.x > lowW / 2 + 12) {
      birdState.active = false
      bird.setVisible(false)
    }
  }

  /* ── 点灯/熄灯 ── */
  const tickLamps = (now: number, dt: number): void => {
    for (const lamp of lamps) {
      if (lamp.flickerAt !== null && now >= lamp.flickerAt) {
        // 点火闪烁：0 → 0.7 → 0.25 → 0.85 → 1（240ms）
        const t = (now - lamp.flickerAt) / 0.24
        lamp.lit = t >= 1 ? 1 : t < 0.25 ? 0.7 : t < 0.5 ? 0.25 : t < 0.75 ? 0.85 : 1
        if (t >= 1) lamp.flickerAt = null
      } else if (lamp.fadeOutAt !== null) {
        lamp.lit = Math.max(0, lamp.lit - dt / 0.2)
        if (lamp.lit <= 0) lamp.fadeOutAt = null
      }
      lamp.env.setGlow(lamp.lit)
    }
  }

  const lampsOn = (now: number): void => {
    lamps.forEach((lamp, index) => {
      lamp.flickerAt = now + index * 0.3
      lamp.fadeOutAt = null
    })
    const mid = lamps[1]
    const cloak = cast.cloak
    if (!cloak) return
    if (mid) cloak.controller.walkTo(mid.virtualX - 5)
    cloak.controller.showBubble(now + 1.0, 'note', 1200)
  }

  const lampsOff = (): void => {
    for (const lamp of lamps) {
      lamp.fadeOutAt = elapsed
      lamp.flickerAt = null
    }
    spawnBird()
  }

  const handleEvent = (kind: string, now: number): void => {
    switch (kind) {
      case 'kid-merchant-meet': {
        const { knight, swordsman } = cast
        if (!knight || !swordsman) break
        knight.controller.walkTo(swordsman.controller.renderX - 12)
        swordsman.controller.faceTowards(knight.controller.renderX)
        swordsman.controller.showBubble(now + 1.4, 'dots', 1300)
        knight.controller.showBubble(now + 2.8, 'note', 1300)
        swordsman.controller.showBubble(now + 4.2, 'exclaim', 1200)
        break
      }
      case 'elder-lamp-visit': {
        const lamp = lamps[0]
        const scholarM = cast.scholarM
        if (!scholarM) break
        if (lamp) scholarM.controller.walkTo(lamp.virtualX - 6)
        scholarM.controller.showBubble(now + 2.2, 'dots', 1400)
        break
      }
      case 'cat-chase-butterfly': {
        // 蝴蝶域 = 中心坐标系（±lowW/2），与猫控制器同域
        const cat = cast.cat
        if (!cat) break
        cat.controller.walkTo(butterflyState.x)
        butterflyState.fleeUntil = now + 1.6
        butterflyState.fleeDir = butterflyState.x > cat.controller.renderX ? 1 : -1
        break
      }
      case 'dog-follow-traveler': {
        const dog = cast.dog
        const cloak = cast.cloak
        if (!dog || !cloak) break
        dog.controller.walkTo(cloak.controller.renderX + 8 * cloak.controller.facingSign)
        break
      }
    }
  }

  /* ── 尺寸/布局 ── */
  const resize = (cssWidth: number, cssHeight: number): void => {
    const scale = computePixelScale(cssHeight)
    env.resize(cssWidth, cssHeight)
    sprites.resize(cssWidth, cssHeight, scale)
    pipeline.setSize(cssWidth, cssHeight, sprites.grid)
    // 虚拟像素 → 世界单位换算率（焦点深度 = 行走带中心）
    worldPerVirtual = visibleHalfWidthAt(env.camera, FOCUS_DISTANCE) / (sprites.grid.lowW / 2)
    // 焦点深度换算基准（精灵透视缩放的 1.0 点）
    const focusGround = worldToArt(env.camera, sprites.grid, scratchWorld.set(0, 0, STAGE_Z.path))
    const focusUp = worldToArt(env.camera, sprites.grid, scratchWorld.set(0, 1, STAGE_Z.path))
    artPerWorldFocus = Math.max(1, focusUp.y - focusGround.y)
    // 灯的世界/事件域坐标（布局比例 × 该深度可视宽，与视口解耦）
    for (const lamp of lamps) {
      lamp.worldX = env.worldXAt(lamp.ratio, STAGE_Z.lamp)
      lamp.virtualX = lamp.worldX / worldPerVirtual
      // 环境层 halo/灯芯对齐精灵灯笼中心：灯笼在脚部锚点上 33 美术像素（灯柱精灵
      // 已按所在深度缩放，世界高 = 33×k/artPerWorld(lampZ) = 33/焦点基准）
      lamp.env.setHeadWorldY(33 / artPerWorldFocus)
    }
    // 循环停止时（reduced-motion / 离屏 / 首帧前）重绘静帧，resize 不留旧画面
    if (!running) renderOnce()
  }

  /* ── 交互 ── */
  const interactions = new FieldInteractions({
    camera: env.camera,
    dom: opts.host,
    isUiEvent: (event) =>
      event.target instanceof Element &&
      Boolean(event.target.closest('.entry-item, a, button')),
  })
  disposables.push(interactions)

  /* ── 帧循环 ── */
  const frame = (nowMs: number): void => {
    if (!running) return
    rafId = null
    const now = nowMs / 1000
    const rawDtMs = lastFrameAt === null ? 0 : (now - lastFrameAt) * 1000
    const dt = lastFrameAt === null ? 1 / 60 : Math.min(now - lastFrameAt, 0.1)
    lastFrameAt = now
    elapsed += dt
    if (rawDtMs > 0) {
      frameEmaMs = framesSeen === 0 ? rawDtMs : frameEmaMs * 0.92 + rawDtMs * 0.08
      framesSeen++
      // 软渲染/弱 GPU 兜底：持续超帧耗预算 → 管线一次性降档
      if (shouldDegrade(frameEmaMs, framesSeen)) pipeline.degrade()
    }

    // 昼夜扫掠（恒速）
    if (uDay !== targetDay) {
      const step = dt / DAY_SWEEP_SECONDS
      const diff = targetDay - uDay
      uDay = Math.abs(diff) <= step ? targetDay : uDay + Math.sign(diff) * step
    }
    const toggle = scheduler.checkDayCrossing(uDay)
    if (toggle === 'lamps-on') lampsOn(elapsed)
    else if (toggle === 'lamps-off') lampsOff()

    env.setDay(uDay)
    spritePalette.apply(uDay)
    env.setPointer(pointer.x, pointer.y)
    env.tick(elapsed)
    pipeline.setBloom(BLOOM_DAY + (BLOOM_NIGHT - BLOOM_DAY) * (1 - uDay))

    for (const kind of scheduler.tick(elapsed)) handleEvent(kind, elapsed)

    if (elapsed >= nextAmbientBirdAt) {
      spawnBird()
      nextAmbientBirdAt = elapsed + 47 + rng() * 8
    }

    // 指针平滑（沿用旧版 0.06 趋近）→ 相机微移 → 全部投影
    pointer.x += (pointerTarget.x - pointer.x) * 0.06
    pointer.y += (pointerTarget.y - pointer.y) * 0.06
    applyCameraNudge()

    placeStatics()
    for (const visual of actors) syncActor(visual, elapsed, dt)
    syncBird(dt)
    placeButterfly(elapsed)
    tickLamps(elapsed, dt)

    pipeline.render()

    if (running) rafId = requestAnimationFrame(frame)
  }

  const start = (): void => {
    if (running) return
    running = true
    lastFrameAt = null
    rafId = requestAnimationFrame(frame)
  }

  const stop = (): void => {
    running = false
    if (rafId !== null) {
      cancelAnimationFrame(rafId)
      rafId = null
    }
  }

  const renderOnce = (): void => {
    env.setDay(uDay)
    spritePalette.apply(uDay)
    pipeline.setBloom(BLOOM_DAY + (BLOOM_NIGHT - BLOOM_DAY) * (1 - uDay))
    // 静帧跳变：灯火与昼夜侧直接对齐，不播点灯动画
    for (const lamp of lamps) {
      lamp.flickerAt = null
      lamp.fadeOutAt = null
      lamp.lit = uDay >= DAY_NIGHT_THRESHOLD ? 0 : 1
    }
    tickLamps(elapsed, 0)
    applyCameraNudge()
    placeStatics()
    for (const visual of actors) syncActor(visual, elapsed, 0)
    placeButterfly(elapsed)
    env.tick(elapsed)
    pipeline.render()
  }

  /* ── 初始化（先 resize 定美术格与换算率；卡司待图集解码完成再登场） ── */
  resize(initialWidth, initialHeight)

  void loadCastArt()
    .then((castArt) => {
      if (disposed) return
      const texture = castArt.texture
      // 纵深摆位（八方地面读法）：旅人+狗在近景、猫前景游走、骑士/剑士
      // 居中带、双学者远带贴近灯列；透视缩放由 syncActor 按 z 逐帧施加
      const knight = spawnActor(castArt.knight, texture, -0.18, -1.0, 0.75)
      const scholarM = spawnActor(castArt.scholarM, texture, 0.24, -2.1, 0.85, {
        walkSpeed: 16,
      })
      const swordsman = spawnActor(castArt.swordsman, texture, 0.13, -0.6, 1.0, {
        walkSpeed: 18,
      })
      const cloak = spawnActor(castArt.cloak, texture, -0.36, 1.4, 0.85)
      const scholarF = spawnActor(castArt.scholarF, texture, -0.02, -1.6, 0.8, {
        walkSpeed: 17,
      })
      const cat = spawnActor(castArt.cat, texture, 0.34, 0.3, 0.5, {
        walkSpeed: 20,
        fleeSpeed: 70,
        idleFrameMs: 420,
        walkFrameMs: 160,
        reactFrameMs: 110,
      })
      const dog = spawnActor(castArt.dog, texture, -0.06, 1.9, 0.6, {
        walkSpeed: 24,
        idleFrameMs: 360,
        reactFrameMs: 200,
      })
      cast.knight = knight
      cast.scholarM = scholarM
      cast.swordsman = swordsman
      cast.cloak = cloak
      cast.scholarF = scholarF
      cast.cat = cat
      cast.dog = dog

      if (!opts.reducedMotion) {
        for (const visual of [knight, scholarM, swordsman, cloak, scholarF]) {
          visual.target.onHover = (point) => {
            visual.controller.faceTowards(point.x / worldPerVirtual)
            visual.controller.react(elapsed, 600, rng() < 0.5 ? 'dots' : 'note')
          }
          visual.target.onPress = (point) => {
            visual.controller.faceTowards(point.x / worldPerVirtual)
            visual.controller.react(elapsed, 800, 'exclaim')
          }
          interactions.register(visual.target)
        }
        cat.target.onHover = () => cat.controller.react(elapsed, 500, 'dots')
        cat.target.onPress = (point) => cat.controller.fleeFrom(point.x / worldPerVirtual, elapsed)
        interactions.register(cat.target)
        dog.target.onHover = () => dog.controller.showBubble(elapsed, 'note', 900)
        dog.target.onPress = () => dog.controller.react(elapsed, 600, 'dots')
        interactions.register(dog.target)
      }

      // 静帧模式（reduced-motion/离屏首帧）补绘一帧让卡司立刻可见
      if (!running) renderOnce()
    })
    .catch(() => {
      // 图集加载失败：环境层/道具/鸟蝶仍在运行，静默降级为无卡司场景
    })

  // AI 环境纹理在 envStage 内完成换装（注册更早，同一 Promise 回调序保证换装先行）；
  // 这里只在静帧模式（reduced-motion/未启动）补绘一帧让换装立刻可见
  void loadEnvArt()
    .then(() => {
      if (disposed) return
      if (!running) renderOnce()
    })
    .catch(() => {
      // 环境素材加载失败：程序化稿兜底，无需打扰
    })

  placeButterfly(0)
  env.setDay(uDay)
  spritePalette.apply(uDay)
  renderOnce()

  return {
    setTheme(theme, paper) {
      targetDay = theme === 'dark' ? 0 : 1
      pipeline.setPaper(paper)
      // 循环停止时（reduced-motion / 离屏 / 首帧前）直接跳变，保证静帧也是正确场景
      if (opts.reducedMotion || !running) {
        uDay = targetDay
        renderOnce()
      }
    },
    setPointer(nx, ny) {
      pointerTarget.x = nx
      pointerTarget.y = ny
    },
    resize,
    start,
    stop,
    renderOnce,
    get running() {
      return running
    },
    dispose() {
      stop()
      disposed = true
      for (const disposable of disposables.splice(0)) disposable.dispose()
      pipeline.renderer.forceContextLoss()
      disposeUnitPlane()
    },
  }
}
