/**
 * 环境层场景图（HD-2D 复刻的 3/4 透视纵深载体）——雪境版：
 * 透视相机 + 真深度 + 线性雾（大气透视），五带纵深——前景雪丛（近镜散景）→
 * 雪地/雪径行走带 → 雪盖灌木/岩石/冰井/栅栏中景 → 雪松林线/雪村剪影 → 雪山/天空。
 * 光照全部手绘：纹理烘焙方向明暗，昼夜经 PaletteRegistry 乘法罩色
 * （罩色 = 夜乘子，昼=white 不动烘焙稿，雪夜 =  luminous 蓝——雪地反照月光）；
 * 方向影为地面倾斜暗斑（雪上影为蓝调），灯光晕/光池/暖窗为加法 HDR（喂 bloom）。
 * 落雪 = env 层 THREE.Points（GPU 时间驱动，真深度没入树后，reduced-motion 静帧自然成立）。
 *
 * 【私有 overlay】大纹理不再用程序化 canvas 稿：启动先以程序化稿即时上屏
 * （jsdom/弱网兜底），loadEnvArt() 解码完成后把各槽位 material.map 直接换成
 * AI 抽卡素材（离线 prep_snow.py 只键控/羽化 alpha，RGB 逐像素保留）；
 * 平铺参数按素材纵横比在 resize 重算，防拉伸。
 */
import * as THREE from 'three'
import { duskAmount, PaletteRegistry } from '../palette'
import { visibleHalfWidthAt } from '../project'
import { loadEnvArt } from './envArt'
import {
  bushBlob,
  dirtPath,
  farHills,
  foregroundGrass,
  grassField,
  radialGlow,
  rgbaToTexture,
  rockChunk,
  treeLineStrip,
  villageSkyline,
} from './textures'

/** 相机与舞台几何（世界单位，全程一致）。俯角 11.3° 长焦：地平线约在屏顶下 16%，地面纵深铺开 */
export const ENV_CAMERA = {
  fov: 30,
  near: 0.5,
  far: 80,
  position: new THREE.Vector3(0, 3.8, 15),
  lookAt: new THREE.Vector3(0, 0.8, 0),
} as const

/** 纵深五带的 z 坐标（近大远小）。grassFg 贴近相机底缘（底缘视线落地 z≈7.3） */
export const STAGE_Z = {
  grassFg: 6.5,
  walkNear: 1.8,
  path: -0.6,
  walkFar: -2.6,
  lamp: -2.4,
  bush: -6.5,
  treeLine: -14,
  village: -22,
  hills: -26,
  sky: -32,
} as const

/** 焦点距离（行走带到相机的 3D 距离）：BokehShader focus 钉这里 */
export const FOCUS_DISTANCE = ENV_CAMERA.position.distanceTo(
  new THREE.Vector3(0, 0, STAGE_Z.path),
)

const smoothstep = (a: number, b: number, x: number): number => {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)))
  return t * t * (3 - 2 * t)
}

/**
 * 雪境槽位罩色（overlay 本地常量，不碰公开色板 palette.ts）：
 * day 一律 white（纹理原色上屏），night 为雪地夜乘子——
 * 雪反照月光，夜雪是「发光的蓝」而非荒原夜的死黑；越近/越暗的带乘子越暗。
 */
const tint = (night: string): { day: string; night: string } => ({ day: '#ffffff', night })
const SNOW_TINT = {
  ground: tint('#46609c'), // 月夜雪面：亮蓝
  path: tint('#3c4e78'), // 踩实雪径：稍暗
  fg: tint('#26355c'), // 前景暗枝：近景压深
  hills: tint('#35466e'), // 雪山脊
  treeline: tint('#2b3a58'), // 远林剪影
  // 村庄远带：纹理本体已是板岩蓝剪影（离线压平，暮色盘细节乘色救不回），
  // day 不动；暖窗层独立加色
  village: tint('#212d49'),
  props: tint('#3a4c7a'), // 中景道具/树
  pond: tint('#42568c'), // 冰湖：反光更亮
} as const
/** 雪上方向影：昼 = 天光蓝影（非荒原的绿影），夜 = 深青 */
const SNOW_SHADOW = { day: '#5f7d9e', night: '#0a1224' } as const
/** 雪境雾/地平线：昼 = 冷白蓝（荒原的奶油绿在雪地里发脏），夜沿用公开色板 */
const SNOW_HORIZON = { day: '#dfe9f4', night: '#2b3a55' } as const

