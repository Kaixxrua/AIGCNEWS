<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useXBoardController } from '@/composables/useXBoardController'
import { authorAvatarUrl, authorDisplayName, displayTweetText, distributeColumns, extractXHandle, formatLocalTime, hasMedia, mediaItems, paginateItems, timelineTweets, tweetTimestamp } from '@/features/xboard/xBoardViewModel'
import { scoreDisplay } from '@/features/dashboard/dashboardViewModel'
import { useAuthStore } from '@/stores/authStore'
import type { TopDoc, TweetMediaItem } from '@/features/dashboard/dashboardViewModel'

const { t, locale } = useI18n()
const authStore = useAuthStore()
const isAdmin = computed(() => authStore.isAdmin)

const {
  docs, selectedDate, today, loading, deleting, errorMsg,
  selectedIds, currentPage, totalPages, hasPrev, hasNext, pageSize,
  load, onDateChange, refresh, dispose, toggleSelection, toggleSelectAll, clearSelection, deleteSelected, goPage,
} = useXBoardController({ translate: t })

// 时间序（新→旧）+ 行主序分列：左上 = 最新推文，从左到右、从上到下。
// CSS columns 是列主序（先填满一列），无法满足该排序，故 JS 分列。
const timelineDocs = computed(() => timelineTweets(docs.value))
// 全天推文客户端分页：时间线排序与瀑布流分列仅在当前页内进行
const pagedTimelineDocs = computed(() => paginateItems(timelineDocs.value, currentPage.value, pageSize))
const totalTweets = () => timelineDocs.value.length
const selectedCount = computed(() => selectedIds.value.size)
const hasSelection = computed(() => selectedCount.value > 0)

// 页级全选（防止一键选中不可见条目误删）：复选框状态按当前页 id 计算
const pageIds = computed(() => pagedTimelineDocs.value.map((doc) => String(doc.id)).filter(Boolean))
const allPageSelected = computed(() => pageIds.value.length > 0 && pageIds.value.every((id) => selectedIds.value.has(id)))
const somePageSelected = computed(() => !allPageSelected.value && pageIds.value.some((id) => selectedIds.value.has(id)))

const computeColumnCount = () => {
  const width = window.innerWidth
  return width >= 1280 ? 4 : width >= 1024 ? 3 : width >= 768 ? 2 : 1
}
const columnCount = ref(computeColumnCount())
const updateColumnCount = () => { columnCount.value = computeColumnCount() }
const masonryColumns = computed(() => distributeColumns(pagedTimelineDocs.value, columnCount.value))

// 翻页回顶：滚动的是内层 overflow-y-auto 容器而非 window
const scrollEl = ref<HTMLElement | null>(null)
const onGoPage = (next: number) => {
  goPage(next)
  scrollEl.value?.scrollTo({ top: 0 })
}

// 发布时间：落库是 UTC ISO，展示换算成用户系统时区（不传 timeZone → 本地）。
const formatTime = (doc: TopDoc) => formatLocalTime(tweetTimestamp(doc))

// 图片放大预览（lightbox）：仅照片可点开；视频封面点击仍是播放。
// ESC 或点击遮罩关闭；预览不阻断视频点击播放逻辑。
const lightboxUrl = ref<string | null>(null)
const openLightbox = (url: string) => { lightboxUrl.value = url }
const closeLightbox = () => { lightboxUrl.value = null }
const onLightboxKeydown = (event: KeyboardEvent) => {
  if (event.key === 'Escape' && lightboxUrl.value) {
    event.stopPropagation()
    closeLightbox()
  }
}

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

onMounted(() => {
  window.addEventListener('resize', updateColumnCount)
  window.addEventListener('keydown', onLightboxKeydown)
  load()
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', updateColumnCount)
  window.removeEventListener('keydown', onLightboxKeydown)
  dispose()
})
</script>

