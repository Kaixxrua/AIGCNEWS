<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowLeft, ExternalLink, Maximize2, PanelRightClose, Repeat2, Users } from 'lucide-vue-next'
import SpinnerLoader from '@/components/SpinnerLoader.vue'
import TweetMediaList from '@/components/xboard/TweetMediaList.vue'
import TweetQuoteCard from '@/components/xboard/TweetQuoteCard.vue'
import TweetLinkCard from '@/components/xboard/TweetLinkCard.vue'
import { useXBoardController } from '@/composables/useXBoardController'
import { useDockSuppression } from '@/composables/useDockSuppression'
import { showToast } from '@/composables/useToast'
import { authorAvatarUrl, authorDisplayName, distributeColumns, emptyStateCopyKeys, estimateTweetCardHeight, extractXHandle, formatLocalTime, hasLinkCard, hasMedia, hasQuote, isLongPhoto, paginateItems, quoteAsDoc, retweetedByHandle, timelineTweets, tweetLinkCard, tweetQuote, tweetTextSegments, tweetTimestamp } from '@/features/xboard/xBoardViewModel'
import { scoreDisplay } from '@/features/dashboard/dashboardViewModel'
import { useAuthStore } from '@/stores/authStore'
import type { TopDoc, TweetMediaItem } from '@/features/dashboard/dashboardViewModel'
import type { TweetTextMetrics } from '@/features/xboard/xBoardViewModel'

const { t, locale } = useI18n()
const authStore = useAuthStore()
const isAdmin = computed(() => authStore.isAdmin)

const {
  docs, visibleDocs, selectedDate, today, loading, deleting, errorMsg,
  selectedIds, currentPage, totalPages, hasPrev, hasNext, pageSize,
  availableDates, availableAccounts, availableAccountOptions, followedAccounts, unfollowedAccounts,
  load, onDateChange, showRecent, refresh, dispose, toggleSelection, toggleSelectAll, clearSelection, deleteSelected, goPage,
  toggleFollowAccount, followAllAccounts, unfollowAllAccounts,
} = useXBoardController({ translate: t })

// 窗口日期是否就是今天：今天 = 最近 24h 滚动窗口（days_back=0）
const isToday = computed(() => selectedDate.value === today)

// 时间序（新→旧）+ 估高贪心分列：每条进当前最矮列，列内保持时间降序、
// 左上角是最新一条。纯轮询不管卡高（纯文字 ~200px vs 多图 >1000px），
// 列高失衡会在短列尾部留下大片空白；CSS columns 是列主序，两者都不用。
const timelineDocs = computed(() => timelineTweets(visibleDocs.value))
// 全天推文客户端分页：时间线排序与瀑布流分列仅在当前页内进行
const pagedTimelineDocs = computed(() => paginateItems(timelineDocs.value, currentPage.value, pageSize))
const totalTweets = computed(() => timelineDocs.value.length)
const selectedCount = computed(() => selectedIds.value.size)
const hasSelection = computed(() => selectedCount.value > 0)

// 页级全选（防止一键选中不可见条目误删）：复选框状态按当前页 id 计算
const pageIds = computed(() => pagedTimelineDocs.value.map((doc) => String(doc.id)).filter(Boolean))
const allPageSelected = computed(() => pageIds.value.length > 0 && pageIds.value.every((id) => selectedIds.value.has(id)))
const somePageSelected = computed(() => !allPageSelected.value && pageIds.value.some((id) => selectedIds.value.has(id)))

// 关注账号收在侧栏里，默认收起：页头按钮展开/收起，推文墙优先占满版面。
const followPanelOpen = ref(false)

const computeColumnCount = () => {
  const width = window.innerWidth
  return width >= 1280 ? 4 : width >= 1024 ? 3 : width >= 768 ? 2 : 1
}
const viewportColumnCount = ref(computeColumnCount())
const updateColumnCount = () => { viewportColumnCount.value = computeColumnCount() }
// 桌面端侧栏展开会占去一列的宽度：三列及以上时少排一列，列宽保持可读。
// 窄屏侧栏叠在推文墙上方，不影响列数。
const columnCount = computed(() =>
  viewportColumnCount.value - (followPanelOpen.value && viewportColumnCount.value >= 3 ? 1 : 0))