/* ── 天空 shader（沿用港湾 GLSL 习语 bayer/hash/vnoise/fbm；太阳/月亮/星星/云在 shader 内） ── */

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
  uniform float uPlaneAspect;
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

    // 天空渐变（uv.y ≈0.06=视觉地平线：天空面片只覆地平线以上视域）
    vec3 col = mix(uSkyHorizon, uSkyTop, pow(vUv.y, 0.8));
    // 黄昏暖带贴地平线
    float duskBand = exp(-pow((vUv.y - 0.11) * 9.0, 2.0));
    col = mix(col, uDuskBand, duskBand * uDusk * 0.6);

    // 太阳：昼半段弧线，硬核边圆盘 + HDR 核（过 bloom 阈值）
    // 圆盘判定在等比空间（pcorr：面片世界宽高比校正），否则扁宽面片把圆拉成椭圆
    vec2 pcorr = vUv * vec2(uPlaneAspect, 1.0);
    float sunVis = smoothstep(0.52, 0.66, uDay);
    if (sunVis > 0.001) {
      float t = clamp((uDay - 0.52) / 0.48, 0.0, 1.0);
      vec2 sunPos = vec2(mix(0.22, 0.72, t) * uPlaneAspect, mix(0.16, 0.60, t));
      float dist = length(pcorr - sunPos);
      float disc = 1.0 - step(0.047, dist);
      float glow = exp(-dist / 0.1375);
      col += uSunGlow * glow * 0.42 * sunVis;
      col += uSunCore * disc * 1.25 * sunVis;
    }

    // 月亮：夜半段镜像弧线，新月 = 两圆盘相减（同样等比校正）
    float moonVis = 1.0 - smoothstep(0.34, 0.48, uDay);
    if (moonVis > 0.001) {
      float t = clamp((0.48 - uDay) / 0.48, 0.0, 1.0);
      vec2 moonPos = vec2(mix(0.30, 0.74, 1.0 - t) * uPlaneAspect, mix(0.18, 0.56, t));
      float dist = length(pcorr - moonPos);
      float bite = length(pcorr - moonPos - vec2(0.01875, 0.009375));
      float disc = (1.0 - step(0.0375, dist)) * step(0.03125, bite);
      float glow = exp(-dist / 0.10625);
      col += uMoonGlow * glow * 0.34 * moonVis;
      col += uMoonCore * disc * 1.30 * moonVis;
    }

    // 星星：4px 格点 hash，夜间淡入闪烁
    float starVis = 1.0 - smoothstep(0.18, 0.5, uDay);
    if (starVis > 0.001 && vUv.y > 0.22) {
      vec2 cell = floor(frag / 4.0);
      float h = hash21(cell);
      if (h > 0.955) {
        float twinkle = 0.55 + 0.45 * sin(uTime * (1.2 + h * 3.0) + h * 40.0);
        col += uStar * twinkle * starVis * smoothstep(0.22, 0.34, vUv.y) * 0.9;
      }
    }

    // 云：fbm 云带，昼亮夜暗，随指针轻移
    vec2 q = frag / vec2(90.0, 52.0) + vec2(uTime * 0.010 + uPointer.x * 0.12, 0.0);
    float n = fbm(q);
    float band = smoothstep(0.14, 0.30, vUv.y) * (1.0 - smoothstep(0.70, 0.92, vUv.y));
    float cloud = smoothstep(0.56, 0.74, n) * band;
    col = mix(col, uCloud, cloud * mix(0.4, 0.8, uDay));

    col += (bayer4(gl_FragCoord.xy) - 0.5) * (2.0 / 255.0);
    gl_FragColor = vec4(col, 1.0);
  }
