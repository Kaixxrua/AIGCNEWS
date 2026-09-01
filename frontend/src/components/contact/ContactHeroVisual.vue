<script setup lang="ts">
/**
 * 联系页 Hero 视觉层：Three.js + WebGL2 全屏 shader 信号场，实时渲染。
 * 纯装饰（aria-hidden），生命周期自包含：
 * - 仅探测 webgl2 上下文；不可用 / 上下文丢失 / three 加载失败 → 露出底层静态 CSS 渐变兜底
 * - 主题色经 getComputedStyle 读取项目 token 注入 uniform，跟随亮暗切换
 * - DPR 上限、离屏（IntersectionObserver）暂停、卸载全量 dispose
 * - prefers-reduced-motion: reduce → 渲染单帧静场，不启动 RAF 循环
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import type { ShaderMaterial, WebGLRenderer } from 'three'

const rootRef = ref<HTMLDivElement | null>(null)
const canvasRef = ref<HTMLCanvasElement | null>(null)
/** 首帧已上屏后才淡入 canvas，盖住静态兜底 */
const live = ref(false)

let cleanup: (() => void) | null = null
let alive = true

const VERTEX_SHADER = /* glsl */ `
void main() {
  gl_Position = vec4(position.xy, 0.0, 1.0);
}
`

/* 霓虹信号束 + 慢速噪声辉光 + 扫描线/颗粒；颜色全部来自 uniform（即项目 token）。
 * GLSL1 语法跑在 WebGL2 上下文上（three r163+ 只创建 WebGL2 context）；
 * 结尾的 colorspace_fragment 把线性计算结果编码回 sRGB 输出
 * （linearToOutputTexel 由 three 的 program prefix 自动定义，不能再 include pars chunk）。 */
