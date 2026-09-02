/**
 * 像素锁定低分渲染管线。
 * 整个 composer 运行在低分辨率缓冲（~230px 高、整数倍率），canvas 以
 * `image-rendering: pixelated` 由浏览器做最近邻整数放大——1 美术像素恒等于
 * 整数个屏幕像素（pixel-art 红线：任何小数倍拉伸都会打出 2,3,2,3 的脏像素）。
 *
 * r180 注意：EffectComposer 内部 renderTarget1/2 默认 LinearFilter，必须在首次
 * 渲染前强制 NearestFilter + needsUpdate，否则 bloom/混合采样会把像素糊掉。
 *
 * 色调映射默认 NoToneMapping：手工 sRGB 色板经 OutputPass 精确往返；灯芯/天体
 * 核以 >1.0 的 HDR 颜色（HalfFloat RT 承载）越过 bloom 阈值发光。
 */
import * as THREE from 'three'
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js'
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js'
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js'
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js'
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js'

export const PIXEL_SCALE_MIN = 2
export const PIXEL_SCALE_MAX = 6
/** 低分缓冲目标高度（美术像素） */
export const PIXEL_TARGET_HEIGHT = 230
/** 边缘融合宽度（占短边比例） */
export const EDGE_BLEND_RATIO = 0.06

/** 整数倍率：容器高 ÷ 目标低分高，四舍五入后钳制到 [2, 6] */
export const computePixelScale = (rawHeight: number): number => {
  if (!Number.isFinite(rawHeight) || rawHeight <= 0) return PIXEL_SCALE_MIN
  return Math.min(
    PIXEL_SCALE_MAX,
    Math.max(PIXEL_SCALE_MIN, Math.round(rawHeight / PIXEL_TARGET_HEIGHT)),
  )
}

/**
 * 收尾边缘融合：最外 ~6% 边缘向 uPaper 混合，1px 有序抖动边界防色带。
 * 位于 OutputPass 之前（线性空间）；uPaper 经 THREE.Color 自动转线性，
 * 编码后边缘像素 = CSS token 精确值。
 */
const EdgeBlendShader = {
  uniforms: {
    tDiffuse: { value: null as THREE.Texture | null },
    uPaper: { value: new THREE.Color('#fffefa') },
    uEdge: { value: EDGE_BLEND_RATIO },
  },
  vertexShader: /* glsl */ `
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,
  fragmentShader: /* glsl */ `
    uniform sampler2D tDiffuse;
    uniform vec3 uPaper;
    uniform float uEdge;
    varying vec2 vUv;

    // GLSL1 可用的有序抖动（无位运算）：2x2 → 4x4 递归
    float bayer2(vec2 a) {
      a = floor(a);
      return fract(a.x / 2.0 + a.y * a.y * 0.75);
    }
    float bayer4(vec2 a) {
      return bayer2(0.5 * a) * 0.25 + bayer2(a);
    }

    void main() {
      vec4 color = texture2D(tDiffuse, vUv);
      vec2 edgeDist = min(vUv, 1.0 - vUv);
      float d = min(edgeDist.x, edgeDist.y);
      float dither = (bayer4(gl_FragCoord.xy) - 0.5) * (1.0 / 32.0);
      float t = smoothstep(0.0, uEdge, d + dither * uEdge);
      gl_FragColor = vec4(mix(uPaper, color.rgb, t), color.a);
    }
  `,
}

export interface PixelPipelineSize {
  scale: number
  lowW: number
  lowH: number
}

export interface PixelPipeline {
  readonly composer: EffectComposer
  readonly bloomPass: UnrealBloomPass
  /** 当前整数倍率与低分尺寸（只读快照，resize 后更新） */
  readonly size: PixelPipelineSize
  /** 边缘融合目标色（线性空间自动转换） */
  setPaper(color: string | THREE.Color): void
  /** bloom 强度（昼 0.15 → 夜 0.55，编排器逐帧插值） */
  setBloom(strength: number): void
  /** 按容器 CSS 尺寸重设；返回新的低分尺寸 */
  setSize(cssWidth: number, cssHeight: number): PixelPipelineSize
  dispose(): void
}

export interface PixelPipelineOptions {
  renderer: THREE.WebGLRenderer
  scene: THREE.Scene
  camera: THREE.Camera
  canvas: HTMLCanvasElement
  paper: string
  /** 留一手切回 ACES 的开关（默认 NoToneMapping 保色板精确往返） */
  toneMapping?: 'none' | 'aces'
}

export const createPixelPipeline = (opts: PixelPipelineOptions): PixelPipeline => {
  const { renderer, scene, camera, canvas } = opts
  renderer.toneMapping = opts.toneMapping === 'aces' ? THREE.ACESFilmicToneMapping : THREE.NoToneMapping

  const composer = new EffectComposer(renderer)
  composer.setPixelRatio(1)

  // r180：内部 RT 默认 LinearFilter，首次渲染前强制 NearestFilter
  for (const rt of [composer.renderTarget1, composer.renderTarget2]) {
    rt.texture.magFilter = THREE.NearestFilter
    rt.texture.minFilter = THREE.NearestFilter
    rt.texture.needsUpdate = true
  }

  const renderPass = new RenderPass(scene, camera)
  const bloomPass = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.15, 0.32, 0.85)
  const edgeBlendPass = new ShaderPass(EdgeBlendShader)
  const outputPass = new OutputPass()

  composer.addPass(renderPass)
  composer.addPass(bloomPass)
  composer.addPass(edgeBlendPass)
  composer.addPass(outputPass)

  const state: PixelPipelineSize = { scale: PIXEL_SCALE_MIN, lowW: 2, lowH: 2 }

  const setPaper = (color: string | THREE.Color): void => {
    const paper = typeof color === 'string' ? new THREE.Color(color) : color
    ;(edgeBlendPass.uniforms.uPaper as { value: THREE.Color }).value.copy(paper)
    renderer.setClearColor(paper, 1)
  }
  setPaper(opts.paper)

  const setSize = (cssWidth: number, cssHeight: number): PixelPipelineSize => {
    const scale = computePixelScale(cssHeight)
    const lowW = Math.max(2, Math.floor(cssWidth / scale))
    const lowH = Math.max(2, Math.floor(cssHeight / scale))
    state.scale = scale
    state.lowW = lowW
    state.lowH = lowH

    // 缓冲 = 低分尺寸；CSS = 整数倍放大并居中（余量由页面纸色吸收）。
    // r180 的 EffectComposer.setSize 不动 renderer 画布缓冲，必须自己钉死：
    // 否则最终 OutputPass 仍按 300×150 默认缓冲出图，像素锁定全线失效。
    renderer.setPixelRatio(1)
    renderer.setSize(lowW, lowH, false)
    composer.setSize(lowW, lowH)
    bloomPass.resolution.set(lowW, lowH)
    canvas.style.width = `${lowW * scale}px`
    canvas.style.height = `${lowH * scale}px`
    return { ...state }
  }

  return {
    composer,
    bloomPass,
    get size() {
      return { ...state }
    },
    setPaper,
    setSize,
    setBloom(strength) {
      bloomPass.strength = strength
    },
    dispose() {
      edgeBlendPass.dispose()
      bloomPass.dispose()
      renderPass.dispose()
      outputPass.dispose()
      composer.dispose()
    },
  }
}
