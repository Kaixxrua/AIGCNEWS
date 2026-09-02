/**
 * 像素原野编排器：正交机位 2.5D 侧视场景。
 * - 世界单位 = 低分缓冲美术像素（相机可视高 = lowH → 精灵 1:1 贴像素格）；
 * - 全材质 depthTest/Write:false，画家算法靠 renderOrder 分层：
 *   天空 shader → 远山 → 树线 → 远地面 → 小径 → 近地面 → 道具/角色 → 前景草；
 * - 昼夜：uDay 0..1 恒速 1.8s 扫掠，PaletteRegistry 仅在 uDay 变化时重写色；
 * - 事件：FieldEventScheduler 循环时间线 + 黄昏错峰点灯（下穿 0.5 恰一次）；
 * - 剪影层 = 白底 alpha 纹理 + material.color 逐帧改色（昼夜零纹理切换）。
 */
import * as THREE from 'three'
import { ActorController, type BubbleKind } from './actors'
import { DAY_NIGHT_THRESHOLD, FieldEventScheduler, mulberry32 } from './events'
import { FieldInteractions } from './interactions'
import { duskAmount, FIELD_PALETTE, PaletteRegistry } from './palette'
import { createPixelPipeline } from './pixelPipeline'
import {
  disposeUnitPlane,
  FrameSet,
  frameToTexture,
  unitPlaneGeometry,
  type PixelFrame,
} from './sprites'
import {
  BIRD,
  BLOB_SHADOW,
  BUBBLES,
  BUTTERFLY,
  CAT,
  DOG,
  ELDER,
  grassStrip,
  groundStrip,
  KID,
  LAMP_POST,
  MERCHANT,
  ridgeStrip,
  TRAVELER,
  TREE_LEAF_A,
  TREE_LEAF_B,
  TREE_TRUNK,
} from './spriteArt'

/** 主题切换扫掠时长（秒），恒定速率 */
export const DAY_SWEEP_SECONDS = 1.8

const BLOOM_DAY = 0.15
const BLOOM_NIGHT = 0.55

/** 竖向布局（占 lowH 比例，y 自底向上） */
const LAYOUT = {
  horizon: 0.4,
  farHillsHeight: 0.17,
  treeLineHeight: 0.12,
  groundFarHeight: 0.12, // 0.30–0.42，盖住地平线接缝
  pathHeight: 0.1, // 0.20–0.30
  groundNearHeight: 0.22,
  grassBackHeight: 0.055,
  actorFeet: 0.24,
  grassFrontHeight: 0.1,
} as const

const WALK_MARGIN = 26

const RENDER_ORDER = {
  sky: 0,
  hills: 1,
  treeLine: 2,
  groundFar: 3,
  path: 4,
  groundNear: 5,
  grassBack: 6,
  shadow: 7,
  props: 8,
  actors: 9,
  bubbles: 10,
  foreground: 11,
} as const

/* ── 天空 ShaderMaterial（沿用港湾 shader 的 GLSL 习语：hash/vnoise/fbm/bayer） ── */

