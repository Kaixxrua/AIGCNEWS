import axios from 'axios'
import { ref } from 'vue'
import {
  DEFAULT_MCP_USAGE_DAYS,
  type McpDailyUsageResponse,
  type McpUsageDays,
} from '@/features/monitor/mcpUsageViewModel'
import { monitorApi, type MonitorApi } from '@/services/monitor/monitorApi'

export interface McpUsageApi {
  fetchMcpDailyUsage: MonitorApi['fetchMcpDailyUsage']
}

export type McpUsageTranslate = (key: string) => string

export interface McpUsageControllerOptions {
  api?: McpUsageApi
  translate?: McpUsageTranslate
}

const defaultApi: McpUsageApi = monitorApi

// MCP 每日用量面板自包含控制器（同 useVisitStatsController）：状态留在卡片内部。
export const useMcpUsageController = (options: McpUsageControllerOptions = {}) => {
  const api = options.api ?? defaultApi
  const translate = options.translate ?? ((key: string) => key)

  const days = ref<McpUsageDays>(DEFAULT_MCP_USAGE_DAYS)
  const data = ref<McpDailyUsageResponse | null>(null)
  const loading = ref(false)
  const errorMsg = ref('')
  const isActive = ref(true)
  // 竞态守卫：快速切换时间范围时，只允许最后一次请求回写
  let requestSeq = 0

  const errorText = (error: unknown): string => {
    if (axios.isAxiosError(error)) {
      const detail = error.response?.data?.detail
      if (typeof detail === 'string' && detail) return detail
    }
    return error instanceof Error && error.message ? error.message : translate('mcpUsage.loadFailed')
  }

  const load = async () => {
    if (!isActive.value) return
    const seq = ++requestSeq
    loading.value = true
    errorMsg.value = ''
    try {
      const result = await api.fetchMcpDailyUsage(days.value)
      if (!isActive.value || seq !== requestSeq) return
      data.value = result
    } catch (error) {
      if (isActive.value && seq === requestSeq) errorMsg.value = errorText(error)
    } finally {
      if (isActive.value && seq === requestSeq) loading.value = false
    }
  }

  const setDays = (value: McpUsageDays) => {
    if (value === days.value) return
    days.value = value
    void load()
  }

  const dispose = () => {
    isActive.value = false
    loading.value = false
  }

  return { data, days, dispose, errorMsg, load, loading, setDays }
}

export type McpUsageController = ReturnType<typeof useMcpUsageController>
