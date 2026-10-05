<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { installNotFoundMessages } from '@/i18n/locales/notFound'

installNotFoundMessages()

const { t } = useI18n()
const route = useRoute()
const router = useRouter()

// 地址原样给人看：vue-router 的 path 是编码过的，中文路径要解码；解不开（残缺的 %xx）就照原样。
const shownPath = computed(() => {
  try {
    return decodeURI(route.path)
  } catch {
    return route.path
  }
})
// 站内点进来的才有上一页可回；从搜索结果、书签直接打开的，返回会离开本站，不给这个按钮。
const canGoBack = Boolean(window.history.state?.back)
// 游客能看的几个大栏目，名字沿用报眉版名。
const SECTIONS = [
  { to: '/projects', key: 'projects' },
  { to: '/report', key: 'report' },
  { to: '/ui-library', key: 'uiLibrary' },
  { to: '/mcp', key: 'mcp' },
] as const
</script>

<template>
  <div class="not-found">
    <section class="not-found__card comic-panel" aria-labelledby="not-found-title">
      <header class="not-found__head">
        <p class="not-found__code" aria-hidden="true">404</p>
        <h1 id="not-found-title" class="not-found__title comic-title">{{ t('notFound.title') }}</h1>
      </header>
      <p class="not-found__path"><code>{{ shownPath }}</code></p>
      <p class="not-found__lead">{{ t('notFound.lead') }}</p>
      <div class="not-found__actions">
        <RouterLink class="not-found__action not-found__action--home comic-btn comic-btn--ink" to="/">{{ t('notFound.home') }}</RouterLink>
        <button v-if="canGoBack" type="button" class="not-found__action comic-btn" @click="router.back()">{{ t('notFound.back') }}</button>
      </div>
      <nav class="not-found__sections" aria-labelledby="not-found-sections">
        <p id="not-found-sections" class="not-found__sections-label">{{ t('notFound.sections') }}</p>
        <ul>
          <li v-for="section in SECTIONS" :key="section.to">
            <RouterLink class="not-found__section comic-chip" :to="section.to">{{ t(`masthead.sections.${section.key}`) }}</RouterLink>
          </li>
        </ul>
      </nav>
    </section>
  </div>
</template>

<style scoped>
.not-found { display: flex; flex-direction: column; width: 100%; height: 100%; overflow-y: auto; padding: 20px 16px 28px; box-sizing: border-box; }
/* margin:auto 居中，内容比视口高时从顶边开始排、能滚到，不像 align-items:center 那样把顶部裁掉 */
.not-found__card { width: 100%; max-width: 620px; margin: auto; box-sizing: border-box; }
.not-found__head { display: flex; flex-direction: column; align-items: flex-start; gap: 6px; }
.not-found__code { margin: 0; color: var(--ink); font-size: 72px; font-style: italic; font-weight: 950; line-height: 1; letter-spacing: -.05em; text-shadow: 4px 4px 0 var(--acid); }
.not-found__path { margin: 16px 0 0; }
.not-found__path code {
  display: inline-block; max-width: 100%; padding: 2px 9px; border: 1.5px solid var(--rule); border-radius: 5px;
  background: var(--acid-soft); color: var(--ink); font: 600 13px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; overflow-wrap: anywhere;
}
.not-found__lead { margin: 10px 0 0; color: var(--ink-secondary); font-size: 15px; line-height: 1.7; }
.not-found__actions { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 22px; }
.not-found__sections { margin-top: 24px; padding-top: 18px; border-top: 1.5px dashed var(--rule); }
.not-found__sections-label { margin: 0 0 10px; color: var(--ink-muted); font-size: 13px; font-weight: 600; }
.not-found__sections ul { display: flex; flex-wrap: wrap; gap: 10px; margin: 0; padding: 0; list-style: none; }
.not-found a:focus-visible, .not-found button:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }

/* 手机与平板没有漫画版样式表（comic-pages.css 只在桌面宽度挂上），画框、按钮、栏目签在这里按同样的笔触画。 */
@media (max-width: 1023px) {
  .not-found__card { padding: 26px 20px 22px; border: solid var(--rule-strong); border-width: 2px 2.5px 3px 2px; border-radius: 6px 8px 5px 9px; background: var(--paper-raised); }
  .not-found__title { margin: 0; color: var(--ink); font-size: 26px; font-weight: 900; line-height: 1.25; }
  .not-found__action {
    display: inline-flex; align-items: center; justify-content: center; min-height: 44px; padding: 8px 18px;
    border: solid var(--rule-strong); border-width: 2px 2.5px 2.5px 2px; border-radius: 6px 8px 5px 9px;
    background: var(--paper-raised); color: var(--ink); font-size: 15px; font-weight: 800; line-height: 1.2; cursor: pointer;
  }
  .not-found__action--home { background: var(--ink); color: var(--paper-raised); }
  .not-found__section {
    display: inline-flex; align-items: center; min-height: 40px; padding: 6px 14px;
    border: 1.5px solid var(--rule-strong); border-radius: 6px 8px 5px 9px; background: var(--paper-raised); color: var(--ink); font-size: 14px; font-weight: 700;
  }
}

/* 桌面：画框、标题、按钮和栏目签用漫画版的 comic-panel / comic-title / comic-btn / comic-chip，这里只管留白与字号。 */
@media (min-width: 1024px) {
  .not-found { padding: 24px 48px calc(var(--peel-clear, 0px) + 28px); }
  .not-found__card { max-width: 640px; padding: 34px 40px 30px; }
  .not-found__code { font-size: 96px; text-shadow: 5px 5px 0 var(--acid); }
}
</style>