<template>
  <div class="xboard-page flex h-full min-h-0 flex-col overflow-hidden">
    <div ref="scrollEl" class="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto p-6 pb-24">

      <!-- 页头 -->
      <div class="stagger-enter flex shrink-0 flex-wrap items-center justify-between gap-3">
        <div>
          <h1 class="text-2xl tracking-tight">{{ t('xboard.title') }}</h1>
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
      <div v-if="isAdmin" class="xboard-toolbar stagger-enter flex shrink-0 flex-wrap items-center justify-between gap-3 px-4 py-2">
        <div class="flex items-center gap-3 text-sm text-stone-600">
          <label class="flex cursor-pointer items-center gap-2">
            <input
              type="checkbox"
              class="h-4 w-4"
              :checked="allPageSelected"
              :indeterminate.prop="somePageSelected"
              @change="toggleSelectAll(pageIds)"
            />
            <span>{{ t('xboard.selectAll') }}</span>
          </label>
          <span v-if="hasSelection" class="text-xs text-stone-400">{{ selectedCount }} / {{ timelineDocs.length }}</span>
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
      <div v-else-if="!timelineDocs.length" class="glass-card flex min-h-[240px] flex-col items-center justify-center text-center text-sm text-stone-400">
        <p class="font-medium text-stone-500">{{ t('xboard.empty') }}</p>
        <p class="mt-1 text-xs">{{ t('xboard.emptyHint') }}</p>
      </div>

      <!-- 瀑布流推文墙（行主序：每列顶部横读即最新 N 条） -->
      <div v-else class="masonry-grid">
        <div
          v-for="(column, columnIndex) in masonryColumns"
          :key="columnIndex"
          class="masonry-col"
        >
          <article
            v-for="tweet in column"
            :key="tweet.url || tweet.title"
            class="tweet-card"
          >
            <div class="tweet-head flex flex-wrap items-center gap-2 px-4 py-3">
              <input
                v-if="isAdmin && tweet.id"
                type="checkbox"
                class="h-4 w-4 shrink-0"
                :checked="isSelected(tweet)"
                @change="toggleSelection(String(tweet.id))"
              />
              <img
                v-if="authorAvatarUrl(tweet)"
                :src="authorAvatarUrl(tweet)"
                :alt="authorDisplayName(tweet)"
                loading="lazy"
                referrerpolicy="no-referrer"
                class="tweet-avatar h-6 w-6 shrink-0 object-cover"
              />
              <span v-else class="tweet-avatar-fallback flex h-6 w-6 shrink-0 items-center justify-center font-mono text-[10px] font-bold">𝕏</span>
              <a
                v-if="extractXHandle(tweet.url)"
                class="tweet-handle truncate px-1 text-xs"
                :href="`https://x.com/${extractXHandle(tweet.url)}`"
                target="_blank"
                rel="noopener noreferrer"
              >{{ authorDisplayName(tweet) }}</a>
              <span v-else class="tweet-handle truncate px-1 text-xs">{{ authorDisplayName(tweet) || t('xboard.unknownHandle') }}</span>
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
                  class="tweet-photo w-full cursor-zoom-in object-cover"
                  :style="item.width && item.height ? { aspectRatio: `${item.width} / ${item.height}` } : {}"
                  :aria-label="t('xboard.previewImage')"
                  @click="openLightbox(item.url)"
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
                  <span class="tweet-play relative flex h-14 w-14 items-center justify-center">
                    <svg class="ml-1 h-6 w-6" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
                  </span>
                  <span v-if="item.type === 'animated_gif'" class="tweet-gif-badge absolute left-2 top-2 px-1.5 py-0.5 text-2xs font-bold uppercase tracking-wide">GIF</span>
                </button>
              </template>
            </div>

            <!-- 文字区 -->
            <div class="px-4 py-3">
              <a :href="tweet.url" target="_blank" rel="noopener noreferrer" class="tweet-text block whitespace-pre-line px-1 text-sm leading-5">
                {{ displayTweetText(tweet, locale) }}
              </a>
              <p v-if="formatTime(tweet)" class="tweet-time mt-2 px-1 text-2xs">{{ formatTime(tweet) }}</p>
            </div>
          </article>
        </div>
      </div>

      <!-- 全天推文分页条：仅超过一页时出现 -->
      <div
        v-if="totalPages > 1"
        class="xboard-pagination stagger-enter flex shrink-0 flex-wrap items-center justify-center gap-3 px-4 py-2"
        :aria-label="t('xboard.pagination')"
      >
        <button class="btn-secondary text-xs" :disabled="!hasPrev" @click="onGoPage(currentPage - 1)">
          {{ t('common.previous') }}
        </button>
        <span class="text-xs text-stone-500">
          {{ t('xboard.pageSummary', { page: currentPage, totalPages, total: timelineDocs.length }) }}
        </span>
        <button class="btn-secondary text-xs" :disabled="!hasNext" @click="onGoPage(currentPage + 1)">
          {{ t('common.next') }}
        </button>
      </div>

      <p v-if="timelineDocs.length" class="shrink-0 text-center text-2xs text-stone-300">{{ t('xboard.tweets', { count: totalTweets() }) }}</p>
    </div>

    <!-- 图片放大预览：点遮罩或 ESC 关闭，点图本身不关闭 -->
    <Teleport to="body">
      <div
        v-if="lightboxUrl"
        class="lightbox-backdrop"
        role="dialog"
        aria-modal="true"
        :aria-label="t('xboard.previewImage')"
        @click="closeLightbox"
      >
        <button
          type="button"
          class="lightbox-close"
          :aria-label="t('xboard.closePreview')"
          @click="closeLightbox"
        >
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
        <img
          :src="lightboxUrl"
          :alt="t('xboard.previewImage')"
          class="lightbox-image"
          referrerpolicy="no-referrer"
          @click.stop
        />
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
/* 行主序瀑布流：JS 轮询分列（见 distributeColumns），列高各自独立，
   卡片按内容高度堆叠；v-bind 列数跟随视口断点（768/1024/1280）。 */
.masonry-grid {
  display: grid;
  grid-template-columns: repeat(v-bind(columnCount), minmax(0, 1fr));
  gap: 1rem;
  align-items: start;
}

.masonry-col {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  min-width: 0;
}

/* ═══ 页面语言对齐 dashboard/projects：Inter + 墨色描边 + 常驻硬阴影 ═══ */
.xboard-page {
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
}

