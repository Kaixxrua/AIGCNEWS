<script setup lang="ts">
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { ref, onMounted, onUnmounted } from 'vue'

const route = useRoute()
const hoveredNav = ref<string | null>(null)

/* ═══ Giant Typewriter Watermark ═══ */
const phrases = [
  '> System.init({ mode: "AIGC_Command_Center" });',
  '> Fetching latest Arxiv papers...',
  '> Analyzing GitHub trending repositories...',
  '> Generating automated AI reports...',
  '> Awaiting next instruction_',
]
const displayText = ref('')
let phraseIndex = 0
let charIndex = 0
let isDeleting = false
let typingTimer: ReturnType<typeof setTimeout> | null = null

const typeEffect = () => {
  const currentPhrase = phrases[phraseIndex]

  if (isDeleting) {
    displayText.value = currentPhrase.substring(0, charIndex - 1)
    charIndex--
  } else {
    displayText.value = currentPhrase.substring(0, charIndex + 1)
    charIndex++
  }

  let typeSpeed = isDeleting ? 30 : 80

  if (!isDeleting && charIndex === currentPhrase.length) {
    typeSpeed = 3000
    isDeleting = true
  } else if (isDeleting && charIndex === 0) {
    isDeleting = false
    phraseIndex = (phraseIndex + 1) % phrases.length
    typeSpeed = 500
  }

  typingTimer = setTimeout(typeEffect, typeSpeed)
}

onMounted(() => { typeEffect() })
onUnmounted(() => { if (typingTimer) clearTimeout(typingTimer) })

const navItems = [
  {
    to: '/',
    label: 'Dashboard',
    exact: true,
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>`,
  },
  {
    to: '/chat',
    label: 'Chat',
    exact: false,
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>`,
  },
  {
    to: '/report',
    label: 'Report',
    exact: false,
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14,2 14,8 20,8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>`,
  },
  {
    to: '/monitor',
    label: 'Monitor',
    exact: false,
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="22,12 18,12 15,21 9,3 6,12 2,12"/></svg>`,
  },
]

const isActive = (item: { to: string; exact: boolean }) => {
  if (item.exact) return route.path === item.to
  return route.path.startsWith(item.to)
}
</script>

<template>
  <!-- ═══ Layer -10: 暖调米白纸张底色 ═══ -->
  <div
    class="fixed inset-0 pointer-events-none bg-[#F9F9F8]"
    style="z-index: -10"
    aria-hidden="true"
  ></div>

  <!-- ═══ Layer -9: 巨型打字机背景水印 (Giant Typewriter Watermark) ═══ -->
  <div
    class="fixed inset-0 flex flex-col justify-center items-center pointer-events-none overflow-hidden select-none"
    style="z-index: -9"
    aria-hidden="true"
  >
    <div class="w-full max-w-[90vw] px-10">
      <p class="font-mono text-4xl md:text-6xl lg:text-8xl text-stone-400/[0.07] font-bold tracking-tight whitespace-pre-wrap break-words leading-tight">
        {{ displayText }}<span class="animate-pulse">_</span>
      </p>
    </div>
  </div>

  <!-- ═══ Layer -8: 极弱纸张噪点 (Subtle Paper Grain) ═══ -->
  <div
    class="fixed inset-0 pointer-events-none"
    style="z-index: -8; opacity: 0.025; mix-blend-mode: multiply; background-image: url('data:image/svg+xml,%3Csvg viewBox=%220 0 256 256%22 xmlns=%22http://www.w3.org/2000/svg%22%3E%3Cfilter id=%22n%22%3E%3CfeTurbulence type=%22fractalNoise%22 baseFrequency=%220.75%22 numOctaves=%224%22 stitchTiles=%22stitch%22/%3E%3C/filter%3E%3Crect width=%22100%25%22 height=%22100%25%22 filter=%22url(%23n)%22/%3E%3C/svg%3E'); background-repeat: repeat; background-size: 256px 256px;"
    aria-hidden="true"
  ></div>

  <!-- ═══ 全屏内容层 ═══ -->
  <div class="relative flex h-screen w-full items-center justify-center overflow-hidden">

    <!-- ═══ 居中悬浮画板（暖白纸质毛玻璃主面板） ═══ -->
    <div class="main-canvas">
      <router-view v-slot="{ Component }">
        <transition name="spatial-fade">
          <component :is="Component" class="view-container" />
        </transition>
      </router-view>
    </div>

    <!-- ═══ 底部悬浮 Dock 导航栏（暖白纸质） ═══ -->
    <nav class="dock">
      <RouterLink
        v-for="item in navItems"
        :key="item.to"
        :to="item.to"
        class="dock-item"
        :class="{ 'dock-item--active': isActive(item) }"
        @mouseenter="hoveredNav = item.to"
        @mouseleave="hoveredNav = null"
      >
        <span class="dock-icon" v-html="item.icon" />
        <Transition name="dock-label">
          <span
            v-if="hoveredNav === item.to"
            class="dock-label"
          >
            {{ item.label }}
          </span>
        </Transition>
      </RouterLink>
    </nav>

  </div>
