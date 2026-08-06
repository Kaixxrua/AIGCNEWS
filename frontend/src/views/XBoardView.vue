<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useXBoardController } from '@/composables/useXBoardController'
import { countTweets, extractXHandle, flattenTweets, hasMedia, mediaItems, tweetText, tweetTimestamp, authorAvatarUrl } from '@/features/xboard/xBoardViewModel'
import { scoreDisplay } from '@/features/dashboard/dashboardViewModel'
import { useAuthStore } from '@/stores/authStore'
import type { TopDoc, TweetMediaItem } from '@/features/dashboard/dashboardViewModel'

const { t } = useI18n()
const authStore = useAuthStore()
const isAdmin = computed(() => authStore.isAdmin)

const {
  sections, docs, selectedDate, today, loading, deleting, errorMsg,
  selectedIds,
  load, onDateChange, refresh, dispose, toggleSelection, selectAll, clearSelection, deleteSelected,
} = useXBoardController({ translate: t })

const masonryTweets = computed(() => flattenTweets(sections.value))
const totalTweets = () => countTweets(sections.value)
const selectedCount = computed(() => selectedIds.value.size)
const hasSelection = computed(() => selectedCount.value > 0)

const formatTime = (doc: TopDoc) => (
  tweetTimestamp(doc).slice(0, 16).replace('T', ' ')
)

const isVideo = (item: TweetMediaItem) => item.type === 'video' || item.type === 'animated_gif'

// X 式点击播放：视频占位零流量（不经代理拉取元数据），点击后才挂载 <video>。
// 键与模板 :key 同源（`${tweet.url}-${index}`），重载推文时清空避免自动重播。
const playingMedia = ref<Set<string>>(new Set())
const mediaKey = (tweet: TopDoc, index: number) => `${tweet.url}-${index}`
const playVideo = (key: string) => {
  const next = new Set(playingMedia.value)
  next.add(key)
  playingMedia.value = next
}
const isPlaying = (key: string) => playingMedia.value.has(key)
watch(docs, () => { playingMedia.value = new Set() })

const isSelected = (doc: TopDoc) => doc.id ? selectedIds.value.has(String(doc.id)) : false

