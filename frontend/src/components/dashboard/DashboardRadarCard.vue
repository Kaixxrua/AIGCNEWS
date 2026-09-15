<script setup lang="ts">
/**
 * 仪表盘侧栏末端纯装饰卡：AIGC Radar 雷达扫掠，Three.js + WebGL2 实时渲染。
 * 纯装饰（aria-hidden），生命周期自包含，约定与 ContactHeroVisual 对齐：
 * - 仅探测 webgl2 上下文；不可用 / 上下文丢失 / three 加载失败 → 露出底层静态 CSS 兜底
 * - reduced-motion 不启动 RAF，只渲染冻结静帧（扫掠停在 215°，与兜底同构图）
 * - 光点位置由 seedDate 哈希驱动（翻日历 = 换一天的信号分布）；查看当日时角标显示 LIVE
 * - 交互：指针移动 → 盘面朝指针 3D 倾斜（阻尼跟随）+ 指针方位淡色高亮扇面；
 *   点击 → 从点击处扩散 ping 涟漪并点亮附近光点
 * - 单 quad 自定义 shader 画同心圆/刻度/扫掠尾迹/光点，外层 mesh 做透视倾斜——一次 draw call；
 *   主题色经 getComputedStyle 读 token 注入 uniform（深浅色自动跟随）；
 *   DPR 上限、离屏（IntersectionObserver）/KeepAlive 停用暂停、卸载全量 dispose
 */
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import type { Mesh, PerspectiveCamera, ShaderMaterial, WebGLRenderer } from 'three'

const props = withDefaults(defineProps<{ seedDate: string; live?: boolean }>(), { live: false })

const rootRef = ref<HTMLDivElement | null>(null)
const canvasRef = ref<HTMLCanvasElement | null>(null)
/** 首帧已上屏后才淡入 canvas，盖住静态兜底 */
const renderLive = ref(false)
/** 紧凑模式：卡片高度低于阈值时隐藏 caption，避免文字压住迷你雷达（对齐排名榜底边后卡片可能很矮） */
const isShort = ref(false)
const SHORT_HEIGHT_THRESHOLD = 150

/** 当日查看 → LIVE；历史日期 → MM/DD */
const caption = computed(() => (props.live ? 'LIVE' : props.seedDate.slice(5).replace('-', '/')))

/** YYYY-MM-DD → [0,1) 稳定哈希，驱动 shader 内光点分布（每日一幅） */
const hashSeed = (s: string): number => {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return (h >>> 0) / 4294967296
}

const VERTEX_SHADER = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`

/* 雷达示波器：极坐标网格 + 表圈刻度 + 扫掠尾迹（指数余辉）+ 日期种子光点。
 * 坐标约定：p 为"半短边=1"的方形坐标，表圈半径 R=0.88，任意长宽比下正圆不裁切。
 * GLSL1 语法跑在 WebGL2 上下文上（three r163+ 只创建 WebGL2 context）；
 * 结尾 colorspace_fragment 把线性结果编码回 sRGB（linearToOutputTexel 由 three 的
 * program prefix 自动定义，不能再 include pars chunk，否则黑屏）。 */
const FRAGMENT_SHADER = /* glsl */ `
varying vec2 vUv;
uniform vec2 uPlane;
uniform float uPx;
uniform float uTime;
uniform float uSeed;
uniform vec2 uPointer;
uniform float uPointerOn;
uniform vec4 uPing;
uniform vec3 uPaper;
uniform vec3 uInk;
uniform vec3 uAcid;

float hash21(vec2 p) {
  p = fract(p * vec2(234.34, 435.345));
  p += dot(p, p + 34.23);
  return fract(p.x * p.y);
}

const float PI = 3.14159265;
const float TAU = 6.2831853;
const float OMEGA = 0.6283185;
const float SWEEP0 = 3.7523;
const float R = 0.88;

