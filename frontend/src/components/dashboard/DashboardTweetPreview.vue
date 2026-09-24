<script setup lang="ts">
import { computed, nextTick, onMounted, ref, useId, watch } from 'vue'
import { useResizeObserver } from '@vueuse/core'
import RankingAvatar from './RankingAvatar.vue'
import { useI18n } from 'vue-i18n'
import type { TopDoc } from '@/features/dashboard/dashboardViewModel'
import { authorDisplayName, displayTweetText } from '@/features/xboard/xBoardViewModel'

const props = defineProps<{ doc: TopDoc; rank: number }>()
const { t, locale } = useI18n()
const contentId = useId()
const content = ref<HTMLElement | null>(null)
const expanded = ref(false)
const overflowing = ref(false)
const text = computed(() => displayTweetText(props.doc, locale.value))
const author = computed(() => authorDisplayName(props.doc) || 'X')

const measureOverflow = () => {
  if (!expanded.value && content.value) {
    overflowing.value = content.value.scrollHeight > content.value.clientHeight + 1
  }
}
useResizeObserver(content, measureOverflow)
watch(text, async () => {
  expanded.value = false
  await nextTick()
  measureOverflow()
})
watch(expanded, async () => { await nextTick(); measureOverflow() })
onMounted(async () => {
  measureOverflow()
  if (document.fonts) await document.fonts.ready
  measureOverflow()
})
</script>

<template>
  <article class="tweet-preview">
    <header class="tweet-preview__author">
      <span class="tweet-preview__rank">{{ String(rank).padStart(2, '0') }}</span>
      <RankingAvatar :doc="doc" />
      <strong>{{ author }}</strong>
    </header>
    <p :id="contentId" ref="content" class="tweet-preview__text" :class="{ 'tweet-preview__text--expanded': expanded }">{{ text }}</p>
    <div class="tweet-preview__actions">
      <button v-if="overflowing" type="button" :aria-expanded="expanded" :aria-controls="contentId" @click="expanded = !expanded">{{ t(expanded ? 'dashboard.collapseText' : 'dashboard.expandText') }}</button>
      <a v-if="doc.url" :href="doc.url" target="_blank" rel="noopener noreferrer">{{ t('xboard.viewOnX') }} <span aria-hidden="true">↗</span></a>
    </div>
  </article>
</template>

<style scoped>
.tweet-preview { padding: 16px 0; }
.tweet-preview__author { display: flex; align-items: baseline; gap: 12px; margin-bottom: 8px; font-size: 15px; line-height: 1.5; }
.tweet-preview__author strong { font-weight: 650; color: var(--ink); }
.tweet-preview__rank { color: var(--ink-muted); font-size: 13px; font-variant-numeric: tabular-nums; }
.tweet-preview__text { margin: 0; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 4; overflow: hidden; overflow-wrap: anywhere; white-space: pre-line; font-size: 16px; font-weight: 400; line-height: 1.65; color: var(--ink); }
.tweet-preview__text--expanded { display: block; -webkit-line-clamp: unset; overflow: visible; }
.tweet-preview__actions { display: flex; align-items: center; gap: 16px; margin-top: 4px; }
.tweet-preview__actions button, .tweet-preview__actions a { display: inline-flex; align-items: center; min-height: 44px; padding: 4px 0; border: 0; border-radius: 0; background: transparent; color: var(--ink-secondary); font-size: 14px; line-height: 1.5; text-decoration: none; cursor: pointer; }
.tweet-preview__actions button { color: var(--ink); font-weight: 600; }
.tweet-preview__actions a { gap: 4px; margin-left: auto; }
.tweet-preview__actions :is(button, a):hover { color: var(--ink); text-decoration: underline; }
.tweet-preview__actions :is(button, a):focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
</style>
