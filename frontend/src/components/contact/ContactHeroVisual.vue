<script setup lang="ts">
/**
 * 联系页 Hero 视觉层：HD-2D 透视双层管线像素原野（ContactFieldScene），实时渲染。
 * 纯装饰（aria-hidden），本组件只做生命周期壳：
 * - 仅探测 webgl2 上下文；不可用 / 上下文丢失 / 场景模块加载失败 → 露出底层静态 CSS 渐变兜底
 * - 昼/夜绑定站点主题（亮=白昼，暗=夜晚），切换经场景内 1.8s 恒速扫掠播时间过渡；
 *   纸色 token（--contact-scene-bg）经 getComputedStyle 读入做画布清屏与边缘融合
 * - reduced-motion / 离屏 / 首帧：不启动 RAF，主题与尺寸变化直接渲染静帧
 * - 离屏（IntersectionObserver）暂停、卸载全量 dispose + forceContextLoss
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import type { FieldSceneHandle, FieldTheme } from './scene/ContactFieldScene'

const rootRef = ref<HTMLDivElement | null>(null)
const canvasRef = ref<HTMLCanvasElement | null>(null)
/** 首帧已上屏后才淡入 canvas，盖住静态兜底 */
const live = ref(false)

let cleanup: (() => void) | null = null
let alive = true

const PAPER_FALLBACK = '#fffefa'

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
    const { createFieldScene } = await import('./scene/ContactFieldScene')
    if (!alive) return

    const readTokenRaw = (name: string): string | null => {
      const raw = getComputedStyle(root).getPropertyValue(name).trim()
      return raw || null
    }
    const themeOf = (): FieldTheme =>
      document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'
    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')

    const hero = (root.closest('.contact-hero') as HTMLElement | null) ?? root
    const scene: FieldSceneHandle | null = createFieldScene({
      canvas,
      host: hero,
      paper: readTokenRaw('--contact-scene-bg') ?? PAPER_FALLBACK,
      theme: themeOf(),
      reducedMotion: motionQuery.matches,
    })
    if (!scene) return

    let onScreen = true
    let contextLost = false
    const maybeStart = () => {
      if (contextLost || !onScreen || motionQuery.matches) return
      scene.start()
    }
    const applyMotionPref = () => {
      if (motionQuery.matches) scene.stop()
      else maybeStart()
    }
    const syncTheme = () => {
      scene.setTheme(themeOf(), readTokenRaw('--contact-scene-bg') ?? PAPER_FALLBACK)
    }
    const resize = () => {
      scene.resize(root.clientWidth || 1, root.clientHeight || 1)
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
              else scene.stop()
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

    const onPointerMove = (event: Event) => {
      const pointerEvent = event as PointerEvent
      const rect = root.getBoundingClientRect()
      if (!rect.width || !rect.height) return
      scene.setPointer(
        ((pointerEvent.clientX - rect.left) / rect.width - 0.5) * 2,
        -(((pointerEvent.clientY - rect.top) / rect.height - 0.5) * 2),
      )
    }
    hero.addEventListener('pointermove', onPointerMove, { passive: true })

    const onContextLost = (event: Event) => {
      event.preventDefault()
      contextLost = true
      scene.stop()
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
      resizeObserver?.disconnect()
      intersectionObserver?.disconnect()
      themeObserver.disconnect()
      motionQuery.removeEventListener('change', applyMotionPref)
      hero.removeEventListener('pointermove', onPointerMove)
      canvas.removeEventListener('webglcontextlost', onContextLost)
      canvas.removeEventListener('webglcontextrestored', onContextRestored)
      scene.dispose()
    }
  } catch {
    // 场景模块加载或启动失败：静默回退，静态兜底层仍在
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
  /* 合成画布与容器同尺寸；与场景边缘融合目标严格同色 */
  --contact-scene-bg: var(--paper-raised);
  background: var(--contact-scene-bg);
}
/* 静态兜底与场景同语义：3/4 浅俯角构图——地平线在屏顶下 ~22%，天空 → 远野 → 近草纵深渐变，各缀一丛暖灯光 */
.hero-fallback {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(40% 26% at 31% 58%, rgb(255 202 122 / 0.22), transparent 70%),
    linear-gradient(180deg, #7ec8e3 0%, #d9eec9 22%, #b8d498 30%, #98c078 60%, #5a9448 100%);
}
:global(:root[data-theme='dark']) .hero-fallback {
  background:
    radial-gradient(40% 26% at 31% 58%, rgb(255 202 122 / 0.16), transparent 70%),
    radial-gradient(30% 22% at 68% 12%, rgb(184 200 232 / 0.14), transparent 70%),
    linear-gradient(180deg, #101830 0%, #2b3a55 22%, #22304c 30%, #18243c 60%, #0f1830 100%);
}
.hero-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  display: block;
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
