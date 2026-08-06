import { computed, onUnmounted, ref } from 'vue'
import type {
  WeChatCatalogAccount,
  WeChatFeedEntry,
} from '@/features/wechat/wechatModel'
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

  function toggleArticleExpanded(key: string) {
    const next = new Set(expandedArticleKeys.value)
    if (next.has(key)) {
      next.delete(key)
    } else {
      next.add(key)
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
    dispose,
    setError,
    clearError,
    loadCatalog,
    loadFeed,
    toggleFollow,
    articleKey,
    toggleArticleExpanded,
    isArticleExpanded,
    selectAccount,
    toggleFollowBoxCollapsed,
  }
}
