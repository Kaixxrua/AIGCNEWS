import { computed, onUnmounted, ref, watch } from 'vue'
import type {
  WeChatArticle,
  WeChatArticleListResult,
  WeChatLoginAttempt,
  WeChatLoginStatus,
  WeChatOfficialAccount,
  WeChatSessionSummary,
} from '@/features/wechat/wechatModel'
import { isWeChatLoginExpired, isWeChatLoginTerminal } from '@/features/wechat/wechatModel'
import { wechatApi } from '@/services/wechat/wechatApi'
import type { WeChatApi } from '@/services/wechat/wechatApi'

const POLL_INTERVAL_MS = 2000

interface ApiErrorLike {
  response?: { data?: { message?: string } }
  message?: string
}

function getErrorMessage(err: unknown, fallback: string): string {
  const e = err as ApiErrorLike
  return e.response?.data?.message ?? e.message ?? fallback
}

export interface UseWechatControllerOptions {
  pollIntervalMs?: number
  api?: WeChatApi
}

export function useWechatController(options: UseWechatControllerOptions = {}) {
  const pollIntervalMs = options.pollIntervalMs ?? POLL_INTERVAL_MS
  const api = options.api ?? wechatApi

  const isActive = ref(true)
  const isLoading = ref(false)
  const error = ref('')
  const notice = ref('')

  const session = ref<WeChatSessionSummary | null>(null)
  const isLoginDialogOpen = ref(false)
  const loginAttempt = ref<WeChatLoginAttempt | null>(null)
  const qrCodeUrl = ref('')
  const isPolling = ref(false)

  const accounts = ref<WeChatOfficialAccount[]>([])
  const selectedAccount = ref<WeChatOfficialAccount | null>(null)
  const articles = ref<WeChatArticle[]>([])
  const articlesTotal = ref(0)
  const articlesOffset = ref(0)
  const articlesLimit = ref(20)

  const isSearching = ref(false)
  const searchQuery = ref('')
  const searchResults = ref<WeChatOfficialAccount[]>([])
  const searchBegin = ref(0)
  const searchSize = ref(5)
  const searchTotal = ref(0)

  const isSyncing = ref(false)

  let pollTimer: ReturnType<typeof setTimeout> | null = null
  let abortController: AbortController | null = null

  const hasSession = computed(() => session.value?.connected === true)

  function dispose() {
    isActive.value = false
    stopPolling()
    revokeQrCodeUrl()
    if (abortController) {
      abortController.abort()
      abortController = null
    }
  }

  function revokeQrCodeUrl() {
    if (qrCodeUrl.value) {
      URL.revokeObjectURL(qrCodeUrl.value)
      qrCodeUrl.value = ''
    }
  }

  function stopPolling() {
    if (pollTimer) {
      clearTimeout(pollTimer)
      pollTimer = null
    }
    isPolling.value = false
  }

  function setError(message: string) {
    error.value = message
  }

  function clearError() {
    error.value = ''
  }

  async function refreshSession() {
    if (!isActive.value) return
    try {
      session.value = await api.fetchSession()
    } catch {
      // Non-fatal; session remains null/disconnected.
      session.value = null
    }
  }

  async function loadAccounts() {
    if (!isActive.value) return
    isLoading.value = true
    clearError()
    try {
      accounts.value = await api.fetchAccounts()
    } catch (err) {
      setError(getErrorMessage(err, '加载公众号失败'))
    } finally {
      isLoading.value = false
    }
  }

  async function openLoginDialog() {
    isLoginDialogOpen.value = true
    clearError()
    await startLogin()
  }

  function closeLoginDialog() {
    isLoginDialogOpen.value = false
    stopPolling()
    revokeQrCodeUrl()
    if (loginAttempt.value?.attempt_id) {
      api.cancelLogin(loginAttempt.value.attempt_id).catch(() => {
        // Best-effort cleanup.
      })
    }
    loginAttempt.value = null
  }

  async function startLogin() {
    stopPolling()
    revokeQrCodeUrl()
    loginAttempt.value = null
    clearError()
    try {
      loginAttempt.value = await api.createLoginSession()
      await loadQrCode(loginAttempt.value.attempt_id)
      startPolling()
    } catch (err) {
      setError(getErrorMessage(err, '启动登录失败'))
    }
  }

  async function loadQrCode(attemptId: string) {
    revokeQrCodeUrl()
    try {
      const blob = await api.fetchQrCodeBlob(attemptId)
      qrCodeUrl.value = URL.createObjectURL(blob)
    } catch (err) {
      setError(getErrorMessage(err, '获取二维码失败'))
    }
  }

  function startPolling() {
    stopPolling()
    isPolling.value = true
    pollOnce()
  }

  async function pollOnce() {
    if (!isActive.value || !isPolling.value || !loginAttempt.value) return
    const attemptId = loginAttempt.value.attempt_id

    try {
      const status = await api.fetchLoginStatus(attemptId)
      loginAttempt.value = status

      if (isWeChatLoginTerminal(status.status)) {
        stopPolling()
        revokeQrCodeUrl()
        if (status.status === 'completed') {
          await refreshSession()
          await loadAccounts()
          isLoginDialogOpen.value = false
        }
        return
      }

      if (isWeChatLoginExpired(status.status)) {
        stopPolling()
        revokeQrCodeUrl()
        return
      }

      pollTimer = setTimeout(pollOnce, pollIntervalMs)
    } catch (err) {
      stopPolling()
      setError(getErrorMessage(err, '轮询登录状态失败'))
    }
  }

  async function confirmLogin() {
    if (!loginAttempt.value) return
    clearError()
    try {
      const summary = await api.completeLogin(loginAttempt.value.attempt_id)
      session.value = summary
      loginAttempt.value = { ...loginAttempt.value, status: 'completed' as WeChatLoginStatus }
      stopPolling()
      revokeQrCodeUrl()
      isLoginDialogOpen.value = false
      await loadAccounts()
    } catch (err) {
      setError(getErrorMessage(err, '确认登录失败'))
    }
  }

  async function searchAccounts(query: string) {
    searchQuery.value = query
    searchBegin.value = 0
    await doSearch()
  }

  async function doSearch() {
    if (!searchQuery.value.trim()) {
      searchResults.value = []
      searchTotal.value = 0
      return
    }
    isSearching.value = true
    clearError()
    try {
      const result = await api.searchAccounts(
        searchQuery.value,
        searchBegin.value,
        searchSize.value,
      )
      searchResults.value = result.items
      searchTotal.value = result.total
    } catch (err) {
      setError(getErrorMessage(err, '搜索公众号失败'))
    } finally {
      isSearching.value = false
    }
  }

  function selectAccount(account: WeChatOfficialAccount) {
    selectedAccount.value = account
    articles.value = []
    articlesTotal.value = 0
    articlesOffset.value = 0
  }

  async function loadArticles(accountId?: number, offset = 0) {
    const targetId = accountId ?? selectedAccount.value?.id
    if (!targetId) return
    isLoading.value = true
    clearError()
    try {
      const result: WeChatArticleListResult = await api.fetchArticles(targetId, offset, articlesLimit.value)
      articles.value = result.items
      articlesTotal.value = result.total
      articlesOffset.value = result.offset
    } catch (err) {
      setError(getErrorMessage(err, '加载文章失败'))
    } finally {
      isLoading.value = false
    }
  }

  async function submitSync() {
    if (!selectedAccount.value?.id) return
    isSyncing.value = true
    clearError()
    try {
      await api.submitSync(selectedAccount.value.id)
      notice.value = '同步任务已提交'
    } catch (err) {
      setError(getErrorMessage(err, '提交同步失败'))
    } finally {
      isSyncing.value = false
    }
  }

  async function saveAccount(account: WeChatOfficialAccount) {
    clearError()
    try {
      const saved = await api.saveAccount({
        fakeid: account.fakeid,
        nickname: account.nickname,
        alias: account.alias,
        avatar_url: account.avatar_url,
        signature: account.signature,
        enabled: true,
        sort_order: 0,
      })
      accounts.value = [saved, ...accounts.value]
      selectedAccount.value = saved
    } catch (err) {
      setError(getErrorMessage(err, '保存公众号失败'))
    }
  }

  function clearSearch() {
    searchQuery.value = ''
    searchResults.value = []
    searchTotal.value = 0
    searchBegin.value = 0
  }

  watch(isLoginDialogOpen, (open) => {
    if (!open) {
      stopPolling()
      revokeQrCodeUrl()
    }
  })

  onUnmounted(dispose)

  return {
    isActive,
    isLoading,
    error,
    notice,
    session,
    hasSession,
    isLoginDialogOpen,
    loginAttempt,
    qrCodeUrl,
    isPolling,
    accounts,
    selectedAccount,
    articles,
    articlesTotal,
    articlesOffset,
    articlesLimit,
    isSearching,
    searchQuery,
    searchResults,
    searchBegin,
    searchSize,
    searchTotal,
    isSyncing,
    dispose,
    refreshSession,
    loadAccounts,
    openLoginDialog,
    closeLoginDialog,
    startLogin,
    confirmLogin,
    searchAccounts,
    doSearch,
    selectAccount,
    loadArticles,
    submitSync,
    saveAccount,
    clearSearch,
    clearError,
    setError,
  }
}