// 估高分列需要真实列宽：量推文墙所在主栏的宽度（已扣除滚动区边距与侧栏）。
// 主栏常驻（不受加载/空态 v-if 影响），ResizeObserver 直接挂它；侧栏开合、
// 断点变化都会改变它的宽度。
const MASONRY_GAP_PX = 16
const masonryWidth = ref(0)
const tweetTextMetrics = ref<TweetTextMetrics | undefined>()
let mainResizeObserver: ResizeObserver | null = null
const masonryColumnWidth = computed(() => {
  const count = columnCount.value
  const width = (masonryWidth.value - MASONRY_GAP_PX * (count - 1)) / count
  return width > 0 ? width : 280 // 首帧未测量时的回退列宽
})
const masonryColumns = computed(() => distributeColumns(
  pagedTimelineDocs.value,
  columnCount.value,
  (doc) => estimateTweetCardHeight(doc, masonryColumnWidth.value, locale.value, tweetTextMetrics.value),
))

// 翻页回顶：滚动的是内层 overflow-y-auto 容器而非 window
const scrollEl = ref<HTMLElement | null>(null)
const mainEl = ref<HTMLElement | null>(null)

// 主栏宽度随断点、滚动区边距（移动端 12px、桌面 24px）与侧栏变化，必须实测。
// 桌面漫画版放大了推文正文，字号与行高经 --tweet-text-size/--tweet-text-line
// 声明在主栏上，估高按实际排版折行；未声明时回落默认 text-sm leading-5。
const measureMasonry = () => {
  const el = mainEl.value
  if (!el) return
  masonryWidth.value = el.clientWidth
  const style = window.getComputedStyle(el)
  const fontSize = parseFloat(style.getPropertyValue('--tweet-text-size'))
  const lineHeight = parseFloat(style.getPropertyValue('--tweet-text-line'))
  tweetTextMetrics.value = fontSize > 0 && lineHeight > 0 ? { fontSize, lineHeight } : undefined
}

const onGoPage = (next: number) => {
  goPage(next)
  scrollEl.value?.scrollTo({ top: 0 })
}

// 发布时间：落库是 UTC ISO，展示换算成用户系统时区（不传 timeZone → 本地）。
const formatTime = (doc: TopDoc) => formatLocalTime(tweetTimestamp(doc))

// 图片放大预览（lightbox）：仅照片可点开；视频封面点击仍是播放。
// 内联渲染用约束框变体（thumb_url）降载，点开 lightbox 才拉大图变体（item.url）。
// 长图按高度等比缩放会窄到不可读，改为限宽纵向滚动（lightboxLong）。
// ESC 或点击遮罩关闭；预览不阻断视频点击播放逻辑。
const lightboxUrl = ref<string | null>(null)
const lightboxLong = ref(false)
const openLightbox = (item: TweetMediaItem) => {
  lightboxUrl.value = item.url
  lightboxLong.value = isLongPhoto(item)
}
const closeLightbox = () => { lightboxUrl.value = null }

// 推文详情浮层：点击卡片正文/引用区就地放大阅读，不直接跳走（跳转由
// 显式按钮承担）。层级低于图片 lightbox（浮层内照片可再放大）；数据
// 重载时关闭，避免悬在已失效的条目上。
// 焦点管理：打开时聚焦关闭钮（键盘/读屏用户有明确落点），关闭后焦点
// 还原到触发元素；下钻/返回后同样把焦点收回关闭钮。
const detailTweet = ref<TopDoc | null>(null)
const detailCloseEl = ref<HTMLButtonElement | null>(null)
let detailReturnFocus: HTMLElement | null = null
const focusDetailClose = () => { void nextTick(() => detailCloseEl.value?.focus()) }
// 浮层内引用卡下钻：点击 = 就地切换为被引推文详情（quote 投影字段齐全，
// 零请求），detailParent 记回跳目标；仅一层（投影不嵌套，与 X 一致）。
// 下钻/返回时清空播放态：媒体块随内容切换整体卸载，不残留他条播放键。
const detailParent = ref<TopDoc | null>(null)
const openDetail = (tweet: TopDoc) => {
  detailReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
  detailTweet.value = tweet
  detailParent.value = null
  focusDetailClose()
}
const closeDetail = () => {
  detailTweet.value = null
  detailParent.value = null
  // 焦点还原到打开浮层的触发元素；元素已随数据重载卸载时跳过
  if (detailReturnFocus?.isConnected) detailReturnFocus.focus()
  detailReturnFocus = null
}
const drillIntoQuote = () => {
  const quote = detailTweet.value ? tweetQuote(detailTweet.value) : null
  if (!quote || detailParent.value) return
  detailParent.value = detailTweet.value
  detailTweet.value = quoteAsDoc(quote)
  playingMedia.value = new Set()
  focusDetailClose()
}
const backToParent = () => {
  if (!detailParent.value) return
  detailTweet.value = detailParent.value
  detailParent.value = null
  playingMedia.value = new Set()
  focusDetailClose()
}

