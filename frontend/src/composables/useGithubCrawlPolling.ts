import { ref, type ComputedRef } from 'vue'
import { i18n } from '@/i18n'
import type { MonitorApi } from '@/services/monitor/monitorApi'
import type { GithubCrawlStatus } from '@/features/monitor/monitorModel'

export const CRAWL_POLL_INTERVAL = 3000
// 200 × 3s ≈ 10 分钟兜底：长时间非终态（如后端任务记录丢失）自动断链，避免无限轮询
export const CRAWL_POLL_MAX = 200

const isCrawlTerminal = (status: string) => status === 'success' || status === 'failed'

interface UseGithubCrawlPollingOptions {
  api: MonitorApi
  isAdmin: ComputedRef<boolean>
  schedule: (callback: () => void, delay: number) => ReturnType<typeof setTimeout>
  setSuccess: (message: string) => void
  setError: (message: string) => void
  refreshTasks: () => Promise<void>
}

export const useGithubCrawlPolling = ({
  api,
  isAdmin,
  schedule,
  setSuccess,
  setError,
  refreshTasks,
}: UseGithubCrawlPollingOptions) => {
  const crawlPolling = ref(false)
  const crawlStatus = ref<GithubCrawlStatus | null>(null)
  const activeCrawlRun = ref<{ channel: string; first_seen_after: string } | null>(null)
  let pollTimer: ReturnType<typeof setTimeout> | null = null
  let pollCount = 0

  const clearPollTimer = () => {
    if (pollTimer) {
      clearTimeout(pollTimer)
      pollTimer = null
    }
  }

  const stopCrawlPolling = () => {
    clearPollTimer()
    crawlPolling.value = false
  }

  // 卸载/离页兜底：停表断链并丢弃在途回调，不触碰服务端任务
  const disposeCrawlPolling = () => {
    stopCrawlPolling()
    activeCrawlRun.value = null
  }

  const pollGithubCrawlStatus = async () => {
    if (!crawlPolling.value) return
    pollCount += 1
    try {
      const status = await api.fetchGithubCrawlStatus(activeCrawlRun.value || undefined)
      // 在途期间被 dispose/终态停链：直接丢弃本次结果
      if (!crawlPolling.value) return
      crawlStatus.value = status
      if (isCrawlTerminal(status.task_status)) {
        stopCrawlPolling()
        activeCrawlRun.value = null
        if (status.task_status === 'success') setSuccess(i18n.global.t('monitor.crawl.runFinished'))
        else setError(i18n.global.t('monitor.crawl.runFailed', { error: status.error_msg || '' }))
        await refreshTasks()
        return
      }
    } catch (error) {
      // 轮询错误容忍：容器重启等瞬态故障不断链
      console.error('Failed to poll GitHub crawl status', error)
    }
    if (!crawlPolling.value) return
    if (pollCount >= CRAWL_POLL_MAX) {
      stopCrawlPolling()
      activeCrawlRun.value = null
      setError(i18n.global.t('monitor.crawl.pollTimeout'))
      return
    }
    pollTimer = schedule(() => { void pollGithubCrawlStatus() }, CRAWL_POLL_INTERVAL)
  }

  const beginCrawlPolling = (run: { channel: string; first_seen_after: string }) => {
    // 重入保护：先停掉上一轮链条，避免双链并行
    stopCrawlPolling()
    pollCount = 0
    activeCrawlRun.value = run
    crawlPolling.value = true
    pollTimer = schedule(() => { void pollGithubCrawlStatus() }, CRAWL_POLL_INTERVAL)
  }

  const resumeGithubCrawlPolling = async () => {
    if (!isAdmin.value || crawlPolling.value) return
    try {
      const status = await api.fetchGithubCrawlStatus()
      if (!status.task_id) return
      crawlStatus.value = status
      if (status.task_status === 'running') {
        beginCrawlPolling({ channel: status.channel, first_seen_after: status.first_seen_after })
      }
    } catch (error) { console.error('Failed to fetch GitHub crawl status', error) }
  }

  return { crawlPolling, crawlStatus, beginCrawlPolling, resumeGithubCrawlPolling, disposeCrawlPolling }
}
