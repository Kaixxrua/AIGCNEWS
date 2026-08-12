<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
defineProps<{
  brandName: string
}>()

// 工信部 ICP 备案号：按公示惯例链接至备案管理系统（备案号为固定登记文本，不做 i18n）
const icpNumber = '蜀ICP备2026011291号'
const icpLookupUrl = 'https://beian.miit.gov.cn/'

const infringementMailto = computed(() => `mailto:kaixxrua@gmail.com?subject=${encodeURIComponent(t('footer.infringement'))}`)
</script>

<template>
  <!-- ═══ Dock 下方小字（版权 / 免责 / 隐私 / 商务合作 / 侵权投诉） ═══ -->
  <div class="dock-footer">
    <span>{{ t('footer.poweredBy', { brandName }) }}</span>
    <span class="footer-sep">·</span>
    <RouterLink to="/disclaimer" class="footer-link">{{ t('footer.disclaimer') }}</RouterLink>
    <span class="footer-sep">·</span>
    <RouterLink to="/privacy" class="footer-link">{{ t('footer.privacy') }}</RouterLink>
    <span class="footer-sep">·</span>
    <RouterLink to="/mcp" class="footer-link">{{ t('footer.mcp') }}</RouterLink>
    <span class="footer-sep">·</span>
    <span>{{ t('footer.ecosystem') }}<a href="mailto:kaixxrua@gmail.com" class="footer-link">kaixxrua@gmail.com</a></span>
    <span class="footer-sep">·</span>
    <a :href="infringementMailto" class="footer-link">{{ t('footer.infringement') }}</a>
    <span class="footer-sep">·</span>
    <a :href="icpLookupUrl" target="_blank" rel="noopener noreferrer nofollow" class="footer-link">{{ icpNumber }}</a>
  </div>
</template>

<style scoped>
.dock-footer {
  position: fixed;
  bottom: 6px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 99;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: center;
  gap: 0 2px;
  font-size: 10px;
  font-weight: 400;
  color: rgb(var(--stone-400-rgb) / 0.7);
  letter-spacing: 0.02em;
  white-space: nowrap;
  pointer-events: auto;
  user-select: none;
}

.footer-sep {
  margin: 0 5px;
  opacity: 0.5;
}

.footer-link {
  color: rgb(var(--stone-400-rgb) / 0.7);
  text-decoration: none;
  transition: color 0.2s;
}

.footer-link:hover {
  color: rgb(var(--stone-500-rgb));
  text-decoration: underline;
}

@media (max-width: 639px) {
  .dock-footer {
    left: 12px;
    right: 12px;
    bottom: calc(66px + env(safe-area-inset-bottom));
    transform: none;
    max-width: calc(100vw - 24px);
    line-height: 1.5;
    white-space: normal;
    text-align: center;
    overflow-wrap: anywhere;
  }
}
</style>
