<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { dockSuppressed } from '@/composables/useDockSuppression'

const { t } = useI18n()
defineProps<{
  brandName: string
  embedded?: boolean
}>()

// 工信部 ICP 备案号：按公示惯例链接至备案管理系统（备案号为固定登记文本，不做 i18n）
const icpNumber = '蜀ICP备2026011291号'
const icpLookupUrl = 'https://beian.miit.gov.cn/'

// 本行 z-index 高于全屏浮层遮罩，浮层（登录对话框等）打开期间须随 dock
// 一起隐藏，否则会浮在遮罩上层且链接仍可点击
const infringementMailto = computed(() => `mailto:kaixxrua@gmail.com?subject=${encodeURIComponent(t('footer.infringement'))}`)
</script>

<template>
  <!-- ═══ Dock 下方小字（版权 / 免责 / 隐私 / 商务合作 / 侵权投诉） ═══ -->
  <div v-show="!dockSuppressed" class="dock-footer" :class="{ 'dock-footer--embedded': embedded }">
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
  bottom: 4px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 99;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: center;
  gap: 0 2px;
  /* fixed + left:50% 时 shrink-to-fit 可用宽度会被 left 偏移吃掉一半，
     长文案（英文）被压成两行后顶行会钻进 dock 底部；
     显式 max-content 让单行用满视口宽度，max-width 兜底窄屏折行 */
  width: max-content;
  max-width: calc(100vw - 24px);
  font-size: 12px;
  /* 两行时总高 24px + bottom 4px，恰好收进 dock 下方 28px 安全区 */
  line-height: 1.2;
  font-weight: 400;
  color: var(--ink-secondary);
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
  color: var(--ink-secondary);
  text-decoration: none;
  transition: color 0.2s;
}

.footer-link:hover {
  color: var(--ink);
  text-decoration: underline;
}


.dock-footer--embedded {
  position: static;
  width: 100%;
  max-width: none;
  transform: none;
  justify-content: flex-start;
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--rule);
  color: var(--ink-muted);
  font-size: 12px;
  line-height: 2;
  white-space: normal;
  overflow-wrap: anywhere;
}
.dock-footer--embedded .footer-link { color: var(--ink-secondary); }
@media (max-width: 1023px) { .dock-footer:not(.dock-footer--embedded) { display: none; } }
</style>