const onLightboxKeydown = (event: KeyboardEvent) => {
  if (event.key !== 'Escape') return
  // 分层关闭：先图片 lightbox，再详情浮层（遮罩嵌套时 ESC 只撤最上层）
  if (lightboxUrl.value) {
    event.stopPropagation()
    closeLightbox()
    return
  }
  if (detailTweet.value) {
    event.stopPropagation()
    closeDetail()
  }
}

// 详情浮层/图片放大打开期间隐藏底部 dock 浮岛：全屏遮罩下 dock 会遮挡卡片
useDockSuppression(() => detailTweet.value !== null || lightboxUrl.value !== null)

// X 式点击播放：视频占位零流量（不经代理拉取元数据），点击后才挂载 <video>。
// 键与 TweetMediaList 模板 :key 同源（`${tweet.url}-${index}`），重载推文时清空避免自动重播。
const playingMedia = ref<Set<string>>(new Set())
const playVideo = (key: string) => {
  const next = new Set(playingMedia.value)
  next.add(key)
  playingMedia.value = next
}
watch(docs, () => { playingMedia.value = new Set(); detailTweet.value = null; detailParent.value = null })

const isSelected = (doc: TopDoc) => doc.id ? selectedIds.value.has(String(doc.id)) : false

// 空态文案三态：今天窗口暂无 / 早于最早数据日 / 该日窗口真空
const emptyCopy = computed(() => emptyStateCopyKeys({
  isToday: isToday.value,
  hasSnapshotDates: availableDates.value.length > 0,
  isBeforeEarliest: earliestSnapshotDate.value !== '' && selectedDate.value < earliestSnapshotDate.value,
}))
// 最早有数据的日期（清单降序，末尾即最早），供「早于最早数据日」空态提示可翻到的起点
const earliestSnapshotDate = computed(() => availableDates.value[availableDates.value.length - 1] ?? '')

const handleDeleteSelected = async () => {
  if (!hasSelection.value) return
  const confirmed = window.confirm(t('xboard.deleteConfirm', { count: selectedCount.value }))
  if (!confirmed) return
  const { deleted, notFound } = await deleteSelected()
  if (deleted > 0 || notFound > 0) {
    const parts = []
    if (deleted > 0) parts.push(t('xboard.deleteSuccess', { count: deleted }))
    if (notFound > 0) parts.push(t('xboard.deleteNotFound', { count: notFound }))
    // 非阻塞全局 Toast（App.vue 渲染 AppToast），不再用 window.alert 打断操作
    showToast(parts.join('；'))
  }
}

onMounted(() => {
  window.addEventListener('resize', updateColumnCount)
  window.addEventListener('keydown', onLightboxKeydown)
  // 量主栏宽度与正文排版供瀑布流估高；clientWidth 不含滚动条。
  measureMasonry()
  if (mainEl.value && typeof ResizeObserver !== 'undefined') {
    // jsdom 等无 ResizeObserver 环境跳过观测，首帧回退列宽接管
    mainResizeObserver = new ResizeObserver(measureMasonry)
    mainResizeObserver.observe(mainEl.value)
  }
  load()
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', updateColumnCount)
  window.removeEventListener('keydown', onLightboxKeydown)
  mainResizeObserver?.disconnect()
  dispose()
})
</script>

