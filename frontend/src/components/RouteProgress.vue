<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useRouteProgress } from '@/composables/useRouteProgress'

const { t } = useI18n()
const { isRouteLoading } = useRouteProgress()
</script>

<template>
  <Transition name="route-progress">
    <div
      v-if="isRouteLoading"
      class="route-progress"
      role="status"
      :aria-label="t('common.loading')"
    >
      <span class="route-progress__bar" />
    </div>
  </Transition>
</template>

<style scoped>
.route-progress {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  z-index: 200; /* 高于 Layout 顶栏(100) 与 AppToast(120) */
  pointer-events: none;
  overflow: hidden;
}

.route-progress__bar {
  display: block;
  width: 40%;
  height: 100%;
  border-radius: 3px;
  background: var(--acid-strong);
  animation: route-progress-slide 1.1s ease-in-out infinite;
}

@keyframes route-progress-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(350%); }
}

.route-progress-enter-active,
.route-progress-leave-active {
  transition: opacity 0.2s ease;
}

.route-progress-enter-from,
.route-progress-leave-to {
  opacity: 0;
}

@media (prefers-reduced-motion: reduce) {
  .route-progress__bar {
    animation: none;
    width: 100%;
  }
}
</style>
