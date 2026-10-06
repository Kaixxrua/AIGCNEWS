import { computed, onScopeDispose, ref } from 'vue'
import { isAxiosError } from 'axios'
import { trackingApi } from '@/services/tracking/trackingApi'
import type {
  TrackingExportFile,
  TrackingExportFormat,
  TrackingOverview,
  TrackingPreview,
  TrackingRule,
  TrackingRuleInput,
  TrackingSettings,
} from '@/features/tracking/trackingModel'
import { ruleInput } from '@/features/tracking/trackingModel'

// 用临时链接触发浏览器下载；地址稍后再回收，有的浏览器点击之后才开始读取
function saveFile({ blob, filename }: TrackingExportFile) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.append(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

export function usePersonalTracking() {
  const data = ref<TrackingOverview | null>(null)
  const loading = ref(false)
  const busy = ref(false)
  const error = ref('')
  const notice = ref('')
  const preview = ref<TrackingPreview | null>(null)
  const previewTitle = ref('')
  const exporting = ref<TrackingExportFormat | ''>('')
  const exportError = ref('')
  let revision = 0
  // 换账号时加一：上一个账号还没下完的导出不再保存
  let account = 0
  let alive = true
  onScopeDispose(() => {
    alive = false
    revision++
  })

  const atLimit = computed(() => !!data.value && data.value.rules.length >= data.value.limit)
  function failure(cause: unknown) {
    const detail = isAxiosError(cause) ? cause.response?.data?.detail : ''
    const known = [
      'rule_limit',
      'rule_not_found',
      'rule_inactive',
      'channel_unavailable',
      'tracking_unavailable',
      'membership_required',
    ]
    return typeof detail === 'string' && known.includes(detail) ? detail : 'request_failed'
  }
  async function load(reset = false) {
    const request = ++revision
    if (reset) {
      data.value = null
      preview.value = null
      notice.value = ''
      busy.value = false
      account++
      exporting.value = ''
      exportError.value = ''
    }
    loading.value = true
    error.value = ''
    try {
      const result = await trackingApi.load()
      if (alive && request === revision) data.value = result
    } catch (cause) {
      if (alive && request === revision) error.value = failure(cause)
    } finally {
      if (alive && request === revision) loading.value = false
    }
  }
  async function mutate(operation: () => Promise<TrackingOverview>) {
    if (busy.value || loading.value) return false
    const request = revision
    busy.value = true
    error.value = ''
    notice.value = ''
    try {
      const result = await operation()
      if (!alive || request !== revision) return false
      data.value = result
      preview.value = null
      notice.value = 'saved'
      return true
    } catch (cause) {
      if (alive && request === revision) error.value = failure(cause)
      return false
    } finally {
      if (alive && request === revision) busy.value = false
    }
  }
  async function showPreview(rule: TrackingRule) {
    if (busy.value || loading.value) return
    const request = revision
    busy.value = true
    error.value = ''
    preview.value = null
    try {
      const result = await trackingApi.preview(rule.id)
      if (alive && request === revision) {
        preview.value = result
        previewTitle.value = rule.query
      }
    } catch (cause) {
      if (alive && request === revision) error.value = failure(cause)
    } finally {
      if (alive && request === revision) busy.value = false
    }
  }
  async function exportHistory(format: TrackingExportFormat) {
    if (exporting.value) return
    const request = account
    exporting.value = format
    exportError.value = ''
    try {
      const file = await trackingApi.exportHistory(format)
      if (alive && request === account) saveFile(file)
    } catch (cause) {
      const reason = failure(cause)
      // 通用的「保存或加载失败」说的是规则填写，导出失败单独提示
      if (alive && request === account) exportError.value = reason === 'request_failed' ? 'export_failed' : reason
    } finally {
      if (alive && request === account) exporting.value = ''
    }
  }
  return {
    data,
    loading,
    busy,
    error,
    notice,
    preview,
    previewTitle,
    exporting,
    exportError,
    atLimit,
    load,
    showPreview,
    exportHistory,
    saveRule: (input: TrackingRuleInput, id?: number) => mutate(() => trackingApi.saveRule(input, id)),
    remove: (id: number) => mutate(() => trackingApi.deleteRule(id)),
    toggle: (row: TrackingRule) =>
      mutate(() => trackingApi.saveRule({ ...ruleInput(row), enabled: !row.enabled }, row.id)),
    saveSettings: (settings: TrackingSettings) => mutate(() => trackingApi.settings(settings)),
  }
}
