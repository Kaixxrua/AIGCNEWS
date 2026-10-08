<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Star } from 'lucide-vue-next'

/** 顶栏「收藏本站」—— 浏览器安全模型不允许网页代写书签，
    点击星星弹出快捷键引导气泡：桌面 Ctrl/⌘+D，触屏改为浏览器菜单指引。 */
const { t } = useI18n()

const open = ref(false)
const root = ref<HTMLElement | null>(null)

const ua = window.navigator.userAgent
const platform = window.navigator.platform
// iPadOS 13+ 自报 Macintosh，用触点数识别；触屏设备没有 Ctrl+D 语义。
const isTouchDevice = /Android|iPhone|iPad|iPod|Mobile/i.test(ua)
  || (platform === 'MacIntel' && window.navigator.maxTouchPoints > 1)
const isMacDesktop = !isTouchDevice && /mac/i.test(platform || ua)
const shortcut = isMacDesktop ? '⌘ + D' : 'Ctrl + D'

const close = () => { open.value = false }
const toggle = () => { open.value = !open.value }

const onDocumentClick = (event: MouseEvent) => {
  if (!root.value?.contains(event.target as Node)) close()
}
const onKeydown = (event: KeyboardEvent) => {
  if (event.key === 'Escape') close()
}

watch(open, (isOpen) => {
  if (isOpen) {
    document.addEventListener('click', onDocumentClick, true)
    document.addEventListener('keydown', onKeydown)
  } else {
    document.removeEventListener('click', onDocumentClick, true)
    document.removeEventListener('keydown', onKeydown)
  }
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocumentClick, true)
  document.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div ref="root" class="favorites-link-wrap">
    <button
      type="button"
      class="favorites-link"
      data-tour="bookmark"
      :class="{ 'favorites-link--open': open }"
      :aria-expanded="open"
      aria-haspopup="dialog"
      :aria-label="t('masthead.favoriteSite')"
      :title="t('masthead.favoriteSite')"
      @click="toggle"
    >
      <Star
        class="favorites-link__icon"
        :size="18"
        :stroke-width="1.8"
        fill="none"
        aria-hidden="true"
      />
    </button>
    <Transition name="favorite-guide">
      <div
        v-if="open"
        class="favorite-guide"
        role="dialog"
        :aria-label="t('masthead.favoriteSite')"
      >
        <p v-if="isTouchDevice" class="favorite-guide__text">
          {{ t('masthead.favoriteSiteGuideTextTouch') }}
        </p>
        <p v-else class="favorite-guide__text">
          <kbd class="favorite-guide__kbd">{{ shortcut }}</kbd>
          <span>{{ t('masthead.favoriteSiteGuideText') }}</span>
        </p>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.favorites-link-wrap {
  position: relative;
  display: inline-flex;
  flex: 0 0 auto;
}

.favorites-link {
  display: inline-grid;
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 50%;
  color: var(--ink-muted);
  background: transparent;
  cursor: pointer;
  transition: color 150ms ease, background-color 150ms ease, transform 150ms ease;
}

.favorites-link:hover,
.favorites-link--open {
  color: var(--ink);
  background: var(--acid-soft);
}

.favorites-link:hover { transform: rotate(-3deg); }
.favorites-link:active { transform: rotate(-3deg) scale(0.92); }
.favorites-link:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }

/* 快捷键引导气泡：安静但可发现 —— 纸面卡片 + 硬边框 + 轻错版阴影 */
.favorite-guide {
  position: absolute;
  top: calc(100% + 8px);
  left: 50%;
  transform: translateX(-50%);
  z-index: 120;
  width: max-content;
  max-width: 260px;
  padding: 10px 14px;
  border: 1px solid var(--rule-strong);
  border-radius: 8px;
  background: var(--paper-raised);
  box-shadow: 3px 3px 0 var(--shadow-ink-soft);
}

.favorite-guide__text {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--ink);
  white-space: nowrap;
}

.favorite-guide__kbd {
  padding: 2px 7px;
  border: 1px solid var(--rule-strong);
  border-radius: 5px;
  background: var(--paper);
  box-shadow: 0 1.5px 0 var(--rule-strong);
  font-family: inherit;
  font-size: 11px;
  font-weight: 700;
  color: var(--ink);
}

.favorite-guide-enter-active,
.favorite-guide-leave-active {
  transition: opacity 160ms ease, translate 160ms ease;
}
.favorite-guide-enter-from,
.favorite-guide-leave-to {
  opacity: 0;
  translate: 0 -4px;
}

@media (prefers-reduced-motion: reduce) {
  .favorites-link { transition: none; }
  .favorites-link:hover,
  .favorites-link:active { transform: none; }
  .favorite-guide-enter-active,
  .favorite-guide-leave-active { transition: none; }
}
</style>