const SKY_VERTEX = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`

const SKY_FRAGMENT = /* glsl */ `
  uniform float uDay;
  uniform float uDusk;
  uniform float uTime;
  uniform vec2 uPointer;
  uniform vec2 uResolution;
  uniform vec3 uSkyTop;
  uniform vec3 uSkyHorizon;
  uniform vec3 uDuskBand;
  uniform vec3 uSunCore;
  uniform vec3 uSunGlow;
  uniform vec3 uMoonCore;
  uniform vec3 uMoonGlow;
  uniform vec3 uStar;
  uniform vec3 uCloud;
  varying vec2 vUv;

  float bayer2(vec2 a) { a = floor(a); return fract(a.x / 2.0 + a.y * a.y * 0.75); }
  float bayer4(vec2 a) { return bayer2(0.5 * a) * 0.25 + bayer2(a); }
  float hash21(vec2 p) {
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
  }
  float vnoise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(
      mix(hash21(i), hash21(i + vec2(1.0, 0.0)), u.x),
      mix(hash21(i + vec2(0.0, 1.0)), hash21(i + vec2(1.0, 1.0)), u.x),
      u.y
    );
  }
  float fbm(vec2 p) {
    float v = 0.0;
    float a = 0.5;
    for (int i = 0; i < 3; i++) {
      v += a * vnoise(p);
      p *= 2.03;
      a *= 0.5;
    }
    return v;
  }

  void main() {
    vec2 frag = vUv * uResolution;

    // 天空渐变
    vec3 col = mix(uSkyHorizon, uSkyTop, pow(vUv.y, 0.85));
    // 黄昏暖带（贴地平线，昼夜中点最强）
    float duskBand = exp(-pow((vUv.y - 0.42) * 4.2, 2.0));
    col = mix(col, uDuskBand, duskBand * uDusk * 0.55);

    // 太阳：昼半段沿小弧线升落，硬核边圆盘 + HDR 核（过 bloom 阈值）
    float sunVis = smoothstep(0.52, 0.66, uDay);
    if (sunVis > 0.001) {
      float t = clamp((uDay - 0.52) / 0.48, 0.0, 1.0);
      vec2 sunPos = vec2(mix(0.30, 0.66, t), mix(0.46, 0.74, t)) * uResolution;
      float dist = length(frag - sunPos);
      float disc = 1.0 - step(8.0, dist);
      float glow = exp(-dist / 16.0);
      col += uSunGlow * glow * 0.35 * sunVis;
      col += uSunCore * disc * 1.10 * sunVis;
    }

    // 月亮：夜半段镜像弧线，新月 = 两圆盘相减
    float moonVis = 1.0 - smoothstep(0.34, 0.48, uDay);
    if (moonVis > 0.001) {
      float t = clamp((0.48 - uDay) / 0.48, 0.0, 1.0);
      vec2 moonPos = vec2(mix(0.34, 0.68, 1.0 - t), mix(0.46, 0.72, t)) * uResolution;
      float dist = length(frag - moonPos);
      float bite = length(frag - moonPos - vec2(3.0, 1.5));
      float disc = (1.0 - step(7.0, dist)) * step(6.0, bite);
      float glow = exp(-dist / 14.0);
      col += uMoonGlow * glow * 0.30 * moonVis;
      col += uMoonCore * disc * 1.15 * moonVis;
    }

    // 星星：3px 格点 hash，夜间淡入，闪烁
    float starVis = 1.0 - smoothstep(0.18, 0.5, uDay);
    if (starVis > 0.001 && vUv.y > 0.44) {
      vec2 cell = floor(frag / 3.0);
      float h = hash21(cell);
      if (h > 0.962) {
        float twinkle = 0.55 + 0.45 * sin(uTime * (1.2 + h * 3.0) + h * 40.0);
        col += uStar * twinkle * starVis * smoothstep(0.44, 0.52, vUv.y) * 0.85;
      }
    }

    // 云：fbm 低矮云带，昼亮夜暗，随指针轻移
    vec2 q = frag / vec2(46.0, 26.0) + vec2(uTime * 0.010 + uPointer.x * 0.12, 0.0);
    float n = fbm(q);
    float band = smoothstep(0.50, 0.62, vUv.y) * (1.0 - smoothstep(0.86, 0.98, vUv.y));
    float cloud = smoothstep(0.58, 0.74, n) * band;
    col = mix(col, uCloud, cloud * mix(0.45, 0.85, uDay));

    // 有序抖动防色带
    col += (bayer4(gl_FragCoord.xy) - 0.5) * (2.0 / 255.0);
    gl_FragColor = vec4(col, 1.0);
  }