const FRAGMENT_SHADER = /* glsl */ `
uniform vec2 uRes;
uniform float uTime;
uniform vec2 uPointer;
uniform vec3 uBg;
uniform vec3 uAcid;
uniform vec3 uTech;

float hash21(vec2 p) {
  p = fract(p * vec2(234.34, 435.345));
  p += dot(p, p + 34.23);
  return fract(p.x * p.y);
}

float noise2(vec2 p) {
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
    v += a * noise2(p);
    p = p * 2.03 + vec2(11.7, -7.3);
    a *= 0.5;
  }
  return v;
}

void main() {
  vec2 uv = (gl_FragCoord.xy - 0.5 * uRes) / uRes.y;
  uv += uPointer * vec2(0.035, 0.025);
  float t = uTime;

  vec3 col = uBg;

  // 背景星云：慢速漂移的低亮辉光
  float neb = fbm(uv * vec2(1.7, 2.3) + vec2(t * 0.045, -t * 0.03));
  col += mix(uTech, uAcid, 0.5 + 0.5 * sin(t * 0.09)) * pow(neb, 2.2) * 0.34;

  // 五条流动信号束，横向两端淡出
  float edgeFade = smoothstep(1.2, 0.5, abs(uv.x));
  for (int i = 0; i < 5; i++) {
    float fi = float(i);
    float dir = mod(fi, 2.0) * 2.0 - 1.0;
    float speed = 0.32 + fi * 0.16;
    float ph = fi * 1.93;
    float y = (fi - 2.0) * 0.13
      + (0.10 - fi * 0.012) * sin(uv.x * (1.5 + fi * 0.5) * dir + t * speed * dir + ph)
      + 0.055 * (noise2(vec2(uv.x * (1.15 + fi * 0.33) + t * speed * 0.55 * dir, ph)) - 0.5);
    float d = abs(uv.y - y);
    float core = 0.004 + fi * 0.0015;
    float glow = 0.9 * exp(-d * d / (core * core)) + 0.32 * exp(-d / (core * 18.0));
    vec3 tint = mix(uAcid, uTech, clamp(0.5 + 0.5 * sin(ph + t * 0.11), 0.0, 1.0));
    col += tint * glow * edgeFade * (0.46 - fi * 0.055);
  }

  // 底部地平线余晖
  col += uTech * exp(-abs(uv.y + 0.46) * 7.0) * 0.10;

  // 细扫描线
  col *= 1.0 - 0.05 * (0.5 + 0.5 * sin(gl_FragCoord.y * 1.9));

  // 暗角
  float vig = smoothstep(1.3, 0.28, length(uv * vec2(0.82, 1.22)));
  col *= mix(0.62, 1.0, vig);

  // 颗粒
  col += (hash21(gl_FragCoord.xy + vec2(fract(t) * 91.7, fract(t * 0.7) * 57.3)) - 0.5) * 0.035;

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
    probe = canvas.getContext('webgl2', { antialias: false, alpha: false })
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
      antialias: false,
      alpha: false,
      depth: false,
      stencil: false,
      powerPreference: 'low-power',
    })

    const uniforms = {
      uRes: { value: new THREE.Vector2(1, 1) },
      uTime: { value: 0 },
      uPointer: { value: new THREE.Vector2(0, 0) },
      uBg: { value: new THREE.Color('#151512') },
      uAcid: { value: new THREE.Color('#d8f14b') },
      uTech: { value: new THREE.Color('#06b6d4') },
    }
    const material: ShaderMaterial = new THREE.ShaderMaterial({
      uniforms,
      vertexShader: VERTEX_SHADER,
      fragmentShader: FRAGMENT_SHADER,
      depthTest: false,
      depthWrite: false,
    })
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), material)
    const scene = new THREE.Scene()
    scene.add(mesh)
    const camera = new THREE.Camera()

    let rafId = 0
    let running = false
    let onScreen = true
    let contextLost = false
    let last = 0
    let elapsed = 0
    const pointerTarget = { x: 0, y: 0 }

    const renderFrame = () => {
      renderer.render(scene, camera)
    }

    const frame = (now: number) => {
      rafId = window.requestAnimationFrame(frame)
      const dt = Math.min((now - last) / 1000, 0.1)
      last = now
      elapsed += dt
      uniforms.uTime.value = elapsed * 0.55
      const pointer = uniforms.uPointer.value
      pointer.x += (pointerTarget.x - pointer.x) * 0.06
      pointer.y += (pointerTarget.y - pointer.y) * 0.06
      renderFrame()
    }

    const stop = () => {
      if (rafId) window.cancelAnimationFrame(rafId)
      rafId = 0
      running = false
    }
    const maybeStart = () => {
      if (running || contextLost || !onScreen || motionQuery.matches) return
      running = true
      last = performance.now()
      rafId = window.requestAnimationFrame(frame)
    }

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
      readToken('--contact-hero-bg', uniforms.uBg.value)
      readToken('--acid', uniforms.uAcid.value)
      readToken('--tech-primary', uniforms.uTech.value)
      if (!running) renderFrame()
    }

    const resize = () => {
      const width = root.clientWidth || 1
      const height = root.clientHeight || 1
      const dpr = Math.min(window.devicePixelRatio || 1, width < 640 ? 1.4 : 1.75)
      renderer.setPixelRatio(dpr)
      renderer.setSize(width, height, false)
      uniforms.uRes.value.set(width * dpr, height * dpr)
      if (!running) renderFrame()
    }

    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
    const applyMotionPref = () => {
      if (motionQuery.matches) stop()
      else maybeStart()
    }

    syncTheme()
    resize()
    live.value = true
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

    const hero = root.closest('.contact-hero') ?? root
    const onPointerMove = (event: Event) => {
      const pointerEvent = event as PointerEvent
      const rect = root.getBoundingClientRect()
      if (!rect.width || !rect.height) return
      pointerTarget.x = ((pointerEvent.clientX - rect.left) / rect.width - 0.5) * 2
      pointerTarget.y = -(((pointerEvent.clientY - rect.top) / rect.height - 0.5) * 2)
    }
    hero.addEventListener('pointermove', onPointerMove, { passive: true })

    const onContextLost = (event: Event) => {
      event.preventDefault()
      contextLost = true
      stop()
      live.value = false
    }
    const onContextRestored = () => {
      contextLost = false
      syncTheme()
      resize()
      live.value = true
      applyMotionPref()
    }
    canvas.addEventListener('webglcontextlost', onContextLost)
    canvas.addEventListener('webglcontextrestored', onContextRestored)
    motionQuery.addEventListener('change', applyMotionPref)

    cleanup = () => {
      stop()
      resizeObserver?.disconnect()
      intersectionObserver?.disconnect()
      themeObserver.disconnect()
      motionQuery.removeEventListener('change', applyMotionPref)
      hero.removeEventListener('pointermove', onPointerMove)
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

onMounted(() => {
  alive = true
  void boot()
})
onBeforeUnmount(() => {
  alive = false
  cleanup?.()
  cleanup = null
})
</script>

<template>
  <div ref="rootRef" class="hero-visual" :class="{ 'hero-visual--live': live }" aria-hidden="true">
    <div class="hero-fallback" />
    <canvas ref="canvasRef" class="hero-canvas" />
  </div>
</template>

<style scoped>
.hero-visual {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
}
.hero-fallback {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(120% 90% at 78% 18%, color-mix(in srgb, var(--acid) 16%, transparent), transparent 60%),
    radial-gradient(90% 70% at 18% 82%, color-mix(in srgb, var(--tech-primary) 14%, transparent), transparent 65%),
    var(--contact-hero-bg);
}
.hero-canvas {
  position: absolute;
  inset: 0;
  display: block;
  width: 100%;
  height: 100%;
  opacity: 0;
  transition: opacity 0.6s ease;
}
.hero-visual--live .hero-canvas {
  opacity: 1;
}
@media (prefers-reduced-motion: reduce) {
  .hero-canvas {
    transition: none;
  }
}
</style>
