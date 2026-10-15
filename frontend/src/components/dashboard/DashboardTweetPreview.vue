<script setup lang="ts">
import { computed, nextTick, onMounted, ref, useId, watch } from 'vue'
import { useResizeObserver } from '@vueuse/core'
import RankingAvatar from './RankingAvatar.vue'
import { useI18n } from 'vue-i18n'
import type { TopDoc } from '@/features/dashboard/dashboardViewModel'
import { authorDisplayName, displayTweetText, formatLocalTime, tweetTimestamp } from '@/features/xboard/xBoardViewModel'

const props = defineProps<{ doc: TopDoc; rank: number }>()
const { t, locale } = useI18n()
const contentId = useId()
const content = ref<HTMLElement | null>(null)
const expanded = ref(false)
const overflowing = ref(false)
const text = computed(() => displayTweetText(props.doc, locale.value))
const author = computed(() => authorDisplayName(props.doc) || 'X')
const publishedTime = computed(() => formatLocalTime(tweetTimestamp(props.doc)))

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
      <time v-if="publishedTime" class="tweet-preview__time" :datetime="tweetTimestamp(doc)">{{ publishedTime }}</time>
      <a v-if="doc.url" :href="doc.url" target="_blank" rel="noopener noreferrer">{{ t('xboard.viewOnX') }} <span aria-hidden="true">↗</span></a>
    </div>
  </article>
</template>

<style scoped>
.tweet-preview { min-width: 0; padding: 14px 14px 8px; }
.tweet-preview__author { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; font-size: 14px; line-height: 1.5; }
.tweet-preview__author strong { min-width: 0; overflow-wrap: anywhere; font-weight: 650; color: var(--ink); }
.tweet-preview__rank { flex-shrink: 0; color: var(--ink-muted); font-size: 12px; font-variant-numeric: tabular-nums; }
.tweet-preview__text { margin: 0; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 4; overflow: hidden; overflow-wrap: anywhere; white-space: pre-line; font-size: 15px; font-weight: 400; line-height: 1.65; color: var(--ink); }
.tweet-preview__text--expanded { display: block; -webkit-line-clamp: unset; overflow: visible; }
.tweet-preview__actions { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 0 12px; margin-top: 10px; padding-top: 4px; border-top: 1px solid var(--rule); }
.tweet-preview__time { grid-column: 1; min-width: 0; overflow-wrap: anywhere; color: var(--ink-secondary); font-size: 12px; line-height: 1.5; font-variant-numeric: tabular-nums; }
.tweet-preview__actions button, .tweet-preview__actions a { display: inline-flex; align-items: center; min-height: 44px; padding: 4px 0; border: 0; border-radius: 0; background: transparent; color: var(--ink-secondary); font-size: 12px; line-height: 1.5; text-decoration: none; cursor: pointer; }
.tweet-preview__actions button { grid-column: 1 / -1; justify-self: start; color: var(--ink); font-size: 13px; font-weight: 600; }
.tweet-preview__actions a { grid-column: 2; justify-self: end; gap: 4px; white-space: nowrap; }
.tweet-preview__actions :is(button, a):hover { color: var(--ink); text-decoration: underline; }
.tweet-preview__actions :is(button, a):focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
</style>
