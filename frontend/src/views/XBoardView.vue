<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMediaQuery } from '@vueuse/core'
import { ArrowLeft, Bookmark, ChevronDown, ExternalLink, ImageIcon, ImageOff, Link2, Maximize2, PanelRightClose, Play, Repeat2, Users } from 'lucide-vue-next'
import SpinnerLoader from '@/components/SpinnerLoader.vue'
import ListKeysSheet from '@/components/keyboard/ListKeysSheet.vue'
import FolioTools from '@/components/layout/FolioTools.vue'
import SaveButton from '@/components/saved/SaveButton.vue'
import TweetMediaList from '@/components/xboard/TweetMediaList.vue'
import TweetQuoteCard from '@/components/xboard/TweetQuoteCard.vue'
import TweetLinkCard from '@/components/xboard/TweetLinkCard.vue'
import { useXBoardController } from '@/composables/useXBoardController'
import { useDockSuppression } from '@/composables/useDockSuppression'
import { useListKeys } from '@/composables/useListKeys'
import { useReadMarks } from '@/composables/useReadMarks'
import { useSavedItems } from '@/composables/useSavedItems'
import { showToast } from '@/composables/useToast'
import { authorAvatarUrl, authorDisplayName, collapsedMedia, distributeColumns, emptyStateCopyKeys, estimateTweetCardHeight, extractXHandle, foldTweetsByAccount, formatLocalTime, hasCollapsedMedia, hasLinkCard, hasMedia, hasQuote, isLongPhoto, paginateFoldedTweets, paginateItems, quoteAsDoc, retweetedByHandle, splitAtSeen, timelineTweets, TWEET_FOLD_BAR_PX, tweetLinkCard, tweetQuote, tweetReadId, tweetTextSegments, tweetTimestamp } from '@/features/xboard/xBoardViewModel'
import { useTextOnly } from '@/features/xboard/useTextOnly'
import { isTypingTarget, listKeyAction } from '@/features/keyboard/listKeys'
import { isSavedTweet } from '@/features/saved/savedTweet'
import { scoreDisplay } from '@/features/dashboard/dashboardViewModel'
import { useAuthStore } from '@/stores/authStore'
import { fold, unfold } from '@/motion/fold'
import { vIndicator } from '@/motion/indicator'
import { vMorph } from '@/motion/morph'
import { canAnimate, popSpring } from '@/motion/motion'
import { slideIn, slideOut } from '@/motion/presence'
import { vReflow } from '@/motion/reflow'
import { vSwap } from '@/motion/swap'
import RollText from '@/motion/RollText.vue'
import type { TopDoc, TweetMediaItem } from '@/features/dashboard/dashboardViewModel'
import type { TweetCardLayout, TweetFold, TweetTextMetrics } from '@/features/xboard/xBoardViewModel'

const { t, locale } = useI18n()
const authStore = useAuthStore()
const isAdmin = computed(() => authStore.isAdmin)