`

/* ── 类型 ── */

export interface LampEnvHandle {
  /** 0=灭 1=亮（含过冲 flicker，由编排器驱动） */
  setGlow(strength: number): void
  /**
   * 灯头世界高度对齐：美术像素/世界单位的换算随视口而变，
   * 编排器在 resize 时按精灵层灯笼中心（脚部锚点上 33 美术像素）反算下发
   */
  setHeadWorldY(y: number): void
}

export interface EnvStage {
  scene: THREE.Scene
  camera: THREE.PerspectiveCamera
  palette: PaletteRegistry
  /** 世界 x = ratio × 该 z 处可视半宽（布局与视口宽高比解耦） */
  worldXAt(ratio: number, z: number): number
  /** 一盏灯的环境层部件（halo 光晕/HDR 灯芯/地面光池） */
  addLamp(ratio: number): LampEnvHandle
  /** 角色地面影（径向暗斑，方向/长度随 uDay） */
  acquireShadow(): THREE.Mesh
  placeShadow(shadow: THREE.Mesh, worldX: number, worldZ: number, baseScale: number): void
  releaseShadow(shadow: THREE.Mesh): void
  setDay(day: number): void
  setPointer(nx: number, ny: number): void
  tick(time: number): void
  resize(cssWidth: number, cssHeight: number): void
  dispose(): void
}

interface TexturedBillboard {
  mesh: THREE.Mesh
  ratio?: number
  z: number
  widthFactor: number
}

export const createEnvStage = (): EnvStage => {
  const palette = new PaletteRegistry()
  const scene = new THREE.Scene()
  const camera = new THREE.PerspectiveCamera(
    ENV_CAMERA.fov,
    16 / 9,
    ENV_CAMERA.near,
    ENV_CAMERA.far,
  )
  camera.position.copy(ENV_CAMERA.position)
  camera.lookAt(ENV_CAMERA.lookAt)

  const disposables: Array<{ dispose(): void }> = []
  const track = <T extends { dispose(): void }>(resource: T): T => {
    disposables.push(resource)
    return resource
  }

  /* ── AI 环境美术接管状态（overlay）：素材解码完成后换装并据视口重算平铺 ── */
  let disposed = false
  let aiGround: THREE.Texture | null = null
  let aiFg: THREE.Texture | null = null
  const aiBands: Array<{
    textures: THREE.Texture[]
    aspect: number
    heightWorld: number
    widthFactor: number
  }> = []
  const lastCss = { w: 0, h: 0 }

  /** 雾 = 大气透视：地面/远山向地平线色融合（雪境冷白蓝 ↔ 夜青） */
  const fog = new THREE.Fog(SNOW_HORIZON.day, 20, 58)
  scene.fog = fog
  palette.register(fog.color, SNOW_HORIZON)
  /**
   * 背景 = 同一地平线色（palette 就地 lerp 的同一 Color 实例）：
   * 地平线以下、地面远缘之外的视线落空域不再是清屏色，
   * 而是随昼夜联动的大气色——等效于雾对几何体的作用
   */
  scene.background = fog.color

  const viewDistanceAt = (z: number): number =>
    camera.position.distanceTo(new THREE.Vector3(0, 0, z))

  const worldXAt = (ratio: number, z: number): number =>
    ratio * visibleHalfWidthAt(camera, viewDistanceAt(z))

  /* ── 天空 ── */
  const skyUniforms = {
    uDay: { value: 1 },
    uDusk: { value: 0 },
    uTime: { value: 0 },
    uPointer: { value: new THREE.Vector2(0, 0) },
    uResolution: { value: new THREE.Vector2(640, 320) },
    uPlaneAspect: { value: 7 }, // 面片世界宽/高，resize 时按 stageW/6.5 更新
    uSkyTop: { value: new THREE.Color('#7ec8e3') },
    uSkyHorizon: { value: new THREE.Color('#d9eec9') },
    uDuskBand: { value: new THREE.Color('#f0a35e') },
    uSunCore: { value: new THREE.Color('#fff3b0') },
    uSunGlow: { value: new THREE.Color('#ffe9a3') },
    uMoonCore: { value: new THREE.Color('#e8f0ff') },
    uMoonGlow: { value: new THREE.Color('#b8c8e8') },
    uStar: { value: new THREE.Color('#f5f7ff') },
    uCloud: { value: new THREE.Color('#ffffff') },
  }
  palette.registerKey(skyUniforms.uSkyTop.value, 'skyTop')
  // 地平线色与雾同源（雪境冷白蓝），天空/雾在地平线无缝相接
  palette.register(skyUniforms.uSkyHorizon.value, SNOW_HORIZON)
  palette.registerKey(skyUniforms.uDuskBand.value, 'duskBand')
  palette.registerKey(skyUniforms.uSunCore.value, 'sunCore')
  palette.registerKey(skyUniforms.uSunGlow.value, 'sunGlow')
  palette.registerKey(skyUniforms.uMoonCore.value, 'moonCore')
  palette.registerKey(skyUniforms.uMoonGlow.value, 'moonGlow')
  palette.registerKey(skyUniforms.uStar.value, 'star')
  palette.registerKey(skyUniforms.uCloud.value, 'cloud')
  const skyMaterial = track(
    new THREE.ShaderMaterial({
      vertexShader: SKY_VERTEX,
      fragmentShader: SKY_FRAGMENT,
      uniforms: skyUniforms,
      depthWrite: false,
    }),
  )
  const skyMesh = new THREE.Mesh(track(new THREE.PlaneGeometry(1, 1)), skyMaterial)
  // 只覆地平线以上视域：底 y=3.0（地平线 y=相机高 3.4 落在 vUv≈0.06），顶 9.5 越过屏顶
  skyMesh.position.set(0, 6.25, STAGE_Z.sky)
  skyMesh.renderOrder = -10
  scene.add(skyMesh)

  /* ── 落雪（GPU 时间驱动 Points：真深度没入树后，前景草带挡住最近雪片；
   * z 上限 6.0 < grassFg 6.5，reduced-motion 下 uTime 冻结即为静帧雪） ── */
  const SNOW_VERTEX_SHADER = /* glsl */ `
    uniform float uTime;
    uniform vec4 uBounds; // x=覆盖半宽 y=落区高 z=落区中 z w=落区 z 半宽
    uniform float uPointScale;
    attribute float aSpeed;
    attribute float aPhase;
    attribute float aSize;
    varying float vFade;
    void main() {
      vec3 p = vec3(
        position.x * uBounds.x + sin(uTime * 0.7 + aPhase) * 0.3,
        mod(position.y * uBounds.y - uTime * aSpeed, uBounds.y),
        uBounds.z + position.z * uBounds.w
      );
      vec4 mv = modelViewMatrix * vec4(p, 1.0);
      gl_PointSize = aSize * uPointScale / max(1.0, -mv.z);
      vFade = smoothstep(0.0, 0.6, p.y);
      gl_Position = projectionMatrix * mv;
    }
  `
  const SNOW_FRAGMENT_SHADER = /* glsl */ `
    uniform sampler2D uMap;
    uniform vec3 uColor;
    varying float vFade;
    void main() {
      vec4 tex = texture2D(uMap, gl_PointCoord);
      gl_FragColor = vec4(uColor, tex.a * 0.85 * vFade);
    }
  `
  const coarseSnow =
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(pointer: coarse)').matches
  const flakeCount = coarseSnow ? 150 : 400
  // 确定性 LCG：雪野分布在 jsdom/快照间稳定
  let lcgState = 0x5f0a
  const lcg = (): number => {
    lcgState = (lcgState * 1664525 + 1013904223) >>> 0
    return lcgState / 0x100000000
  }
  const snowGeo = track(new THREE.BufferGeometry())
  {
    const pos = new Float32Array(flakeCount * 3)
    const speed = new Float32Array(flakeCount)
    const phase = new Float32Array(flakeCount)
    const size = new Float32Array(flakeCount)
    for (let i = 0; i < flakeCount; i++) {
      pos[i * 3] = lcg() * 2 - 1
      pos[i * 3 + 1] = lcg()
      pos[i * 3 + 2] = lcg() * 2 - 1
      speed[i] = 0.45 + lcg() * 0.6
      phase[i] = lcg() * Math.PI * 2
      size[i] = 0.02 + lcg() * 0.035
    }
    snowGeo.setAttribute('position', new THREE.BufferAttribute(pos, 3))
    snowGeo.setAttribute('aSpeed', new THREE.BufferAttribute(speed, 1))
    snowGeo.setAttribute('aPhase', new THREE.BufferAttribute(phase, 1))
    snowGeo.setAttribute('aSize', new THREE.BufferAttribute(size, 1))
  }
  const snowUniforms = {
    uTime: { value: 0 },
    uMap: { value: rgbaToTexture(radialGlow(32, 1.8)) },
    uColor: { value: new THREE.Color('#ffffff') },
    uBounds: { value: new THREE.Vector4(14, 7, -4, 10) },
    uPointScale: { value: 600 },
  }
  if (snowUniforms.uMap.value) track(snowUniforms.uMap.value)
  palette.register(snowUniforms.uColor.value, { day: '#ffffff', night: '#c4d2ec' })
  const snowMaterial = track(
    new THREE.ShaderMaterial({
      vertexShader: SNOW_VERTEX_SHADER,
      fragmentShader: SNOW_FRAGMENT_SHADER,
      uniforms: snowUniforms,
      transparent: true,
      depthWrite: false,
    }),
  )
  const snowPoints = new THREE.Points(snowGeo, snowMaterial)
  snowPoints.frustumCulled = false // 粒子在顶点着色器内游走，包围球失真
  scene.add(snowPoints)

  /* ── 纹理 billboard 工厂 ── */
  const billboards: TexturedBillboard[] = []
  const addTextured = (
    texture: THREE.CanvasTexture | null,
    z: number,
    yBottom: number,
    heightWorld: number,
    widthFactor: number,
    tint: { day: string; night: string },
    options: { additive?: boolean; ratio?: number; x?: number } = {},
  ): THREE.Mesh | null => {
    if (!texture) return null
    track(texture)
    const material = track(
      new THREE.MeshBasicMaterial({
        map: texture,
        transparent: true,
        depthWrite: !options.additive,
        blending: options.additive ? THREE.AdditiveBlending : THREE.NormalBlending,
      }),
    )
    palette.register(material.color, tint)
    const mesh = new THREE.Mesh(track(new THREE.PlaneGeometry(1, 1)), material)
    mesh.position.set(options.x ?? 0, yBottom + heightWorld / 2, z)
    mesh.scale.set(1, heightWorld, 1)
    const entry: TexturedBillboard = { mesh, z, widthFactor }
    if (options.ratio !== undefined) entry.ratio = options.ratio
    billboards.push(entry)
    scene.add(mesh)
    return mesh
  }

  // 远山（雪山脊；高度沿地平线收敛——浅俯角下远物顶边贴近 0° 视线）
  const hillsMesh = addTextured(rgbaToTexture(farHills(0xa11, 192, 48)), STAGE_Z.hills, -0.35, 3.3, 1.35, SNOW_TINT.hills)
  // 雪村剪影 + 独立暖窗层（夜里亮起，HDR 喂 bloom）
  // yBottom 抬到 0.5：带底藏在树线密枝后，屋身/暖窗恰好从林隙与树线顶部
  // 渐隐区透出（-0.2 时整带被树线挡死，夜里暖窗完全不可见）
  const village = villageSkyline(0xb22, 320, 64)
  const villageMesh = addTextured(rgbaToTexture(village.silhouette), STAGE_Z.village, 0.5, 2.3, 1.1, SNOW_TINT.village)
  const windowsMesh = addTextured(rgbaToTexture(village.windows), STAGE_Z.village + 0.1, 0.5, 2.3, 1.1, { day: '#ffca7a', night: '#ffca7a' }, { additive: true })
  if (windowsMesh) {
    const windowsMaterial = windowsMesh.material as THREE.MeshBasicMaterial
    windowsMaterial.color.multiplyScalar(1.8) // HDR：夜里暖窗过 bloom 阈值
    windowsMaterial.opacity = 0
  }
  // 雪松林线
  const treeLineMesh = addTextured(rgbaToTexture(treeLineStrip(0xc33, 256, 64)), STAGE_Z.treeLine, -0.2, 2.1, 1.2, SNOW_TINT.treeline)
  // 中景灌木与岩石
  const bushTextureA = rgbaToTexture(bushBlob(0xd44, 28, 18))
  const bushTextureB = rgbaToTexture(bushBlob(0xd45, 24, 16))
  const rockTexture = rgbaToTexture(rockChunk(0xe55, 20, 14))
  // AI 素材为近方团块（雪盖灌木/岩石），尺寸收敛到贴地灌木量级；
  // 底部埋入地面 16%（圆底不悬空）。中景树（昼绿雪松/黄昏蓝松）以树干贴地为准只浅埋 3%；
  // 树高 3.3–4.2 世界单位 ≈ 角色的 2.5–3 倍（八方式近景锚点），第三棵镜像复用
  // 雪松素材（scale.x 取负镜像防重复感）。启动占位沿用灌木团块，AI 素材解码后
  // 换装并重算纵横比（镜像在换装时保留）。冰井/栅栏同槽换装，冰湖是地面贴片（见换装回调）
  const midProps: Array<{ texture: THREE.CanvasTexture | null; ratio: number; z: number; h: number; slot: 'bush' | 'rock' | 'treeA' | 'treeB' | 'well' | 'fence'; bury?: number; mirror?: boolean }> = [
    { texture: bushTextureA, ratio: -0.46, z: -7.5, h: 0.78, slot: 'bush' },
    { texture: bushTextureB, ratio: -0.2, z: -6.2, h: 0.6, slot: 'bush' },
    { texture: rockTexture, ratio: 0.28, z: -5.6, h: 0.5, slot: 'rock' },
    { texture: bushTextureA, ratio: 0.48, z: -8.2, h: 0.92, slot: 'bush' },
    { texture: bushTextureB, ratio: 0.08, z: -9.0, h: 0.68, slot: 'bush' },
    { texture: rockTexture, ratio: -0.34, z: -4.6, h: 0.42, slot: 'rock' },
    // 行走带近缘的灌木/岩石（z -2.2..-3.0，角色近景参照物）
    // 注：-0.62 是冰湖贴片位（z -4.0），灌木别压上去
    { texture: bushTextureB, ratio: -0.18, z: -2.8, h: 0.55, slot: 'bush' },
    { texture: rockTexture, ratio: 0.58, z: -2.2, h: 0.45, slot: 'rock' },
    { texture: bushTextureA, ratio: 0.72, z: -3.0, h: 0.62, slot: 'bush' },
    { texture: bushTextureA, ratio: -0.4, z: -4.5, h: 4.2, slot: 'treeA', bury: 0.03 },
    { texture: bushTextureB, ratio: 0.44, z: -3.2, h: 3.3, slot: 'treeB', bury: 0.03 },
    { texture: bushTextureA, ratio: 0.8, z: -6.5, h: 3.0, slot: 'treeA', bury: 0.03, mirror: true },
    // 雪境新道具：冰井（行走带旁）与木栅栏（中景左缘横栏）
    { texture: rockTexture, ratio: 0.68, z: -3.8, h: 1.15, slot: 'well', bury: 0.04 },
    { texture: bushTextureA, ratio: -0.75, z: -6.4, h: 0.62, slot: 'fence', bury: 0.1 },
  ]
  const midPropMeshes: Array<{ mesh: THREE.Mesh; slot: 'bush' | 'rock' | 'treeA' | 'treeB' | 'well' | 'fence'; h: number; mirror: boolean }> = []
  for (const prop of midProps) {
    if (!prop.texture) continue
    track(prop.texture)
    const material = track(
      new THREE.MeshBasicMaterial({ map: prop.texture, transparent: true }),
    )
    palette.register(material.color, SNOW_TINT.props)
    const mesh = new THREE.Mesh(track(new THREE.PlaneGeometry(1, 1)), material)
    const width = (prop.texture.image.width / prop.texture.image.height) * prop.h
    mesh.scale.set(prop.mirror ? -width : width, prop.h, 1)
    mesh.position.set(0, prop.h / 2 - prop.h * (prop.bury ?? 0.16), prop.z)
    billboards.push({ mesh, ratio: prop.ratio, z: prop.z, widthFactor: 0 })
    midPropMeshes.push({ mesh, slot: prop.slot, h: prop.h, mirror: prop.mirror ?? false })
    scene.add(mesh)
  }

  /* ── 地面（草地整幅纹理，雾负责远处融合） ── */
  const groundTexture = rgbaToTexture(grassField(0x677, 640, 352))
  let groundMesh: THREE.Mesh | null = null
  let groundMaterial: THREE.MeshBasicMaterial | null = null
  if (groundTexture) {
    track(groundTexture)
    const material = track(new THREE.MeshBasicMaterial({ map: groundTexture }))
    groundMaterial = material
    palette.register(material.color, SNOW_TINT.ground)
    groundMesh = new THREE.Mesh(track(new THREE.PlaneGeometry(1, 1)), material)
    groundMesh.rotation.x = -Math.PI / 2
    // 覆盖到相机底缘视线落点（z≈7.4）之外：z ∈ [-30, 10]
    groundMesh.position.set(0, 0, -10)
    scene.add(groundMesh)
  }

  /* ── 土径（横贯行走带） ── */
  const pathTexture = rgbaToTexture(dirtPath(0x788, 512, 48))
  let pathMesh: THREE.Mesh | null = null
  let pathMaterial: THREE.MeshBasicMaterial | null = null
  if (pathTexture) {
    track(pathTexture)
    const material = track(
      new THREE.MeshBasicMaterial({ map: pathTexture, transparent: true, depthWrite: false }),
    )
    pathMaterial = material
    palette.register(material.color, SNOW_TINT.path)
    pathMesh = new THREE.Mesh(track(new THREE.PlaneGeometry(1, 1)), material)
    pathMesh.rotation.x = -Math.PI / 2
    pathMesh.position.set(0, 0.02, STAGE_Z.path)
    pathMesh.scale.set(1, 3.8, 1)
    pathMesh.renderOrder = 1
    scene.add(pathMesh)
  }

  /* ── 前景草（近镜散景带，宽度平铺防拉伸；贴近相机底缘、顶边约屏高 71% 处） ── */
  const fgTexture = rgbaToTexture(foregroundGrass(0x899, 512, 96), { repeat: true })
  let fgMesh: THREE.Mesh | null = null
  let fgMaterial: THREE.MeshBasicMaterial | null = null
  if (fgTexture) {
    track(fgTexture)
    const material = track(
      new THREE.MeshBasicMaterial({ map: fgTexture, transparent: true, depthWrite: false }),
    )
    fgMaterial = material
    palette.register(material.color, SNOW_TINT.fg)
    fgMesh = new THREE.Mesh(track(new THREE.PlaneGeometry(1, 1)), material)
    fgMesh.position.set(0, 0.35, STAGE_Z.grassFg)
    fgMesh.scale.set(1, 1.4, 1)
    scene.add(fgMesh)
  }

  /* ── 路灯环境部件（halo + HDR 灯芯 + 地面光池） ── */
  const glowHaloTexture = rgbaToTexture(radialGlow(64, 2.0))
  const glowCoreTexture = rgbaToTexture(radialGlow(32, 1.4))
  const poolTexture = rgbaToTexture(radialGlow(64, 2.6))
  for (const tex of [glowHaloTexture, glowCoreTexture, poolTexture]) {
    if (tex) track(tex)
  }
  const lampEntries: Array<{ ratio: number; meshes: THREE.Mesh[] }> = []
  const lamps: LampEnvHandle[] = []
  const addLamp = (ratio: number): LampEnvHandle => {
    const x = worldXAt(ratio, STAGE_Z.lamp)
    // 默认灯头高（桌面视口校准值；编排器 resize 时按精灵换算率经 setHeadWorldY 精调）
    const headY = 1.24
    const haloMaterial = track(
      new THREE.MeshBasicMaterial({
        map: glowHaloTexture ?? null,
        transparent: true,
        opacity: 0,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      }),
    )
    haloMaterial.color.set('#ffca7a').multiplyScalar(1.35)
    const halo = new THREE.Mesh(track(new THREE.PlaneGeometry(1, 1)), haloMaterial)
    halo.position.set(x, headY, STAGE_Z.lamp)
    halo.scale.set(2.6, 2.6, 1)
    halo.renderOrder = 6
    scene.add(halo)

    const coreMaterial = track(
      new THREE.MeshBasicMaterial({
        map: glowCoreTexture ?? null,
        transparent: true,
        opacity: 0,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      }),
    )
    coreMaterial.color.set('#ffca7a').multiplyScalar(2.4)
    const core = new THREE.Mesh(track(new THREE.PlaneGeometry(1, 1)), coreMaterial)
    core.position.set(x, headY, STAGE_Z.lamp + 0.02)
    core.scale.set(0.5, 0.5, 1)
    core.renderOrder = 7
    scene.add(core)

    const poolMaterial = track(
      new THREE.MeshBasicMaterial({
        map: poolTexture ?? null,
        transparent: true,
        opacity: 0,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      }),
    )
    poolMaterial.color.set('#ffca7a')
    const pool = new THREE.Mesh(track(new THREE.PlaneGeometry(1, 1)), poolMaterial)
    pool.rotation.x = -Math.PI / 2
    pool.position.set(x, 0.03, STAGE_Z.lamp + 0.4)
    pool.scale.set(4.2, 2.0, 1)
    pool.renderOrder = 2
    scene.add(pool)

    const handle: LampEnvHandle = {
      setGlow(strength: number) {
        haloMaterial.opacity = 0.62 * strength
        coreMaterial.opacity = 0.9 * strength
        poolMaterial.opacity = 0.42 * strength
      },
      setHeadWorldY(y: number) {
        halo.position.y = y
        core.position.y = y
      },
    }
    lamps.push(handle)
    lampEntries.push({ ratio, meshes: [halo, core, pool] })
    return handle
  }

  /* ── 角色方向影 ── */
  const shadowTexture = rgbaToTexture(radialGlow(32, 1.6))
  if (shadowTexture) track(shadowTexture)
  const shadowState = { dirX: 1, length: 1.2, opacity: 0.3 }
  const shadows = new Set<THREE.Mesh>()
  const acquireShadow = (): THREE.Mesh => {
    const material = track(
      new THREE.MeshBasicMaterial({
        map: shadowTexture ?? null,
        transparent: true,
        opacity: shadowState.opacity,
        depthWrite: false,
      }),
    )
    palette.register(material.color, SNOW_SHADOW)
    const mesh = new THREE.Mesh(track(new THREE.PlaneGeometry(1, 1)), material)
    mesh.rotation.x = -Math.PI / 2
    mesh.renderOrder = 1
    scene.add(mesh)
    shadows.add(mesh)
    return mesh
  }
  const placeShadow = (shadow: THREE.Mesh, worldX: number, worldZ: number, baseScale: number): void => {
    const len = shadowState.length * baseScale
    const dirZ = 0.3
    const angle = Math.atan2(dirZ, shadowState.dirX)
    shadow.position.set(
      worldX + (shadowState.dirX * len) / 2.6,
      0.025,
      worldZ + (dirZ * len) / 4,
    )
    shadow.rotation.z = -angle
    shadow.scale.set(len, baseScale * 0.52, 1)
  }
  const releaseShadow = (shadow: THREE.Mesh): void => {
    shadows.delete(shadow)
    scene.remove(shadow)
    const material = shadow.material as THREE.MeshBasicMaterial
    material.dispose()
    shadow.geometry.dispose()
  }

  /* ── 布局：宽度随可视域自适应 ── */
  const resize = (cssWidth: number, cssHeight: number): void => {
    const safeH = Math.max(1, cssHeight)
    lastCss.w = cssWidth
    lastCss.h = cssHeight
    camera.aspect = Math.max(1, cssWidth) / safeH
    camera.updateProjectionMatrix()
    const stageHalfW = Math.max(16, visibleHalfWidthAt(camera, viewDistanceAt(STAGE_Z.sky)) * 1.2)
    const stageW = stageHalfW * 2
    skyMesh.scale.set(stageW, 6.5, 1)
    skyUniforms.uPlaneAspect.value = stageW / 6.5
    if (groundMesh) groundMesh.scale.set(stageW, 40, 1)
    // AI 地面按 ~9 世界单位一块平铺（MirroredRepeat），避免整幅拉伸把草叶抹成糊
    if (aiGround) aiGround.repeat.set(stageW / 9, 40 / 9)
    if (pathMesh) pathMesh.scale.x = stageW
    if (fgMesh && fgTexture) {
      fgMesh.scale.x = stageW
      // AI 前景草纵横比 2:1，按 ~7 世界单位一簇平铺；程序化稿维持原 24
      ;(aiFg ?? fgTexture).repeat.set(stageW / (aiFg ? 7 : 24), 1)
    }
    for (const billboard of billboards) {
      if (billboard.widthFactor > 0) {
        billboard.mesh.scale.x = stageW * billboard.widthFactor * 0.5
      }
      if (billboard.ratio !== undefined) {
        billboard.mesh.position.x = worldXAt(billboard.ratio, billboard.z)
      }
    }
    // AI 纵深带：网格仍铺满目标宽，纹理按素材纵横比 RepeatWrapping 平铺保比例
    for (const band of aiBands) {
      const targetW = stageW * band.widthFactor * 0.5
      const naturalW = band.heightWorld * band.aspect
      const rep = Math.max(1, targetW / naturalW)
      for (const tex of band.textures) tex.repeat.x = rep
    }
    // 灯随可视宽重摆（halo/core 在原 z，pool 略靠前）
    for (const entry of lampEntries) {
      const x = worldXAt(entry.ratio, STAGE_Z.lamp)
      entry.meshes[0]!.position.x = x
      entry.meshes[1]!.position.x = x
      entry.meshes[2]!.position.x = x
    }
    // 落雪覆盖域：横宽取树线处可视半宽（远端屏宽最大），点大小随视口高度换算
    snowUniforms.uBounds.value.x = visibleHalfWidthAt(camera, viewDistanceAt(STAGE_Z.treeLine)) * 1.05
    snowUniforms.uPointScale.value = (safeH * 1.0) / (2 * Math.tan((ENV_CAMERA.fov * Math.PI) / 360))
  }

  /* ── AI 环境美术换装：map 直换（MeshBasicMaterial 已有 map，着色器定义不变） ── */
  const texAspect = (tex: THREE.Texture): number => {
    const img = tex.image as { width: number; height: number }
    return img.width / img.height
  }
  void loadEnvArt()
    .then((art) => {
      if (disposed) return
      for (const tex of Object.values(art)) track(tex)
      const swap = (material: THREE.MeshBasicMaterial | null, tex: THREE.Texture): void => {
        if (!material) return
        material.map = tex
        material.needsUpdate = true
      }
      swap(groundMaterial, art.grass)
      aiGround = art.grass
      swap(pathMaterial, art.path)
      swap(fgMaterial, art.fggrass)
      aiFg = art.fggrass
      if (hillsMesh) {
        swap(hillsMesh.material as THREE.MeshBasicMaterial, art.hills)
        aiBands.push({ textures: [art.hills], aspect: texAspect(art.hills), heightWorld: 3.3, widthFactor: 1.35 })
      }
      if (villageMesh) {
        swap(villageMesh.material as THREE.MeshBasicMaterial, art.village)
        const band = { textures: [art.village], aspect: texAspect(art.village), heightWorld: 2.3, widthFactor: 1.1 }
        if (windowsMesh) {
          swap(windowsMesh.material as THREE.MeshBasicMaterial, art.villageWindows)
          band.textures.push(art.villageWindows)
        }
        aiBands.push(band)
      }
      if (treeLineMesh) {
        swap(treeLineMesh.material as THREE.MeshBasicMaterial, art.treeline)
        aiBands.push({ textures: [art.treeline], aspect: texAspect(art.treeline), heightWorld: 2.1, widthFactor: 1.2 })
      }
      for (const prop of midPropMeshes) {
        const tex =
          prop.slot === 'bush'
            ? art.bush
            : prop.slot === 'rock'
              ? art.rock
              : prop.slot === 'treeA'
                ? art.treeA
                : prop.slot === 'treeB'
                  ? art.treeB
                  : prop.slot === 'well'
                    ? art.well
                    : art.fence
        swap(prop.mesh.material as THREE.MeshBasicMaterial, tex)
        const w = texAspect(tex) * prop.h
        prop.mesh.scale.x = prop.mirror ? -w : w
      }
      // 冰湖：地面贴片（XZ 平躺， Clamp 单幅，不重复；霜花纹理不烤进地面层以保冰面完整）
      {
        const material = track(
          new THREE.MeshBasicMaterial({ map: art.pond, transparent: true, depthWrite: false }),
        )
        palette.register(material.color, SNOW_TINT.pond)
        const mesh = new THREE.Mesh(track(new THREE.PlaneGeometry(1, 1)), material)
        mesh.rotation.x = -Math.PI / 2
        mesh.position.set(worldXAt(-0.62, -4.0), 0.015, -4.0)
        mesh.scale.set(2.6, 2.0, 1)
        mesh.renderOrder = 1
        billboards.push({ mesh, ratio: -0.62, z: -4.0, widthFactor: 0 })
        scene.add(mesh)
      }
      // 换装后按当前视口重算平铺（resize 可能已在解码前跑过）
      if (lastCss.w > 0) resize(lastCss.w, lastCss.h)
    })
    .catch(() => {
      // 素材缺失/解码失败：保留程序化稿，场景照常运行
    })

  /* ── 昼夜 ── */
  const setDay = (day: number): void => {
    palette.apply(day)
    skyUniforms.uDay.value = day
    skyUniforms.uDusk.value = duskAmount(day)
    if (windowsMesh) {
      ;(windowsMesh.material as THREE.MeshBasicMaterial).opacity =
        0.9 * (1 - smoothstep(0.3, 0.5, day))
    }
    // 影：上午太阳在左→影朝右；正午短而正；黄昏长斜；夜间弱而短
    const sunT = Math.min(1, Math.max(0, (day - 0.52) / 0.48))
    const moonT = Math.min(1, Math.max(0, (0.48 - day) / 0.48))
    if (day >= 0.5) {
      shadowState.dirX = -(sunT - 0.5) * 2 || 1
      shadowState.length = 0.85 + (1 - Math.sin(sunT * Math.PI)) * 1.7
      shadowState.opacity = 0.42
    } else {
      shadowState.dirX = (moonT - 0.5) * 2 || 1
      shadowState.length = 0.8 + (1 - Math.sin(moonT * Math.PI)) * 0.7
      shadowState.opacity = 0.22
    }
    for (const shadow of shadows) {
      ;(shadow.material as THREE.MeshBasicMaterial).opacity = shadowState.opacity
    }
  }

  const setPointer = (nx: number, ny: number): void => {
    skyUniforms.uPointer.value.set(nx, ny)
  }

  const tick = (time: number): void => {
    skyUniforms.uTime.value = time
    snowUniforms.uTime.value = time
  }

  const dispose = (): void => {
    disposed = true
    palette.dispose()
    for (const resource of disposables.splice(0)) resource.dispose()
    scene.fog = null
  }

  return {
    scene,
    camera,
    palette,
    worldXAt,
    addLamp,
    acquireShadow,
    placeShadow,
    releaseShadow,
    setDay,
    setPointer,
    tick,
    resize,
    dispose,
  }
}
