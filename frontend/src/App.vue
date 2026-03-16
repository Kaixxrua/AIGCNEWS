<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { RouterView } from 'vue-router'

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
  const currentPhrase = phrases[phraseIndex] ?? ''

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
</script>

<template>
  <!-- ═══ Layer -10: 暖调米白纸张底色 ═══ -->
  <div
    class="fixed inset-0 pointer-events-none bg-[#F9F9F8]"
    style="z-index: -10"
    aria-hidden="true"
  ></div>

  <!-- ═══ Layer -9: 巨型打字机背景水印 ═══ -->
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

  <!-- ═══ Layer -8: 极弱纸张噪点 ═══ -->
  <div
    class="fixed inset-0 pointer-events-none"
    style="z-index: -8; opacity: 0.025; mix-blend-mode: multiply; background-image: url('data:image/svg+xml,%3Csvg viewBox=%220 0 256 256%22 xmlns=%22http://www.w3.org/2000/svg%22%3E%3Cfilter id=%22n%22%3E%3CfeTurbulence type=%22fractalNoise%22 baseFrequency=%220.75%22 numOctaves=%224%22 stitchTiles=%22stitch%22/%3E%3C/filter%3E%3Crect width=%22100%25%22 height=%22100%25%22 filter=%22url(%23n)%22/%3E%3C/svg%3E'); background-repeat: repeat; background-size: 256px 256px;"
    aria-hidden="true"
  ></div>

  <!-- ═══ 顶层路由出口（Layout 或 Login/Register） ═══ -->
  <RouterView />
</template>
