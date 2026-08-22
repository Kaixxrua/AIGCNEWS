<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import { usePwaUpdate } from '@/pwa/registerPwa'

const { t } = useI18n()
const { needRefresh, reload, dismiss } = usePwaUpdate()
</script>

<template>
  <!-- 右下角小卡片：安静但可发现（实色底、轻形状、软阴影），不做全宽横幅。 -->
  <Transition name="pwa-update">
    <div v-if="needRefresh" class="pwa-update-card" role="status" aria-live="polite">
      <p class="pwa-update-card__message">{{ t('pwa.updateAvailable') }}</p>
      <div class="pwa-update-card__actions">
        <button
          type="button"
          class="pwa-update-card__btn pwa-update-card__btn--primary"
          @click="reload"
        >
          {{ t('pwa.reload') }}
        </button>
        <button type="button" class="pwa-update-card__btn" @click="dismiss">
          {{ t('pwa.later') }}
        </button>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.pwa-update-card {
  position: fixed;
  right: 20px;
  bottom: 20px;
  z-index: 120;
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-width: 260px;
  border: 1px solid var(--ink, #151512);
  border-radius: 8px;
  padding: 14px 16px;
  color: var(--ink, #151512);
  background: var(--paper-raised, #fffefa);
  box-shadow: 4px 4px 0 var(--toast-shadow, rgba(17, 17, 15, 0.18));
}

.pwa-update-card__message {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.5;
}

.pwa-update-card__actions {
  display: flex;
  gap: 8px;
}

.pwa-update-card__btn {
  border: 1px solid var(--ink, #151512);
  border-radius: 6px;
  padding: 6px 12px;
  color: var(--ink, #151512);
  background: transparent;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.4;
  cursor: pointer;
}

.pwa-update-card__btn--primary {
  color: var(--ink-on-solid, #ffffff);
  background: var(--ink-solid, #44403c);
  border-color: var(--ink-solid, #44403c);
}

.pwa-update-card__btn--primary:hover {
  background: var(--ink-solid-hover, #292524);
  border-color: var(--ink-solid-hover, #292524);
}

.pwa-update-enter-active,
.pwa-update-leave-active {
  transition: opacity 180ms ease, transform 180ms ease;
}

.pwa-update-enter-from,
.pwa-update-leave-to {
  opacity: 0;
  transform: translateY(8px);
}

@media (prefers-reduced-motion: reduce) {
  .pwa-update-enter-active,
  .pwa-update-leave-active {
    transition: none;
  }
}
</style>