`

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
  mesh: THREE.Mesh
  material: THREE.MeshBasicMaterial
  frames: { idle: FrameSet; walk: FrameSet; react: FrameSet }
  shadow: THREE.Mesh
  hitArea: THREE.Mesh
  bubble: THREE.Mesh
  bubbleMaterial: THREE.MeshBasicMaterial
  bubbleScale: number
  bubbleShownAt: number
  lastBubble: BubbleKind | null
}

interface LampVisual {
  group: THREE.Group
  coreMaterial: THREE.MeshBasicMaterial
  poolMaterial: THREE.MeshBasicMaterial
  lit: number
  flickerAt: number | null
  fadeOutAt: number | null
}

const SILHOUETTE_RENDER = {
  depthTest: false,
  depthWrite: false,
} as const

/** 白底 alpha 剪影帧 → 调色板色网格（material.color 由 PaletteRegistry 逐帧改色） */
const makeSilhouetteMesh = (
  frame: PixelFrame,
): { mesh: THREE.Mesh; material: THREE.MeshBasicMaterial } => {
  const texture = frameToTexture(frame)
  if (!texture) throw new Error('Canvas 2D 不可用')
  const material = new THREE.MeshBasicMaterial({
    map: texture,
    transparent: true,
    ...SILHOUETTE_RENDER,
  })
  const mesh = new THREE.Mesh(unitPlaneGeometry(), material)
  mesh.scale.set(frame.rows[0]!.length, frame.rows.length, 1)
  return { mesh, material }
}

export const createFieldScene = (opts: FieldSceneOptions): FieldSceneHandle | null => {
  let renderer: THREE.WebGLRenderer
  try {
    renderer = new THREE.WebGLRenderer({
      canvas: opts.canvas,
      antialias: false,
      alpha: false,
      powerPreference: 'low-power',
    })
  } catch {
    return null
  }

  const disposables: Array<{ dispose(): void }> = [renderer]
  const cleanup = (): void => {
    for (const disposable of disposables.splice(0)) disposable.dispose()
  }

  try {
    return boot(renderer, opts, disposables)
  } catch {
    // Canvas 2D 不可用 / 纹理创建失败等：清理后回退静态兜底
    cleanup()
    renderer.forceContextLoss()
    disposeUnitPlane()
    return null
  }
}

const boot = (
  renderer: THREE.WebGLRenderer,
  opts: FieldSceneOptions,
  disposables: Array<{ dispose(): void }>,
): FieldSceneHandle => {
  const scene = new THREE.Scene()
  const camera = new THREE.OrthographicCamera(-1, 1, 1, 0, -10, 10)
  camera.position.z = 5

  const pipeline = createPixelPipeline({
    renderer,
    scene,
    camera,
    canvas: opts.canvas,
    paper: opts.paper,
  })
  disposables.push(pipeline)

  const registry = new PaletteRegistry()
  const scheduler = new FieldEventScheduler()
  const rng = mulberry32(0xa16d)

  /* ── 状态 ── */
  let lowW = 2
  let lowH = 2
  let uDay = opts.theme === 'dark' ? 0 : 1
  let targetDay = uDay
  let dusk = duskAmount(uDay)
  const pointer = { x: 0, y: 0 }
  const pointerTarget = { x: 0, y: 0 }
  let elapsed = 0
  let lastFrameAt: number | null = null
  let rafId: number | null = null
  let running = false
  let bandRegenTimer: ReturnType<typeof setTimeout> | null = null
  let nextAmbientBirdAt = 12

  /* ── 天空 ── */
  const skyUniforms = {
    uDay: { value: uDay },
    uDusk: { value: dusk },
    uTime: { value: 0 },
    uPointer: { value: new THREE.Vector2(0, 0) },
    uResolution: { value: new THREE.Vector2(2, 2) },
    uSkyTop: { value: new THREE.Color(FIELD_PALETTE.skyTop.day) },
    uSkyHorizon: { value: new THREE.Color(FIELD_PALETTE.skyHorizon.day) },
    uDuskBand: { value: new THREE.Color(FIELD_PALETTE.duskBand.day) },
    uSunCore: { value: new THREE.Color(FIELD_PALETTE.sunCore.day) },
    uSunGlow: { value: new THREE.Color(FIELD_PALETTE.sunGlow.day) },
    uMoonCore: { value: new THREE.Color(FIELD_PALETTE.moonCore.day) },
    uMoonGlow: { value: new THREE.Color(FIELD_PALETTE.moonGlow.day) },
    uStar: { value: new THREE.Color(FIELD_PALETTE.star.day) },
    uCloud: { value: new THREE.Color(FIELD_PALETTE.cloud.day) },
  }
  const skyMaterial = new THREE.ShaderMaterial({
    uniforms: skyUniforms,
    vertexShader: SKY_VERTEX,
    fragmentShader: SKY_FRAGMENT,
    ...SILHOUETTE_RENDER,
  })
  disposables.push(skyMaterial)
  const skyMesh = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), skyMaterial)
  skyMesh.renderOrder = RENDER_ORDER.sky
  disposables.push(skyMesh.geometry)
  scene.add(skyMesh)
  registry.registerKey(skyUniforms.uSkyTop.value, 'skyTop')
  registry.registerKey(skyUniforms.uSkyHorizon.value, 'skyHorizon')
  registry.registerKey(skyUniforms.uCloud.value, 'cloud')
  registry.registerKey(skyUniforms.uStar.value, 'star')

  /* ── 视差层组 ── */
  const parallaxLayers: Array<{ group: THREE.Group; factor: number }> = []
  const makeLayer = (factor: number): THREE.Group => {
    const group = new THREE.Group()
    scene.add(group)
    parallaxLayers.push({ group, factor })
    return group
  }
  const hillsLayer = makeLayer(0.03)
  const treeLineLayer = makeLayer(0.05)
  const groundFarLayer = makeLayer(0.07)
  const pathLayer = makeLayer(0.1)
  const groundNearLayer = makeLayer(0.12)
  const propsLayer = makeLayer(0.15)
  const actorsLayer = makeLayer(0.15)
  const skyExtrasLayer = makeLayer(0.04)
  const foregroundLayer = makeLayer(0.22)

  /* ── 剪影带（按 lowW 重生成，含视差余量） ── */
  interface Band {
    mesh: THREE.Mesh
    material: THREE.MeshBasicMaterial
    rebuild: (frame: PixelFrame) => void
    kind: 'ridge' | 'ground' | 'grass'
    seed: number
    heightRatio: number
    bottomRatio: number
    ridgeArgs?: { base: number; amp: number; freq: number }
    speckle?: number
  }

  const bands: Band[] = []
  const makeBand = (
    layer: THREE.Group,
    paletteKey: keyof typeof FIELD_PALETTE,
    init: Omit<Band, 'mesh' | 'material' | 'rebuild'>,
  ): Band => {
    const placeholder: PixelFrame = { rows: ['x'], palette: { x: '#ffffff' } }
    const { mesh, material } = makeSilhouetteMesh(placeholder)
    mesh.renderOrder =
      init.kind === 'grass'
        ? RENDER_ORDER.grassBack
        : init.kind === 'ridge'
          ? RENDER_ORDER.hills
          : RENDER_ORDER.groundFar
    layer.add(mesh)
    registry.registerKey(material.color, paletteKey)
    disposables.push(material, { dispose: () => material.map?.dispose() })
    const band: Band = {
      mesh,
      material,
      rebuild(frame) {
        const old = material.map
        const texture = frameToTexture(frame)
        if (!texture) return
        material.map = texture
        old?.dispose()
        mesh.scale.set(frame.rows[0]!.length, frame.rows.length, 1)
      },
      ...init,
    }
    bands.push(band)
    return band
  }

  makeBand(hillsLayer, 'farHill', {
    kind: 'ridge',
    seed: 101,
    heightRatio: LAYOUT.farHillsHeight,
    bottomRatio: LAYOUT.horizon,
    ridgeArgs: { base: 0.35, amp: 0.45, freq: 3 },
  })
  const treeLineBand = makeBand(treeLineLayer, 'treeLine', {
    kind: 'ridge',
    seed: 202,
    heightRatio: LAYOUT.treeLineHeight,
    bottomRatio: LAYOUT.horizon,
    ridgeArgs: { base: 0.5, amp: 0.3, freq: 7 },
  })
  treeLineBand.mesh.renderOrder = RENDER_ORDER.treeLine
  const groundFarBand = makeBand(groundFarLayer, 'groundFar', {
    kind: 'ground',
    seed: 303,
    heightRatio: LAYOUT.groundFarHeight,
    bottomRatio: LAYOUT.horizon + 0.02 - LAYOUT.groundFarHeight,
    speckle: 0.05,
  })
  groundFarBand.mesh.renderOrder = RENDER_ORDER.groundFar
  const pathBand = makeBand(pathLayer, 'path', {
    kind: 'ground',
    seed: 404,
    heightRatio: LAYOUT.pathHeight,
    bottomRatio: 0.2,
    speckle: 0.1,
  })
  pathBand.mesh.renderOrder = RENDER_ORDER.path
  const groundNearBand = makeBand(groundNearLayer, 'groundNear', {
    kind: 'ground',
    seed: 505,
    heightRatio: LAYOUT.groundNearHeight,
    bottomRatio: 0,
    speckle: 0.07,
  })
  groundNearBand.mesh.renderOrder = RENDER_ORDER.groundNear
  const grassBackBand = makeBand(groundNearLayer, 'grass', {
    kind: 'grass',
    seed: 606,
    heightRatio: LAYOUT.grassBackHeight,
    bottomRatio: 0.19,
  })
  grassBackBand.mesh.renderOrder = RENDER_ORDER.grassBack
  const grassFrontBand = makeBand(foregroundLayer, 'grassFg', {
    kind: 'grass',
    seed: 707,
    heightRatio: LAYOUT.grassFrontHeight,
    bottomRatio: 0,
  })
  grassFrontBand.mesh.renderOrder = RENDER_ORDER.foreground

  const rebuildBands = (): void => {
    const margin = Math.ceil(0.35 * lowH * 0.22) + 6
    const width = lowW + margin * 2
    for (const band of bands) {
      const height = Math.max(2, Math.round(band.heightRatio * lowH))
      let frame: PixelFrame
      if (band.kind === 'ridge' && band.ridgeArgs) {
        frame = ridgeStrip(width, height, band.seed, band.ridgeArgs.base, band.ridgeArgs.amp, band.ridgeArgs.freq)
      } else if (band.kind === 'grass') {
        frame = grassStrip(width, height, band.seed)
      } else {
        frame = groundStrip(width, height, band.seed, band.speckle ?? 0.05)
      }
      band.rebuild(frame)
      band.mesh.position.set(0, band.bottomRatio * lowH, 0)
    }
  }

  /* ── 道具：路灯 ×3（柱剪影 + HDR 灯芯 + 加法光池 + blob 影） ── */
  const lamps: LampVisual[] = []
  const lampCoreColor = new THREE.Color(FIELD_PALETTE.lampCore.day)
  const poolTexture = (() => {
    const frame: PixelFrame = {
      rows: Array.from({ length: 6 }, (_, y) =>
        Array.from({ length: 24 }, (__, x) => {
          const dx = (x - 11.5) / 11.5
          const dy = (y - 2.5) / 2.5
          const d = Math.sqrt(dx * dx + dy * dy)
          return d >= 1 ? '.' : d < 0.45 ? 'x' : 'd'
        }).join(''),
      ),
      palette: { x: '#ffffff', d: '#ffffff66' },
    }
    const texture = frameToTexture(frame)
    if (!texture) throw new Error('Canvas 2D 不可用')
    return texture
  })()
  disposables.push(poolTexture)

  const shadowTexture = frameToTexture(BLOB_SHADOW)
  if (!shadowTexture) throw new Error('Canvas 2D 不可用')
  disposables.push(shadowTexture)

  const makeShadow = (width: number): THREE.Mesh => {
    const material = new THREE.MeshBasicMaterial({
      map: shadowTexture,
      transparent: true,
      opacity: 0.32,
      ...SILHOUETTE_RENDER,
    })
    disposables.push(material)
    registry.registerKey(material.color, 'shadowBlob')
    const mesh = new THREE.Mesh(unitPlaneGeometry(), material)
    mesh.scale.set(width, 3, 1)
    mesh.renderOrder = RENDER_ORDER.shadow
    return mesh
  }

  for (const xRatio of [-0.28, 0.03, 0.31]) {
    const group = new THREE.Group()
    const { mesh: post, material: postMaterial } = makeSilhouetteMesh(LAMP_POST)
    post.renderOrder = RENDER_ORDER.props
    registry.registerKey(postMaterial.color, 'lampPost')
    disposables.push(postMaterial, postMaterial.map as THREE.Texture)
    group.add(post)

    // HDR 灯芯：叠加在玻璃窗口（柱高 30，窗口中心 ≈ 24）
    const coreMaterial = new THREE.MeshBasicMaterial({
      color: lampCoreColor.clone(),
      transparent: true,
      ...SILHOUETTE_RENDER,
    })
    disposables.push(coreMaterial)
    const core = new THREE.Mesh(unitPlaneGeometry(), coreMaterial)
    core.scale.set(3, 4, 1)
    core.position.set(0, 22.5, 0)
    core.renderOrder = RENDER_ORDER.props + 0.1
    group.add(core)

    // 地面加法光池
    const poolMaterial = new THREE.MeshBasicMaterial({
      map: poolTexture,
      color: lampCoreColor.clone(),
      transparent: true,
      opacity: 0,
      blending: THREE.AdditiveBlending,
      ...SILHOUETTE_RENDER,
    })
    disposables.push(poolMaterial)
    const pool = new THREE.Mesh(unitPlaneGeometry(), poolMaterial)
    pool.scale.set(26, 7, 1)
    pool.position.set(0, -1, 0)
    pool.renderOrder = RENDER_ORDER.props + 0.2
    group.add(pool)

    group.add(makeShadow(14))
    propsLayer.add(group)
    lamps.push({
      group,
      coreMaterial,
      poolMaterial,
      lit: uDay >= 0.5 ? 0 : 1,
      flickerAt: null,
      fadeOutAt: null,
    })
    group.userData.xRatio = xRatio
  }

  /* ── 道具：树 ×2（干 + 叶两色剪影 + blob 影） ── */
  const treeSpecs = [
    { xRatio: -0.4, leaf: TREE_LEAF_A, feetRatio: 0.27 },
    { xRatio: 0.44, leaf: TREE_LEAF_B, feetRatio: 0.22 },
  ]
  for (const spec of treeSpecs) {
    const group = new THREE.Group()
    const { mesh: trunk, material: trunkMaterial } = makeSilhouetteMesh(TREE_TRUNK)
    trunk.renderOrder = RENDER_ORDER.props
    registry.registerKey(trunkMaterial.color, 'treeTrunk')
    disposables.push(trunkMaterial, trunkMaterial.map as THREE.Texture)
    group.add(trunk)
    const { mesh: leaf, material: leafMaterial } = makeSilhouetteMesh(spec.leaf)
    leaf.renderOrder = RENDER_ORDER.props + 0.1
    leaf.position.set(-10, 16, 0) // 叶冠 28 宽，相对干（8 宽）居中偏置
    registry.registerKey(leafMaterial.color, 'treeLeaf')
    disposables.push(leafMaterial, leafMaterial.map as THREE.Texture)
    group.add(leaf)
    group.add(makeShadow(18))
    group.userData.xRatio = spec.xRatio
    group.userData.feetRatio = spec.feetRatio
    propsLayer.add(group)
  }

  /* ── 角色 ── */
  const bubbleTextures: Record<BubbleKind, THREE.Texture> = {
    exclaim: frameToTexture(BUBBLES.exclaim) as THREE.Texture,
    dots: frameToTexture(BUBBLES.dots) as THREE.Texture,
    note: frameToTexture(BUBBLES.note) as THREE.Texture,
  }
  for (const texture of Object.values(bubbleTextures)) {
    if (!texture) throw new Error('Canvas 2D 不可用')
    disposables.push(texture)
  }

  const actors: ActorVisual[] = []
  const feetY = (): number => LAYOUT.actorFeet * lowH

  const spawnActor = (
    art: { idle: PixelFrame[]; walk: PixelFrame[]; react: PixelFrame[] },
    startXRatio: number,
    spec: {
      walkSpeed?: number
      fleeSpeed?: number
      idleFrameMs?: number
      walkFrameMs?: number
      reactFrameMs?: number
      bubbleScale?: number
    } = {},
  ): ActorVisual => {
    const idle = new FrameSet(art.idle)
    const walk = new FrameSet(art.walk)
    const react = new FrameSet(art.react)
    disposables.push(idle, walk, react)
    const material = new THREE.MeshBasicMaterial({
      map: idle.textureAt(0),
      transparent: true,
      ...SILHOUETTE_RENDER,
    })
    disposables.push(material)
    registry.registerKey(material.color, 'actorNightTint')
    const mesh = new THREE.Mesh(unitPlaneGeometry(), material)
    mesh.scale.set(idle.width, idle.height, 1)
    mesh.renderOrder = RENDER_ORDER.actors

    const shadow = makeShadow(Math.round(idle.width * 0.85))
    shadow.renderOrder = RENDER_ORDER.shadow

    const hitArea = new THREE.Mesh(
      unitPlaneGeometry(),
      new THREE.MeshBasicMaterial({
        transparent: true,
        opacity: 0,
        colorWrite: false,
        ...SILHOUETTE_RENDER,
      }),
    )
    disposables.push(hitArea.material as THREE.MeshBasicMaterial)
    hitArea.scale.set(Math.max(idle.width, 18), Math.max(idle.height, 18), 1)

    const bubbleMaterial = new THREE.MeshBasicMaterial({
      map: bubbleTextures.dots,
      transparent: true,
      ...SILHOUETTE_RENDER,
    })
    disposables.push(bubbleMaterial)
    const bubble = new THREE.Mesh(unitPlaneGeometry(), bubbleMaterial)
    const bubbleScale = spec.bubbleScale ?? 1
    bubble.scale.set(14 * bubbleScale, 12 * bubbleScale, 1)
    bubble.renderOrder = RENDER_ORDER.bubbles
    bubble.visible = false

    actorsLayer.add(shadow, mesh, hitArea, bubble)

    const controller = new ActorController(0, {
      idleFrameCount: idle.frameCount,
      walkFrameCount: walk.frameCount,
      reactFrameCount: react.frameCount,
      walkSpeed: spec.walkSpeed,
      fleeSpeed: spec.fleeSpeed,
      idleFrameMs: spec.idleFrameMs,
      walkFrameMs: spec.walkFrameMs,
      reactFrameMs: spec.reactFrameMs,
      rng,
    })

    const visual: ActorVisual = {
      controller,
      mesh,
      material,
      frames: { idle, walk, react },
      shadow,
      hitArea,
      bubble,
      bubbleMaterial,
      bubbleScale,
      bubbleShownAt: -1,
      lastBubble: null,
    }
    visual.controller.teleport(startXRatio * lowW, 0)
    actors.push(visual)
    return visual
  }

  const kid = spawnActor(KID, -0.18)
  const elder = spawnActor(ELDER, 0.24, { walkSpeed: 16 })
  const merchant = spawnActor(MERCHANT, 0.13, { walkSpeed: 18 })
  const traveler = spawnActor(TRAVELER, -0.36)
  const cat = spawnActor(
    { idle: CAT.groom, walk: CAT.walk, react: CAT.scurry },
    0.34,
    { walkSpeed: 20, fleeSpeed: 70, idleFrameMs: 420, walkFrameMs: 160, reactFrameMs: 110 },
  )
  const dog = spawnActor({ idle: DOG.sit, walk: DOG.walk, react: DOG.sit }, -0.06, {
    walkSpeed: 24,
    idleFrameMs: 360,
    reactFrameMs: 200,
  })

  /* 飞鸟（事件生成，平时隐藏） */
  const birdFrames = new FrameSet(BIRD.fly)
  disposables.push(birdFrames)
  const birdMaterial = new THREE.MeshBasicMaterial({
    map: birdFrames.textureAt(0),
    transparent: true,
    ...SILHOUETTE_RENDER,
  })
  disposables.push(birdMaterial)
  registry.registerKey(birdMaterial.color, 'actorNightTint')
  const bird = new THREE.Mesh(unitPlaneGeometry(), birdMaterial)
  bird.scale.set(10, 6, 1)
  bird.renderOrder = RENDER_ORDER.actors
  bird.visible = false
  skyExtrasLayer.add(bird)
  const birdState = { active: false, x: 0, y: 0, vx: 0 }

  /* 蝴蝶（常驻，8 字舞） */
  const butterflyFrames = new FrameSet(BUTTERFLY.fly)
  disposables.push(butterflyFrames)
  const butterflyMaterial = new THREE.MeshBasicMaterial({
    map: butterflyFrames.textureAt(0),
    transparent: true,
    ...SILHOUETTE_RENDER,
  })
  disposables.push(butterflyMaterial)
  registry.registerKey(butterflyMaterial.color, 'actorNightTint')
  const butterfly = new THREE.Mesh(unitPlaneGeometry(), butterflyMaterial)
  butterfly.scale.set(5, 4, 1)
  butterfly.renderOrder = RENDER_ORDER.actors
  actorsLayer.add(butterfly)
  const butterflyState = { fleeUntil: -1, fleeDir: 1 as 1 | -1 }

  /* ── 交互 ── */
  const interactions = new FieldInteractions({
    camera,
    dom: opts.host,
    isUiEvent: (event) =>
      event.target instanceof Element &&
      Boolean(event.target.closest('.entry-item, a, button')),
  })
  disposables.push(interactions)

  if (!opts.reducedMotion) {
    for (const visual of [kid, elder, merchant, traveler]) {
      interactions.register({
        hitArea: visual.hitArea,
        onHover: (point) => {
          visual.controller.faceTowards(point.x)
          visual.controller.react(elapsed, 600, rng() < 0.5 ? 'dots' : 'note')
        },
        onPress: (point) => {
          visual.controller.faceTowards(point.x)
          visual.controller.react(elapsed, 800, 'exclaim')
        },
      })
    }
    interactions.register({
      hitArea: cat.hitArea,
      onHover: () => cat.controller.react(elapsed, 500, 'dots'),
      onPress: (point) => cat.controller.fleeFrom(point.x, elapsed),
    })
    interactions.register({
      hitArea: dog.hitArea,
      onHover: () => dog.controller.showBubble(elapsed, 'note', 900),
      onPress: () => dog.controller.react(elapsed, 600, 'dots'),
    })
  }

  /* ── 事件行为 ── */
  const lampsOn = (now: number): void => {
    lamps.forEach((lamp, index) => {
      lamp.flickerAt = now + index * 0.3
      lamp.fadeOutAt = null
    })
    const mid = lamps[1]
    if (mid) traveler.controller.walkTo(mid.group.position.x - 5)
    traveler.controller.showBubble(now + 1.0, 'note', 1200)
  }
  const lampsOff = (): void => {
    for (const lamp of lamps) {
      lamp.fadeOutAt = elapsed
      lamp.flickerAt = null
    }
    spawnBird()
  }

  const spawnBird = (): void => {
    birdState.active = true
    birdState.x = -(lowW / 2) - 12
    birdState.y = lowH * (0.6 + rng() * 0.15)
    birdState.vx = 26 + rng() * 10
    bird.visible = true
  }

  const handleEvent = (kind: string, now: number): void => {
    switch (kind) {
      case 'kid-merchant-meet': {
        kid.controller.walkTo(merchant.controller.renderX - 12)
        merchant.controller.faceTowards(kid.controller.renderX)
        merchant.controller.showBubble(now + 1.4, 'dots', 1300)
        kid.controller.showBubble(now + 2.8, 'note', 1300)
        merchant.controller.showBubble(now + 4.2, 'exclaim', 1200)
        break
      }
      case 'elder-lamp-visit': {
        const lamp = lamps[0]
        if (lamp) elder.controller.walkTo(lamp.group.position.x - 6)
        elder.controller.showBubble(now + 2.2, 'dots', 1400)
        break
      }
      case 'cat-chase-butterfly': {
        cat.controller.walkTo(butterfly.position.x)
        butterflyState.fleeUntil = now + 1.6
        butterflyState.fleeDir = butterfly.position.x > cat.controller.renderX ? 1 : -1
        break
      }
      case 'dog-follow-traveler': {
        dog.controller.walkTo(traveler.controller.renderX + 8 * traveler.controller.facingSign)
        break
      }
    }
  }

  /* ── 尺寸/布局 ── */
  const applyLayout = (): void => {
    camera.left = -lowW / 2
    camera.right = lowW / 2
    camera.top = lowH
    camera.bottom = 0
    camera.updateProjectionMatrix()
    skyMesh.scale.set(lowW, lowH, 1)
    skyMesh.position.set(0, lowH / 2, 0)
    skyUniforms.uResolution.value.set(lowW, lowH)

    for (const lamp of lamps) {
      lamp.group.position.set((lamp.group.userData.xRatio as number) * lowW, 0.25 * lowH, 0)
    }
    for (const group of propsLayer.children) {
      if (group.userData.feetRatio !== undefined) {
        group.position.set(
          (group.userData.xRatio as number) * lowW,
          (group.userData.feetRatio as number) * lowH,
          0,
        )
      }
    }
  }

  const resize = (cssWidth: number, cssHeight: number): void => {
    const size = pipeline.setSize(cssWidth, cssHeight)
    lowW = size.lowW
    lowH = size.lowH
    applyLayout()
    // 剪影带按新宽度重生成（去抖 150ms，避免拖拽期间反复画 canvas）
    if (bandRegenTimer !== null) clearTimeout(bandRegenTimer)
    bandRegenTimer = setTimeout(() => {
      bandRegenTimer = null
      rebuildBands()
      if (!running) renderOnce()
    }, 150)
    // 循环停止时（reduced-motion / 离屏 / 首帧前）重绘静帧，resize 不留旧画面
    if (!running) renderOnce()
  }

  /* ── 帧循环 ── */
  const walkBounds = (): { min: number; max: number } => ({
    min: -(lowW / 2 - WALK_MARGIN),
    max: lowW / 2 - WALK_MARGIN,
  })

  const syncActor = (visual: ActorVisual, now: number, dt: number): void => {
    const snapshot = visual.controller.update(now, dt, walkBounds())
    const frames =
      snapshot.state === 'walk'
        ? visual.frames.walk
        : snapshot.state === 'react'
          ? visual.frames.react
          : visual.frames.idle
    visual.material.map = frames.textureAt(snapshot.frame)
    const width = frames.width
    visual.mesh.scale.set(width * snapshot.facing, frames.height, 1)
    visual.mesh.position.set(snapshot.x, feetY(), 0)
    visual.shadow.position.set(snapshot.x, feetY() - 1.5, 0)
    visual.hitArea.position.set(snapshot.x, feetY(), 0)

    if (snapshot.bubble) {
      if (snapshot.bubble !== visual.lastBubble) {
        visual.lastBubble = snapshot.bubble
        visual.bubbleMaterial.map = bubbleTextures[snapshot.bubble]
        visual.bubbleShownAt = now
      }
      visual.bubble.visible = true
      const pop = (now - visual.bubbleShownAt < 0.12 ? 0.75 : 1) * visual.bubbleScale
      visual.bubble.scale.set(14 * pop, 12 * pop, 1)
      visual.bubble.position.set(
        snapshot.x + snapshot.facing * 4,
        feetY() + frames.height + 2,
        0,
      )
    } else {
      visual.bubble.visible = false
      visual.lastBubble = null
    }
  }

  const tickLamps = (now: number, dt: number): void => {
    for (const lamp of lamps) {
      if (lamp.flickerAt !== null && now >= lamp.flickerAt) {
        // 点火闪烁：0 → 0.7 → 0.3 → 1（240ms）
        const t = (now - lamp.flickerAt) / 0.24
        lamp.lit = t >= 1 ? 1 : t < 0.25 ? 0.7 : t < 0.5 ? 0.25 : t < 0.75 ? 0.85 : 1
        if (t >= 1) lamp.flickerAt = null
      } else if (lamp.fadeOutAt !== null) {
        lamp.lit = Math.max(0, lamp.lit - dt / 0.2)
        if (lamp.lit <= 0) lamp.fadeOutAt = null
      }
      const lit = lamp.lit
      lamp.coreMaterial.color.copy(lampCoreColor).multiplyScalar(0.45 + lit * 1.9)
      lamp.poolMaterial.opacity = lit * 0.55
    }
  }

  const frame = (nowMs: number): void => {
    if (!running) return
    rafId = null
    const now = nowMs / 1000
    const dt = lastFrameAt === null ? 1 / 60 : Math.min(now - lastFrameAt, 0.1)
    lastFrameAt = now
    elapsed += dt

    // 昼夜扫掠（恒速）
    if (uDay !== targetDay) {
      const step = dt / DAY_SWEEP_SECONDS
      const diff = targetDay - uDay
      uDay = Math.abs(diff) <= step ? targetDay : uDay + Math.sign(diff) * step
      dusk = duskAmount(uDay)
    }
    const toggle = scheduler.checkDayCrossing(uDay)
    if (toggle === 'lamps-on') lampsOn(elapsed)
    else if (toggle === 'lamps-off') lampsOff()

    skyUniforms.uDay.value = uDay
    skyUniforms.uDusk.value = dusk
    skyUniforms.uTime.value = elapsed
    registry.apply(uDay)
    pipeline.setBloom(BLOOM_DAY + (BLOOM_NIGHT - BLOOM_DAY) * (1 - uDay))

    for (const kind of scheduler.tick(elapsed)) handleEvent(kind, elapsed)

    if (elapsed >= nextAmbientBirdAt) {
      spawnBird()
      nextAmbientBirdAt = elapsed + 47 + rng() * 8
    }

    for (const visual of actors) syncActor(visual, elapsed, dt)

    // 飞鸟横穿
    if (birdState.active) {
      birdState.x += birdState.vx * dt
      bird.position.set(birdState.x, birdState.y + Math.sin(elapsed * 3) * 2, 0)
      birdMaterial.map = birdFrames.textureAt(Math.floor(elapsed * 8) % 2)
      if (birdState.x > lowW / 2 + 12) {
        birdState.active = false
        bird.visible = false
      }
    }

    // 蝴蝶 8 字舞 + 逃窜偏置
    const fleeActive = elapsed < butterflyState.fleeUntil
    const fleeOffset = fleeActive ? butterflyState.fleeDir * 10 : 0
    const bx = 0.16 * lowW + Math.sin(elapsed * 0.7) * 12 + fleeOffset
    const by = 0.3 * lowH + Math.sin(elapsed * 1.4) * 5
    const prevX = butterfly.position.x
    butterfly.position.set(bx, by, 0)
    butterfly.scale.x = (bx >= prevX ? 1 : -1) * 5
    butterflyMaterial.map = butterflyFrames.textureAt(Math.floor(elapsed * 10) % 2)

    tickLamps(elapsed, dt)

    // 指针平滑（沿用港湾壳的 0.06 趋近），视差越近越大；相机固定
    pointer.x += (pointerTarget.x - pointer.x) * 0.06
    pointer.y += (pointerTarget.y - pointer.y) * 0.06
    for (const { group, factor } of parallaxLayers) {
      group.position.x = -pointer.x * factor * 0.35 * lowH
    }
    skyUniforms.uPointer.value.set(pointer.x, pointer.y)

    pipeline.composer.render()

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
    skyUniforms.uDay.value = uDay
    skyUniforms.uDusk.value = duskAmount(uDay)
    registry.apply(uDay)
    pipeline.setBloom(BLOOM_DAY + (BLOOM_NIGHT - BLOOM_DAY) * (1 - uDay))
    // 静帧跳变：灯火与昼夜侧直接对齐，不播点灯动画
    for (const lamp of lamps) {
      lamp.flickerAt = null
      lamp.fadeOutAt = null
      lamp.lit = uDay >= DAY_NIGHT_THRESHOLD ? 0 : 1
    }
    tickLamps(elapsed, 0)
    for (const visual of actors) syncActor(visual, elapsed, 0)
    pipeline.composer.render()
  }

  /* ── 初始化 ── */
  resize(opts.host.clientWidth || opts.canvas.clientWidth || 320, opts.host.clientHeight || opts.canvas.clientHeight || 240)
  if (bandRegenTimer !== null) {
    clearTimeout(bandRegenTimer)
    bandRegenTimer = null
  }
  rebuildBands()
  registry.apply(uDay)
  renderOnce()

  return {
    setTheme(theme, paper) {
      targetDay = theme === 'dark' ? 0 : 1
      pipeline.setPaper(paper)
      // 循环停止时（reduced-motion / 离屏 / 首帧前）直接跳变，保证静帧也是正确场景
      if (opts.reducedMotion || !running) {
        uDay = targetDay
        dusk = duskAmount(uDay)
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
      if (bandRegenTimer !== null) {
        clearTimeout(bandRegenTimer)
        bandRegenTimer = null
      }
      for (const disposable of disposables.splice(0)) disposable.dispose()
      renderer.forceContextLoss()
      disposeUnitPlane()
    },
  }
}
