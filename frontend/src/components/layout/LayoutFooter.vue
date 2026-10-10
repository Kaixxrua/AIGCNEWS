<script setup lang="ts">
import { computed, ref } from 'vue'
import { useResizeObserver } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
import { dockSuppressed } from '@/composables/useDockSuppression'
import ComicSticker from './ComicSticker.vue'

const { t } = useI18n()
defineProps<{
  brandName: string
  embedded?: boolean
  editorial?: boolean
}>()

// 工信部 ICP 备案号：按公示惯例链接至备案管理系统（备案号为固定登记文本，不做 i18n）
const icpNumber = '蜀ICP备2026011291号'
const icpLookupUrl = 'https://beian.miit.gov.cn/'
const year = new Date().getFullYear()
const aboutDialog = ref<HTMLDialogElement | null>(null)
const footerElement = ref<HTMLElement | null>(null)
const emit = defineEmits<{ resize: [height: number] }>()
useResizeObserver(footerElement, ([entry]) => {
  // Border-box includes the content-page padding; keep the last size while overlays hide the footer.
  const height = entry?.borderBoxSize[0]?.blockSize ?? footerElement.value?.offsetHeight ?? 0
  if (height > 0) emit('resize', height)
}, { box: 'border-box' })

// 本行 z-index 高于全屏浮层遮罩，浮层（登录对话框等）打开期间须随 dock
// 一起隐藏，否则会浮在遮罩上层且链接仍可点击
const infringementMailto = computed(() => `mailto:kaixxrua@gmail.com?subject=${encodeURIComponent(t('footer.infringement'))}`)
</script>