const handleDeleteSelected = async () => {
  if (!hasSelection.value) return
  const confirmed = window.confirm(t('xboard.deleteConfirm', { count: selectedCount.value }))
  if (!confirmed) return
  const { deleted, notFound } = await deleteSelected()
  if (deleted > 0 || notFound > 0) {
    const parts = []
    if (deleted > 0) parts.push(t('xboard.deleteSuccess', { count: deleted }))
    if (notFound > 0) parts.push(t('xboard.deleteNotFound', { count: notFound }))
    window.alert(parts.join('\n'))
  }
}

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

      <!-- 管理员多选工具栏 -->
      <div v-if="isAdmin" class="stagger-enter flex shrink-0 flex-wrap items-center justify-between gap-3 rounded-xl border border-stone-200/60 bg-white/60 px-4 py-2 backdrop-blur-sm">
        <div class="flex items-center gap-3 text-sm text-stone-600">
          <label class="flex cursor-pointer items-center gap-2">
            <input
              type="checkbox"
              class="h-4 w-4 rounded border-stone-300 text-stone-700 focus:ring-stone-500"
              :checked="hasSelection && selectedCount === masonryTweets.length"
              :indeterminate.prop="hasSelection && selectedCount < masonryTweets.length"
              @change="hasSelection ? clearSelection() : selectAll()"
            />
            <span>{{ t('xboard.selectAll') }}</span>
          </label>
          <span v-if="hasSelection" class="text-xs text-stone-400">{{ selectedCount }} / {{ masonryTweets.length }}</span>
        </div>
        <div class="flex items-center gap-2">
          <button
            v-if="hasSelection"
            class="btn-secondary text-xs"
            @click="clearSelection"
          >
            {{ t('xboard.clearSelection') }}
          </button>
          <button
            class="btn-danger text-xs"
            :disabled="!hasSelection || deleting"
            @click="handleDeleteSelected"
          >
            {{ deleting ? t('common.processing') : t('xboard.deleteSelectedCount', { count: selectedCount }) }}
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
      <div v-else-if="!masonryTweets.length" class="glass-card flex min-h-[240px] flex-col items-center justify-center text-center text-sm text-stone-400">
        <p class="font-medium text-stone-500">{{ t('xboard.empty') }}</p>
        <p class="mt-1 text-xs">{{ t('xboard.emptyHint') }}</p>
      </div>

      <!-- 瀑布流推文墙 -->
      <div v-else class="masonry-grid">
        <article
          v-for="tweet in masonryTweets"
          :key="tweet.url || tweet.title"
          class="tweet-card"
        >
          <div class="tweet-head flex flex-wrap items-center gap-2 px-4 py-3">
            <input
              v-if="isAdmin && tweet.id"
              type="checkbox"
              class="h-4 w-4 shrink-0 rounded"
              :checked="isSelected(tweet)"
              @change="toggleSelection(String(tweet.id))"
            />
            <img
              v-if="authorAvatarUrl(tweet)"
              :src="authorAvatarUrl(tweet)"
              :alt="extractXHandle(tweet.url) || ''"
              loading="lazy"
              referrerpolicy="no-referrer"
              class="h-6 w-6 shrink-0 rounded-lg object-cover"
            />
            <span v-else class="tweet-avatar-fallback flex h-6 w-6 shrink-0 items-center justify-center font-mono text-[10px] font-bold">𝕏</span>
            <a
              v-if="extractXHandle(tweet.url)"
              class="tweet-handle truncate px-1 text-xs font-semibold"
              :href="`https://x.com/${extractXHandle(tweet.url)}`"
              target="_blank"
              rel="noopener noreferrer"
            >@{{ extractXHandle(tweet.url) }}</a>
            <span v-else class="tweet-handle truncate px-1 text-xs font-semibold">{{ t('xboard.unknownHandle') }}</span>
            <span class="tweet-score ml-auto shrink-0">
              <component :is="scoreDisplay(tweet).icon" class="h-3 w-3 shrink-0" />{{ scoreDisplay(tweet).text }}
            </span>
          </div>

          <!-- 媒体区 -->
          <div v-if="hasMedia(tweet)" class="tweet-media-list">
            <template v-for="(item, index) in mediaItems(tweet)" :key="mediaKey(tweet, index)">
              <img
                v-if="!isVideo(item)"
                :src="item.url"
                :alt="tweet.title"
                loading="lazy"
                decoding="async"
                referrerpolicy="no-referrer"
                class="w-full object-cover"
                :style="item.width && item.height ? { aspectRatio: `${item.width} / ${item.height}` } : {}"
              />
              <!-- 视频：未点击时渲染零流量占位，点击后挂载 <video> 经代理加载播放 -->
              <video
                v-else-if="isPlaying(mediaKey(tweet, index))"
                :src="item.url"
                controls
                autoplay
                playsinline
                preload="auto"
                class="w-full bg-stone-900"
                :style="item.width && item.height ? { aspectRatio: `${item.width} / ${item.height}` } : {}"
              />
              <button
                v-else
                type="button"
                class="tweet-video-btn group relative flex w-full items-center justify-center"
                :style="{ aspectRatio: item.width && item.height ? `${item.width} / ${item.height}` : '16 / 9' }"
                :aria-label="t('xboard.playVideo')"
                @click="playVideo(mediaKey(tweet, index))"
              >
                <!-- 服务端抽帧封面；加载失败（404/网络）隐藏 img，回退深色占位 -->
                <img
                  v-if="item.poster_url"
                  :src="item.poster_url"
                  :alt="tweet.title"
                  loading="lazy"
                  decoding="async"
                  referrerpolicy="no-referrer"
                  class="absolute inset-0 h-full w-full object-cover"
                  @error="($event.target as HTMLImageElement).style.display = 'none'"
                />
                <span class="absolute inset-0 bg-[radial-gradient(circle_at_30%_20%,rgba(255,255,255,0.08),transparent_60%)]" />
                <span class="tweet-play relative flex h-14 w-14 items-center justify-center rounded-full">
                  <svg class="ml-1 h-6 w-6" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
                </span>
                <span v-if="item.type === 'animated_gif'" class="tweet-gif-badge absolute left-2 top-2 px-1.5 py-0.5 text-2xs font-semibold uppercase tracking-wide">GIF</span>
              </button>
            </template>
          </div>

          <!-- 文字区 -->
          <div class="px-4 py-3">
            <a :href="tweet.url" target="_blank" rel="noopener noreferrer" class="tweet-text block whitespace-pre-line text-sm leading-5">
              {{ tweetText(tweet) }}
            </a>
            <p v-if="formatTime(tweet)" class="tweet-time mt-2 text-2xs">{{ formatTime(tweet) }}</p>
          </div>
        </article>
      </div>

      <p v-if="masonryTweets.length" class="shrink-0 text-center text-2xs text-stone-300">{{ t('xboard.tweets', { count: totalTweets() }) }}</p>
    </div>
  </div>
