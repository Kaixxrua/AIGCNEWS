<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import WechatAccountPanel from '@/components/wechat/WechatAccountPanel.vue'

defineOptions({ name: 'WechatView' })

const { t } = useI18n()
</script>

<template>
  <div class="wechat-page flex h-full min-h-0 flex-col overflow-hidden">
    <div class="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto p-6 pb-24">
      <!-- 页头 -->
      <div class="stagger-enter flex flex-wrap items-center justify-between gap-3 shrink-0">
        <div>
          <h1 class="text-2xl font-bold tracking-tight">{{ t('wechat.panelTitle') }}</h1>
          <p class="monitor-caption mt-0.5 text-sm">{{ t('wechat.panelDescription') }}</p>
        </div>
      </div>

      <WechatAccountPanel />
    </div>
  </div>
</template>

<style scoped>
.wechat-page {
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
}

.wechat-page :deep(.monitor-section-title) {
  color: var(--projects-accent);
  font-weight: 800;
}

.wechat-page :deep(.monitor-caption) {
  color: var(--ink-muted);
}

.wechat-page :deep(.monitor-surface) {
  border: 1px solid var(--projects-accent);
  border-radius: 6px;
  background: var(--projects-paper-light);
  box-shadow: 4px 4px 0 var(--shadow-hard);
}

.wechat-page :deep(.monitor-btn-primary) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 14px;
  font-size: 12px;
  font-weight: 800;
  line-height: 1;
  border-radius: 4px;
  border: 1px solid var(--projects-accent);
  color: var(--projects-on-acid);
  background: var(--projects-acid);
  box-shadow: 3px 3px 0 var(--shadow-hard);
  transition: transform 150ms ease, box-shadow 150ms ease, background 150ms ease;
}

.wechat-page :deep(.monitor-btn-primary:hover:not(:disabled)) {
  background: var(--acid-strong);
  transform: translate(-1px, -1px);
}

.wechat-page :deep(.monitor-btn-primary:disabled) {
  cursor: not-allowed;
  opacity: 0.4;
}

.wechat-page :deep(.monitor-btn-secondary) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 14px;
  font-size: 12px;
  font-weight: 800;
  line-height: 1;
  border-radius: 4px;
  border: 1px solid var(--projects-accent);
  color: var(--projects-accent);
  background: var(--projects-paper-light);
  transition: transform 150ms ease, box-shadow 150ms ease, background 150ms ease, color 150ms ease;
}

.wechat-page :deep(.monitor-btn-secondary:hover:not(:disabled)) {
  background: var(--acid-soft);
  color: var(--ink);
  transform: translate(-1px, -1px);
  box-shadow: 2px 2px 0 var(--shadow-hard);
}

.wechat-page :deep(.monitor-btn-secondary:disabled) {
  cursor: not-allowed;
  opacity: 0.4;
}

.wechat-page :deep(.monitor-badge) {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 700;
  line-height: 1.4;
  border-radius: 4px;
  border: 1px solid var(--projects-accent);
  color: var(--ink-muted);
  background: var(--projects-paper-light);
}

.wechat-page :deep(.monitor-status-success) {
  color: var(--success-ink);
  background: var(--success-bg);
  border-color: var(--success-border);
}

.wechat-page :deep(.monitor-status-error) {
  color: var(--error-ink);
  background: var(--error-bg);
  border-color: var(--error-accent);
}

.wechat-page :deep(.monitor-status-running) {
  color: var(--tech-primary);
  background: rgb(var(--tech-primary-rgb) / 0.12);
  border-color: rgb(var(--tech-primary-rgb) / 0.3);
}

.wechat-page :deep(.monitor-avatar) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--projects-accent);
  border-radius: 6px;
  background: var(--paper-raised);
  color: var(--projects-accent);
  box-shadow: 2px 2px 0 var(--shadow-hard);
}

.wechat-page :deep(.monitor-avatar-accent) {
  background: var(--projects-acid);
  color: var(--projects-on-acid);
}

.wechat-page :deep(.monitor-empty) {
  border: 1px dashed var(--rule);
  background: rgb(var(--card-rgb) / 0.3);
  color: var(--ink-muted);
}

.wechat-page :deep(.monitor-divider) {
  border-color: var(--rule);
}

.wechat-page :deep(.monitor-input) {
  padding: 8px 10px;
  border: 1px solid var(--projects-accent);
  border-radius: 4px;
  background: var(--projects-paper-light);
  color: var(--ink);
  outline: none;
  transition: box-shadow 150ms ease, border-color 150ms ease;
}

.wechat-page :deep(.monitor-input:focus) {
  border-color: var(--projects-accent);
  box-shadow: 3px 3px 0 var(--shadow-hard);
}

.wechat-page :deep(.text-2xs) {
  font-size: 0.65rem;
  line-height: 0.875rem;
}

@media (prefers-reduced-motion: reduce) {
  .wechat-page :deep(*),
  .wechat-page :deep(*::before),
  .wechat-page :deep(*::after) {
    scroll-behavior: auto !important;
    transition-duration: 0.01ms !important;
    animation-duration: 0.01ms !important;
  }
}
</style>
