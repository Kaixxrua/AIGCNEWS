import axios from 'axios'
import { ref } from 'vue'
import {
  DEFAULT_VISIT_STATS_WINDOW,
  type VisitPlatformStatsResponse,
  type VisitStatsWindow,
} from '@/features/monitor/visitStatsViewModel'
import { monitorApi, type MonitorApi } from '@/services/monitor/monitorApi'

export interface VisitStatsApi {
  fetchVisitPlatformStats: MonitorApi['fetchVisitPlatformStats']
}

export type VisitStatsTranslate = (key: string) => string

export interface VisitStatsControllerOptions {
  api?: VisitStatsApi
  translate?: VisitStatsTranslate
}

const defaultApi: VisitStatsApi = monitorApi

// 访问统计面板自包含控制器：不走 useMonitorPageController，避免与监控页其它面板共享状态。
export const useVisitStatsController = (options: VisitStatsControllerOptions = {}) => {
  const api = options.api ?? defaultApi
  const translate = options.translate ?? ((key: string) => key)

  const window_ = ref<VisitStatsWindow>(DEFAULT_VISIT_STATS_WINDOW)
  const data = ref<VisitPlatformStatsResponse | null>(null)
  const loading = ref(false)
  const errorMsg = ref('')
  const isActive = ref(true)
  // 竞态守卫：快速连点窗口 tab 时，只允许最后一次请求回写
  let requestSeq = 0

  const errorText = (error: unknown): string => {
    if (axios.isAxiosError(error)) {
      const detail = error.response?.data?.detail
      if (typeof detail === 'string' && detail) return detail
    }
    return error instanceof Error && error.message ? error.message : translate('monitor.visitStats.loadFailed')
  }

  const load = async () => {
    if (!isActive.value) return
    const seq = ++requestSeq
    loading.value = true
    errorMsg.value = ''
    try {
      const result = await api.fetchVisitPlatformStats(window_.value)
      if (!isActive.value || seq !== requestSeq) return
      data.value = result
    } catch (error) {
      if (isActive.value && seq === requestSeq) errorMsg.value = errorText(error)
    } finally {
      if (isActive.value && seq === requestSeq) loading.value = false
    }
  }

  const setWindow = (value: VisitStatsWindow) => {
    if (value === window_.value) return
    window_.value = value
    void load()
  }

  const dispose = () => {
    isActive.value = false
    loading.value = false
  }

  return { data, dispose, errorMsg, load, loading, setWindow, window: window_ }
}

export type VisitStatsController = ReturnType<typeof useVisitStatsController>