<template>
  <!-- ═══ Dock 下方小字（版权 / 免责 / 隐私 / 商务合作 / 侵权投诉） ═══ -->
  <div ref="footerElement" v-show="!dockSuppressed" class="dock-footer" :class="{ 'dock-footer--embedded': embedded, 'dock-footer--editorial': editorial && !embedded }">
    <template v-if="editorial && !embedded">
      <ComicSticker variant="peel" class="comic-footer-sticker" />
      <div class="footer-brand">
        <RouterLink to="/" class="footer-wordmark">{{ brandName }}</RouterLink>
        <span class="footer-brand__tagline">{{ t('footer.createMore') }}</span>
      </div>
      <div class="footer-right">
        <nav class="footer-nav" :aria-label="t('footer.siteInfo')">
          <button type="button" class="footer-link" @click="aboutDialog?.showModal()">{{ t('footer.about') }}</button>
          <RouterLink to="/privacy" class="footer-link">{{ t('footer.privacy') }}</RouterLink>
          <a href="mailto:kaixxrua@gmail.com" class="footer-link">{{ t('footer.contact') }}</a>
        </nav>
        <div class="footer-copyright">
          <span>© {{ year }} {{ brandName }}</span>
          <span>{{ t('footer.discoverMore') }}</span>
          <a :href="icpLookupUrl" target="_blank" rel="noopener noreferrer nofollow" class="footer-link footer-icp">{{ icpNumber }}</a>
        </div>
      </div>
    </template>
    <template v-else>
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
    </template>
  </div>
  <dialog v-if="editorial && !embedded" ref="aboutDialog" class="footer-about" aria-labelledby="footer-about-title">
    <form method="dialog"><button class="footer-about__close" :aria-label="t('common.close')">×</button></form>
    <h2 id="footer-about-title">{{ t('footer.about') }} · {{ brandName }}</h2>
    <p>{{ t('footer.aboutDescription') }}</p>
    <nav :aria-label="t('footer.siteInfo')">
      <RouterLink to="/disclaimer" @click="aboutDialog?.close()">{{ t('footer.disclaimer') }}</RouterLink>
      <RouterLink to="/mcp" @click="aboutDialog?.close()">{{ t('footer.mcp') }}</RouterLink>
      <a href="mailto:kaixxrua@gmail.com">{{ t('footer.contact') }}</a>
      <a :href="infringementMailto">{{ t('footer.infringement') }}</a>
    </nav>
  </dialog>
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
.dock-footer--editorial {
  bottom: 8px; left: 42px; right: 32px; width: auto; max-width: none;
  height: auto; min-height: 74px; transform: none; justify-content: space-between;
  flex-wrap: nowrap; font-size: 12px; color: var(--ink-muted); pointer-events: none;
}
.footer-brand, .footer-right { display: flex; align-items: center; gap: 20px; pointer-events: auto; }
.footer-brand { max-width: calc((100vw - 880px) / 2); }
.footer-wordmark { position: relative; color: var(--ink); font-size: 18px; font-weight: 850; letter-spacing: -.04em; }
.footer-wordmark::before { content: ''; position: absolute; left: 0; top: 2px; bottom: 2px; width: 4px; background: var(--acid); transform: skewX(-25deg); z-index: -1; }
.footer-brand__tagline { border-left: 1px solid var(--rule); padding-left: 20px; }
.footer-right { gap: 16px; }
.footer-nav { display: flex; align-items: center; gap: 20px; }
.footer-nav button { font: inherit; background: none; border: 0; padding: 0; cursor: pointer; }
.footer-copyright { display: flex; flex-direction: column; gap: 4px; border-left: 1px solid var(--rule); padding-left: 18px; font-size: 10px; }
.footer-icp { font-size: 9px; }
.footer-about { position: fixed; inset: 0; margin: auto; max-width: min(480px, calc(100vw - 32px)); padding: 28px; border: 1px solid var(--rule-strong); border-radius: 5px; background: var(--paper-raised); color: var(--ink); box-shadow: 4px 4px 0 #171a14; }
.footer-about::backdrop { background: rgb(0 0 0 / .45); }
.footer-about h2 { margin: 0 28px 16px 0; font-size: 20px; font-weight: 750; }
.footer-about p { white-space: normal; line-height: 1.8; }
.footer-about nav { display: flex; flex-wrap: wrap; gap: 16px; margin-top: 20px; font-size: 13px; }
.footer-about nav a:hover { text-decoration: underline; }
.footer-about__close { position: absolute; right: 10px; top: 10px; width: 32px; height: 32px; font-size: 24px; }
@media (min-width: 1024px) and (max-width: 1599px) {
  .dock-footer--editorial { left: 24px; right: 24px; }
  .footer-brand { flex-direction: column; align-items: flex-start; gap: 6px; }
  .footer-brand__tagline { border: 0; padding: 0; font-size: 11px; }
  .footer-right { flex-direction: column; align-items: flex-end; gap: 7px; }
  .footer-nav { gap: 14px; font-size: 11px; }
  .footer-copyright { border: 0; padding: 0; text-align: right; gap: 3px; }
  .footer-copyright > span:nth-child(2) { display: none; }
}
@media (min-width: 1024px) and (max-width: 1199px) { .footer-brand__tagline { display: none; } .footer-wordmark { font-size: 14px; } .footer-nav { gap: 9px; font-size: 10px; } .footer-icp { font-size: 8px; } }
@media (max-width: 1023px) { .dock-footer:not(.dock-footer--embedded) { display: none; } }

/* Reserve the same center lane as the dock. Locale text wraps only in its own side. */
@media (min-width: 1024px) {
 .dock-footer--editorial { left: 16px; right: 16px; display: grid; grid-template-columns: minmax(0, 1fr) var(--home-dock-width, clamp(560px, 58vw, 900px)) minmax(0, 1fr); column-gap: 16px; }
 .dock-footer--editorial .footer-brand { grid-column: 1; max-width: none; min-width: 0; flex-direction: column; align-items: flex-start; gap: 6px; white-space: normal; }
 .dock-footer--editorial .footer-brand__tagline { border: 0; padding: 0; font-size: 11px; }
 .dock-footer--editorial .footer-right { grid-column: 3; min-width: 0; flex-direction: column; align-items: flex-end; gap: 5px; white-space: normal; }
 .dock-footer--editorial .footer-nav { justify-content: flex-end; flex-wrap: wrap; gap: 4px 12px; font-size: 11px; }
 .dock-footer--editorial .footer-link { display:inline-flex;align-items:center;min-height:24px;white-space:nowrap; }
 .dock-footer--editorial .footer-copyright { border: 0; padding: 0; text-align: right; gap: 3px; }
}
@media (min-width: 1024px) and (max-width: 1199px) {
 .dock-footer--editorial .footer-nav { gap: 4px 8px; font-size: 10px; }
}

</style>
