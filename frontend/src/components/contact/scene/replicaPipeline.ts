/**
 * HD-2D 混合分辨率渲染管线（复刻八方旅人技法的核心）：
 *
 *   环境层 composerEnv（0.5×CSS，Linear，HalfFloat）:
 *     RenderPass(envScene 透视真深度) → BokehShader(自定义深度) → UnrealBloomPass
 *   精灵层 rtSprite（低分整数格，Nearest，透明清屏，无深度——画家算法）
 *   合成 composerFinal（全 CSS 分辨率）:
 *     CompositePass(tEnv×tSprite 整数格最近邻采样) → EdgeBlend(uPaper) → OutputPass
 *
 * 关键决策：
 * - 不用 BokehPass：其内部 MeshDepthMaterial override 忽略 map/alphaTest，
 *   alpha 贴图 billboard 会得到矩形散景光斑；这里每帧手动换材质渲深度
 *   （透明 billboard 用 map+alphaTest=0.5 的专属 MeshDepthMaterial）。
 * - NoToneMapping：手工 sRGB 色板经 OutputPass 精确往返；HDR 灯芯/日月核
 *   （>1.0，HalfFloat RT 承载）越 bloom 阈值发光。
 * - 精灵整数像素不由相机放大保证，而由 CompositeShader 的 floor 取格保证。
 */
import * as THREE from 'three'
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js'
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js'
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js'
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js'
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js'
import { BokehShader } from 'three/addons/shaders/BokehShader.js'
import { EdgeBlendShader } from './pixelPipeline'
import type { ArtGrid } from './project'

