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
    <div class="crystal"><i v-for="face in 4" :key="face" :style="{ '--face': face - 1 }" /></div>
  </div>
</template>

<style scoped>
.digest-geometry { position: absolute; right: -18px; bottom: -28px; width: 135px; height: 150px; perspective: 500px; pointer-events: none; z-index: 0; opacity: .65; }
.crystal { position: absolute; inset: 25px; transform-style: preserve-3d; animation: crystal-orbit 22s linear infinite; }
.crystal i { position: absolute; inset: 0; border: 1px solid #c9e3b1; background: linear-gradient(135deg, #d6fb5315, #ffffff04); transform: rotateY(calc(var(--face) * 45deg)) rotateZ(35deg); }
.crystal i::after { content: ''; position: absolute; inset: 0; background: linear-gradient(48deg, transparent 49.4%, #d2dfc6 50%, transparent 50.6%); }
.paused .crystal { animation-play-state: paused; }
@keyframes crystal-orbit { from { transform: rotateX(25deg) rotateY(0deg) rotateZ(-18deg); } to { transform: rotateX(25deg) rotateY(360deg) rotateZ(-18deg); } }
@media (prefers-reduced-motion: reduce) { .crystal { animation: none; transform: rotateX(25deg) rotateY(35deg); } }
</style>
