<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { showInstallEntry, usePwaInstall } from '@/pwa/installPrompt'

/** 顶栏下载入口：普通网页中常驻，浏览器支持时调用系统安装弹窗，
    其余情况展示安装指引；已安装的独立应用中隐藏。 */
const { t } = useI18n()
const { promptInstall } = usePwaInstall()
</script>

<template>
  <button
    v-if="showInstallEntry"
    type="button"
    class="pwa-install-link"
    :aria-label="t('pwa.installApp')"
    :title="t('pwa.installApp')"
    @click="promptInstall"
  >
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="1.8"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
    >
      <path d="M12 3v10" />
      <polyline points="7,9 12,14 17,9" />
      <path d="M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2" />
    </svg>
  </button>
</template>

<style scoped>
.pwa-install-link {
  display: inline-grid;
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 50%;
  color: var(--ink);
  background: var(--acid-soft);
  cursor: pointer;
  transition: color 150ms ease, background-color 150ms ease, transform 150ms ease;
}

.pwa-install-link:hover {
  color: var(--acid-ink);
  background: var(--acid);
  transform: translateY(-1px);
}

.pwa-install-link:active { transform: translateY(-1px) scale(0.92); }
.pwa-install-link:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }

.pwa-install-link svg {
  width: 18px;
  height: 18px;
}

@media (max-width: 767px) {
  .pwa-install-link {
    position: relative;
    isolation: isolate;
    width: 44px;
    height: 44px;
    flex-basis: 44px;
    background: transparent;
  }
  .pwa-install-link::before {
    content: '';
    position: absolute;
    inset: 8px;
    z-index: -1;
    border-radius: 6px;
    background: var(--acid-soft);
  }
  .pwa-install-link:hover::before { background: var(--acid); }
}

@media (prefers-reduced-motion: reduce) {
  .pwa-install-link { transition: none; }
  .pwa-install-link:hover,
  .pwa-install-link:active { transform: none; }
}
</style>
