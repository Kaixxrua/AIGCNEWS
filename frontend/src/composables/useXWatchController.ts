import axios from 'axios'
import { ref } from 'vue'
import {
  createEmptyXWatchForm,
  createXWatchForm,
  removeXWatchAccount,
  replaceXWatchAccount,
  upsertXWatchAccount,
  type XWatchAccount,
  type XWatchAccountForm,
} from '@/features/monitor/monitorModel'
import { monitorApi, type MonitorApi } from '@/services/monitor/monitorApi'

export interface XWatchApi {
  fetchXWatchAccounts: MonitorApi['fetchXWatchAccounts']
  saveXWatchAccount: MonitorApi['saveXWatchAccount']
  deleteXWatchAccount: MonitorApi['deleteXWatchAccount']
  testXWatchAccount: MonitorApi['testXWatchAccount']
  ingestSource: MonitorApi['ingestSource']
}

export type XWatchTranslate = (key: string, params?: Record<string, unknown>) => string

export interface XWatchControllerOptions {
  api?: XWatchApi
  confirm?: (message: string) => boolean
  translate?: XWatchTranslate
}

const defaultApi: XWatchApi = monitorApi

// XWatchCard 自包含控制器：不走 useMonitorPageController，避免与监控页其它面板共享状态。
export const useXWatchController = (options: XWatchControllerOptions = {}) => {
  const api = options.api ?? defaultApi
  const confirmAction = options.confirm ?? ((message: string) => window.confirm(message))
  const translate = options.translate ?? ((key: string) => key)

  const accounts = ref<XWatchAccount[]>([])
  const form = ref<XWatchAccountForm>(createEmptyXWatchForm())
  const loading = ref(false)
  const saving = ref(false)
  const togglingId = ref<number | null>(null)
  const testingId = ref<number | null>(null)
  const deletingId = ref<number | null>(null)
  const ingesting = ref(false)
  const errorMsg = ref('')
  const noticeMsg = ref('')
  const isActive = ref(true)

  const errorText = (error: unknown, fallbackKey: string): string => {
    if (axios.isAxiosError(error)) {
      const detail = error.response?.data?.detail
      if (typeof detail === 'string' && detail) return detail
    }
    return error instanceof Error && error.message ? error.message : translate(fallbackKey)
  }

  const loadAccounts = async () => {
    if (!isActive.value) return
    loading.value = true
    errorMsg.value = ''
    try {
      accounts.value = await api.fetchXWatchAccounts()
    } catch (error) {
      if (isActive.value) errorMsg.value = errorText(error, 'monitor.xWatch.loadFailed')
    } finally {
      if (isActive.value) loading.value = false
    }
  }

  const resetForm = () => {
    form.value = createEmptyXWatchForm()
  }

  const editAccount = (account: XWatchAccount) => {
    form.value = createXWatchForm(account)
  }

  const saveAccount = async () => {
    if (saving.value) return
    errorMsg.value = ''
    noticeMsg.value = ''
    const screenName = form.value.screen_name.trim().replace(/^@+/, '')
    if (!screenName) {
      errorMsg.value = translate('monitor.xWatch.handleRequired')
      return
    }
    saving.value = true
    try {
      const saved = await api.saveXWatchAccount({ ...form.value, screen_name: screenName })
      if (!isActive.value) return
      accounts.value = upsertXWatchAccount(accounts.value, saved)
      noticeMsg.value = translate('monitor.xWatch.saved')
      resetForm()
    } catch (error) {
      if (isActive.value) errorMsg.value = errorText(error, 'monitor.xWatch.saveFailed')
    } finally {
      if (isActive.value) saving.value = false
    }
  }

  const toggleAccount = async (account: XWatchAccount) => {
    if (togglingId.value !== null) return
    errorMsg.value = ''
    noticeMsg.value = ''
    togglingId.value = account.id
    try {
      const saved = await api.saveXWatchAccount({ ...createXWatchForm(account), enabled: !account.enabled })
      if (!isActive.value) return
      accounts.value = replaceXWatchAccount(accounts.value, saved)
    } catch (error) {
      if (isActive.value) errorMsg.value = errorText(error, 'monitor.xWatch.saveFailed')
    } finally {
      if (isActive.value) togglingId.value = null
    }
  }

  const testAccount = async (account: XWatchAccount) => {
    if (testingId.value !== null) return
    errorMsg.value = ''
    noticeMsg.value = ''
    testingId.value = account.id
    try {
      const result = await api.testXWatchAccount(account.id)
      if (!isActive.value) return
      accounts.value = replaceXWatchAccount(accounts.value, result.account)
      noticeMsg.value = result.message || translate('monitor.xWatch.testDone')
    } catch (error) {
      if (isActive.value) errorMsg.value = errorText(error, 'monitor.xWatch.testFailed')
    } finally {
      if (isActive.value) testingId.value = null
    }
  }

  const ingestX = async () => {
    if (ingesting.value) return
    errorMsg.value = ''
    noticeMsg.value = ''
    ingesting.value = true
    try {
      const result = await api.ingestSource('x')
      if (!isActive.value) return
      noticeMsg.value = result.message || translate('monitor.xWatch.ingestSubmitted')
    } catch (error) {
      if (isActive.value) errorMsg.value = errorText(error, 'monitor.xWatch.ingestFailed')
    } finally {
      if (isActive.value) ingesting.value = false
    }
  }

  const removeAccount = async (account: XWatchAccount) => {
    if (deletingId.value !== null) return
    if (!confirmAction(translate('monitor.xWatch.deleteConfirm', { name: account.screen_name }))) return
    errorMsg.value = ''
    noticeMsg.value = ''
    deletingId.value = account.id
    try {
      const result = await api.deleteXWatchAccount(account.id)
      if (!isActive.value) return
      accounts.value = removeXWatchAccount(accounts.value, account.id)
      if (form.value.id === account.id) resetForm()
      noticeMsg.value = result.message || translate('monitor.xWatch.deleted')
    } catch (error) {
      if (isActive.value) errorMsg.value = errorText(error, 'monitor.xWatch.deleteFailed')
    } finally {
      if (isActive.value) deletingId.value = null
    }
  }

  const dispose = () => {
    isActive.value = false
    loading.value = false
    saving.value = false
    togglingId.value = null
    testingId.value = null
    deletingId.value = null
    ingesting.value = false
  }

  return {
    accounts,
    deletingId,
    dispose,
    editAccount,
    errorMsg,
    form,
    ingestX,
    ingesting,
    loadAccounts,
    loading,
    noticeMsg,
    removeAccount,
    resetForm,
    saveAccount,
    saving,
    testAccount,
    testingId,
    toggleAccount,
    togglingId,
  }
}

export type XWatchController = ReturnType<typeof useXWatchController>
