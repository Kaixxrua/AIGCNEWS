import axios from 'axios'
import { ref } from 'vue'
import type { RevenueStatsResponse } from '@/features/monitor/monitorModel'
import { monitorApi, type MonitorApi } from '@/services/monitor/monitorApi'

export interface RevenueStatsApi {
  fetchRevenueStats: MonitorApi['fetchRevenueStats']
}

export type RevenueStatsTranslate = (key: string) => string

export interface RevenueStatsControllerOptions {
  api?: RevenueStatsApi
  translate?: RevenueStatsTranslate
}

export const useRevenueStatsController = (options: RevenueStatsControllerOptions = {}) => {
  const api = options.api ?? monitorApi
  const translate = options.translate ?? ((key: string) => key)
  const data = ref<RevenueStatsResponse | null>(null)
  const loading = ref(false)
  const errorMsg = ref('')
  const isActive = ref(true)

  const errorText = (error: unknown): string => {
    if (axios.isAxiosError(error)) {
      const detail = error.response?.data?.detail
      if (typeof detail === 'string' && detail) return detail
    }
    return error instanceof Error && error.message
      ? error.message
      : translate('monitor.revenue.loadFailed')
  }

  const load = async () => {
    if (!isActive.value) return
    loading.value = true
    errorMsg.value = ''
    try {
      const result = await api.fetchRevenueStats()
      if (isActive.value) data.value = result
    } catch (error) {
      if (isActive.value) errorMsg.value = errorText(error)
    } finally {
      if (isActive.value) loading.value = false
    }
  }

  const dispose = () => {
    isActive.value = false
    loading.value = false
  }

  return { data, dispose, errorMsg, load, loading }
}

export type RevenueStatsController = ReturnType<typeof useRevenueStatsController>