<template>
  <div class="xboard-page flex h-full min-h-0 flex-col overflow-hidden">
    <div ref="scrollEl" class="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto p-6 pb-24">

      <!-- 页头 -->
      <div class="xboard-header stagger-enter flex shrink-0 flex-wrap items-center justify-between gap-3">
        <div class="xboard-heading">
          <h1 class="comic-title text-2xl tracking-tight">{{ t('xboard.title') }}</h1>
          <p class="mt-0.5 text-sm text-stone-400">{{ t('xboard.subtitle') }}</p>
        </div>
        <div class="xboard-header-actions flex flex-wrap items-center gap-2">
          <button
            class="btn-secondary text-xs"
            :class="{ 'xboard-mode-active': isToday }"
            :aria-pressed="isToday"
            @click="showRecent"
          >
            {{ t('xboard.recent24h') }}
          </button>
          <label class="flex items-center gap-2 text-xs text-stone-400">
            {{ t('xboard.dateLabel') }}
            <input
              type="date"
              class="input py-1.5 text-xs"
              :class="{ 'xboard-mode-active': !isToday }"
              :value="selectedDate"
              :max="today"
              @change="onDateChange(($event.target as HTMLInputElement).value)"
            />
          </label>
          <button class="btn-secondary xboard-refresh" :disabled="loading" @click="refresh">
            <svg class="h-3.5 w-3.5" :class="loading ? 'animate-spin' : ''" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/></svg>
            {{ t(loading ? 'common.refreshing' : 'common.refresh') }}
          </button>
          <!-- 关注账号侧栏开关：收起时仍显示已关注数，筛选状态一眼可见 -->
          <button
            v-if="availableAccounts.length"
            type="button"
            class="btn-secondary xboard-follow-toggle"
            :class="{ 'xboard-mode-active': followPanelOpen }"
            :aria-expanded="followPanelOpen"
            aria-controls="xboard-follow-panel"
            @click="followPanelOpen = !followPanelOpen"
          >
            <Users class="h-3.5 w-3.5" />
            {{ t('xboard.followAccounts') }}
            <span class="xboard-follow-count">{{ followedAccounts.length }}/{{ availableAccounts.length }}</span>
          </button>
        </div>
      </div>

      <div class="xboard-body">

        <!-- 账号关注筛选侧栏：默认全部关注；按账号即时过滤当前窗口推文。
             DOM 上紧跟页头开关（键盘可直达），桌面端经 CSS order 排到推文墙右侧。 -->
        <aside
          v-if="availableAccounts.length && followPanelOpen"
          id="xboard-follow-panel"
          class="xboard-follow-panel px-4 py-3"
          :aria-label="t('xboard.followAccounts')"
        >
          <div class="flex items-start justify-between gap-3">
            <div>
              <h2 class="text-sm font-bold text-stone-600">{{ t('xboard.followAccounts') }}</h2>
              <p class="mt-0.5 text-2xs text-stone-400">
                {{ t('xboard.followSummary', { selected: followedAccounts.length, total: availableAccounts.length }) }}
              </p>
            </div>
            <button type="button" class="tweet-icon-btn xboard-follow-close" :aria-label="t('xboard.hideFollowPanel')" @click="followPanelOpen = false">
              <PanelRightClose class="h-3.5 w-3.5" />
            </button>
          </div>
          <div class="mt-3 flex items-center gap-2">
            <button class="btn-secondary text-xs" :disabled="followedAccounts.length === availableAccounts.length" @click="followAllAccounts">
              {{ t('xboard.followAll') }}
            </button>
            <button class="btn-secondary text-xs" :disabled="followedAccounts.length === 0" @click="unfollowAllAccounts">
              {{ t('xboard.clearFollowed') }}
            </button>
          </div>
          <div class="xboard-follow-list mt-3 flex flex-wrap gap-2">
            <label
              v-for="account in availableAccountOptions"
              :key="account.handle"
              class="xboard-account-chip flex cursor-pointer items-center gap-1.5 px-2.5 py-1.5 text-xs"
              :class="{ 'xboard-account-chip-active': !unfollowedAccounts.has(account.handle) }"
              :title="`@${account.handle}`"
            >
              <input
                type="checkbox"
                class="h-3.5 w-3.5"
                :checked="!unfollowedAccounts.has(account.handle)"
                @change="toggleFollowAccount(account.handle)"
              />
              <span>{{ account.displayName }}</span>
            </label>
          </div>
        </aside>

        <div ref="mainEl" class="xboard-main">
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
          <SpinnerLoader v-if="loading && !docs.length" class="min-h-[240px]" :label="t('xboard.loading')" />
          <div v-else-if="!timelineDocs.length" class="glass-card flex min-h-[240px] flex-col items-center justify-center text-center text-sm text-stone-400">
            <template v-if="docs.length && followedAccounts.length === 0">
              <p class="font-medium text-stone-500">{{ t('xboard.emptyFollowed') }}</p>
              <p class="mt-1 text-xs">{{ t('xboard.emptyFollowedHint') }}</p>
            </template>
            <template v-else>
              <p class="font-medium text-stone-500">{{ t(emptyCopy.titleKey) }}</p>
              <p class="mt-1 text-xs">{{ t(emptyCopy.hintKey, { earliest: earliestSnapshotDate }) }}</p>
            </template>
          </div>

          <!-- 瀑布流推文墙（估高贪心分列：每条进当前最矮列，列内时间降序） -->
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
                <!-- 纯转贴标注行：转贴者在上、原作者在下（与 X 原生转发卡同形态） -->
                <div v-if="retweetedByHandle(tweet)" class="tweet-retweet-line flex items-center gap-1.5 px-4 pt-2.5 text-2xs">
                  <Repeat2 class="h-3 w-3 shrink-0" />
                  <a
                    :href="`https://x.com/${retweetedByHandle(tweet)}`"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="tweet-retweet-link truncate font-semibold"
                  >@{{ retweetedByHandle(tweet) }}</a>
                  <span class="shrink-0">{{ t('xboard.repostedSuffix') }}</span>
                </div>
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
                  <span class="tweet-actions ml-auto flex shrink-0 items-center gap-1.5">
                    <button
                      type="button"
                      class="tweet-icon-btn"
                      :aria-label="t('xboard.openDetail')"
                      @click="openDetail(tweet)"
                    >
                      <Maximize2 class="h-3.5 w-3.5" />
                    </button>
                    <a
                      class="tweet-icon-btn"
                      :href="tweet.url"
                      target="_blank"
                      rel="noopener noreferrer"
                      :aria-label="t('xboard.viewOnX')"
                    >
                      <ExternalLink class="h-3.5 w-3.5" />
                    </a>
                    <span class="tweet-score shrink-0">
                      <component :is="scoreDisplay(tweet).icon" class="h-3 w-3 shrink-0" />{{ scoreDisplay(tweet).text }}
                    </span>
                  </span>
                </div>

                <!-- 媒体区：照片点开 lightbox、视频点击播放（与详情浮层同一子组件渲染） -->
                <TweetMediaList
                  v-if="hasMedia(tweet)"
                  :tweet="tweet"
                  :playing-media="playingMedia"
                  @preview="openLightbox"
                  @play="playVideo"
                />

                <!-- 文字区：点击/回车放大详情（不跳走）；URL 段仍是真链接可直跳 -->
                <div class="px-4 py-3">
                  <div
                    role="button"
                    tabindex="0"
                    class="tweet-text block cursor-pointer whitespace-pre-line px-1 text-sm leading-5"
                    :aria-label="t('xboard.openDetail')"
                    @click="openDetail(tweet)"
                    @keydown.enter="openDetail(tweet)"
                  >
                    <template v-for="(seg, segIndex) in tweetTextSegments(tweet, locale)" :key="segIndex">
                      <a
                        v-if="seg.isUrl"
                        :href="seg.text"
                        target="_blank"
                        rel="noopener noreferrer"
                        class="tweet-link"
                        @click.stop
                      >{{ seg.text }}</a>
                      <a
                        v-else-if="seg.isMention"
                        :href="`https://x.com/${seg.mentionHandle}`"
                        target="_blank"
                        rel="noopener noreferrer"
                        class="tweet-link"
                        @click.stop
                      >{{ seg.text }}</a>
                      <span
                        v-else
                        class="tweet-text-seg"
                      >{{ seg.text }}</span>
                    </template>
                  </div>

                  <!-- 引用推文卡片：看板上点击放大主推详情（不跳走）；
                       ↗ 钮显式直跳被引推文，详情浮层内点击则下钻看被引详情 -->
                  <TweetQuoteCard
                    v-if="hasQuote(tweet)"
                    :quote="tweetQuote(tweet)!"
                    context="wall"
                    @activate="openDetail(tweet)"
                  />
                  <!-- 外链预览卡：整卡跳目标页（与 X 一致），不放大详情 -->
                  <TweetLinkCard
                    v-if="hasLinkCard(tweet)"
                    :card="tweetLinkCard(tweet)!"
                    context="wall"
                  />
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

          <p v-if="timelineDocs.length" class="shrink-0 text-center text-2xs text-stone-300">{{ t('xboard.tweets', { count: totalTweets }) }}</p>
        </div>
      </div>
    </div>

    <!-- 推文详情浮层：就地放大阅读（全文/媒体/引用卡），跳转走显式按钮；
         点遮罩或 ESC 关闭；z 低于图片 lightbox，浮层内照片可再放大 -->
    <Teleport to="body">
      <div
        v-if="detailTweet"
        class="detail-backdrop"
        role="dialog"
        aria-modal="true"
        :aria-label="t(detailParent ? 'xboard.quoteDetailTitle' : 'xboard.detailTitle')"
        @click="closeDetail"
      >
        <article class="detail-panel" @click.stop>
          <button
            v-if="detailParent"
            type="button"
            class="detail-back"
            :aria-label="t('xboard.backToTweet')"
            @click="backToParent"
          >
            <ArrowLeft class="h-4 w-4" />
          </button>
          <button
            ref="detailCloseEl"
            type="button"
            class="detail-close"
            :aria-label="t('xboard.closePreview')"
            @click="closeDetail"
          >
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>

          <div v-if="retweetedByHandle(detailTweet)" class="tweet-retweet-line flex items-center gap-1.5 px-5 pt-3 text-xs" :class="{ 'pl-14': detailParent }">
            <Repeat2 class="h-3.5 w-3.5 shrink-0" />
            <a
              :href="`https://x.com/${retweetedByHandle(detailTweet)}`"
              target="_blank"
              rel="noopener noreferrer"
              class="tweet-retweet-link truncate font-semibold"
            >@{{ retweetedByHandle(detailTweet) }}</a>
            <span class="shrink-0">{{ t('xboard.repostedSuffix') }}</span>
          </div>
          <div class="tweet-head flex items-center gap-2 px-5 py-4 pr-14" :class="{ 'pl-14': detailParent }">
            <img
              v-if="authorAvatarUrl(detailTweet)"
              :src="authorAvatarUrl(detailTweet)"
              :alt="authorDisplayName(detailTweet)"
              loading="lazy"
              referrerpolicy="no-referrer"
              class="tweet-avatar h-8 w-8 shrink-0 object-cover"
            />
            <span v-else class="tweet-avatar-fallback flex h-8 w-8 shrink-0 items-center justify-center font-mono text-xs font-bold">𝕏</span>
            <div class="min-w-0">
              <p class="tweet-handle truncate text-sm">{{ authorDisplayName(detailTweet) }}</p>
              <p v-if="extractXHandle(detailTweet.url)" class="tweet-quote-handle truncate text-2xs">@{{ extractXHandle(detailTweet.url) }}</p>
            </div>
            <!-- 下钻态无本站互动分（quote 投影不携带），隐藏分数徽章 -->
            <span v-if="!detailParent" class="tweet-score ml-auto shrink-0">
              <component :is="scoreDisplay(detailTweet).icon" class="h-3 w-3 shrink-0" />{{ scoreDisplay(detailTweet).text }}
            </span>
          </div>

          <div class="px-5 py-3">
            <div class="tweet-text block whitespace-pre-line px-1 text-sm leading-6">
              <template v-for="(seg, segIndex) in tweetTextSegments(detailTweet, locale)" :key="segIndex">
                <a
                  v-if="seg.isUrl"
                  :href="seg.text"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="tweet-link"
                >{{ seg.text }}</a>
                <span v-else class="tweet-text-seg">{{ seg.text }}</span>
              </template>
            </div>
          </div>

          <!-- 媒体区：与看板同一子组件渲染（照片可再放大、视频点击播放，键同源不冲突） -->
          <TweetMediaList
            v-if="hasMedia(detailTweet)"
            :tweet="detailTweet"
            :playing-media="playingMedia"
            context="detail"
            @preview="openLightbox"
            @play="playVideo"
          />

          <!-- 引用卡：浮层内点击下钻为被引推文详情（就地切换不跳走，与 X
               点击引用在 App 内导航一致）；↗ 钮显式直跳被引推文 -->
          <TweetQuoteCard
            v-if="hasQuote(detailTweet)"
            :quote="tweetQuote(detailTweet)!"
            context="detail"
            @activate="drillIntoQuote"
          />

          <!-- 外链预览卡：整卡跳目标页（与 X 一致） -->
          <TweetLinkCard
            v-if="hasLinkCard(detailTweet)"
            :card="tweetLinkCard(detailTweet)!"
            context="detail"
          />

          <div class="detail-foot flex flex-wrap items-center gap-3 px-5 py-3">
            <span v-if="formatTime(detailTweet)" class="tweet-time text-2xs">{{ formatTime(detailTweet) }}</span>
            <a
              class="btn-primary detail-jump ml-auto inline-flex items-center gap-1.5 text-xs"
              :href="detailTweet.url"
              target="_blank"
              rel="noopener noreferrer"
            >{{ t('xboard.viewOnX') }}<ExternalLink class="h-3 w-3" /></a>
          </div>
        </article>
      </div>
    </Teleport>

    <!-- 图片放大预览：点遮罩或 ESC 关闭，点图本身不关闭 -->
    <Teleport to="body">
      <div
        v-if="lightboxUrl"
        class="lightbox-backdrop"
        :class="{ 'lightbox-backdrop--long': lightboxLong }"
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
/* 估高贪心瀑布流：JS 按卡片估高把每条放进当前最矮列（见 distributeColumns），
   列高各自独立、卡片按内容高度堆叠；v-bind 列数跟随视口断点（768/1024/1280）。 */
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

