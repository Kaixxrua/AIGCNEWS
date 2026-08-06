import { computed, onUnmounted, ref } from 'vue'
import type {
  WeChatArticle,
  WeChatArticleDetail,
  WeChatCatalogAccount,
  WeChatFeedEntry,
} from '@/features/wechat/wechatModel'
import { sanitizeWechatArticleHtml } from '@/features/wechat/wechatArticleHtml'
import { wechatFollowApi } from '@/services/wechat/wechatFollowApi'
import type { WeChatFollowApi } from '@/services/wechat/wechatFollowApi'

const FOLLOW_BOX_COLLAPSED_KEY = 'wechat:followBoxCollapsed'

interface ApiErrorLike {
  response?: {
    data?: {
      message?: string
      detail?: { message?: string; code?: string } | string
    }
  }
  message?: string
}

function getErrorMessage(err: unknown, fallback: string): string {
  const e = err as ApiErrorLike
  const data = e.response?.data
  const detail = data?.detail
  const detailMessage = typeof detail === 'string' ? detail : detail?.message
  return data?.message ?? detailMessage ?? e.message ?? fallback
}

function readCollapsedPreference(): boolean {
  try {
    // 默认收起；只有用户显式展开过（存 '0'）才保持展开。
    return window.localStorage.getItem(FOLLOW_BOX_COLLAPSED_KEY) !== '0'
  } catch {
    return true
  }
}

function persistCollapsedPreference(collapsed: boolean): void {
  try {
    window.localStorage.setItem(FOLLOW_BOX_COLLAPSED_KEY, collapsed ? '1' : '0')
  } catch {
    // localStorage unavailable (private mode); keep in-memory state only.
  }
}

export interface UseWechatFollowControllerOptions {
  api?: WeChatFollowApi
}

