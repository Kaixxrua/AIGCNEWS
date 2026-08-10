<script setup lang="ts">
withDefaults(defineProps<{
  width?: string
  height?: string
  radius?: string
}>(), {
  width: '100%',
  height: '12px',
  radius: '6px',
})
</script>

<template>
  <span class="skeleton-block" :style="{ width, height, borderRadius: radius }" aria-hidden="true" />
</template>

<style scoped>
.skeleton-block {
  display: block;
  position: relative;
  overflow: hidden;
  background: rgb(var(--stone-400-rgb) / 0.22);
}

.skeleton-block::after {
  content: '';
  position: absolute;
  inset: 0;
  transform: translateX(-100%);
  background: linear-gradient(90deg, transparent, rgb(255 255 255 / 0.55), transparent);
  animation: skeleton-sweep 1.4s ease-in-out infinite;
}

:global(html[data-theme='dark']) .skeleton-block::after {
  background: linear-gradient(90deg, transparent, rgb(255 255 255 / 0.08), transparent);
}

@keyframes skeleton-sweep {
  to { transform: translateX(100%); }
}

@media (prefers-reduced-motion: reduce) {
  .skeleton-block::after { animation: none; }
}
</style>
