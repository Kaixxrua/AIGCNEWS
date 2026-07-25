import { ref, type ComputedRef, type Ref } from 'vue'
import { api } from '../services/http/apiClient'
import type { SourceKey } from '../features/monitor/monitorViewModel'

interface MonitorControllerOptions {
  isTaskRunning: ComputedRef<boolean>
  errorMsg: Ref<string>
  successMsg: Ref<string>
  clearMessages: () => void
  fetchTasks: () => Promise<void>
  refreshData: () => Promise<void>
}

export const useMonitorController = ({
  isTaskRunning,
  errorMsg,
  successMsg,
  clearMessages,
  fetchTasks,
  refreshData,
}: MonitorControllerOptions) => {
  const syncing = ref(false)
  const generatingBriefing = ref(false)
  const clearingCache = ref(false)
  const targetDate = ref<string>(new Date().toISOString().slice(0, 10))
  const maxTargetDate = new Date().toISOString().slice(0, 10)
  const ingestingByDate = ref(false)
  const ingestingSource = ref<SourceKey | null>(null)
  const clearing = ref(false)
  const showClearConfirm = ref(false)

  const ingestSingleSource = async (sourceKey: SourceKey) => {
    if (ingestingSource.value) return
    clearMessages()
    ingestingSource.value = sourceKey
    try {
      const res = await api.post('/ops/ingest-source', null, { params: { source: sourceKey, limit: 20 } })
      successMsg.value = res.data?.message || `「${sourceKey}」采集任务已提交，后台执行中…`
      setTimeout(fetchTasks, 1000); setTimeout(fetchTasks, 4000)
    } catch (e: any) {
      const status = e?.response?.status
      errorMsg.value = status === 409 ? '当前已有任务正在运行，请等待完成后再试。' : status === 400 ? e?.response?.data?.detail || '未知数据源' : e?.response?.data?.detail || String(e)
    } finally { ingestingSource.value = null }
  }

  const generateAllBriefings = async (forceRegenerate = true) => {
    if (generatingBriefing.value) return
    clearMessages()
    generatingBriefing.value = true
    try {
      const res = await api.post('/ops/briefing/generate-all', null, { params: { force_regenerate: forceRegenerate } })
      successMsg.value = res.data?.message || '全维度每日简报生成任务已提交，后台执行中…'
    } catch (e: any) {
      errorMsg.value = e?.response?.data?.detail || String(e)
    } finally { generatingBriefing.value = false }
  }

  const clearDashboardCache = async () => {
    if (clearingCache.value) return
    clearMessages()
    clearingCache.value = true
    try {
      const res = await api.post('/ops/cache/clear-dashboard')
      successMsg.value = res.data?.message || 'Dashboard 缓存已清除，刷新仪表盘即可看到最新数据。'
    } catch (e: any) {
      errorMsg.value = e?.response?.data?.detail || String(e)
    } finally { clearingCache.value = false }
  }

  const syncDataNow = async (force = false) => {
    if (syncing.value || isTaskRunning.value) return
    clearMessages()
    syncing.value = true
    try {
      await api.post('/ops/ingest', { limit: 20, force })
      successMsg.value = force ? '强制采集任务已提交，后台执行中…' : '智能同步任务已提交，后台执行中…'
      setTimeout(fetchTasks, 1000); setTimeout(fetchTasks, 3000)
    } catch (e: any) {
      const status = e?.response?.status
      errorMsg.value = status === 409 ? '当前已有任务正在运行，请等待完成后再试。' : e?.response?.data?.detail || String(e)
    } finally { syncing.value = false }
  }

  const ingestByDate = async () => {
    if (ingestingByDate.value) return
    if (!targetDate.value) { errorMsg.value = '请选择目标日期'; return }
    clearMessages()
    ingestingByDate.value = true
    try {
      const res = await api.post('/ops/ingest-by-date', { target_date: targetDate.value, limit: 30 })
      successMsg.value = res.data?.message || `已提交 ${targetDate.value} 的采集任务，后台执行中…`
      setTimeout(fetchTasks, 1000); setTimeout(fetchTasks, 4000)
    } catch (e: any) {
      const status = e?.response?.status
      errorMsg.value = status === 409 ? '当前已有任务正在运行，请等待完成后再试。' : status === 400 ? e?.response?.data?.detail || '日期格式错误' : e?.response?.data?.detail || String(e)
    } finally { ingestingByDate.value = false }
  }

  const clearAllData = async () => {
    showClearConfirm.value = false
    clearMessages()
    clearing.value = true
    try {
      const res = await api.post('/ops/clear-data')
      successMsg.value = res.data?.message || '数据已清空'
      await refreshData()
    } catch (e: any) { errorMsg.value = e?.response?.data?.detail || String(e) }
    finally { clearing.value = false }
  }

  return {
    syncing,
    generatingBriefing,
    clearingCache,
    targetDate,
    maxTargetDate,
    ingestingByDate,
    ingestingSource,
    clearing,
    showClearConfirm,
    ingestSingleSource,
    generateAllBriefings,
    clearDashboardCache,
    syncDataNow,
    ingestByDate,
    clearAllData,
  }
}
