import { nextTick, onBeforeUnmount, onMounted, ref, useTemplateRef, watch, type Ref } from 'vue'
import type { TopDoc, TweetMediaItem } from '@/features/dashboard/dashboardViewModel'
import { isLongPhoto, quoteAsDoc, tweetQuote } from '@/features/xboard/xBoardViewModel'
import { isTypingTarget, listKeyAction } from '@/features/keyboard/listKeys'
import { useDockSuppression } from '@/composables/useDockSuppression'

interface TweetDetailOptions {
  docs: Readonly<Ref<TopDoc[]>>
  desktop: Readonly<Ref<boolean>>
  listOrder: Readonly<Ref<TopDoc[]>>
  wallPage: Readonly<Ref<number>>
  wallPageCount: Readonly<Ref<number>>
  onGoPage: (page: number) => void
  markOpened: (tweet: TopDoc) => void
  focusCursor: () => void
  setCursor: (key: string) => void
  toggleSave: (tweet: TopDoc) => void
}

/** Owns overlays, keyboard listeners, media state and focus restoration. */
export function useTweetDetail({ docs, desktop, listOrder, wallPage, wallPageCount, onGoPage, markOpened, focusCursor, setCursor, toggleSave }: TweetDetailOptions) {
  const tweetKey = (tweet: TopDoc) => tweet.url || tweet.title || ''
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
  const detailCloseEl = useTemplateRef<HTMLButtonElement>('detailCloseEl')
  let detailReturnFocus: HTMLElement | null = null
  const focusDetailClose = () => { void nextTick(() => detailCloseEl.value?.focus()) }
  // 浮层内引用卡下钻：点击 = 就地切换为被引推文详情（quote 投影字段齐全，
  // 零请求），detailParent 记回跳目标；仅一层（投影不嵌套，与 X 一致）。
  // 下钻/返回时清空播放态：媒体块随内容切换整体卸载，不残留他条播放键。
  const detailParent = ref<TopDoc | null>(null)
  const openDetail = (tweet: TopDoc) => {
    markOpened(tweet)
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
    else if (desktop.value) focusCursor()
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

  // 详情开着时 j / k 换下一条、上一条（下钻看被引推文时不换），新的一条从按的方向滑进来，墙上的光标跟着走，到一页头尾接着翻页。
  const detailPanelEl = useTemplateRef<HTMLElement>('detailPanelEl')
  const detailSwap = ref(0)
  const detailStep = ref<1 | -1>(1)
  const stepDetail = (direction: 1 | -1) => {
    const tweet = detailTweet.value
    const index = tweet ? listOrder.value.findIndex((doc) => tweetKey(doc) === tweetKey(tweet)) : -1
    if (index < 0) return
    let next = listOrder.value[index + direction]
    if (!next) {
      const page = wallPage.value + direction
      if (page < 1 || page > wallPageCount.value) return
      onGoPage(page)
      next = direction > 0 ? listOrder.value[0] : listOrder.value[listOrder.value.length - 1]
      if (!next) return
    }
    markOpened(next)
    detailReturnFocus = null
    detailStep.value = direction
    detailSwap.value += 1
    detailTweet.value = next
    playingMedia.value = new Set()
    detailPanelEl.value?.scrollTo({ top: 0 })
    setCursor(tweetKey(next))
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
  watch(docs, () => { playingMedia.value = new Set(); detailTweet.value = null; detailParent.value = null })
  onMounted(() => {
    window.addEventListener('keydown', onLightboxKeydown)
    window.addEventListener('keydown', onDetailKeydown)
  })
  onBeforeUnmount(() => {
    window.removeEventListener('keydown', onLightboxKeydown)
    window.removeEventListener('keydown', onDetailKeydown)
  })
  return { lightboxUrl, lightboxLong, openLightbox, closeLightbox, detailTweet, detailParent, detailSwap, detailStep, openDetail, closeDetail, drillIntoQuote, backToParent, playingMedia, playVideo }
}
