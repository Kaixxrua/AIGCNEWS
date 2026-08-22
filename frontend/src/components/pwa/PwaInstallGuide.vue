<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import { usePwaInstall } from '@/pwa/installPrompt'

const { t } = useI18n()
const { showIOSGuide, closeIOSGuide } = usePwaInstall()
</script>

<template>
  <!-- iOS 安装指引：右下角小卡片（与更新提示同族），安静但可发现；
       安装本身无系统弹窗，只能给两步指引。 -->
  <Transition name="pwa-ios-guide">
    <div
      v-if="showIOSGuide"
      class="pwa-ios-card"
      role="dialog"
      aria-modal="false"
      :aria-label="t('pwa.iosGuideTitle')"
    >
      <p class="pwa-ios-card__title">{{ t('pwa.iosGuideTitle') }}</p>
      <ol class="pwa-ios-card__steps">
        <li>
          <span class="pwa-ios-card__step-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 3v12"/>
              <polyline points="7,7 12,3 17,7"/>
              <path d="M5 12v7a2 2 0 002 2h10a2 2 0 002-2v-7"/>
            </svg>
          </span>
          <span>{{ t('pwa.iosGuideStepShare') }}</span>
        </li>
        <li>
          <span class="pwa-ios-card__step-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <rect x="4" y="3" width="16" height="18" rx="3"/>
              <line x1="12" y1="9" x2="12" y2="15"/>
              <line x1="9" y1="12" x2="15" y2="12"/>
            </svg>
          </span>
          <span>{{ t('pwa.iosGuideStepAdd') }}</span>
        </li>
      </ol>
      <p class="pwa-ios-card__note">{{ t('pwa.iosGuideNote') }}</p>
      <div class="pwa-ios-card__actions">
        <button
          type="button"
          class="pwa-ios-card__btn pwa-ios-card__btn--primary"
          @click="closeIOSGuide"
        >
          {{ t('pwa.gotIt') }}
        </button>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.pwa-ios-card {
  position: fixed;
  right: 20px;
  bottom: 20px;
  z-index: 120;
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: min(320px, calc(100vw - 32px));
  border: 1px solid var(--ink, #151512);
  border-radius: 8px;
  padding: 14px 16px;
  color: var(--ink, #151512);
  background: var(--paper-raised, #fffefa);
  box-shadow: 4px 4px 0 var(--toast-shadow, rgba(17, 17, 15, 0.18));
}

.pwa-ios-card__title {
  margin: 0;
  font-size: 13px;
  font-weight: 700;
  line-height: 1.4;
}

.pwa-ios-card__steps {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 12px;
  line-height: 1.5;
}

.pwa-ios-card__steps li {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.pwa-ios-card__step-icon {
  display: inline-flex;
  width: 18px;
  height: 18px;
  flex: 0 0 18px;
  align-items: center;
  justify-content: center;
  color: var(--acid-ink, #171a09);
}

.pwa-ios-card__step-icon svg {
  width: 18px;
  height: 18px;
}

.pwa-ios-card__note {
  margin: 0;
  font-size: 11px;
  line-height: 1.5;
  color: var(--ink-muted, #797a70);
}

.pwa-ios-card__actions {
  display: flex;
  justify-content: flex-end;
}

.pwa-ios-card__btn {
  min-height: 36px;
  border: 1px solid var(--ink, #151512);
  border-radius: 6px;
  padding: 6px 14px;
  color: var(--ink, #151512);
  background: transparent;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.4;
  cursor: pointer;
}

.pwa-ios-card__btn--primary {
  color: var(--ink-on-solid, #ffffff);
  background: var(--ink-solid, #44403c);
  border-color: var(--ink-solid, #44403c);
}

.pwa-ios-card__btn--primary:hover {
  background: var(--ink-solid-hover, #292524);
  border-color: var(--ink-solid-hover, #292524);
}

/* 移动端：卡片落在 dock 上方，避开底部导航与 home 指示条。 */
@media (max-width: 639px) {
  .pwa-ios-card {
    right: 12px;
    left: 12px;
    bottom: max(76px, calc(env(safe-area-inset-bottom) + 68px));
    width: auto;
  }
}

.pwa-ios-guide-enter-active,
.pwa-ios-guide-leave-active {
  transition: opacity 180ms ease, transform 180ms ease;
}

.pwa-ios-guide-enter-from,
.pwa-ios-guide-leave-to {
  opacity: 0;
  transform: translateY(8px);
}

@media (prefers-reduced-motion: reduce) {
  .pwa-ios-guide-enter-active,
  .pwa-ios-guide-leave-active {
    transition: none;
  }
}
</style>