export function useWechatFollowController(options: UseWechatFollowControllerOptions = {}) {
  const api = options.api ?? wechatFollowApi

  const isActive = ref(true)
  const error = ref('')

  const catalog = ref<WeChatCatalogAccount[]>([])
  const isCatalogLoading = ref(false)

  const feed = ref<WeChatFeedEntry[]>([])
  const isFeedLoading = ref(false)

  const pendingFollowIds = ref<Set<number>>(new Set())
  const expandedArticleKeys = ref<Set<string>>(new Set())
  const selectedAccountId = ref<number | null>(null)
  const followBoxCollapsed = ref(readCollapsedPreference())

  // 全文详情：按 articleKey 懒加载并缓存（正文已清洗，可直接 v-html）
  const articleDetails = ref<Map<string, WeChatArticleDetail>>(new Map())
  const articleDetailLoading = ref<Set<string>>(new Set())
  const articleDetailErrors = ref<Map<string, string>>(new Map())

  const followedAccounts = computed(() =>
    catalog.value.filter((account) => account.followed),
  )

  const visibleFeed = computed(() => {
    if (selectedAccountId.value === null) return feed.value
    return feed.value.filter((entry) => entry.account.id === selectedAccountId.value)
  })

  function dispose() {
    isActive.value = false
  }

  function setError(message: string) {
    error.value = message
  }

  function clearError() {
    error.value = ''
  }

  async function loadCatalog() {
    if (!isActive.value) return
    isCatalogLoading.value = true
    clearError()
    try {
      catalog.value = await api.fetchCatalog()
    } catch (err) {
      setError(getErrorMessage(err, '加载公众号目录失败'))
    } finally {
      isCatalogLoading.value = false
    }
  }

  async function loadFeed() {
    if (!isActive.value) return
    isFeedLoading.value = true
    try {
      const result = await api.fetchFeed()
      feed.value = result.items
    } catch (err) {
      setError(getErrorMessage(err, '加载公众号消息失败'))
    } finally {
      isFeedLoading.value = false
    }
  }

  async function toggleFollow(account: WeChatCatalogAccount) {
    if (pendingFollowIds.value.has(account.id)) return
    const previous = account.followed
    const nextPending = new Set(pendingFollowIds.value)
    nextPending.add(account.id)
    pendingFollowIds.value = nextPending

    // 乐观切换：先更新本地标志，失败时回滚。
    account.followed = !previous
    clearError()
    try {
      if (previous) {
        await api.unfollowAccount(account.id)
        feed.value = feed.value.filter((entry) => entry.account.id !== account.id)
        if (selectedAccountId.value === account.id) {
          selectedAccountId.value = null
        }
      } else {
        await api.followAccount(account.id)
        await loadFeed()
      }
    } catch (err) {
      account.followed = previous
      setError(getErrorMessage(err, previous ? '取消关注失败' : '关注失败'))
    } finally {
      const settled = new Set(pendingFollowIds.value)
      settled.delete(account.id)
      pendingFollowIds.value = settled
    }
  }

  function articleKey(accountId: number, articleId: number | null, stableKey: string): string {
    return `${accountId}:${articleId ?? stableKey}`
  }

  async function ensureArticleDetail(key: string, accountId: number, article: WeChatArticle) {
    // 无正文（旧数据待回填）或已在缓存/加载中/失败态时不发起请求；
    // 失败态只能经 retryArticleDetail 清错后重试，避免收起再展开反复打失败请求。
    if (!article.has_content || article.id === null) return
    if (
      articleDetails.value.has(key) ||
      articleDetailLoading.value.has(key) ||
      articleDetailErrors.value.has(key)
    ) {
      return
    }

    const nextLoading = new Set(articleDetailLoading.value)
    nextLoading.add(key)
    articleDetailLoading.value = nextLoading
    try {
      const detail = await api.fetchArticleDetail(accountId, article.id)
      detail.content_html = sanitizeWechatArticleHtml(detail.content_html)
      const next = new Map(articleDetails.value)
      next.set(key, detail)
      articleDetails.value = next
      const cleared = new Map(articleDetailErrors.value)
      cleared.delete(key)
      articleDetailErrors.value = cleared
    } catch (err) {
      const next = new Map(articleDetailErrors.value)
      next.set(key, getErrorMessage(err, '加载全文失败'))
      articleDetailErrors.value = next
    } finally {
      const settled = new Set(articleDetailLoading.value)
      settled.delete(key)
      articleDetailLoading.value = settled
    }
  }

  function retryArticleDetail(key: string, accountId: number, article: WeChatArticle) {
    const cleared = new Map(articleDetailErrors.value)
    cleared.delete(key)
    articleDetailErrors.value = cleared
    void ensureArticleDetail(key, accountId, article)
  }

  function toggleArticleExpanded(key: string, accountId?: number, article?: WeChatArticle) {
    const next = new Set(expandedArticleKeys.value)
    if (next.has(key)) {
      next.delete(key)
    } else {
      next.add(key)
      if (accountId !== undefined && article) {
        void ensureArticleDetail(key, accountId, article)
      }
    }
    expandedArticleKeys.value = next
  }

  function isArticleExpanded(key: string): boolean {
    return expandedArticleKeys.value.has(key)
  }

  function selectAccount(accountId: number | null) {
    selectedAccountId.value =
      selectedAccountId.value === accountId ? null : accountId
  }

  function toggleFollowBoxCollapsed() {
    followBoxCollapsed.value = !followBoxCollapsed.value
    persistCollapsedPreference(followBoxCollapsed.value)
  }

  onUnmounted(dispose)

  return {
    error,
    catalog,
    isCatalogLoading,
    feed,
    isFeedLoading,
    pendingFollowIds,
    expandedArticleKeys,
    selectedAccountId,
    followBoxCollapsed,
    followedAccounts,
    visibleFeed,
    articleDetails,
    articleDetailLoading,
    articleDetailErrors,
    dispose,
    setError,
    clearError,
    loadCatalog,
    loadFeed,
    toggleFollow,
    articleKey,
    ensureArticleDetail,
    retryArticleDetail,
    toggleArticleExpanded,
    isArticleExpanded,
    selectAccount,
    toggleFollowBoxCollapsed,
  }
}