</template>

<style>
/* ═══ 视图容器 ═══ */
.view-container {
  width: 100%;
  height: 100%;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* ═══ 主悬浮画板（暖白纸质毛玻璃） ═══ */
.main-canvas {
  width: 92%;
  max-width: 1400px;
  height: 84vh;
  border-radius: 32px;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(32px) saturate(180%);
  -webkit-backdrop-filter: blur(32px) saturate(180%);
  border: 1px solid rgba(168, 162, 158, 0.20);
  box-shadow:
    0 2px 12px rgba(0, 0, 0, 0.03),
    inset 0 1px 0 0 rgba(255, 255, 255, 0.8);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  position: relative;
}

/* ═══ 底部 Dock（暖白纸质） ═══ */
.dock {
  position: fixed;
  bottom: 28px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 100;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 24px;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(24px) saturate(180%);
  -webkit-backdrop-filter: blur(24px) saturate(180%);
  border: 1px solid rgba(168, 162, 158, 0.20);
  border-radius: 999px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
}

.dock-item {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  transition: all 0.25s cubic-bezier(0.25, 0.8, 0.25, 1);
  color: #a8a29e; /* stone-400 */
  text-decoration: none;
}

.dock-item:hover {
  color: #57534e; /* stone-600 */
  background: rgba(245, 245, 244, 0.8); /* stone-100 */
  transform: scale(1.08);
}

.dock-item--active {
  color: #44403c; /* stone-700 */
  background: #f5f5f4; /* stone-100 */
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
}

.dock-item--active:hover {
  color: #44403c;
  background: #e7e5e4; /* stone-200 */
  transform: scale(1.08);
}

.dock-icon {
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.dock-icon svg {
  width: 20px;
  height: 20px;
}

/* Dock 悬浮标签（tooltip — 暖色） */
.dock-label {
  position: absolute;
  bottom: calc(100% + 10px);
  left: 50%;
  transform: translateX(-50%);
  white-space: nowrap;
  font-size: 11px;
  font-weight: 600;
  color: #44403c; /* stone-700 */
  background: rgba(255, 255, 255, 0.90);
  backdrop-filter: blur(10px);
  padding: 4px 12px;
  border-radius: 999px;
  border: 1px solid rgba(168, 162, 158, 0.15);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
  pointer-events: none;
}

.dock-label-enter-active,
.dock-label-leave-active {
  transition: all 0.2s cubic-bezier(0.25, 0.8, 0.25, 1);
}
.dock-label-enter-from,
.dock-label-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(4px) scale(0.9);
}
.dock-label-enter-to,
.dock-label-leave-from {
  opacity: 1;
  transform: translateX(-50%) translateY(0) scale(1);
}

/* ═══ 路由切换：无缝交叉空间缩放 ═══ */
.spatial-fade-enter-active,
.spatial-fade-leave-active {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  transition: opacity 0.6s ease,
              transform 0.6s cubic-bezier(0.22, 1, 0.36, 1),
              filter 0.6s ease;
  will-change: transform, opacity, filter;
}

.spatial-fade-enter-from {
  opacity: 0;
  transform: scale(0.95);
  filter: blur(10px);
}

.spatial-fade-leave-to {
  opacity: 0;
  transform: scale(1.05);
  filter: blur(10px);
  z-index: 10;
}
</style>
