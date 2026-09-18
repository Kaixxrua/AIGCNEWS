<script setup lang="ts">
import { useDocumentVisibility, usePreferredReducedMotion } from '@vueuse/core'
import { onActivated, onDeactivated, ref } from 'vue'
const visibility = useDocumentVisibility()
const motion = usePreferredReducedMotion()
const active = ref(true)
onActivated(() => { active.value = true })
onDeactivated(() => { active.value = false })
</script>

<template>
  <div class="digest-geometry" :class="{ paused: !active || visibility !== 'visible' || motion === 'reduce' }" aria-hidden="true">
    <svg class="crystal" viewBox="0 0 160 150" fill="none">
      <path d="M12 103 59 88 64 53 121 12 153 45 91 145 50 137Z" fill="#ffffff08" stroke="#ffffffb0" />
      <path d="m12 103 79 42-32-57 62-76-30 133 62-100-89 8-14 84 71-125M59 88l94-43M64 53l27 92" stroke="#ffffff70" stroke-width=".7" />
    </svg>
  </div>
</template>

<style scoped>
.digest-geometry { position: absolute; right: 7px; bottom: -8px; width: 165px; height: 135px; perspective: 500px; pointer-events: none; z-index: 0; opacity: .85; }
.crystal { width: 100%; height: 100%; transform-style: preserve-3d; animation: crystal-orbit 22s linear infinite; }
.crystal i { position: absolute; inset: 0; border: 1px solid #c9e3b1; background: linear-gradient(135deg, #d6fb5315, #ffffff04); transform: rotateY(calc(var(--face) * 45deg)) rotateZ(35deg); }
.crystal i::after { content: ''; position: absolute; inset: 0; background: linear-gradient(48deg, transparent 49.4%, #d2dfc6 50%, transparent 50.6%); }
.paused .crystal { animation-play-state: paused; }
@keyframes crystal-orbit { 0%, 100% { transform: rotateY(-12deg) rotateZ(-3deg); } 50% { transform: rotateY(30deg) rotateZ(9deg); } }
@media (prefers-reduced-motion: reduce) { .crystal { animation: none; transform: rotateX(25deg) rotateY(35deg); } }
</style>