/* 推文墙主栏 + 关注账号侧栏：窄屏侧栏叠在推文墙上方；桌面端并排，侧栏居右、
   随滚动吸顶，账号多时列表在侧栏内滚动。 */
.xboard-body,
.xboard-main {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  min-width: 0;
}

.xboard-body {
  flex-shrink: 0;
}

@media (min-width: 1024px) {
  .xboard-body {
    flex-direction: row;
    align-items: flex-start;
  }

  .xboard-main {
    flex: 1 1 auto;
  }

  .xboard-follow-panel {
    position: sticky;
    top: 0.75rem;
    order: 2;
    display: flex;
    flex: 0 0 18rem;
    flex-direction: column;
    max-height: calc(100dvh - 18rem); /* 减去刊头、页头与页脚，侧栏底边落在页脚之上 */
  }

  .xboard-follow-list {
    min-height: 0;
    overflow-y: auto;
    padding: 2px 4px 4px 2px; /* 给芯片的硬阴影留位，免得被滚动区裁掉 */
  }
}

.xboard-follow-count {
  font-variant-numeric: tabular-nums;
  color: var(--ink-muted);
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

.xboard-follow-panel {
  border: 1px solid var(--ink);
  border-radius: 5px;
  background: var(--projects-paper-light);
  box-shadow: 3px 3px 0 var(--shadow-hard);
}

.xboard-account-chip {
  border: 1px solid var(--rule);
  border-radius: 4px;
  color: var(--ink-secondary);
  background: var(--projects-paper-light);
  transition: background 150ms ease, border-color 150ms ease;
}

.xboard-account-chip:hover,
.xboard-account-chip-active {
  border-color: var(--ink);
  background: var(--acid-soft);
  color: var(--ink);
}

.xboard-pagination {
  border: 1px solid var(--ink);
  border-radius: 5px;
  background: var(--projects-paper-light);
  box-shadow: 3px 3px 0 var(--shadow-hard);
}

/* 视图模式开关（最近 24h / 快照日）：激活态走 acid 硬边 chip 配方 */
.xboard-mode-active {
  border-color: var(--ink);
  background: var(--acid);
  color: var(--projects-on-acid);
  box-shadow: 2px 2px 0 var(--shadow-hard);
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
  transition:
    background 150ms ease,
    transform 180ms ease,
    box-shadow 180ms ease;
}

.tweet-card:hover {
  background: var(--acid-soft);
}

/* 悬停浮起：左上位移 + 硬阴影加深（项目库同款浮起感）。
   不抄项目库的 rotate(-0.4deg)：旋转会让字形离开像素网格，浏览器对变换层
   重采样时文字退化为灰阶抗锯齿——推文卡整段正文，糊感远比项目卡显眼。
   仅在有悬停能力的设备启用（触屏不留粘滞态）；键盘焦点进入卡内控件时同样浮起 */
@media (hover: hover) {
  .tweet-card:hover,
  .tweet-card:focus-within {
    transform: translate(-2px, -4px);
    box-shadow: 8px 8px 0 var(--shadow-hard);
  }
}

.tweet-head {
  border-bottom: 1px solid var(--rule);
}

/* 转贴标注行：弱化灰字但可发现（与 quote handle 同墨色），链接 hover 走 acid 高亮 */
.tweet-retweet-line {
  color: var(--ink-muted);
}

.tweet-retweet-line .tweet-retweet-link {
  color: var(--ink-muted);
  border-radius: 4px;
}

.tweet-retweet-line a.tweet-retweet-link:hover {
  background: var(--acid);
  color: var(--ink);
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

/* 媒体块与引用卡样式已随模板内聚到 components/xboard/ 子组件 */

.tweet-text {
  border-radius: 4px;
  color: var(--ink);
}

/* 文本段不再自带跳转（点击 = 放大详情）；URL 段保持真链接可直跳 */
.tweet-text-seg {
  border-radius: 4px;
  color: var(--ink);
}

/* 卡片头部动作钮（详情/跳转）：quiet 小方钮，hover acid 反转 */
.tweet-icon-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 1.375rem;
  height: 1.375rem;
  border: 1px solid var(--rule);
  border-radius: 4px;
  color: var(--ink-muted);
  cursor: pointer;
  transition:
    background 150ms ease,
    border-color 150ms ease,
    color 150ms ease;
}

.tweet-icon-btn:hover {
  border-color: var(--ink);
  background: var(--acid);
  color: var(--projects-on-acid);
}

.tweet-link {
  border-radius: 4px;
  color: var(--ink);
  text-decoration: underline;
  text-underline-offset: 2px;
  word-break: break-all;
}

a.tweet-link:hover {
  background: var(--acid);
  color: var(--projects-on-acid);
}

.tweet-time {
  color: var(--ink-muted);
}

/* ═══ 推文详情浮层：墨色遮罩 + 卡片面板；z 低于图片 lightbox(90)，
       浮层内照片可再放大一层 ═══ */
.detail-backdrop {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 3vh 3vw;
  background: rgb(21 21 18 / 0.86); /* --ink 的透明化，深浅主题下都保持墨色 */
}

.detail-panel {
  position: relative;
  width: min(36rem, 100%);
  max-height: 100%;
  overflow-y: auto;
  border: 1px solid var(--ink);
  border-radius: 5px;
  background: var(--projects-paper-light);
  box-shadow: 4px 4px 0 var(--shadow-hard);
}

.detail-close,
.detail-back {
  position: absolute;
  top: 0.75rem;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  border: 1px solid var(--ink);
  border-radius: var(--control-radius);
  background: var(--ink);
  color: var(--acid);
  cursor: pointer;
  transition:
    background 150ms ease,
    color 150ms ease,
    box-shadow 150ms ease;
}

.detail-close { right: 0.75rem; }

/* 下钻返回钮：与关闭钮同一墨底酸绿配方，居面板左上 */
.detail-back { left: 0.75rem; }

.detail-close:hover,
.detail-back:hover {
  background: var(--acid);
  color: var(--projects-on-acid);
  box-shadow: 2px 2px 0 var(--shadow-hard);
}

.detail-foot {
  border-top: 1px solid var(--rule);
}

.detail-jump {
  text-decoration: none;
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

/* 长图：遮罩自身纵向滚动，图按原宽（上限 960px）展示而非压到一屏高 */
.lightbox-backdrop--long {
  align-items: flex-start;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.lightbox-backdrop--long .lightbox-image {
  max-width: min(100%, 960px);
  max-height: none;
}

.lightbox-close {
  position: fixed; /* 长图模式遮罩滚动时仍钉在视口右上角 */
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

/* 移动端：收窄滚动区边距；卡片头部动作钮加高到可触尺寸；
   详情浮层与图片预览全屏化，去掉圆角与阴影吃掉的可视面积 */
@media (max-width: 639px) {
  .xboard-page > div {
    padding: 12px 12px 80px;
    gap: 12px;
  }

  .tweet-icon-btn {
    width: 2rem;
    height: 2rem;
  }

  .detail-backdrop { padding: 0; }

  .detail-panel {
    width: 100%;
    max-height: 100dvh;
    border-right: none;
    border-left: none;
    border-radius: 0;
  }

  .lightbox-backdrop { padding: 0; }

  .lightbox-image {
    border-right: none;
    border-left: none;
    border-radius: 0;
    box-shadow: none;
  }
}
</style>
