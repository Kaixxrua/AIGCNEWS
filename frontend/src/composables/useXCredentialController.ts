import axios from 'axios'
import { ref } from 'vue'
import {
  createEmptyXCredentialForm,
  createXCredentialForm,
  removeXCredential,
  replaceXCredential,
  upsertXCredential,
  type XCredential,
  type XCredentialForm,
} from '@/features/monitor/monitorModel'
import { monitorApi, type MonitorApi } from '@/services/monitor/monitorApi'

export interface XCredentialApi {
  fetchXCredentials: MonitorApi['fetchXCredentials']
  saveXCredential: MonitorApi['saveXCredential']
  deleteXCredential: MonitorApi['deleteXCredential']
  testXCredential: MonitorApi['testXCredential']
}

export type XCredentialTranslate = (key: string, params?: Record<string, unknown>) => string

export interface XCredentialControllerOptions {
  api?: XCredentialApi
  confirm?: (message: string) => boolean
  translate?: XCredentialTranslate
}

const defaultApi: XCredentialApi = monitorApi

// The credential panel owns its request state so MonitorView only needs to mount it for admins.
export const useXCredentialController = (options: XCredentialControllerOptions = {}) => {
  const api = options.api ?? defaultApi
  const confirmAction = options.confirm ?? ((message: string) => window.confirm(message))
  const translate = options.translate ?? ((key: string) => key)

  const credentials = ref<XCredential[]>([])
  const form = ref<XCredentialForm>(createEmptyXCredentialForm())
  const loading = ref(false)
  const saving = ref(false)
  const togglingId = ref<number | null>(null)
  const testingId = ref<number | null>(null)
  const deletingId = ref<number | null>(null)
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

  const loadCredentials = async () => {
    if (!isActive.value) return
    loading.value = true
    errorMsg.value = ''
    try {
      credentials.value = await api.fetchXCredentials()
    } catch (error) {
      if (isActive.value) errorMsg.value = errorText(error, 'monitor.xCredentials.loadFailed')
    } finally {
      if (isActive.value) loading.value = false
    }
  }

  const resetForm = () => {
    form.value = createEmptyXCredentialForm()
  }

  const editCredential = (credential: XCredential) => {
    form.value = createXCredentialForm(credential)
  }

  const saveCredential = async () => {
    if (saving.value) return
    errorMsg.value = ''
    noticeMsg.value = ''
    const draft = {
      ...form.value,
      display_name: form.value.display_name.trim(),
      note: form.value.note.trim(),
      auth_token: form.value.auth_token.trim(),
      ct0: form.value.ct0.trim(),
    }
    if (!draft.id && !draft.auth_token) {
      errorMsg.value = translate('monitor.xCredentials.authTokenRequired')
      return
    }
    if (!draft.id && !draft.ct0) {
      errorMsg.value = translate('monitor.xCredentials.ct0Required')
      return
    }
    saving.value = true
    try {
      const saved = await api.saveXCredential(draft)
      if (!isActive.value) return
      credentials.value = upsertXCredential(credentials.value, saved)
      noticeMsg.value = translate('monitor.xCredentials.saved')
      resetForm()
    } catch (error) {
      if (isActive.value) errorMsg.value = errorText(error, 'monitor.xCredentials.saveFailed')
    } finally {
      if (isActive.value) saving.value = false
    }
  }

  const toggleCredential = async (credential: XCredential) => {
    if (togglingId.value !== null) return
    errorMsg.value = ''
    noticeMsg.value = ''
    togglingId.value = credential.id
    try {
      const saved = await api.saveXCredential({
        ...createXCredentialForm(credential),
        enabled: !credential.enabled,
      })
      if (!isActive.value) return
      credentials.value = replaceXCredential(credentials.value, saved)
    } catch (error) {
      if (isActive.value) errorMsg.value = errorText(error, 'monitor.xCredentials.saveFailed')
    } finally {
      if (isActive.value) togglingId.value = null
    }
  }

  const testCredential = async (credential: XCredential) => {
    if (testingId.value !== null) return
    errorMsg.value = ''
    noticeMsg.value = ''
    testingId.value = credential.id
    try {
      const result = await api.testXCredential(credential.id)
      if (!isActive.value) return
      credentials.value = replaceXCredential(credentials.value, result.credential)
      noticeMsg.value = result.message || translate('monitor.xCredentials.testDone')
    } catch (error) {
      if (isActive.value) errorMsg.value = errorText(error, 'monitor.xCredentials.testFailed')
    } finally {
      if (isActive.value) testingId.value = null
    }
  }

  const removeCredential = async (credential: XCredential) => {
    if (deletingId.value !== null) return
    if (!confirmAction(translate('monitor.xCredentials.deleteConfirm', { name: credential.display_name || credential.id }))) return
    errorMsg.value = ''
    noticeMsg.value = ''
    deletingId.value = credential.id
    try {
      const result = await api.deleteXCredential(credential.id)
      if (!isActive.value) return
      credentials.value = removeXCredential(credentials.value, credential.id)
      if (form.value.id === credential.id) resetForm()
      noticeMsg.value = result.message || translate('monitor.xCredentials.deleted')
    } catch (error) {
      if (isActive.value) errorMsg.value = errorText(error, 'monitor.xCredentials.deleteFailed')
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
  }

  return {
    credentials,
    deletingId,
    dispose,
    editCredential,
    errorMsg,
    form,
    loadCredentials,
    loading,
    noticeMsg,
    removeCredential,
    resetForm,
    saveCredential,
    saving,
    testCredential,
    testingId,
    toggleCredential,
    togglingId,
  }
}

export type XCredentialController = ReturnType<typeof useXCredentialController>