const {
  docs, visibleDocs, selectedDate, today, loading, deleting, errorMsg,
  selectedIds, currentPage, totalPages, pageSize,
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
const selectedCount = computed(() => selectedIds.value.size)
const hasSelection = computed(() => selectedCount.value > 0)

// 桌面推文墙排得更紧：同账号折叠、多图排成一行胶片、可一键切纯文字；手机与平板照旧。
const desktop = useMediaQuery('(min-width: 1024px)')
const { textOnly, toggle: toggleTextOnly } = useTextOnly(desktop)
// 报眉放不下完整的一组时先把纯文字与刷新收成图标（trim），再放不下才连关注账号也只留图标与人数（compact），
// 还放不下（比如选了历史日期）就把窗口开关写短成「24 小时 / 日期」（tight），最后才回到页头
const FOLIO_LEVELS = ['full', 'trim', 'compact', 'tight'] as const
const iconOnly = (level: string | null) => level === 'trim' || level === 'compact' || level === 'tight'

// 本机收藏（只在桌面）：点书签或按 s 收下推文，连内容一起存在本机。页头的窗口开关里多一段「收藏」，切过去看收下的推文：
// 最近收的在前，不折叠、不变淡、不画「上次看到这里」。在收藏里取消的那条留到离开收藏再撤，点错了还能再收回来。
const saved = useSavedItems({ list: 'x', accept: isSavedTweet })
const savedCount = saved.count
const savedView = ref(false)
const savedDocs = shallowRef<TopDoc[]>([])
const savedPage = ref(1)
const isSaved = (tweet: TopDoc) => saved.has(tweetReadId(tweet))
const toggleSave = (tweet: TopDoc) => { saved.toggle(tweetReadId(tweet), tweet) }
// 推文墙上排的：平时是这个窗口的时间线，看收藏时是收下的推文
const wallSource = computed(() => (savedView.value ? savedDocs.value : timelineDocs.value))
const totalTweets = computed(() => wallSource.value.length)
// 收藏里不折叠：门槛设成永远到不了
const foldThreshold = computed(() => (savedView.value ? Number.POSITIVE_INFINITY : undefined))
// 看收藏时不转圈、不淡下去：收藏就在本机，窗口那边在不在拉都不相干
const wallLoading = computed(() => loading.value && !savedView.value)

// 全天推文客户端分页：时间线排序与瀑布流分列仅在当前页内进行。手机与平板每页 20 条；
// 桌面按卡位分页，每页排满 20 张卡，同账号折叠收起的不占卡位，页数随之变少。
const wallPages = computed(() => (desktop.value ? paginateFoldedTweets(wallSource.value, pageSize, foldThreshold.value) : null))
const wallPageCount = computed(() => wallPages.value?.length ?? totalPages.value)
const wallPage = computed(() => Math.min(savedView.value ? savedPage.value : currentPage.value, wallPageCount.value))
const wallHasPrev = computed(() => wallPage.value > 1)
const wallHasNext = computed(() => wallPage.value < wallPageCount.value)
const pagedTimelineDocs = computed(() => (wallPages.value
  ? wallPages.value[wallPage.value - 1] ?? []
  : paginateItems(timelineDocs.value, currentPage.value, pageSize)))

// 同账号折叠：一页里同一账号达到 3 条只留第一条，其余收进它底下的一行，点开就地展开、再点收回；
// 换一批推文（换窗口、刷新）时全部收回。
const tweetKey = (tweet: TopDoc) => tweet.url || tweet.title || ''
const expandedFolds = ref<Set<string>>(new Set())
const foldedPage = computed(() => (desktop.value
  ? foldTweetsByAccount(pagedTimelineDocs.value, tweetKey, expandedFolds.value, foldThreshold.value)
  : { visible: pagedTimelineDocs.value, folds: new Map<string, TweetFold>() }))
const wallDocs = computed(() => foldedPage.value.visible)
// 模板里按 v-for 取用：留下的那条有折叠行时给出一项，其余给空表
const foldsOf = (tweet: TopDoc): TweetFold[] => {
  const fold = foldedPage.value.folds.get(tweetKey(tweet))
  return fold ? [fold] : []
}
const toggleFoldOf = (key: string) => {
  const next = new Set(expandedFolds.value)
  if (!next.delete(key)) next.add(key)
  expandedFolds.value = next
}
const toggleFold = (tweet: TopDoc) => toggleFoldOf(tweetKey(tweet))
// 已读淡化（只在桌面）：看过的推文变淡；再来时，在新来的和上回看过的之间画「上次看到这里」，线上面全是新的。
// 记录只存在本机浏览器。每次重新拉取（进来、刷新、换窗口）算新的一次，这之前看过的都算上回看过的。
const readMarks = useReadMarks({ list: 'x', enabled: desktop })
const vReadMark = readMarks.directive
const isRead = (tweet: TopDoc) => !savedView.value && readMarks.isRead(tweetReadId(tweet))
watch(loading, (value) => { if (value) readMarks.snapshot() })
const timelineIndex = computed(() => new Map(timelineDocs.value.map((doc, index) => [doc, index])))
// 时间线上第一条上回就看过的推文；它前面的都是这之后新来的，也就是线上面的条数。
const seenBoundary = computed(() => (savedView.value ? -1 : timelineDocs.value.findIndex((doc) => readMarks.seenBefore(tweetReadId(doc)))))
const wallSplit = computed(() => splitAtSeen(
  pagedTimelineDocs.value, foldedPage.value, seenBoundary.value, (doc) => timelineIndex.value.get(doc) ?? -1, tweetKey,
))
// 纯文字时收起了配图或链接卡的推文，时间行里留一枚提示钮，点开详情看
const mediaHint = (tweet: TopDoc) => (textOnly.value && hasCollapsedMedia(tweet) ? collapsedMedia(tweet) : null)

// 正文或引用被限行截住的推文，时间行里多一枚「全文」，点开详情看全文。截没截住随列宽、字体与译文而变，排好后实测。
const wallEl = ref<HTMLElement | null>(null)
const clampedTweets = ref<ReadonlySet<string>>(new Set())
const isClamped = (tweet: TopDoc) => clampedTweets.value.has(tweetKey(tweet))
const measureClamps = () => {
  const next = new Set<string>()
  if (desktop.value) {
    for (const text of wallEl.value?.querySelectorAll<HTMLElement>('.tweet-text, .tweet-quote-text') ?? []) {
      const key = text.closest<HTMLElement>('[data-reflow-key]')?.dataset.reflowKey
      if (key && text.scrollHeight > text.clientHeight + 1) next.add(key)
    }
  }
  const current = clampedTweets.value
  if (next.size !== current.size || [...next].some((key) => !current.has(key))) clampedTweets.value = next
}

// 页级全选（防止一键选中不可见条目误删）：复选框状态按当前页墙上看得见的 id 计算，折叠收起的不算
const pageIds = computed(() => wallDocs.value.map((doc) => String(doc.id)).filter(Boolean))
const allPageSelected = computed(() => pageIds.value.length > 0 && pageIds.value.every((id) => selectedIds.value.has(id)))
const somePageSelected = computed(() => !allPageSelected.value && pageIds.value.some((id) => selectedIds.value.has(id)))

// 关注账号收在侧栏里，默认收起：页头按钮展开/收起，推文墙优先占满版面。
const followPanelOpen = ref(false)

// 宽屏多排几列，列宽保持在 340 到 400px 上下：配图限高后列太宽只会把图裁成细长条
const computeColumnCount = () => {
  const width = window.innerWidth
  return width >= 2200 ? 6 : width >= 1800 ? 5 : width >= 1280 ? 4 : width >= 1024 ? 3 : width >= 768 ? 2 : 1
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
const masonryGap = ref(MASONRY_GAP_PX)
const tweetTextMetrics = ref<TweetTextMetrics | undefined>()
const compactMetrics = ref<Omit<TweetCardLayout, 'textOnly'> | undefined>()
const cardLayout = computed<TweetCardLayout | undefined>(() => (
  compactMetrics.value ? { ...compactMetrics.value, textOnly: textOnly.value } : undefined
))
let mainResizeObserver: ResizeObserver | null = null
const masonryColumnWidth = computed(() => {
  const count = columnCount.value
  const width = (masonryWidth.value - masonryGap.value * (count - 1)) / count
  return width > 0 ? width : 280 // 首帧未测量时的回退列宽
})
const estimateCardHeight = (doc: TopDoc) => estimateTweetCardHeight(doc, masonryColumnWidth.value, locale.value, tweetTextMetrics.value, cardLayout.value)
  + (foldedPage.value.folds.has(tweetKey(doc)) ? TWEET_FOLD_BAR_PX : 0)
// 这一页画「上次看到这里」时，线上、线下各自分列，线横跨整面墙；没有线时整页一块。
const masonryBlocks = computed(() => {
  const { fresh, earlier, rule } = wallSplit.value
  const block = (key: string, docs: TopDoc[]) => ({ key, columns: distributeColumns(docs, columnCount.value, estimateCardHeight) })
  if (!rule) return [block('all', fresh)]
  return fresh.length ? [block('fresh', fresh), block('earlier', earlier)] : [block('earlier', earlier)]
})

// 翻页回顶：滚动的是内层 overflow-y-auto 容器而非 window
const scrollEl = ref<HTMLElement | null>(null)
const mainEl = ref<HTMLElement | null>(null)

// 主栏宽度随断点、滚动区边距（移动端 12px、桌面 24px）与侧栏变化，必须实测。
// 桌面漫画版放大了推文正文，字号与行高经 --tweet-text-size/--tweet-text-line
// 声明在主栏上，估高按实际排版折行；未声明时回落默认 text-sm leading-5。
// 列间距同理经 --masonry-gap 声明（瀑布流网格也读它），未声明时 16px。
// 紧凑排版（正文与引用限行、配图限高）也声明在那里，以 --tweet-media-max 为准：没声明就按完整排版估高。
const measureMasonry = () => {
  const el = mainEl.value
  if (!el) return
  masonryWidth.value = el.clientWidth
  const style = window.getComputedStyle(el)
  const read = (name: string) => parseFloat(style.getPropertyValue(name))
  const gap = read('--masonry-gap')
  masonryGap.value = gap > 0 ? gap : MASONRY_GAP_PX
  const fontSize = read('--tweet-text-size')
  const lineHeight = read('--tweet-text-line')
  tweetTextMetrics.value = fontSize > 0 && lineHeight > 0 ? { fontSize, lineHeight } : undefined
  const mediaMax = read('--tweet-media-max')
  compactMetrics.value = mediaMax > 0
    ? {
        textClamp: read('--tweet-text-clamp') || Number.POSITIVE_INFINITY,
        mediaMax,
        quoteSize: read('--tweet-quote-size') || 11,
        quoteLine: read('--tweet-quote-line') || 16,
        quoteClamp: read('--tweet-quote-clamp') || Number.POSITIVE_INFINITY,
        quoteMediaMax: read('--tweet-quote-media-max') || 220,
      }
    : undefined
}

const onGoPage = (next: number) => {
  if (savedView.value) savedPage.value = Math.min(Math.max(next, 1), wallPageCount.value)
  else goPage(next)
  scrollEl.value?.scrollTo({ top: 0 })
}

// ── 切换动效 ──
// 推文墙的排布：每列依次是哪几条。换了一批（换窗口、刷新、翻页、改关注）、列数变了（开合侧栏）或折叠展开时随之变化，
// 推文墙据此逐条过渡：留下的滑到新位置，新来的由左上角起依次浮现，离开的原地淡出。切纯文字时各条一齐变矮变高，
// 也算换了排布，留下的随之滑到新位置。
const wallLayout = computed(() => [
  textOnly.value ? 'text' : 'media',
  ...masonryBlocks.value.flatMap((block) => [block.key, ...block.columns.map((column) => column.map(tweetKey).join(' '))]),
].join('|'))
// 新推文从哪边浮现：翻页时从翻去的一侧进来，换窗口、刷新、改关注、折叠展开自下而上；分页摘要里的页码随之上下滚动。
const RISE = { x: 0, y: 14 }
const wallEnterFrom = ref(RISE)
const pageDirection = ref<1 | -1>(1)
watch([docs, unfollowedAccounts, expandedFolds, textOnly], () => { wallEnterFrom.value = RISE }, { flush: 'sync' })
watch([wallLayout, locale, desktop], measureClamps, { flush: 'post' })
watch(wallPage, (page, previous) => {
  const step = Math.sign(page - previous)
  wallEnterFrom.value = { x: step * 18, y: 0 }
  pageDirection.value = step < 0 ? -1 : 1
}, { flush: 'sync' })
// 换窗口、刷新后到首批推文到达前，墙上还是旧的一批：稍后淡下去示意正在换，首批一到即恢复。
const wallStale = ref(false)
watch(loading, (value) => { wallStale.value = value })
watch(docs, () => { wallStale.value = false })

// 关注侧栏开合：桌面端并排时整块从窗口右缘外滑入、滑回右缘外，离场时先脱离版面，推文墙随即按新列数重排；
// 窄屏叠在推文墙上方，高度展开收起。
const panelSlide = (el: Element) => ({ x: Math.max(36, document.documentElement.clientWidth - el.getBoundingClientRect().left) })
const sideBySide = (el: Element) => el.parentElement !== null && getComputedStyle(el.parentElement).flexDirection === 'row'
const panelEnter = (el: Element, done: () => void) => (sideBySide(el) ? slideIn(el, done, panelSlide(el)) : unfold(el, done))
const panelLeave = (el: Element, done: () => void) => (sideBySide(el) ? slideOut(el, done, panelSlide(el)) : fold(el, done))

// 勾选关注勾选框时盖章式弹一下；已关注数随之滚动换值，多了新数字自下而上，少了自上而下。
const stampCheck = (event: Event) => {
  const box = event.target as HTMLElement
  if (canAnimate(box)) box.animate([{ scale: '0.7' }, { scale: '1' }], { duration: 420, easing: popSpring() })
}
const followDirection = ref<1 | -1>(1)
watch(() => followedAccounts.value.length, (count, previous) => { followDirection.value = count < previous ? -1 : 1 }, { flush: 'sync' })
const savedDirection = ref<1 | -1>(1)
watch(savedCount, (count, previous) => { savedDirection.value = count < previous ? -1 : 1 }, { flush: 'sync' })
// 分页摘要里只让页码滚动：按页码位置把译文切成前后两段。
const pageSummaryParts = computed(() => {
  const parts = t('xboard.pageSummary', { page: '\u0000', totalPages: wallPageCount.value, total: wallSource.value.length }).split('\u0000')
  return parts.length === 2 ? parts : null
})

// 进出收藏：进来时把收下的推文照此刻拍一份上墙，从第一页看起，关注侧栏收起（收藏不按关注筛）；
// 再点「收藏」或刷新按此刻重拍，刚取消的这才撤下。回到窗口时那边原样还在，窗口本来就是最近 24 小时的，点「最近」只是回来、不重拉。
const enterSaved = () => {
  savedDocs.value = saved.entries.value.map((entry) => entry.data)
  if (!savedView.value) {
    savedPage.value = 1
    followPanelOpen.value = false
    savedView.value = true
    scrollEl.value?.scrollTo({ top: 0 })
  }
  wallEnterFrom.value = RISE
}
const leaveSaved = () => {
  if (!savedView.value) return false
  savedView.value = false
  wallEnterFrom.value = RISE
  scrollEl.value?.scrollTo({ top: 0 })
  return true
}
const pickRecent = () => {
  if (leaveSaved() && isToday.value) return
  void showRecent()
}
const pickDate = (date: string) => {
  leaveSaved()
  onDateChange(date)
}
const refreshWall = () => {
  if (savedView.value) enterSaved()
  else void refresh()
}
// 窗口日期这一段亮不亮：看收藏时两段窗口都不亮
const dateShown = computed(() => !isToday.value && !savedView.value)
watch(desktop, (value) => { if (!value) leaveSaved() })

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
  readMarks.markOpened(tweetReadId(tweet))
  detailReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
  detailTweet.value = tweet
  detailParent.value = null
  focusDetailClose()
}
const closeDetail = () => {
  detailTweet.value = null
  detailParent.value = null
  // 焦点还原到打开浮层的触发元素；元素已随数据重载卸载时跳过。在详情里用 j / k 换过条目的，落到最后看的那条上
  if (detailReturnFocus?.isConnected) detailReturnFocus.focus()
  else if (desktop.value) listKeys.focusCursor()
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

// 键盘流（只在桌面）：j / k 按时间线顺序在这一页的推文之间走（线上面新来的在前），走过的记为看过，走到一页头尾再按就翻页；
// o 打开详情，x 开合同账号折叠（在展开的组里按也行，收回后光标落回领头那条）。
const listOrder = computed(() => [...wallSplit.value.fresh, ...wallSplit.value.earlier])
const listKeyOrder = computed(() => listOrder.value.map(tweetKey))
const tweetOf = (key: string) => listOrder.value.find((doc) => tweetKey(doc) === key)
// 这条所在折叠组领头那条的 key：它自己领头，或在展开的组里；不在折叠组里为 null
const foldHeadOf = (key: string) => {
  const { folds } = foldedPage.value
  if (folds.has(key)) return key
  for (const [head, fold] of folds) if (fold.expanded && fold.rest.some((doc) => tweetKey(doc) === key)) return head
  return null
}
const listKeys = useListKeys({
  enabled: desktop,
  root: wallEl,
  keys: listKeyOrder,
  open: (key) => {
    const tweet = tweetOf(key)
    if (tweet) openDetail(tweet)
  },
  save: (key) => {
    const tweet = tweetOf(key)
    if (tweet) toggleSave(tweet)
  },
  toggle: (key) => {
    const head = foldHeadOf(key)
    if (head == null) return
    toggleFoldOf(head)
    if (head !== key) listKeys.setCursor(head, { reveal: true, focus: true })
  },
  passed: (key) => {
    const tweet = tweetOf(key)
    if (tweet) readMarks.markSeen(tweetReadId(tweet))
  },
  edge: (direction) => {
    const page = wallPage.value + direction
    if (page < 1 || page > wallPageCount.value) return false
    onGoPage(page)
    return true
  },
})
const { help: keysHelp, isCursor } = listKeys

// 详情开着时 j / k 换下一条、上一条（下钻看被引推文时不换），新的一条从按的方向滑进来，墙上的光标跟着走，到一页头尾接着翻页。
const detailPanelEl = ref<HTMLElement | null>(null)
const detailSwap = ref(0)
const detailStep = ref<1 | -1>(1)
const stepDetail = (direction: 1 | -1) => {
  const tweet = detailTweet.value
  const index = tweet ? listKeyOrder.value.indexOf(tweetKey(tweet)) : -1
  if (index < 0) return
  let next = listOrder.value[index + direction]
  if (!next) {
    const page = wallPage.value + direction
    if (page < 1 || page > wallPageCount.value) return
    onGoPage(page)
    next = direction > 0 ? listOrder.value[0] : listOrder.value[listOrder.value.length - 1]
    if (!next) return
  }
  readMarks.markOpened(tweetReadId(next))
  detailReturnFocus = null
  detailStep.value = direction
  detailSwap.value += 1
  detailTweet.value = next
  playingMedia.value = new Set()
  detailPanelEl.value?.scrollTo({ top: 0 })
  listKeys.setCursor(tweetKey(next), { reveal: true })
}
const onDetailKeydown = (event: KeyboardEvent) => {
  if (!detailTweet.value || detailParent.value || lightboxUrl.value || !desktop.value) return
  const action = listKeyAction(event)
  if (isTypingTarget(event.target)) return
  if (action === 'save') {
    // 详情里按 s 收下正在看的这条
    event.preventDefault()
    toggleSave(detailTweet.value)
    return
  }
  if (action !== 'next' && action !== 'prev') return
  event.preventDefault()
  stepDetail(action === 'next' ? 1 : -1)
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
watch(docs, () => { playingMedia.value = new Set(); detailTweet.value = null; detailParent.value = null; expandedFolds.value = new Set() })

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
  window.addEventListener('keydown', onDetailKeydown)
  // 量主栏宽度与正文排版供瀑布流估高；clientWidth 不含滚动条。
  measureMasonry()
  if (mainEl.value && typeof ResizeObserver !== 'undefined') {
    // jsdom 等无 ResizeObserver 环境跳过观测，首帧回退列宽接管
    // 列宽变了正文就重新折行：排布没变时推文墙不重渲染，在这里重量一次截没截住
    mainResizeObserver = new ResizeObserver(() => {
      measureMasonry()
      void nextTick(measureClamps)
    })
    mainResizeObserver.observe(mainEl.value)
  }
  // 字体晚到会改折行
  void document.fonts?.ready.then(measureClamps)
  load()
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', updateColumnCount)
  window.removeEventListener('keydown', onLightboxKeydown)
  window.removeEventListener('keydown', onDetailKeydown)
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
        <!-- 本版工具：桌面报眉放得下就搬进报眉（trim 档纯文字与刷新只留图标，compact 档按钮都只留图标），放不下或在手机上留在页头 -->
        <FolioTools v-slot="{ level }" :levels="FOLIO_LEVELS">
          <div class="xboard-header-actions flex flex-wrap items-center gap-2">
            <!-- 关注账号侧栏开关：收起时仍显示已关注数，筛选状态一眼可见 -->
            <button
              v-if="availableAccounts.length && !savedView"
              type="button"
              class="btn-secondary xboard-follow-toggle"
              :class="{ 'xboard-mode-active': followPanelOpen }"
              :title="level === 'compact' || level === 'tight' ? t('xboard.followAccounts') : undefined"
              :aria-expanded="followPanelOpen"
              aria-controls="xboard-follow-panel"
              @click="followPanelOpen = !followPanelOpen"
            >
              <Users class="h-3.5 w-3.5" />
              <span class="xboard-tool-label">{{ t('xboard.followAccounts') }}</span>
              <span class="xboard-follow-count"><RollText :value="followedAccounts.length" :direction="followDirection" />/{{ availableAccounts.length }}</span>
            </button>
            <!-- 纯文字：一键收起所有配图与链接卡，只读字（桌面推文墙；选择记在本机） -->
            <button
              v-if="desktop"
              type="button"
              class="btn-secondary xboard-text-only"
              :class="{ 'xboard-mode-active': textOnly }"
              :title="iconOnly(level) ? t('xboard.textOnly') : undefined"
              :aria-pressed="textOnly"
              @click="toggleTextOnly"
            >
              <ImageOff class="h-3.5 w-3.5" />
              <span class="xboard-tool-label">{{ t('xboard.textOnly') }}</span>
            </button>
            <!-- 最近 24 小时 / 窗口日期 / 收藏：并排成一组开关，选中的一段高亮；换选时高亮滑过去（漫画版）或盖章式落定。
                 收藏一段只在桌面有，一直在（收下第一条时报眉不用换档；没收过时点进去说怎么收），带着收了几条；
                 除了报眉最宽的一档，都只留书签与条数，名字放在提示里。 -->
            <div v-indicator="{ active: '.xboard-window-active', pop: true }" class="xboard-window-switch">
              <button
                class="btn-secondary xboard-recent text-xs"
                :class="{ 'xboard-mode-active xboard-window-active': isToday && !savedView }"
                :aria-pressed="isToday && !savedView"
                @click="pickRecent"
              >
                <span class="xboard-recent-long">{{ t('xboard.recent24h') }}</span>
                <span class="xboard-recent-short" aria-hidden="true">{{ t('xboard.recent24hShort') }}</span>
              </button>
              <label v-morph="dateShown" class="xboard-date flex items-center gap-2 text-xs text-stone-400" :class="{ 'xboard-window-active': dateShown }">
                <span class="xboard-date-text"><span class="xboard-date-long">{{ t('xboard.dateLabel') }}</span><span class="xboard-date-short" aria-hidden="true">{{ t('xboard.dateLabelShort') }}</span></span>
                <input
                  type="date"
                  class="input py-1.5 text-xs"
                  :class="{ 'xboard-mode-active': dateShown }"
                  :value="selectedDate"
                  :max="today"
                  @change="pickDate(($event.target as HTMLInputElement).value)"
                />
              </label>
              <button
                v-if="desktop"
                type="button"
                class="btn-secondary xboard-saved text-xs"
                :class="{ 'xboard-mode-active xboard-window-active': savedView }"
                :aria-pressed="savedView"
                :title="level === 'full' ? undefined : t('saved.title')"
                @click="enterSaved"
              >
                <Bookmark class="h-3.5 w-3.5" />
                <span class="xboard-tool-label">{{ t('saved.title') }}</span>
                <span class="xboard-saved-count"><RollText :value="savedCount" :direction="savedDirection" /></span>
              </button>
            </div>
            <button
              class="btn-secondary xboard-refresh"
              :disabled="wallLoading"
              :title="iconOnly(level) ? t(wallLoading ? 'common.refreshing' : 'common.refresh') : undefined"
              @click="refreshWall"
            >
              <svg class="h-3.5 w-3.5" :class="wallLoading ? 'animate-spin' : ''" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/></svg>
              <span class="xboard-tool-label"><RollText :value="t(wallLoading ? 'common.refreshing' : 'common.refresh')" :direction="wallLoading ? 1 : -1" /></span>
            </button>
          </div>
        </FolioTools>
      </div>

      <div class="xboard-body">

        <!-- 账号关注筛选侧栏：默认全部关注；按账号即时过滤当前窗口推文。
             DOM 上紧跟页头开关（键盘可直达），桌面端经 CSS order 排到推文墙右侧。 -->
        <Transition @enter="panelEnter" @leave="panelLeave">
          <aside
            v-if="availableAccounts.length && followPanelOpen"
            id="xboard-follow-panel"
            class="xboard-follow-panel px-4 py-3"
            :aria-label="t('xboard.followAccounts')"
          >
            <div class="flex items-start justify-between gap-3">
              <div class="xboard-follow-heading">
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
                  @change="toggleFollowAccount(account.handle); stampCheck($event)"
                />
                <span>{{ account.displayName }}</span>
              </label>
            </div>
          </aside>
        </Transition>

        <div ref="mainEl" class="xboard-main">
          <!-- 管理员多选工具栏 -->
          <div v-if="isAdmin && !savedView" class="xboard-toolbar stagger-enter flex shrink-0 flex-wrap items-center justify-between gap-3 px-4 py-2">
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
          <div v-if="errorMsg" class="xboard-notice shrink-0 glass-card flex items-center justify-between px-5 py-3 text-sm text-rose-600">
            <span>{{ errorMsg }}</span>
            <button class="ml-3 text-rose-400 transition hover:text-rose-600" @click="errorMsg = ''">
              <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>

          <!-- 加载 / 空态 -->
          <SpinnerLoader v-if="wallLoading && !docs.length" class="min-h-[240px]" :label="t('xboard.loading')" />
          <div v-else-if="!wallSource.length" class="xboard-notice glass-card flex min-h-[240px] flex-col items-center justify-center text-center text-sm text-stone-400">
            <template v-if="savedView">
              <p class="font-medium text-stone-500">{{ t('saved.emptyTitle') }}</p>
              <p class="mt-1 text-xs">{{ t('saved.emptyXHint') }}</p>
            </template>
            <template v-else-if="docs.length && followedAccounts.length === 0">
              <p class="font-medium text-stone-500">{{ t('xboard.emptyFollowed') }}</p>
              <p class="mt-1 text-xs">{{ t('xboard.emptyFollowedHint') }}</p>
            </template>
            <template v-else>
              <p class="font-medium text-stone-500">{{ t(emptyCopy.titleKey) }}</p>
              <p class="mt-1 text-xs">{{ t(emptyCopy.hintKey, { earliest: earliestSnapshotDate }) }}</p>
            </template>
          </div>

          <!-- 瀑布流推文墙（估高贪心分列：每条进当前最矮列，列内时间降序）；键盘光标是墙上一枚会滑动的标记 -->
          <div
            v-else
            ref="wallEl"
            v-reflow="{ key: wallLayout, ...wallEnterFrom }"
            v-indicator="{ active: '.is-cursor', mark: 'after' }"
            class="masonry-grid"
            :class="{ 'masonry-grid--stale': wallStale && !savedView }"
          >
            <template v-for="block in masonryBlocks" :key="block.key">
              <!-- 上次看到这里：线上面是上回之后新来的，线横跨整面墙 -->
              <div
                v-if="block.key === 'earlier'"
                class="xboard-seen-rule"
                data-reflow-key="xboard-seen-rule"
                role="separator"
                :aria-label="`${t('xboard.seenRule')} · ${t('xboard.seenRuleCount', { count: seenBoundary })}`"
              >
                <span class="xboard-seen-rule__tag">{{ t('xboard.seenRule') }}</span>
                <span class="xboard-seen-rule__count">{{ t('xboard.seenRuleCount', { count: seenBoundary }) }}</span>
                <svg class="xboard-seen-rule__line" viewBox="0 0 1000 6" preserveAspectRatio="none" aria-hidden="true"><path d="M0 3.3 L380 2.6 L1000 3.7" /></svg>
              </div>
              <div
                v-for="(column, columnIndex) in block.columns"
                :key="`${block.key}-${columnIndex}`"
                class="masonry-col"
              >
                <article
                  v-for="tweet in column"
                  :key="tweetKey(tweet)"
                  v-read-mark="tweetReadId(tweet)"
                  :data-reflow-key="tweetKey(tweet)"
                  :data-list-key="tweetKey(tweet)"
                  class="tweet-card"
                  :class="{ 'is-read': isRead(tweet), 'is-cursor': isCursor(tweetKey(tweet)) }"
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
                      v-if="isAdmin && !savedView && tweet.id"
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
                      <SaveButton v-if="desktop" class="tweet-icon-btn" :saved="isSaved(tweet)" @toggle="toggleSave(tweet)" />
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
                        @click="readMarks.markOpened(tweetReadId(tweet))"
                      >
                        <ExternalLink class="h-3.5 w-3.5" />
                      </a>
                      <span class="tweet-score shrink-0">
                        <component :is="scoreDisplay(tweet).icon" class="h-3 w-3 shrink-0" />{{ scoreDisplay(tweet).text }}
                      </span>
                    </span>
                  </div>

                  <!-- 媒体区：照片点开 lightbox、视频点击播放（与详情浮层同一子组件渲染）；
                       桌面多图排成一行胶片，纯文字时收起 -->
                  <TweetMediaList
                    v-if="hasMedia(tweet) && !textOnly"
                    :tweet="tweet"
                    :playing-media="playingMedia"
                    :filmstrip="desktop"
                    @preview="openLightbox"
                    @play="playVideo"
                    @expand="openDetail(tweet)"
                  />

                  <!-- 文字区：点击/回车放大详情（不跳走）；URL 段仍是真链接可直跳 -->
                  <div class="tweet-body px-4 py-3">
                    <div
                      role="button"
                      tabindex="0"
                      class="tweet-text block cursor-pointer whitespace-pre-line px-1 text-sm leading-5"
                      :aria-label="t('xboard.openDetail')"
                      @click="openDetail(tweet)"
                      @keydown.enter="openDetail(tweet)"
                    >
                      <template v-for="(seg, segIndex) in tweetTextSegments(tweet, locale, desktop)" :key="segIndex">
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
                      :compact="desktop"
                      :text-only="textOnly"
                      @activate="openDetail(tweet)"
                    />
                    <!-- 外链预览卡：整卡跳目标页（与 X 一致），不放大详情；纯文字时收起 -->
                    <TweetLinkCard
                      v-if="hasLinkCard(tweet) && !textOnly"
                      :card="tweetLinkCard(tweet)!"
                      context="wall"
                      :compact="desktop"
                    />
                    <p v-if="formatTime(tweet) || mediaHint(tweet) || isClamped(tweet)" class="tweet-time mt-2 px-1 text-2xs">
                      {{ formatTime(tweet) }}
                      <!-- 截住了、收起了什么：「全文」点开看全文；纯文字时收起了几张图、几段视频、有没有链接卡，点开详情看 -->
                      <span v-if="isClamped(tweet) || mediaHint(tweet)" class="tweet-time-tools">
                        <button v-if="isClamped(tweet)" type="button" class="tweet-more" @click="openDetail(tweet)">{{ t('xboard.readMore') }}</button>
                        <button
                          v-if="mediaHint(tweet)"
                          type="button"
                          class="tweet-media-hint"
                          :aria-label="t('xboard.showMedia')"
                          :title="t('xboard.showMedia')"
                          @click="openDetail(tweet)"
                        >
                          <span v-if="mediaHint(tweet)?.photos"><ImageIcon />{{ mediaHint(tweet)?.photos }}</span>
                          <span v-if="mediaHint(tweet)?.videos"><Play />{{ mediaHint(tweet)?.videos }}</span>
                          <Link2 v-if="mediaHint(tweet)?.link" />
                        </button>
                      </span>
                    </p>
                  </div>

                  <!-- 同账号折叠：这一页里该账号其余各条收在这一行，点开就地展开、再点收回 -->
                  <button
                    v-for="fold in foldsOf(tweet)"
                    :key="fold.handle"
                    type="button"
                    class="tweet-fold"
                    :aria-expanded="fold.expanded"
                    @click="toggleFold(tweet)"
                  >
                    <span class="tweet-fold-label">{{ t('xboard.foldMore', { count: fold.rest.length, name: fold.name }) }}</span>
                    <span class="tweet-fold-action">{{ t(fold.expanded ? 'xboard.foldHide' : 'xboard.foldShow') }}<ChevronDown class="tweet-fold-chevron" /></span>
                  </button>
                </article>
              </div>
            </template>
          </div>

          <!-- 全天推文分页条：仅超过一页时出现 -->
          <div
            v-if="wallPageCount > 1"
            class="xboard-pagination stagger-enter flex shrink-0 flex-wrap items-center justify-center gap-3 px-4 py-2"
            :aria-label="t('xboard.pagination')"
          >
            <button class="btn-secondary text-xs" :disabled="!wallHasPrev" @click="onGoPage(wallPage - 1)">
              {{ t('common.previous') }}
            </button>
            <span class="text-xs text-stone-500">
              <template v-if="pageSummaryParts">{{ pageSummaryParts[0] }}<RollText :value="wallPage" :direction="pageDirection" />{{ pageSummaryParts[1] }}</template>
              <template v-else>{{ t('xboard.pageSummary', { page: wallPage, totalPages: wallPageCount, total: wallSource.length }) }}</template>
            </span>
            <button class="btn-secondary text-xs" :disabled="!wallHasNext" @click="onGoPage(wallPage + 1)">
              {{ t('common.next') }}
            </button>
          </div>

          <p v-if="wallSource.length" class="shrink-0 text-center text-2xs text-stone-300">{{ t(savedView ? 'saved.xFooter' : 'xboard.tweets', { count: totalTweets }) }}</p>
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
        <article ref="detailPanelEl" v-swap="{ key: detailSwap, x: detailStep * 24, y: 0 }" class="detail-panel" @click.stop>
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
            <!-- 收藏正在看的这条（下钻看被引推文时不收：那是引用里的一截，不是整条推文） -->
            <SaveButton
              v-if="desktop && !detailParent"
              class="btn-secondary detail-save ml-auto inline-flex items-center gap-1.5 text-xs"
              label
              :saved="isSaved(detailTweet)"
              @toggle="toggleSave(detailTweet)"
            />
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

    <!-- 键盘快捷键表：按 ? 开合（桌面） -->
    <ListKeysSheet
      v-if="desktop"
      v-model:open="keysHelp"
      :actions="{ open: t('listKeys.tweetOpen'), save: t('listKeys.save'), toggle: savedView ? undefined : t('listKeys.tweetToggle') }"
      :extra="[{ keys: ['j', 'k'], label: t('listKeys.tweetDetail') }]"
    />
  </div>
</template>

<style scoped>
/* 估高贪心瀑布流：JS 按卡片估高把每条放进当前最矮列（见 distributeColumns），
   列高各自独立、卡片按内容高度堆叠；v-bind 列数跟随视口断点（768/1024/1280）。
   墙是定位元素、自成层叠上下文：v-reflow 重排时离开的推文垫在底层淡出。 */
.masonry-grid {
  position: relative;
  isolation: isolate;
  display: grid;
  grid-template-columns: repeat(v-bind(columnCount), minmax(0, 1fr));
  gap: var(--masonry-gap, 1rem);
  align-items: start;
  transition: opacity 200ms ease;
}

/* 换窗口、刷新后首批新推文到达前，旧的一批稍后淡下去示意正在换（请求很快时不闪）；首批一到立即恢复。 */
.masonry-grid--stale {
  opacity: 0.45;
  transition: opacity 240ms ease 150ms;
}

.masonry-col {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  min-width: 0;
}

/* 上次看到这里：横跨整面墙的一行，线上、线下的推文各自分列。 */
.xboard-seen-rule {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  color: var(--ink-muted);
  font-size: 12px;
}

.xboard-seen-rule__tag {
  flex: none;
  color: var(--ink);
  font-weight: 800;
}

.xboard-seen-rule__count {
  flex: none;
  font-variant-numeric: tabular-nums;
}

.xboard-seen-rule__line {
  flex: 1 1 auto;
  min-width: 24px;
  height: 6px;
  overflow: visible;
}

.xboard-seen-rule__line path {
  fill: none;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
  vector-effect: non-scaling-stroke;
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
  position: relative; /* 侧栏滑出时钉在原处脱离版面 */
  flex-shrink: 0;
}

/* 最近 24 小时 / 窗口日期一组：选中标记只在漫画版画出来滑动，这里各项自带选中样式，换选时盖章式落定。 */
.xboard-window-switch {
  position: relative;
  isolation: isolate;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.xboard-window-switch::before {
  content: none;
}

/* 「24 小时」「日期」只在报眉最紧的一档（tight）替「最近 24 小时」「窗口日期」露面，其余时候不画；读屏始终读全名。 */
.xboard-recent-short,
.xboard-date-short {
  display: none;
}

/* 空态与错误提示出现时浮上来。 */
.xboard-notice {
  animation: motion-rise 360ms var(--motion-ease-out) both;
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
/* 页头工具搬进报眉后不在页面里，字体单独带上。 */
.xboard-page,
.xboard-header-actions {
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

/* 收藏钮在前时由它推到右边，查看原帖紧挨着它 */
.detail-save + .detail-jump {
  margin-left: 0;
}

/* 收下了：酸绿底，与主按钮悬停同一配色 */
.detail-save.is-saved,
.detail-save.is-saved:hover:not(:disabled) {
  background: var(--acid);
  color: var(--acid-ink);
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
