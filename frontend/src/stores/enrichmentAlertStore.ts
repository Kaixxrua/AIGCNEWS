import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { monitorApi } from '@/services/monitor/monitorApi'
import { useAuthStore } from '@/stores/authStore'

const POLL_INTERVAL_MS = 5 * 60 * 1000

/**
 * GitHub 项目库富化失败的全局告警：admin 登录后每 5 分钟轮询一次富化状态，
 * 失败数 > 0 时导航 Dock 的「监控」按钮显示小红点。
 */
export const useEnrichmentAlertStore = defineStore('enrichmentAlert', () => {
  const authStore = useAuthStore()
  const failedCount = ref(0)
  const hasFailures = computed(() => failedCount.value > 0)

  let timer: ReturnType<typeof setInterval> | null = null

  const refresh = async () => {
    if (!authStore.isAdmin) {
      failedCount.value = 0
      return
    }
    try {
      const status = await monitorApi.fetchGithubEnrichmentStatus()
      failedCount.value = Math.max(0, Number(status?.failed) || 0)
    } catch (error) {
      // 轮询场景容忍瞬态故障（容器重启、网关 503），保留上次计数
      console.error('Failed to fetch GitHub enrichment alert status', error)
    }
  }

  const start = () => {
    if (timer) return
    void refresh()
    timer = setInterval(() => { void refresh() }, POLL_INTERVAL_MS)
  }

  const stop = () => {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
    failedCount.value = 0
  }

  watch(() => authStore.isAdmin, (isAdmin) => (isAdmin ? start() : stop()), { immediate: true })

  return { failedCount, hasFailures, refresh }
})