</template>

<style scoped>
/* 真瀑布流：CSS 多列。原 grid 方案同一行的卡片被拉到同一行高，
   短推文下方出现大片留白；columns 让卡片按自身高度紧密堆叠。
   顺序约定：按分数沿列向下排列（瀑布流标准读法）。 */
.masonry-grid {
  columns: 1;
  column-gap: 1rem;
}

@media (min-width: 768px) {
  .masonry-grid {
    columns: 2;
  }
}

@media (min-width: 1024px) {
  .masonry-grid {
    columns: 3;
  }
}

@media (min-width: 1280px) {
  .masonry-grid {
    columns: 4;
  }
}

/* 卡片：全站纸面语言（paper-raised 平面 + rule 细边 + module 圆角），
   hover 复用 card-hover 的硬边反馈（位移 + 硬影 + 深边）。
   颜色全部走主题变量，data-theme 暗色自动适配。 */
.tweet-card {
  display: inline-block; /* multicol 内防跨列撕裂的稳妥姿势 */
  width: 100%;
  margin: 0 0 1rem;
  vertical-align: top;
  break-inside: avoid;
  overflow: hidden;
  border-radius: var(--module-radius);
  border: 1px solid var(--rule);
  background: var(--paper-raised);
  transition:
    transform 150ms ease,
    border-color 150ms ease,
    box-shadow 150ms ease;
}

.tweet-card:hover {
  border-color: var(--rule-strong);
  box-shadow: var(--shadow-low);
  transform: translate(-1px, -1px);
}

.tweet-head {
  border-bottom: 1px solid var(--rule);
  background: var(--paper-muted);
}

.tweet-handle {
  border-radius: 4px;
  color: var(--ink);
}

a.tweet-handle:hover {
  background: var(--acid-soft);
}

.tweet-avatar-fallback {
  border-radius: 8px;
  background: var(--ink);
  color: var(--paper-raised);
}

/* 分数徽章：对齐全局 .badge 语言（5px 小圆角 + 三色组） */
.tweet-score {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.125rem 0.5rem;
  font-size: 0.625rem;
  font-weight: 600;
  border-radius: 5px;
  color: var(--badge-default-ink);
  background: var(--badge-default-bg);
  border: 1px solid var(--badge-default-border);
}

/* 媒体块：内嵌圆角 + 细边（X 式内嵌媒体，替代原来的通栏贴边） */
.tweet-media-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 12px 0;
}

.tweet-media-list > * {
  display: block;
  overflow: hidden;
  border: 1px solid var(--rule);
  border-radius: var(--control-radius);
}

/* 视频占位保持深色语义底；播放按钮复用 btn-primary 的墨底酸绿反转 */
.tweet-video-btn {
  cursor: pointer;
  background: linear-gradient(150deg, #2a2723, #100e0c);
}

.tweet-play {
  background: var(--ink);
  color: var(--acid);
  transition:
    transform 150ms ease,
    background 150ms ease,
    color 150ms ease;
}

.tweet-video-btn:hover .tweet-play {
  background: var(--acid);
  color: var(--acid-ink);
  transform: scale(1.06);
}

.tweet-gif-badge {
  border-radius: 4px;
  background: var(--ink);
  color: var(--acid);
}

.tweet-text {
  color: var(--ink-secondary);
}

.tweet-text:hover {
  color: var(--ink);
}

.tweet-time {
  color: var(--ink-muted);
}
</style>