/** 合成：tEnv 平滑底图 + tSprite 整数格最近邻叠层（格域外恒透明） */
const CompositeShader = {
  uniforms: {
    tDiffuse: { value: null as THREE.Texture | null }, // ShaderPass 自动绑定（弃用）
    tEnv: { value: null as THREE.Texture | null },
    tSprite: { value: null as THREE.Texture | null },
    uResolution: { value: new THREE.Vector2(1, 1) }, // CSS 像素
    uGridSize: { value: new THREE.Vector2(1, 1) }, // 美术格
    uGridOffset: { value: new THREE.Vector2(0, 0) }, // CSS 像素
    uScale: { value: 3 },
  },
  vertexShader: /* glsl */ `
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,
  fragmentShader: /* glsl */ `
    uniform sampler2D tEnv;
    uniform sampler2D tSprite;
    uniform vec2 uResolution;
    uniform vec2 uGridSize;
    uniform vec2 uGridOffset;
    uniform float uScale;
    varying vec2 vUv;

    void main() {
      vec4 env = texture2D(tEnv, vUv);
      // 整数格映射：CSS 像素 → 美术格 texel 中心（红线：floor，绝不在格间插值）
      vec2 frag = vUv * uResolution;
      vec2 sprF = (frag - uGridOffset) / uScale;
      vec4 spr = vec4(0.0);
      if (sprF.x >= 0.0 && sprF.y >= 0.0 && sprF.x < uGridSize.x && sprF.y < uGridSize.y) {
        vec2 texel = (floor(sprF) + 0.5) / uGridSize;
        spr = texture2D(tSprite, texel);
      }
      gl_FragColor = vec4(mix(env.rgb, spr.rgb, spr.a), 1.0);
    }
  `,
}

export interface ReplicaPipelineOptions {
  canvas: HTMLCanvasElement
  envScene: THREE.Scene
  envCamera: THREE.PerspectiveCamera
  spriteScene: THREE.Scene
  spriteCamera: THREE.OrthographicCamera
  /** 边缘融合/清屏目标色（--contact-scene-bg 解析值） */
  paper: string
  /** 焦点距离（行走带到相机） */
  focus: number
  /** high=桌面全效果；low=移动端弱散景 */
  quality?: 'high' | 'low'
}

export interface ReplicaPipeline {
  readonly renderer: THREE.WebGLRenderer
  /** bloom 强度（昼 0.15 → 夜 0.55，编排器插值） */
  setBloom(strength: number): void
  setPaper(color: string): void
  setSize(cssWidth: number, cssHeight: number, grid: ArtGrid): void
  /** 自适应降档（一次性）：env 0.5→0.4×、弱散景——软渲染/弱 GPU 保帧率 */
  degrade(): void
  /** 逐帧：深度→环境链→精灵 RT→合成到屏 */
  render(): void
  dispose(): void
}

/**
 * 降级判定（纯函数，可测）：预热 60 帧后每 45 帧评估一次，EMA 帧耗 >40ms
 * （≈稳态 <25fps）即降一档——躲开 RT 分配/纹理上传的首帧尖峰；
 * 编排器重复调用，管线内部分两段（0.4×+弱散景 → 关散景）逐档生效
 */
export const shouldDegrade = (emaMs: number, framesSeen: number): boolean =>
  framesSeen >= 60 && framesSeen % 45 === 0 && emaMs > 40

export const createReplicaPipeline = (opts: ReplicaPipelineOptions): ReplicaPipeline => {
  const { canvas, envScene, envCamera, spriteScene, spriteCamera } = opts
  let quality = opts.quality ?? 'high'

  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: false,
    alpha: false,
    powerPreference: 'default',
  })
  renderer.toneMapping = THREE.NoToneMapping
  renderer.setPixelRatio(1)

  /* ── 环境链（半分辨率） ── */
  const composerEnv = new EffectComposer(renderer)
  composerEnv.renderToScreen = false
  composerEnv.setPixelRatio(1)

  const renderPass = new RenderPass(envScene, envCamera)
  const bokehPass = new ShaderPass(BokehShader, 'tColor')
  bokehPass.uniforms.focus!.value = opts.focus
  bokehPass.uniforms.nearClip!.value = envCamera.near
  bokehPass.uniforms.farClip!.value = envCamera.far
  bokehPass.uniforms.aperture!.value = quality === 'high' ? 0.004 : 0.0022
  bokehPass.uniforms.maxblur!.value = quality === 'high' ? 0.011 : 0.006

  const bloomPass = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.15, 0.42, 1.0)

  composerEnv.addPass(renderPass)
  composerEnv.addPass(bokehPass)
  composerEnv.addPass(bloomPass)

  /** 自定义深度 RT（RGBADepthPacking，BokehShader DEPTH_PACKING=1 对应） */
  const rtDepth = new THREE.WebGLRenderTarget(2, 2, {
    minFilter: THREE.NearestFilter,
    magFilter: THREE.NearestFilter,
    depthBuffer: true,
  })
  bokehPass.uniforms.tDepth!.value = rtDepth.texture

  const depthMaterialOpaque = new THREE.MeshDepthMaterial({
    depthPacking: THREE.RGBADepthPacking,
  })
  const depthMaterialsByMap = new Map<THREE.Texture, THREE.MeshDepthMaterial>()
  const depthMaterialFor = (material: THREE.Material): THREE.MeshDepthMaterial => {
    const basic = material as THREE.MeshBasicMaterial
    if (basic.isMeshBasicMaterial && basic.map && basic.transparent) {
      let dm = depthMaterialsByMap.get(basic.map)
      if (!dm) {
        dm = new THREE.MeshDepthMaterial({
          depthPacking: THREE.RGBADepthPacking,
          map: basic.map,
          alphaTest: 0.5,
        })
        depthMaterialsByMap.set(basic.map, dm)
      }
      return dm
    }
    return depthMaterialOpaque
  }
  const swapped: Array<{ mesh: THREE.Mesh; material: THREE.Material | THREE.Material[] }> = []
  const renderDepth = (): void => {
    envScene.traverse((obj) => {
      const mesh = obj as THREE.Mesh
      if (!mesh.isMesh) return
      swapped.push({ mesh, material: mesh.material })
      mesh.material = depthMaterialFor(
        Array.isArray(mesh.material) ? mesh.material[0]! : mesh.material,
      )
    })
    renderer.setRenderTarget(rtDepth)
    renderer.setClearColor(0xffffff, 1) // 空域 = 远平面 = 最大散景
    renderer.clear(true, true)
    renderer.render(envScene, envCamera)
    renderer.setRenderTarget(null)
    renderer.setClearColor(paper, 1) // 复原：随后的 composerEnv RenderPass 沿用当前清屏色
    for (let i = swapped.length - 1; i >= 0; i--) {
      const entry = swapped[i]!
      entry.mesh.material = entry.material
    }
    swapped.length = 0
  }

  /* ── 精灵 RT（低分整数格，透明） ── */
  const rtSprite = new THREE.WebGLRenderTarget(2, 2, {
    minFilter: THREE.NearestFilter,
    magFilter: THREE.NearestFilter,
    depthBuffer: false,
    generateMipmaps: false,
  })

  /* ── 合成链（全分辨率） ── */
  const composerFinal = new EffectComposer(renderer)
  composerFinal.setPixelRatio(1)

  const compositePass = new ShaderPass(CompositeShader)
  compositePass.uniforms.tSprite!.value = rtSprite.texture
  const edgeBlendPass = new ShaderPass(EdgeBlendShader)
  const outputPass = new OutputPass()
  composerFinal.addPass(compositePass)
  composerFinal.addPass(edgeBlendPass)
  composerFinal.addPass(outputPass)

  let paper = new THREE.Color(opts.paper)
  renderer.setClearColor(paper, 1)
  let lastSize: { cssWidth: number; cssHeight: number; grid: ArtGrid } | null = null
  let degradeStage = 0

  const setSize = (cssWidth: number, cssHeight: number, grid: ArtGrid): void => {
    lastSize = { cssWidth, cssHeight, grid }
    const cssW = Math.max(2, Math.floor(cssWidth))
    const cssH = Math.max(2, Math.floor(cssHeight))
    renderer.setPixelRatio(1)
    renderer.setSize(cssW, cssH, false)
    const envW = Math.max(2, Math.floor(cssW * (quality === 'high' ? 0.5 : 0.4)))
    const envH = Math.max(2, Math.floor(cssH * (quality === 'high' ? 0.5 : 0.4)))
    composerEnv.setSize(envW, envH)
    rtDepth.setSize(envW, envH)
    rtSprite.setSize(grid.lowW, grid.lowH)
    composerFinal.setSize(cssW, cssH)
    bokehPass.uniforms.aspect!.value = cssW / cssH
    compositePass.uniforms.uResolution!.value.set(cssW, cssH)
    compositePass.uniforms.uGridSize!.value.set(grid.lowW, grid.lowH)
    compositePass.uniforms.uGridOffset!.value.set(grid.offsetX, grid.offsetY)
    compositePass.uniforms.uScale!.value = grid.scale
  }

  const render = (): void => {
    if (bokehPass.enabled) renderDepth()
    composerEnv.render()
    // 精灵层：透明清屏 + 画家算法（无深度）
    renderer.setRenderTarget(rtSprite)
    renderer.setClearColor(0x000000, 0)
    renderer.clear(true, false)
    renderer.render(spriteScene, spriteCamera)
    renderer.setRenderTarget(null)
    renderer.setClearColor(paper, 1)
    // 环境结果经 uniform 进入合成（readBuffer 身份逐帧交替，引用必须每帧刷新）
    compositePass.uniforms.tEnv!.value = composerEnv.readBuffer.texture
    composerFinal.render()
  }

  return {
    renderer,
    setBloom(strength) {
      bloomPass.strength = strength
    },
    setPaper(color: string) {
      paper = new THREE.Color(color)
      ;(edgeBlendPass.uniforms.uPaper as { value: THREE.Color }).value.copy(paper)
      renderer.setClearColor(paper, 1)
    },
    setSize,
    degrade() {
      if (degradeStage === 0) {
        // 一档：等效 mobile low——env 0.4×、弱散景
        quality = 'low'
        bokehPass.uniforms.aperture!.value = 0.0022
        bokehPass.uniforms.maxblur!.value = 0.006
        if (lastSize) setSize(lastSize.cssWidth, lastSize.cssHeight, lastSize.grid)
        degradeStage = 1
      } else if (degradeStage === 1) {
        // 二档：关散景（连带跳过逐帧深度 RT 渲——环境层省一遍全场景光栅）
        bokehPass.enabled = false
        degradeStage = 2
      }
    },
    render,
    dispose() {
      renderPass.dispose()
      bokehPass.dispose()
      bloomPass.dispose()
      compositePass.dispose()
      edgeBlendPass.dispose()
      outputPass.dispose()
      composerEnv.dispose()
      composerFinal.dispose()
      rtDepth.dispose()
      rtSprite.dispose()
      depthMaterialOpaque.dispose()
      for (const dm of depthMaterialsByMap.values()) dm.dispose()
      depthMaterialsByMap.clear()
      renderer.dispose()
    },
  }
}