.xboard-page h1 {
  color: var(--ink);
  font-weight: 850;
  letter-spacing: -0.04em;
}

/* 页内 glass-card 统一硬边化（加载/空态/错误条） */
.xboard-page .glass-card {
  border: 1px solid var(--ink);
  border-radius: 5px;
  background: var(--projects-paper-light);
  box-shadow: 3px 3px 0 var(--shadow-hard);
  backdrop-filter: none;
}

/* 中性文字走主题变量（对齐 dashboard 的 muted 映射） */
.xboard-page :where(.text-stone-300, .text-stone-400) {
  color: var(--ink-muted);
}

.xboard-page :where(.text-stone-500, .text-stone-600) {
  color: var(--ink-secondary);
}

.xboard-toolbar {
  border: 1px solid var(--ink);
  border-radius: 5px;
  background: var(--projects-paper-light);
  box-shadow: 3px 3px 0 var(--shadow-hard);
}

.xboard-pagination {
  border: 1px solid var(--ink);
  border-radius: 5px;
  background: var(--projects-paper-light);
  box-shadow: 3px 3px 0 var(--shadow-hard);
}

/* 推文卡片：与 dashboard 卡片同方——1px 墨边 + 5px 圆角 + 纸面 + 常驻硬阴影 */
.tweet-card {
  display: block;
  width: 100%;
  overflow: hidden;
  border: 1px solid var(--ink);
  border-radius: 5px;
  background: var(--projects-paper-light);
  box-shadow: 3px 3px 0 var(--shadow-hard);
  transition: background 150ms ease;
}

.tweet-card:hover {
  background: var(--acid-soft);
}

.tweet-head {
  border-bottom: 1px solid var(--rule);
}

.tweet-avatar {
  border-radius: 4px; /* 主题去胶囊化 */
  border: 1px solid var(--rule);
}

.tweet-handle {
  border-radius: 4px;
  color: var(--ink);
  font-weight: 700;
}

a.tweet-handle:hover {
  background: var(--acid);
}

.tweet-avatar-fallback {
  border-radius: 4px;
  background: var(--ink);
  color: var(--acid);
}

/* 分数徽章：对齐 dashboard 的 acid 硬边 chip */
.tweet-score {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.125rem 0.5rem;
  font-size: 0.625rem;
  font-weight: 700;
  border-radius: 4px;
  border: 1px solid var(--ink);
  background: var(--acid);
  color: var(--projects-on-acid);
}

/* 媒体块：内嵌 + 墨边 + 小圆角 */
.tweet-media-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 12px 0;
}

.tweet-media-list > * {
  display: block;
  overflow: hidden;
  border: 1px solid var(--ink);
  border-radius: 5px;
}

/* 视频占位保持深色语义底；播放键走 btn-primary 的墨底酸绿反转，
   方形圆角（主题去胶囊化），hover 硬边位移反馈 */
.tweet-video-btn {
  cursor: pointer;
  background: linear-gradient(150deg, #2a2723, #100e0c);
}

.tweet-play {
  border: 1px solid var(--ink);
  border-radius: var(--control-radius);
  background: var(--ink);
  color: var(--acid);
  transition:
    transform 150ms ease,
    background 150ms ease,
    color 150ms ease,
    box-shadow 150ms ease;
}

.tweet-video-btn:hover .tweet-play {
  background: var(--acid);
  color: var(--projects-on-acid);
  box-shadow: 2px 2px 0 var(--shadow-hard);
  transform: translate(-1px, -1px);
}

.tweet-gif-badge {
  border: 1px solid var(--ink);
  border-radius: 4px;
  background: var(--acid);
  color: var(--projects-on-acid);
}

.tweet-text {
  border-radius: 4px;
  color: var(--ink);
}

a.tweet-text:hover {
  background: var(--acid-soft);
}

.tweet-time {
  color: var(--ink-muted);
}

/* ═══ 图片放大预览：墨色遮罩 + 硬边图框，对齐卡片配方 ═══ */
.lightbox-backdrop {
  position: fixed;
  inset: 0;
  z-index: 90;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 4vh 4vw;
  background: rgb(21 21 18 / 0.86); /* --ink 的透明化，深浅主题下都保持墨色 */
  cursor: zoom-out;
}

.lightbox-image {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  border: 1px solid var(--ink);
  border-radius: 5px;
  background: var(--projects-paper-light);
  box-shadow: 4px 4px 0 var(--shadow-hard);
  cursor: default;
}

.lightbox-close {
  position: absolute;
  top: 1.25rem;
  right: 1.25rem;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 2.25rem;
  height: 2.25rem;
  border: 1px solid var(--ink);
  border-radius: var(--control-radius);
  background: var(--ink);
  color: var(--acid);
  cursor: pointer;
  transition:
    transform 150ms ease,
    background 150ms ease,
    color 150ms ease,
    box-shadow 150ms ease;
}

.lightbox-close:hover {
  background: var(--acid);
  color: var(--projects-on-acid);
  box-shadow: 2px 2px 0 var(--shadow-hard);
  transform: translate(-1px, -1px);
}
</style>
