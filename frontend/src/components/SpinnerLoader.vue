<script setup lang="ts">
import { useI18n } from 'vue-i18n'

withDefaults(defineProps<{
  label?: string
  size?: number
}>(), {
  label: '',
  size: 28,
})

const { t } = useI18n()
</script>

<template>
  <div class="spinner-loader" role="status" :aria-label="label || t('common.loading')">
    <svg
      class="spinner-loader__ring"
      :style="{ width: `${size}px`, height: `${size}px` }"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="9" class="spinner-loader__track" stroke-width="2.5" />
      <path d="M21 12a9 9 0 0 0-9-9" class="spinner-loader__arc" stroke-width="2.5" stroke-linecap="round" />
    </svg>
  </div>
</template>

<style scoped>
.spinner-loader {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  width: 100%;
}

.spinner-loader__ring {
  animation: spinner-loader-rotate 0.9s linear infinite;
}

.spinner-loader__track {
  stroke: rgb(var(--stone-400-rgb) / 0.25);
}

.spinner-loader__arc {
  stroke: var(--acid-strong);
}

@keyframes spinner-loader-rotate {
  to { transform: rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
  .spinner-loader__ring { animation: none; }
}
</style>