void main() {
  float mn = min(uPlane.x, uPlane.y);
  vec2 p = (vUv - 0.5) * uPlane / mn * 2.0;
  float r = length(p);
  float a = atan(p.y, p.x);

  vec3 col = uPaper;
  float inScope = smoothstep(R + uPx, R - uPx, r);

  // 极坐标网格：内环 ×2 + 表圈 + 12 刻度 + 十字轴
  float ringInner = smoothstep(uPx, 0.0, abs(r - R * 0.33))
                  + smoothstep(uPx, 0.0, abs(r - R * 0.66));
  col = mix(col, uInk, ringInner * 0.22);
  col = mix(col, uInk, smoothstep(1.6 * uPx, 0.0, abs(r - R)) * 0.85);
  col = mix(col, uInk, smoothstep(uPx, 0.0, min(abs(p.x), abs(p.y))) * inScope * 0.14);
  float sector = mod(a, TAU / 12.0);
  float dTick = min(sector, TAU / 12.0 - sector) * r;
  float tick = smoothstep(1.2 * uPx, 0.0, dTick)
             * smoothstep(uPx, 0.0, abs(r - (R - 0.05)) - 0.035);
  col = mix(col, uInk, tick * 0.45);

  // 扫掠：顺时针 10s/圈，余辉指数衰减；前沿用墨色细针（纸面对比）+ 酸绿晕
  float sweepA = SWEEP0 - uTime * OMEGA;
  float trail = mod(a - sweepA, TAU);
  col = mix(col, uAcid, exp(-trail * 1.9) * inScope * 0.22);
  col = mix(col, uAcid, exp(-trail * 26.0) * inScope * 0.55);
  col = mix(col, uInk, exp(-trail * 90.0) * inScope * 0.55);

  // ping 涟漪包络（点击触发；同时点亮附近光点）
  float pingT = uTime - uPing.z;
  float pingEnv = (uPing.w > 0.5 && pingT >= 0.0 && pingT < 3.0) ? exp(-pingT * 1.7) : 0.0;

  // 光点：位置由日期种子派生；墨色芯常驻（纸面可读），扫掠掠过后酸绿余辉渐暗
  for (int i = 0; i < 9; i++) {
    float fi = float(i);
    float h1 = hash21(vec2(uSeed * 613.0 + fi * 17.13, fi * 3.70));
    float h2 = hash21(vec2(fi * 7.77, uSeed * 577.0 + fi * 13.31));
    float h3 = hash21(vec2(fi * 5.51, fi * 9.13 + uSeed * 313.0));
    float ba = h1 * TAU;
    float br = R * (0.20 + 0.68 * h2);
    vec2 bp = vec2(cos(ba), sin(ba)) * br;
    float bd = length(p - bp);
    float glow = exp(-mod(ba - sweepA, TAU) / OMEGA * 0.85);
    glow = max(glow, pingEnv * exp(-length(bp - uPing.xy) * 4.0));
    float body = smoothstep((1.6 + h3 * 1.2) * uPx, 0.0, bd);
    col = mix(col, uInk, body * 0.45);
    col = mix(col, uAcid, body * glow * 0.85);
    col += uAcid * exp(-bd * bd / (uPx * uPx * 40.0)) * glow * 0.30;
  }

  // 指针方位高亮扇面（悬停跟随，淡）
  float dAng = abs(mod(a - atan(uPointer.y, uPointer.x) + PI, TAU) - PI);
  col = mix(col, uAcid, exp(-dAng * dAng * 14.0) * uPointerOn * inScope * 0.18);

  // ping：墨色扩散环 + 落点酸绿闪光
  if (pingEnv > 0.0) {
    float pr = pingT * 0.45;
    float pring = smoothstep((1.5 + pingT * 1.5) * uPx, 0.0, abs(length(p - uPing.xy) - pr));
    col = mix(col, uInk, pring * pingEnv * 0.55 * inScope);
    col = mix(col, uAcid, exp(-length(p - uPing.xy) * 22.0) * exp(-pingT * 4.0) * 0.6);
  }

  // 表圈外轻微压暗，把示波器"嵌"进卡面；细颗粒防色带
  col *= 1.0 - 0.04 * (1.0 - inScope);
  col += (hash21(gl_FragCoord.xy + vec2(fract(uTime * 0.61) * 91.7, fract(uTime * 0.37) * 57.3)) - 0.5) * 0.02;

  gl_FragColor = vec4(col, 1.0);
  #include <colorspace_fragment>
}
`

const boot = async () => {
  const root = rootRef.value
  const canvas = canvasRef.value
  if (!root || !canvas) return
  // jsdom 等环境没有 WebGL2，直接留在静态兜底层
  if (typeof window === 'undefined' || typeof window.WebGL2RenderingContext !== 'function') return
  let probe: WebGL2RenderingContext | null = null
  try {
    probe = canvas.getContext('webgl2', { antialias: true, alpha: false })
  } catch {
    probe = null
  }
  if (!probe) return

  try {
    const THREE = await import('three')
    if (!alive) return

    const renderer: WebGLRenderer = new THREE.WebGLRenderer({
      canvas,
      context: probe,
      antialias: true,
      alpha: false,
      depth: false,
      stencil: false,
      powerPreference: 'low-power',
    })

    const uniforms = {
      uPlane: { value: new THREE.Vector2(2, 2) },
      uPx: { value: 0.01 },
      uTime: { value: 0 },
      uSeed: { value: hashSeed(props.seedDate) },
      uPointer: { value: new THREE.Vector2(0, 0) },
      uPointerOn: { value: 0 },
      uPing: { value: new THREE.Vector4(0, 0, 0, 0) },
      uPaper: { value: new THREE.Color('#f2f0e4') },
      uInk: { value: new THREE.Color('#151512') },
      uAcid: { value: new THREE.Color('#d8f14b') },
    }
    const material: ShaderMaterial = new THREE.ShaderMaterial({
      uniforms,
      vertexShader: VERTEX_SHADER,
      fragmentShader: FRAGMENT_SHADER,
      depthTest: false,
      depthWrite: false,
    })
    const mesh: Mesh = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), material)
    const scene = new THREE.Scene()
    scene.add(mesh)
    /* 透视相机：盘面朝指针微倾时产生真实的近大远小，这是 WebGL 相对纯 CSS 的增量 */
    const camera: PerspectiveCamera = new THREE.PerspectiveCamera(26, 1, 0.1, 10)
    camera.position.z = 4

    let rafId = 0
    let running = false
    let onScreen = true
    let contextLost = false
    let last = 0
    let elapsed = 0
    /** 平面世界尺寸（随卡片长宽比变化），指针/落点换算到 shader 的 p 空间要用 */
    let planeW = 2
    let planeH = 2
    const pointerNdc = { x: 0, y: 0 }
    const pointerTarget = { x: 0, y: 0 }
    let pointerOnTarget = 0

    const renderFrame = () => {
      renderer.render(scene, camera)
    }

    const frame = (now: number) => {
      rafId = window.requestAnimationFrame(frame)
      const dt = Math.min((now - last) / 1000, 0.1)
      last = now
      elapsed += dt
      uniforms.uTime.value = elapsed
      const damp = 1 - Math.exp(-dt * 7)
      pointerNdc.x += (pointerTarget.x - pointerNdc.x) * damp
      pointerNdc.y += (pointerTarget.y - pointerNdc.y) * damp
      const mn = Math.min(planeW, planeH)
      uniforms.uPointer.value.set(pointerNdc.x * planeW / mn, pointerNdc.y * planeH / mn)
      uniforms.uPointerOn.value += (pointerOnTarget - uniforms.uPointerOn.value) * damp
      mesh.rotation.x = -pointerNdc.y * 0.10
      mesh.rotation.y = pointerNdc.x * 0.12
      renderFrame()
    }

    const stop = () => {
      if (rafId) window.cancelAnimationFrame(rafId)
      rafId = 0
      running = false
    }
    const maybeStart = () => {
      if (running || contextLost || !onScreen || deactivated || motionQuery.matches) return
      running = true
      last = performance.now()
      rafId = window.requestAnimationFrame(frame)
    }
    pauseFn = stop
    resumeFn = maybeStart

    const readToken = (name: string, target: InstanceType<typeof THREE.Color>) => {
      const raw = getComputedStyle(root).getPropertyValue(name).trim()
      if (!raw) return
      try {
        target.set(raw)
      } catch {
        // token 解析失败时保留上一值，不中断渲染
      }
    }
    const syncTheme = () => {
      readToken('--paper-light', uniforms.uPaper.value)
      readToken('--ink', uniforms.uInk.value)
      readToken('--acid', uniforms.uAcid.value)
      // 循环停止时（reduced-motion / 离屏 / 首帧前）直接渲染静帧，保证兜底之上画面正确
      if (!running) renderFrame()
    }

    const resize = () => {
      const width = root.clientWidth || 1
      const height = root.clientHeight || 1
      const dpr = Math.min(window.devicePixelRatio || 1, width < 640 ? 1.4 : 1.75)
      renderer.setPixelRatio(dpr)
      renderer.setSize(width, height, false)
      camera.aspect = width / height
      camera.updateProjectionMatrix()
      // z=4、fov 26° 下恰好铺满视口的平面尺寸
      planeH = 2 * 4 * Math.tan((26 * Math.PI) / 360)
      planeW = planeH * camera.aspect
      mesh.scale.set(planeW, planeH, 1)
      uniforms.uPlane.value.set(planeW, planeH)
      uniforms.uPx.value = 2 / Math.min(width, height)
      if (!running) renderFrame()
    }

    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
    const applyMotionPref = () => {
      if (motionQuery.matches) stop()
      else maybeStart()
    }

    syncTheme()
    resize()
    renderLive.value = true
    applyMotionPref()

    const resizeObserver =
      typeof ResizeObserver === 'function' ? new ResizeObserver(resize) : null
    resizeObserver?.observe(root)

    const intersectionObserver =
      typeof IntersectionObserver === 'function'
        ? new IntersectionObserver(
            (entries) => {
              onScreen = entries[0]?.isIntersecting ?? true
              if (onScreen) maybeStart()
              else stop()
            },
            { threshold: 0.02 },
          )
        : null
    intersectionObserver?.observe(root)

    const themeObserver = new MutationObserver(syncTheme)
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme'],
    })

    const toNdc = (event: PointerEvent) => {
      const rect = root.getBoundingClientRect()
      if (!rect.width || !rect.height) return null
      return {
        x: ((event.clientX - rect.left) / rect.width) * 2 - 1,
        y: -(((event.clientY - rect.top) / rect.height) * 2 - 1),
      }
    }
    const onPointerMove = (event: PointerEvent) => {
      const ndc = toNdc(event)
      if (!ndc) return
      pointerTarget.x = ndc.x
      pointerTarget.y = ndc.y
      pointerOnTarget = 1
    }
    const onPointerLeave = () => {
      pointerOnTarget = 0
      pointerTarget.x = 0
      pointerTarget.y = 0
    }
    const onPointerDown = (event: PointerEvent) => {
      if (!running) return
      const ndc = toNdc(event)
      if (!ndc) return
      const mn = Math.min(planeW, planeH)
      uniforms.uPing.value.set(ndc.x * planeW / mn, ndc.y * planeH / mn, elapsed, 1)
    }
    root.addEventListener('pointermove', onPointerMove, { passive: true })
    root.addEventListener('pointerleave', onPointerLeave, { passive: true })
    root.addEventListener('pointerdown', onPointerDown, { passive: true })

    const onContextLost = (event: Event) => {
      event.preventDefault()
      contextLost = true
      stop()
      renderLive.value = false
    }
    const onContextRestored = () => {
      contextLost = false
      syncTheme()
      resize()
      renderLive.value = true
      applyMotionPref()
    }
    canvas.addEventListener('webglcontextlost', onContextLost)
    canvas.addEventListener('webglcontextrestored', onContextRestored)
    motionQuery.addEventListener('change', applyMotionPref)

    const stopWatch = watch(
      () => props.seedDate,
      (value) => {
        uniforms.uSeed.value = hashSeed(value)
        if (!running) renderFrame()
      },
    )

    cleanup = () => {
      stopWatch()
      stop()
      resizeObserver?.disconnect()
      intersectionObserver?.disconnect()
      themeObserver.disconnect()
      motionQuery.removeEventListener('change', applyMotionPref)
      root.removeEventListener('pointermove', onPointerMove)
      root.removeEventListener('pointerleave', onPointerLeave)
      root.removeEventListener('pointerdown', onPointerDown)
      canvas.removeEventListener('webglcontextlost', onContextLost)
      canvas.removeEventListener('webglcontextrestored', onContextRestored)
      mesh.geometry.dispose()
      material.dispose()
      renderer.dispose()
      renderer.forceContextLoss()
    }
  } catch {
    // three 加载或渲染器创建失败：静默回退，静态兜底层仍在
  }
}

let cleanup: (() => void) | null = null
let alive = true
/** KeepAlive 停用时冻结渲染（boot 完成后由闭包注入） */
let deactivated = false
let pauseFn: (() => void) | null = null
let resumeFn: (() => void) | null = null
/** 紧凑模式尺寸观察器（组件级，与 WebGL 生命周期无关） */
let sizeObserver: ResizeObserver | null = null

onMounted(() => {
  alive = true
  deactivated = false
  void boot()
  /* 紧凑模式观察：独立于 WebGL boot，静态兜底路径同样生效；
     jsdom 等无 ResizeObserver 环境静默跳过 */
  const root = rootRef.value
  if (root && typeof ResizeObserver === 'function') {
    sizeObserver = new ResizeObserver(() => {
      const h = root.clientHeight
      isShort.value = h > 0 && h < SHORT_HEIGHT_THRESHOLD
    })
    sizeObserver.observe(root)
  }
})
onActivated(() => {
  deactivated = false
  resumeFn?.()
})
onDeactivated(() => {
  deactivated = true
  pauseFn?.()
})
onBeforeUnmount(() => {
  alive = false
  cleanup?.()
  cleanup = null
  pauseFn = null
  resumeFn = null
  sizeObserver?.disconnect()
  sizeObserver = null
})
</script>

<template>
  <div ref="rootRef" class="radar-card" :class="{ 'radar-card--live': renderLive, 'radar-card--short': isShort }" aria-hidden="true">
    <div class="radar-fallback" />
    <canvas ref="canvasRef" class="radar-canvas" />
    <span class="radar-caption">AIGC RADAR · {{ caption }}</span>
  </div>
</template>

<style scoped>
.radar-card {
  position: relative;
  overflow: hidden;
  cursor: crosshair;
}
/* 静态兜底与场景同构图：同心环 + 215° 扫掠楔 + 表圈遮罩 + 两颗固定光点 */
.radar-fallback {
  position: absolute;
  inset: 0;
  background:
    conic-gradient(
      from 215deg at 50% 50%,
      color-mix(in srgb, var(--acid) 14%, transparent) 0deg,
      transparent 55deg
    ),
    radial-gradient(circle 5px at 62% 36%, color-mix(in srgb, var(--acid) 75%, var(--ink)) 100%, transparent),
    radial-gradient(circle 4px at 38% 64%, color-mix(in srgb, var(--acid) 65%, var(--ink)) 100%, transparent),
    radial-gradient(
      circle closest-side at 50% 50%,
      transparent calc(88% - 2px),
      color-mix(in srgb, var(--ink) 80%, transparent) calc(88% - 2px) 88%,
      transparent 88%
    ),
    radial-gradient(
      circle closest-side at 50% 50%,
      transparent calc(58% - 1px),
      color-mix(in srgb, var(--ink) 20%, transparent) calc(58% - 1px) 58%,
      transparent 58%
    ),
    radial-gradient(
      circle closest-side at 50% 50%,
      transparent calc(29% - 1px),
      color-mix(in srgb, var(--ink) 20%, transparent) calc(29% - 1px) 29%,
      transparent 29%
    );
  -webkit-mask: radial-gradient(circle closest-side at 50% 50%, #000 88%, transparent 89%);
  mask: radial-gradient(circle closest-side at 50% 50%, #000 88%, transparent 89%);
}
.radar-fallback::before,
.radar-fallback::after {
  content: '';
  position: absolute;
  background: color-mix(in srgb, var(--ink) 12%, transparent);
}
.radar-fallback::before {
  left: 6%;
  right: 6%;
  top: 50%;
  height: 1px;
}
.radar-fallback::after {
  top: 6%;
  bottom: 6%;
  left: 50%;
  width: 1px;
}
.radar-canvas {
  position: absolute;
  inset: 0;
  display: block;
  width: 100%;
  height: 100%;
  opacity: 0;
  transition: opacity 0.6s ease;
}
.radar-card--live .radar-canvas {
  opacity: 1;
}
.radar-caption {
  position: absolute;
  left: 12px;
  bottom: 8px;
  z-index: 1;
  font-size: 10px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--dash-muted, var(--muted));
}
/* 紧凑模式：卡片过矮（对齐榜单底边后剩余高度不足）时隐藏 caption，避免压住迷你雷达 */
.radar-card--short .radar-caption {
  display: none;
}
@media (prefers-reduced-motion: reduce) {
  .radar-canvas {
    transition: none;
  }
}
</style>
