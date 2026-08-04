<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useXBoardController } from '@/composables/useXBoardController'
import { countTweets, tweetTimestamp } from '@/features/xboard/xBoardViewModel'
import { scoreDisplay } from '@/features/dashboard/dashboardViewModel'

const { t } = useI18n()

// 自包含视图：日期选择 + source=x 日榜拉取 + 按账号分组（分组逻辑在 xBoardViewModel）
const {
  sections, docs, selectedDate, today, loading, errorMsg,
  load, onDateChange, refresh, dispose,
} = useXBoardController({ translate: t })

const totalTweets = () => countTweets(sections.value)

const formatTime = (doc: Parameters<typeof tweetTimestamp>[0]) => (
  tweetTimestamp(doc).slice(0, 16).replace('T', ' ')
)

onMounted(load)
onBeforeUnmount(dispose)
</script>

<template>
  <div class="flex h-full min-h-0 flex-col overflow-hidden">
    <div class="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto p-6 pb-24">

      <!-- 页头 -->
      <div class="stagger-enter flex shrink-0 flex-wrap items-center justify-between gap-3">
        <div>
          <h1 class="font-serif text-2xl font-bold tracking-tight text-stone-800">{{ t('xboard.title') }}</h1>
          <p class="mt-0.5 text-sm text-stone-400">{{ t('xboard.subtitle') }}</p>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <label class="flex items-center gap-2 text-xs text-stone-400">
            {{ t('xboard.dateLabel') }}
            <input
              type="date"
              class="input py-1.5 text-xs"
              :value="selectedDate"
              :max="today"
              @change="onDateChange(($event.target as HTMLInputElement).value)"
            />
          </label>
          <button class="btn-secondary" :disabled="loading" @click="refresh">
            <svg class="h-3.5 w-3.5" :class="loading ? 'animate-spin' : ''" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/></svg>
            {{ t(loading ? 'common.refreshing' : 'common.refresh') }}
          </button>
        </div>
      </div>

      <!-- 错误提示 -->
      <div v-if="errorMsg" class="shrink-0 glass-card flex items-center justify-between px-5 py-3 text-sm text-rose-600">
        <span>{{ errorMsg }}</span>
        <button class="ml-3 text-rose-400 transition hover:text-rose-600" @click="errorMsg = ''">
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>

      <!-- 加载 / 空态 -->
      <div v-if="loading && !docs.length" class="glass-card flex min-h-[240px] items-center justify-center gap-2 text-sm text-stone-400">
        <span class="inline-block h-4 w-4 animate-spin rounded-full border-2 border-stone-200 border-t-stone-500" />{{ t('xboard.loading') }}
      </div>
      <div v-else-if="!sections.length" class="glass-card flex min-h-[240px] flex-col items-center justify-center text-center text-sm text-stone-400">
        <p class="font-medium text-stone-500">{{ t('xboard.empty') }}</p>
        <p class="mt-1 text-xs">{{ t('xboard.emptyHint') }}</p>
      </div>

      <!-- 账号分区 -->
      <div v-else class="grid gap-5 xl:grid-cols-2">
        <section v-for="section in sections" :key="section.handle || '_unknown'" class="stagger-enter glass-card shrink-0 overflow-hidden p-0">
          <div class="flex flex-wrap items-center justify-between gap-2 border-b border-stone-200/60 bg-gradient-to-br from-white/80 via-stone-50/50 to-stone-100/60 px-5 py-3.5">
            <div class="flex min-w-0 items-center gap-2">
              <span class="flex h-7 w-7 shrink-0 items-center justify-center rounded-xl bg-stone-900 font-mono text-xs font-bold text-white">𝕏</span>
              <a
                v-if="section.handle"
                class="truncate text-sm font-semibold text-stone-700 hover:text-stone-900"
                :href="`https://x.com/${section.handle}`"
                target="_blank"
                rel="noopener noreferrer"
              >@{{ section.handle }}</a>
              <span v-else class="truncate text-sm font-semibold text-stone-500">{{ t('xboard.unknownHandle') }}</span>
              <span class="badge border border-stone-200 bg-white/80 text-stone-500">{{ t('xboard.tweets', { count: section.tweets.length }) }}</span>
            </div>
            <span class="text-2xs text-stone-400">{{ t('xboard.maxScore', { score: Math.round(section.maxScore) }) }}</span>
          </div>
          <ul class="divide-y divide-stone-100">
            <li v-for="tweet in section.tweets" :key="tweet.url || tweet.title" class="px-5 py-3 transition hover:bg-stone-50/60">
              <div class="flex items-start gap-3">
                <span class="mt-0.5 flex shrink-0 items-center gap-1 rounded-full border border-stone-200 bg-stone-50 px-2 py-0.5 text-2xs font-medium text-stone-500">
                  <component :is="scoreDisplay(tweet).icon" class="h-3 w-3 shrink-0" />{{ scoreDisplay(tweet).text }}
                </span>
                <div class="min-w-0 flex-1">
                  <a :href="tweet.url" target="_blank" rel="noopener noreferrer" class="block text-sm leading-5 text-stone-700 hover:text-stone-900">
                    {{ tweet.title }}
                  </a>
                  <p v-if="tweet.summary && tweet.summary !== tweet.title" class="mt-1 line-clamp-3 whitespace-pre-line text-xs leading-5 text-stone-500">{{ tweet.summary }}</p>
                  <p v-if="formatTime(tweet)" class="mt-1 text-2xs text-stone-400">{{ formatTime(tweet) }}</p>
                </div>
              </div>
            </li>
          </ul>
        </section>
      </div>

      <p v-if="sections.length" class="shrink-0 text-center text-2xs text-stone-300">{{ t('xboard.tweets', { count: totalTweets() }) }}</p>
    </div>
  </div>
</template>
