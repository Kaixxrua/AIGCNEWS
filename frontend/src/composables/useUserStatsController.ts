import axios from 'axios'
import { ref } from 'vue'
import type { UserStatsResponse } from '@/features/monitor/monitorViewModel'
import { monitorApi, type MonitorApi } from '@/services/monitor/monitorApi'

export interface UserStatsApi {
  fetchUserStats: MonitorApi['fetchUserStats']
}

export type UserStatsTranslate = (key: string) => string

export interface UserStatsControllerOptions {
  api?: UserStatsApi
  translate?: UserStatsTranslate
}

const defaultApi: UserStatsApi = monitorApi

// 自包含面板控制器（XWatchCard 模式）：状态留在卡片内，MonitorView 只负责挂载
export const useUserStatsController = (options: UserStatsControllerOptions = {}) => {
  const api = options.api ?? defaultApi
  const translate = options.translate ?? ((key: string) => key)

  const data = ref<UserStatsResponse | null>(null)
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
      : translate('monitor.userStats.loadFailed')
  }

  const load = async () => {
    if (!isActive.value) return
    loading.value = true
    errorMsg.value = ''
    try {
      const result = await api.fetchUserStats()
      if (!isActive.value) return
      data.value = result
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

export type UserStatsController = ReturnType<typeof useUserStatsController>
